from __future__ import annotations
import logging

import numpy as np

from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

from django.db import transaction
from django.db.models import Prefetch, Q

from pgvector import Vector

from ..utils.lazy_loaders import (
    umap_model,
    get_highest_versions_by_tool,
)
from ..utils.helpers import normalize_class_distribution_dict
from ..models import (
    Bgc,
    BgcBgcClass,
    BgcDetector,
    BgcClass,
    Cds,
    Contig,
)

_EMBED_DIM: int = 1152  # keep in one place for safety
_ZERO_VECTOR = Vector([0.0] * _EMBED_DIM)
embedder = None
umap = None
current_tool_versions = None

log = logging.getLogger(__name__)


@dataclass(slots=True)
class _Region:
    """A simple value-object that holds one merged BGC region."""

    start: int
    end: int
    bgcs: List[Bgc]


# ──────────────────────────────────────────────────────────────────────────────
# Helper functions
# ──────────────────────────────────────────────────────────────────────────────
def merge_overlaps(bgcs: Sequence[Bgc]) -> List[_Region]:
    """
    Classic “merge overlapping intervals” – emits non-overlapping regions.
    Input: all BGCs for ONE contig.
    """
    if not bgcs:
        return []

    ordered = sorted(bgcs, key=lambda b: b.start_position)
    regions: List[_Region] = []

    cur_start, cur_end, cur_group = (
        ordered[0].start_position,
        ordered[0].end_position,
        [ordered[0]],
    )

    for bgc in ordered[1:]:
        if bgc.start_position <= cur_end:  # overlap
            cur_end = max(cur_end, bgc.end_position)
            cur_group.append(bgc)
        else:  # gap – flush
            regions.append(_Region(cur_start, cur_end, cur_group))
            cur_start, cur_end, cur_group = (
                bgc.start_position,
                bgc.end_position,
                [bgc],
            )
    regions.append(_Region(cur_start, cur_end, cur_group))
    return regions


# returns a tuple of embeddings and mean embedding
def _weighted_mean_embedding(
    contig: Contig, region: _Region, cds_qs: Iterable[Cds]
) -> Tuple[Vector, List[float]]:
    """
    Implements the weighting rule:
        weight(p) = (# detectors covering p) / (# detectors in the region)
    where “detectors” == number of BGCs (each BGC has exactly one detector FK).
    """
    detectors_in_region = len(region.bgcs)
    if detectors_in_region == 0:
        return _ZERO_VECTOR, []

    prot_info: dict[int, Tuple[Vector, int]] = {}

    # All CDS on thi contig whose interval sits wholly inside the region
    cds_inside = (
        cds_qs.filter(start_position__gte=region.start, end_position__lte=region.end)
        .select_related("protein")
        .iterator()
    )

    for cds in cds_inside:
        p = cds.protein
        if p.embedding is None or len(p.embedding) == 0:
            continue
        prot_info.setdefault(p.id, (p.embedding, 0))

    # For every BGC in the region add 1 “detector hit” to proteins covered by it
    for bgc in region.bgcs:
        cds_hits = (
            cds_qs.filter(
                start_position__gte=bgc.start_position,
                end_position__lte=bgc.end_position,
            )
            .values_list("protein_id", flat=True)
            .iterator()
        )
        for pid in cds_hits:
            if pid in prot_info:
                emb, w = prot_info[pid]
                prot_info[pid] = (emb, w + 1)

    if not prot_info:
        return _ZERO_VECTOR, []

    # Compute the weighted mean
    protein_weights = [w / detectors_in_region for _, w in prot_info.values()]

    emb_array = np.array([emb for emb, _ in prot_info.values()])

    weights_array = np.array(protein_weights, dtype=np.float32)
    weights_array /= weights_array.sum()
    mean_emb = np.sum(emb_array * weights_array[:, None], axis=0)

    return mean_emb, protein_weights


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────
_ITER_CHUNK: int = 1_000


