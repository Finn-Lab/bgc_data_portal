from __future__ import annotations
from django.conf import settings

from typing import Sequence, Collection, Mapping, Any, Dict, List


import pandas as pd
from ..models import Bgc, CurrentStats
import logging
import numpy as np
from django.db.models import Count
from django.db.models import OuterRef, Exists


from django.db.models import F, Value
from django.db.models.functions import Coalesce
from django.contrib.postgres.aggregates import ArrayAgg

log = logging.getLogger(__name__)
numeric_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
log.setLevel(numeric_level)

UMAP_SEED = 0
UMAP_PLOT_SAMPLE = 1_000

# helper functions that are unrelated to queries live in this module


def mgyb_converter(mgyb, text_to_int=True):
    """
    Convert MGYB identifier between text and integer formats.

    Args:
        mgyb (str or int): The MGYB identifier to convert.
        text_to_int (bool): If True, convert text to int; if False, convert int to text.

    Returns:
        int or str: The converted MGYB identifier.
    """
    mgyb_template = "MGYB{:012}"
    if text_to_int:
        return int(str(mgyb)[4:])
    else:
        return mgyb_template.format(int(mgyb))


def find_doppelganger_bgcs(queryset):
    """
    Find BGCs that are doppelgangers (i.e., the aggragated_regions of those bgcs).

    Args:
        queryset: A queryset of BGC objects.

    Returns:
        dict: A dictionary mapping BGC IDs to a set of doppelganger BGC IDs.
    """
    doppelgangers_queryset = (
        Bgc.objects.filter(is_aggregated_region=True)
        .annotate(
            overlaps=Exists(
                queryset.filter(
                    contig_id=OuterRef("contig_id"),
                    # non_agg.start ≤ agg.end
                    start_position__lte=OuterRef("end_position"),
                    # non_agg.end   ≥ agg.start
                    end_position__gte=OuterRef("start_position"),
                )
            )
        )
        .filter(overlaps=True)
    )
    return doppelgangers_queryset


def annotate_queryset(queryset):
    """
    Process BGC queryset results by annotating .

    """

    queryset = queryset.select_related("contig__assembly__study")

    # Step 3: Annotate related fields
    queryset = queryset.annotate(
        start_position_plus_one=F("start_position") + Value(1),
        contig_accession=F("contig__name"),
        assembly_accession=Coalesce(F("contig__assembly__accession"), Value("")),
        study_accession=Coalesce(F("contig__assembly__study__accession"), Value("")),
        class_names=ArrayAgg("classes__name", distinct=True),
        detector_names=F("metadata__detectors"),
    ).defer(
        "embedding",
        "contig__sequence",
        "contig__sequence_sha256",  # your @property
    )
    return queryset


def cosine_similarity(
    a: Sequence[float] | np.ndarray, b: Sequence[float] | np.ndarray
) -> float:
    """Compute cosine similarity between two vectors.

    Accepts Python sequences or numpy arrays (we coerce to numpy internally).
    """
    # TODO only rely on PGVECTOR cosine similarity
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return 0.0 if denom == 0 else float(np.dot(a, b) / denom)


def sorensen_dice(set_a: Collection, set_b: Collection) -> float:
    """2*|A∩B| / (|A|+|B|) for any hashable collections."""
    if not set_a and not set_b:
        return 1.0
    intersection = len(set(set_a).intersection(set(set_b)))
    return 2 * intersection / (len(set_a) + len(set_b))


def generate_current_stats():
    """
    Compute summary stats across the new models:
      - total BGC regions
      - distribution of BGC classes
      - number of distinct assemblies
      - number of distinct studies
    Returns:
      dict suitable for CurrentStats.stats
    """
    # total number of regions
    aggregated_bgc_queryset = Bgc.objects.filter(is_aggregated_region=True)
    annotated_queryset = annotate_queryset(aggregated_bgc_queryset)
    stats = calcluate_annotated_bgc_queryset_stats(annotated_queryset)
    return stats


def get_latest_stats():
    """
    Retrieve the latest cached statistics from the database.

    Returns:
        dict: The most recent statistics if available, otherwise an empty dictionary.
    """
    latest_stats = CurrentStats.objects.order_by("-created_at").first()
    if latest_stats:
        return latest_stats.stats
    return {}


