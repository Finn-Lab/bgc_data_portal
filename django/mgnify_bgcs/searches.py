import logging
import re
import operator
from functools import reduce
from typing import Optional, Any

from django.conf import settings
from django.http import HttpResponseBadRequest
from django.db.models import F, Q
from django.db.models import Case, When, Value, FloatField

from Bio.SeqRecord import SeqRecord

from rdkit import Chem
from rdkit.Chem import DataStructs, rdFingerprintGenerator

from mgnify_bgcs.utils.helpers import annotate_queryset, find_doppelganger_bgcs
from mgnify_bgcs.utils.lazy_loaders import get_highest_versions_by_tool
from mgnify_bgcs.filters import BgcKeywordFilter
from mgnify_bgcs.models import Bgc

log = logging.getLogger(__name__)
numeric_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
log.setLevel(numeric_level)


def search_bgcs_by_keyword(keyword):
    """
    Get BGC DataFrame based on keyword search criteria.
    """
    base_qs = Bgc.objects.filter(
        is_aggregated_region=False
    ).select_related(  # or use the corrected name if typo
        "contig",
        "contig__assembly",
        "contig__assembly__study",
        "contig__assembly__biome",
        "detector",
    )
    if not keyword:
        # empty keyword -> return empty annotated queryset
        return annotate_queryset(Bgc.objects.none())
    bgc_filter = BgcKeywordFilter({"keyword": keyword}, queryset=base_qs)
    if not bgc_filter.is_valid():
        raise ValueError("Invalid keyword search criteria")
    # Get lenght of the queryset
    if bgc_filter.qs.count() == 0:
        log.debug("Number of BGCs found for keyword: %s", bgc_filter.qs.count())
        return annotate_queryset(Bgc.objects.none())

    aggregated_bgcs = find_doppelganger_bgcs(bgc_filter.qs)
    return annotate_queryset(aggregated_bgcs)


def search_bgcs_by_advanced(criteria):
    """
    Get BGC DataFrame based on advanced search criteria using updated models.
    """

    # Base queryset with related selects
    queryset = (
        Bgc.objects.filter(is_aggregated_region=False)
        .select_related(
            "detector", "contig", "contig__assembly", "contig__assembly__biome"
        )
        .prefetch_related("classes")
    )

    # ---------------------------
    # BGC Detector filtering
    # ---------------------------
    detectors = criteria.get("detectors")
    if detectors:
        # detectors now provided as detector names (case-insensitive).
        # Map names -> latest-version PKs using a case-insensitive match.
        latest_map = get_highest_versions_by_tool() or {}
        selected_lower = {str(d).strip().lower() for d in detectors if d is not None}
        selected_pks = [
            pk
            for name, pk in latest_map.items()
            if str(name).strip().lower() in selected_lower
        ]
        if selected_pks:
            queryset = queryset.filter(detector__pk__in=selected_pks)
        else:
            # No valid detectors matched -> empty set
            return annotate_queryset(Bgc.objects.none())

    # ---------------------------
    # BGC Class filtering
    # ---------------------------
    bgc_class_name = criteria.get("bgc_class_name")
    if bgc_class_name:
        queryset = queryset.filter(classes__name__icontains=bgc_class_name)

    # ---------------------------
    # MGYB Accession filtering
    # e.g., "MGYB000000123456" -> id=123456
    # ---------------------------
    mgyb = criteria.get("mgyb")
    if mgyb:
        try:
            bgc_id = int(mgyb.strip().upper().lstrip("MGYB"))
            queryset = queryset.filter(id=bgc_id)
        except ValueError:
            queryset = queryset.none()

    # ---------------------------
    # Assembly accession
    # ---------------------------
    assembly_accession = criteria.get("assembly_accession")
    if assembly_accession:
        queryset = queryset.filter(contig__assembly__accession=assembly_accession)

    # ---------------------------
    # MGYC (stored on Contig)
    # ---------------------------
    mgyc = criteria.get("mgyc")
    if mgyc:
        queryset = queryset.filter(contig__mgyc=mgyc)

    # ---------------------------
    # Biome lineage
    # ---------------------------
    biome_lineage = criteria.get("biome_lineage")
    if biome_lineage:
        queryset = queryset.filter(
            contig__assembly__biome__lineage__icontains=biome_lineage
        )

    # ---------------------------
    # Completeness
    # e.g., ["0", "1"] → False (complete), True (partial)
    # ---------------------------
    completeness = criteria.get("completeness")
    if completeness:
        bool_map = {"1": True, "0": False}
        values = [bool_map.get(str(c)) for c in completeness if str(c) in bool_map]
        queryset = queryset.filter(is_partial__in=values)

    # ---------------------------
    # Protein domains (Pfams -> Domains)
    # Strategy: 'intersection' or 'union'
    # ---------------------------
    pfam = criteria.get("protein_pfam")
    if pfam:
        pfam_terms = [p.strip() for p in re.split(r"[, ]+", pfam) if p.strip()]
        pfam_strategy = criteria.get("pfam_strategy", "union")

        domain_queries = [
            Q(
                contig__cds__protein__domains__acc=pfam_term,
                contig__cds__start_position__lte=F("end_position"),
                contig__cds__end_position__gte=F("start_position"),
            )
            for pfam_term in pfam_terms
        ]

        if domain_queries:
            if pfam_strategy == "intersection":
                for condition in domain_queries:
                    queryset = queryset.filter(condition)
            else:  # default to union
                queryset = queryset.filter(reduce(operator.or_, domain_queries))

    # Execute and convert queryset to desired output format
    aggregated_bgcs = find_doppelganger_bgcs(queryset)
    return annotate_queryset(aggregated_bgcs)


"""
Main dispatcher; everything that touches Django lives here.
"""