def build_aggregated_for_contigs(contig_ids: Sequence[int] | None = None) -> int:
    """
    Creates / refreshes all aggregated BGC regions for the requested contigs.

    If `contig_ids` is None all contigs with “canonical” (non-aggregated) BGCs
    are processed. The function is **idempotent** – it first deletes any
    previously generated aggregated rows for a contig before rebuilding them.
    Returns the number of regions created.
    """
    if contig_ids is None:
        contig_ids = (
            Bgc.objects.filter(~Q(is_aggregated_region=True))  # canonical only
            .values_list("contig_id", flat=True)
            .distinct()
        )

    contigs = (
        Contig.objects.filter(id__in=contig_ids)
        .prefetch_related(
            Prefetch(
                "bgcs",
                queryset=Bgc.objects.filter(~Q(is_aggregated_region=True))
                .prefetch_related("classes")
                .order_by("start_position"),
                to_attr="canonical_bgcs",
            ),
            "cds__protein",
        )
        .iterator(chunk_size=_ITER_CHUNK)
    )

    total_regions = 0
    for contig in contigs:
        if not contig.canonical_bgcs:
            continue

        current_tool_versions = get_highest_versions_by_tool()
        canonical = [
            b
            for b in contig.canonical_bgcs
            if b.detector_id in current_tool_versions.values()
        ]
        if not canonical:
            continue

        # remove any stale aggregated rows first
        Bgc.objects.filter(contig=contig, is_aggregated_region=True).delete()

        regions = merge_overlaps(canonical)
        total_regions += len(regions)

        new_bgcs: list[Bgc] = []
        new_m2m: list[BgcBgcClass] = []

        cds_qs = contig.cds.all()  # already prefetched above

        for region in regions:
            identifier = f"{contig.id}_{region.start}_{region.end}"

            # Union of all classes present in member BGCs
            class_ids = (
                BgcClass.objects.filter(bgcs__in=region.bgcs)
                .values_list("id", flat=True)
                .distinct()
            )
            class_names = (
                BgcClass.objects.filter(id__in=class_ids)
                .values_list("name", flat=True)
                .distinct()
            )
            normalized_class_names = normalize_class_distribution_dict(
                {name: 1 for name in class_names}
            )

            detector_ids = (
                BgcDetector.objects.filter(bgcs__in=region.bgcs)
                .values_list("id", flat=True)
                .distinct()
            )
            detector_names = (
                BgcDetector.objects.filter(id__in=detector_ids)
                .values_list("tool", flat=True)
                .distinct()
            )
            embedding, protein_weight = _weighted_mean_embedding(contig, region, cds_qs)

            # UMAP transformation
            umap = umap_model()
            umap_coords = umap.transform([embedding])

            # Collect compound and get svg images
            compounds = [
                compound for b in region.bgcs for compound in b.compounds or []
            ]
            smiles_svg = None
            for compound in compounds:
                structure = compound.get("structure")
                if structure:
                    try:
                        from ..services.compound_search_utils import smiles_to_svg
                        smiles_svg = smiles_to_svg(structure)
                    except Exception as e:
                        log.error(f"Error getting SVG for compound {compound.id}: {e}")

            agg_bgc = Bgc(
                contig=contig,
                detector=None,
                identifier=identifier,
                start_position=region.start,
                end_position=region.end,
                is_partial=False,
                embedding=embedding,
                metadata={
                    "aggregated_bgc_ids": [b.id for b in region.bgcs],
                    "detectors": list(sorted(detector_names)),
                    "classes": list(normalized_class_names.keys()),
                    "protein_weight": protein_weight,
                    "umap_x_coord": x if not np.isnan(x := float(umap_coords[0][0])) else None,
                    "umap_y_coord": y if not np.isnan(y := float(umap_coords[0][1])) else None,
                },
                compounds=compounds,
                smiles_svg=smiles_svg,
                is_aggregated_region=True,
            )
            new_bgcs.append(agg_bgc)

            # We must add the m2m rows **after** we have PKs – collect for later
            for cid in class_ids:
                new_m2m.append((agg_bgc, cid))

        # Bulk-insert the new rows in one go
        with transaction.atomic():
            Bgc.objects.bulk_create(new_bgcs, batch_size=1_000)

            m2m_rows = [
                BgcBgcClass(bgc=bgc, bgc_class_id=cls_id) for bgc, cls_id in new_m2m
            ]
            BgcBgcClass.objects.bulk_create(m2m_rows, ignore_conflicts=True)

    return total_regions