def normalize_class_distribution_dict(
    class_dist: Mapping[str, int]
) -> dict[str, float]:
    """
    Normalize a class distribution dictionary to percentages and different names.
    Finaly order the classes by percentage in descending order.

    Args:
        class_dist (dict[str, int]): A dictionary with class names as keys and counts as values.

    Returns:
        dict[str, int]: A dictionary with class names as keys and normalized percentages as values.
    """
    log.debug("Normalizing class distribution: %s", class_dist)

    # Work on a fresh mutable copy with integer counts
    counts: dict[str, int] = {k: int(v) for k, v in class_dist.items()}

    # Normalize names by folding counts into canonical names
    for source, target in [
        ("NRPS", "NRP"),
        ("PKS", "Polyketide"),
        ("other", "Other"),
        ("ribosomal", "RiPP"),
        ("saccharide", "Saccharide"),
        ("terpene", "Terpene"),
        ("alkaloid", "Alkaloid"),
    ]:
        if counts.get(source, 0):
            counts[target] = counts.get(target, 0) + counts.pop(source, 0)

        # remove empty entries
        if counts.get(target, 0) == 0:
            counts.pop(target, None)

    total_count = sum(counts.values())

    # Produce normalized percentages in a separate dict[str, float]
    if total_count > 0:
        percents: dict[str, float] = {
            k: round(v / total_count * 100, 1) for k, v in counts.items()
        }
    else:
        percents = {k: 0.0 for k in counts.keys()}

    # Return sorted by percentage (descending)
    return dict(sorted(percents.items(), key=lambda item: item[1], reverse=True))


def calcluate_annotated_bgc_queryset_stats(queryset):
    """
    Calculate statistics for a queryset of BGCs.

    Args:
        queryset: A queryset of BGC objects.

    Returns:
        dict: A dictionary containing the statistics.
    """

    stats = queryset.aggregate(
        total_regions=Count("pk"),
        n_assemblies=Count("contig__assembly__accession", distinct=True),
        n_studies=Count("contig__assembly__study__accession", distinct=True),
    )

    # Class counts
    class_counts_qs = (
        queryset.values("classes__name")
        .annotate(count=Count("classes__name"))
        .order_by()  # remove any implicit ordering (so you just get groups)
    )
    # turn that into a plain dict
    class_counts = {entry["classes__name"]: entry["count"] for entry in class_counts_qs}

    # finally, normalize however you like
    normalized_stats = {
        **stats,
        "bgc_class_dist": normalize_class_distribution_dict(class_counts),
    }

    return normalized_stats


def from_queryset_to_website_results(queryset):
    # Columns to expose in the UI table
    display_columns = [
        {"name": "MGYB", "slug": "accession"},
        {"name": "Assembly", "slug": "assembly_accession"},
        {"name": "Contig", "slug": "contig_accession"},
        {"name": "Start", "slug": "start_position_plus_one"},
        {"name": "End", "slug": "end_position"},
        {"name": "Detectors", "slug": "detector_names"},
        {"name": "Classes", "slug": "class_names"},
    ]

    # Fields we expect from the queryset
    value_fields = [
        "id",
        "metadata",
        "assembly_accession",
        "contig_accession",
        "start_position_plus_one",
        "end_position",
        "detector_names",
        "class_names",
        "smiles_svg",
    ]

    # Always compute stats (aggregations are safe on empty querysets)
    result_stats = calcluate_annotated_bgc_queryset_stats(queryset)

    # Handle empty queryset early with structured empty artifacts
    if not queryset.exists():
        empty_df = pd.DataFrame(
            columns=value_fields + ["accession"]
        )  # include computed column
        return empty_df, result_stats, [], display_columns

    # Build DataFrame with explicit columns to avoid KeyErrors on empties
    records = list(queryset.values(*value_fields))
    df = pd.DataFrame.from_records(records, columns=value_fields)

    # Convert integer PK to MGYB text accession
    if not df.empty:
        df["accession"] = df["id"].apply(lambda x: mgyb_converter(x, text_to_int=False))
    else:
        df["accession"] = []

    # Build scatter plot sample safely
    scatter_data: list[dict] = []
    sample_n = min(UMAP_PLOT_SAMPLE, len(df))
    sampled_df = df.sample(n=sample_n, random_state=UMAP_SEED) if sample_n > 0 else df
    for _, bgc in sampled_df.iterrows():
        metadata = bgc.get("metadata") or {}
        class_names = bgc.get("class_names") or []
        detector_names = bgc.get("detector_names") or []
        # Ensure list for join
        if not isinstance(detector_names, (list, tuple, set)):
            detector_names = [str(detector_names)] if detector_names is not None else []

        record = {
            "id": bgc.get("id"),
            "accession": bgc.get("accession"),
            "x": metadata.get("umap_x_coord"),
            "y": metadata.get("umap_y_coord"),
            "class_tag": (
                class_names[0]
                if isinstance(class_names, (list, tuple)) and class_names
                else None
            ),
            "is_mibig_tag": "mibig" in "".join(map(str, detector_names)).lower(),
        }
        for col in display_columns:
            val = bgc.get(col["slug"]) if hasattr(bgc, "get") else None
            if isinstance(val, (list, tuple, set)):
                val = ", ".join(map(str, val))
            record[col["name"]] = val
        scatter_data.append(record)

    return df, result_stats, scatter_data, display_columns


def to_post_dict(data: Dict[str, Any]) -> Dict[str, List[str]]:
    """Convert a dict of parameters to a POST-like dict
    All values are converted to lists of strings. None values become empty lists.
    """
    out: Dict[str, List[str]] = {}
    for k, v in data.items():
        if v is None:
            out[k] = []
        elif isinstance(v, (list, tuple, set)):
            out[k] = [str(x) for x in v]
        else:
            out[k] = [str(v)]
    return out