# --------------------------------------------------------------
# Public façade ------------------------------------------------
# --------------------------------------------------------------
from .services.bgc_query import (
    _bgc_embedding_search,
    _bgc_hmmer_search,
    _proteins_set_embedding_search,
    _proteins_set_hmmer_search,
    _protein_embedding_search,
    _protein_hmmer_search,
)


def search_bgcs_by_record(
    record: SeqRecord,
    unit_of_comparison: str,
    similarity_measure: str,
    molecule_type: str,
    similarity_threshold: float,
    set_similarity_threshold: Optional[float] = None,
) -> Any:
    """
    Parameters
    ----------
    record : Bio.SeqRecord.SeqRecord
        Input BGC or protein record (already parsed with BioPython).
        *If unit_of_comparison == 'bgc'*        expect record.annotations['bgc_embedding']
        *If unit_of_comparison == 'proteins'*   expect CDS features with .qualifiers['embedding'] or 'translation'
        *If molecule_type == 'protein'*         expect whole-protein embedding / sequence in record.annotations
    unit_of_comparison : {'bgc', 'proteins'}
    similarity_measure : {'cosine', 'hmmer'}
    molecule_type : {'nucleotide', 'protein'}
    similarity_threshold : float
        Cosine (≥) or Sørensen-Dice (≥) for embeddings; for HMMER treat as fraction identity.

    Returns
    -------
    list[(Bgc, float)]  ordered best-first
    """

    log.info(
        "search_bgcs_by_record: %s, %s, %s, %s, %s",
        record.id,
        unit_of_comparison,
        similarity_measure,
        molecule_type,
        similarity_threshold,
    )

    if molecule_type == "protein":  # single-protein query
        if similarity_measure == "cosine":
            similarity_results = _protein_embedding_search(record, similarity_threshold)
        elif similarity_measure == "hmmer":
            similarity_results = _protein_hmmer_search(record, similarity_threshold)
        else:
            raise ValueError(
                "Unsupported similarity_measure for molecule_type='protein'"
            )

    elif unit_of_comparison == "bgc":
        if similarity_measure == "cosine":
            similarity_results = _bgc_embedding_search(record, similarity_threshold)
        elif similarity_measure == "hmmer":
            similarity_results = _bgc_hmmer_search(record, similarity_threshold)
        else:
            raise ValueError(
                "Unsupported similarity_measure for unit_of_comparison='bgc'"
            )

    elif unit_of_comparison == "proteins":
        if similarity_measure == "cosine":
            similarity_results = _proteins_set_embedding_search(
                record, similarity_threshold
            )
        elif similarity_measure == "hmmer":
            # If caller didn't supply an explicit set-similarity threshold,
            # fall back to the per-item similarity threshold.
            _set_sim = (
                similarity_threshold
                if set_similarity_threshold is None
                else set_similarity_threshold
            )
            similarity_results = _proteins_set_hmmer_search(
                record,
                similarity_threshold=similarity_threshold,
                set_similarity_threshold=_set_sim,
            )
        else:
            raise ValueError(
                "Unsupported similarity_measure for unit_of_comparison='proteins'"
            )

    else:
        raise ValueError("Combination of arguments not supported")

    # similarity_results is expected to be a mapping {bgc_id: score}
    # ensure we have a mapping from bgc_id -> score
    similarity_results = dict(similarity_results)

    cases = [When(pk=pk, then=Value(val)) for pk, val in similarity_results.items()]

    queryset = (
        Bgc.objects.filter(id__in=list(similarity_results.keys()))
        .annotate(
            similarity=Case(
                *cases,
                default=Value(None),
                output_field=FloatField(),
            )
        )
        .order_by("-similarity")
    )

    aggregated_bgcs = find_doppelganger_bgcs(queryset)
    return annotate_queryset(aggregated_bgcs)


def sequence_bgcs_by_smiles(query_smiles, similarity_threshold: float):
    """
    Sequence BGC by molecular structure
    """
    log.info("sequence_bgcs_by_smiles: %s, %s", query_smiles, similarity_threshold)
    mfpgen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)

    query_mol = Chem.MolFromSmiles(query_smiles)
    if query_mol is None:
        return HttpResponseBadRequest("Invalid query SMILES")

    # Compute fingerprint for query
    query_fp = mfpgen.GetFingerprint(query_mol)

    # Iterate through all Molecule objects and compute Tanimoto similarity
    bgcs_with_smiles = Bgc.objects.filter(is_aggregated_region=True).exclude(
        compounds=[]
    )

    similarity_results = {}

    for bgc in bgcs_with_smiles.all():
        compounds = getattr(bgc, "compounds", None)
        if not compounds:
            continue
        for compound in compounds:
            smile_string = compound.get("structure")
            if not smile_string:
                continue

            db_mol = Chem.MolFromSmiles(smile_string)
            if db_mol is None:
                continue
            db_fp = mfpgen.GetFingerprint(db_mol)
            sim = DataStructs.TanimotoSimilarity(query_fp, db_fp)
            if sim >= similarity_threshold:
                similarity_results[bgc.id] = max(
                    similarity_results.get(bgc.id, 0.0), sim
                )

    if not similarity_results:
        log.info("No BGCs found with similarity above threshold")
        return annotate_queryset(Bgc.objects.none())

    similarity_cases = [
        When(pk=pk, then=Value(val)) for pk, val in similarity_results.items()
    ]

    queryset = (
        Bgc.objects.filter(id__in=list(similarity_results.keys()))
        .annotate(
            similarity=Case(
                *similarity_cases,
                default=Value(None),
                output_field=FloatField(),
            ),
        )
        .order_by("-similarity")
    )

    log.info(f"Found {queryset.count()} BGCs with similarity above threshold")

    return annotate_queryset(queryset)
