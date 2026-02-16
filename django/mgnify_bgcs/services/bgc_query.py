from __future__ import annotations

from typing import Dict
from django.conf import settings
import numpy as np
from Bio.SeqRecord import SeqRecord
from pgvector.django import CosineDistance
from ..models import Bgc, Protein

from ..utils.helpers import sorensen_dice
from .hmmer_utils import (
    global_bgc_sequence_block,
    global_protein_sequence_block,
    create_block_from_tuples,
    iter_protein_tuples_from_bgcs,
)

from pyhmmer.hmmer import phmmer, nhmmer

import logging

log = logging.getLogger(__name__)
numeric_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
log.setLevel(numeric_level)


# --------------------------------------------------------------
# 4.1 – BGC-level embedding search -----------------------------
# --------------------------------------------------------------
def _bgc_embedding_search(record: SeqRecord, threshold: float) -> Dict[int, float]:
    """Vector cosine search through the pgvector HNSW index."""
    if len([feat for feat in record.features if feat.type.upper() == "CDS"]) == 0:
        raise ValueError(
            "Insufficient data for search: No CDS features found in the record for BGC embedding."
        )
    if "bgc_embedding" not in record.annotations:
        raise ValueError(
            "Insufficient data for search: No BGC embedding found in the record annotations."
        )
    embedding = np.asarray(record.annotations["bgc_embedding"], dtype=float).tolist()
    qs = (
        Bgc.objects.filter(is_aggregated_region=True, embedding__isnull=False)
        .annotate(distance=CosineDistance("embedding", embedding))
        .filter(distance__lte=1 - threshold)  # pgvector returns *distance* ∈ [0,2]
        .order_by("distance")
        .select_related("contig")
    )

    results: Dict[int, float] = {}
    for bgc in qs:
        dist = getattr(bgc, "distance", None)
        if dist is None:
            continue
        results[bgc.id] = 1.0 - dist
    return results


# --------------------------------------------------------------
# 4.2 – BGC-level sequence search (HMMER/pairwise) -------------
# --------------------------------------------------------------
def _bgc_hmmer_search(record: SeqRecord, threshold: float) -> Dict[int, float]:
    similarity_results: Dict[int, float] = {}
    seq_query = str(record.seq)
    if len(seq_query) < 50:
        raise ValueError(
            "Insufficient data for search: Query sequence is too short for HMMER search (must be at least 50 bp)."
        )

    subject_sequences = global_bgc_sequence_block()
    query_sequence = create_block_from_tuples([(record.id, seq_query)], alphabet="dna")

    for query_tophits in nhmmer(
        query_sequence,
        subject_sequences,
        cpus=1,  # use 1 thread to avoid parallelism issues
    ):
        for hit in query_tophits:
            if hit.score > threshold:
                # nhmmer hit.name should identify the BGC id; cast to int when possible
                try:
                    bgc_id = int(hit.name.decode())
                except Exception:
                    # unexpected name format; skip this hit
                    continue
                similarity_results[bgc_id] = max(
                    similarity_results.get(bgc_id, 0.0), hit.score
                )
    return similarity_results


# --------------------------------------------------------------
# 4.3 – Protein-set embedding search ---------------------------
# --------------------------------------------------------------
from collections import defaultdict


def _proteins_set_embedding_search(record: SeqRecord, threshold: float):
    """
    1.  Pull every query-protein embedding from the GenBank record
        (usually a few-dozen).
    2.  For each query vector run ONE ORM query:

            Protein.objects
                   .annotate(dist=CosineDistance("embedding", vec))
                   .filter(dist__lte=1-threshold)

        That executes inside PostgreSQL and is index-accelerated.
    3.  Map the matching protein IDs to BGCs through the CDS → Contig
        relationship.
    4.  Count how many query proteins intersect each BGC and calculate
        Sørensen–Dice **in Python** (cheap: only for the BGCs that have ≥1 hit).
    """
    # ----------------------------------------------------------
    # 1. extract query embeddings
    # ----------------------------------------------------------
    query_vecs: list[list[float]] = []
    for feat in record.features:
        if feat.type.upper() == "CDS" and "embedding" in feat.qualifiers:
            query_vecs.append([float(x) for x in feat.qualifiers["embedding"][0]])

    if not query_vecs:  # nothing to compare
        return {}

    n_query = len(query_vecs)
    distance_cut = 1.0 - threshold  # pgvector distance = 1 − cosine

    # ----------------------------------------------------------
    # 2–3. per-vector search, then map to BGCs
    # ----------------------------------------------------------

    hits_by_bgc: dict[int, set[int]] = defaultdict(set)
    similarity_results: Dict[int, float] = {}

    for q_idx, vec in enumerate(query_vecs):
        # proteins similar to this query vector
        prot_ids = list(
            Protein.objects.annotate(dist=CosineDistance("embedding", vec))
            .filter(dist__lte=distance_cut)
            .values_list("id", flat=True)
        )
        if not prot_ids:
            continue

        # BGCs whose contig carries ≥1 of those proteins
        bgc_ids = (
            Bgc.objects.filter(
                is_aggregated_region=True, contig__cds__protein_id__in=prot_ids
            )
            .values_list("id", flat=True)
            .distinct()
        )
        for bgc_id in bgc_ids:
            hits_by_bgc[bgc_id].add(q_idx)  # remember *which* query protein matched

    # ----------------------------------------------------------
    # 4. Sørensen–Dice & thresholding
    # ----------------------------------------------------------
    for bgc_id, matched_idxs in hits_by_bgc.items():
        dice = (2 * len(matched_idxs)) / (n_query + len(matched_idxs))
        if dice >= threshold:
            similarity_results[bgc_id] = max(similarity_results.get(bgc_id, 0), dice)

    return similarity_results


# ----------------------------------------------------------------
# 4.4 – Protein-set HMMER search -------------------------------
# --------------------------------------------------------------
def _proteins_set_hmmer_search(
    record: SeqRecord, similarity_threshold: float, set_similarity_threshold: float
) -> Dict[int, float]:
    # TODO production you would first cut down candidates (e.g. by length ±10 %), or pre-compute profile HMMs and store them; then run HMMER on a temporary FASTA built from that shortlist.
    """
    Use translated CDS sequences; treat a *protein* as intersecting when pairwise similarity ≥ threshold
    then fall back to Sørensen-Dice across the set.
    """
    similarity_results: Dict[int, float] = {}

    query_proteins = [
        (f"query_{ix}", feat.qualifiers["translation"][0])
        for ix, feat in enumerate(record.features)
        if feat.type.upper() == "CDS" and "translation" in feat.qualifiers
    ]
    if not query_proteins:
        raise ValueError(
            "Insufficient data for search: No CDS features with translations found in the record for protein HMMER search."
        )
    query_block = create_block_from_tuples(query_proteins, alphabet="amino")

    bgc_queryset = (
        Bgc.objects.filter(is_aggregated_region=True).select_related("contig").all()
    )
    for bgc in bgc_queryset:
        # materialize protein tuples so we can both build the HMMER block and
        # inspect the identifiers without exhausting a generator
        bgc_proteins = list(iter_protein_tuples_from_bgcs(bgc_queryset=[bgc]))
        if not bgc_proteins:
            continue
        subject_block = create_block_from_tuples(bgc_proteins, alphabet="amino")

        # sets of identifiers for Sørensen–Dice calculation
        query_set = {str(x[0]) for x in query_proteins}
        subject_set = {
            str(x[0]) if isinstance(x, (list, tuple)) else str(getattr(x, "id", x))
            for x in bgc_proteins
        }

        for query_tophits in phmmer(
            query_block,
            subject_block,
            cpus=1,  # use 1 thread to avoid parallelism issues
        ):
            for hit in query_tophits:
                if hit.score > similarity_threshold:
                    query_prot = query_tophits.query.name.decode()
                    query_set.discard(query_prot)

                    subject_prot = hit.name.decode()
                    subject_set.discard(subject_prot)

                    new_element = f"{min(query_prot, subject_prot)}-{max(query_prot, subject_prot)}"

                    query_set.add(new_element)
                    subject_set.add(new_element)

        dice = sorensen_dice(query_set, subject_set)
        if dice >= set_similarity_threshold:
            similarity_results[bgc.id] = max(similarity_results.get(bgc.id, 0), dice)

    return similarity_results


# --------------------------------------------------------------
# 4.5 – Single-protein embedding search ------------------------
# --------------------------------------------------------------
def _protein_embedding_search(record: SeqRecord, threshold: float) -> Dict[int, float]:
    similarity_results: Dict[int, float] = {}

    record_features = [
        feat
        for feat in record.features
        if feat.type.upper() == "CDS" and "translation" in feat.qualifiers
    ]
    if not record_features:
        raise ValueError(
            "Insufficient data for search: No CDS features with translations found in the record for protein embedding search."
        )
    vec = record_features[0].qualifiers.get("embedding", [None])[0]
    if not vec:
        raise ValueError(
            "Insufficient data for search: No embedding found in the record for protein embedding search."
        )

    bgcs_queryset = (
        Bgc.objects.filter(is_aggregated_region=True).select_related("contig").all()
    )
    prots_in_bgc = {}
    for bgc in bgcs_queryset:
        prot_objs = list(
            iter_protein_tuples_from_bgcs(bgc_queryset=[bgc], yield_objects=True)
        )
        prots_in_bgc[bgc.id] = [
            prot[0] if isinstance(prot, (list, tuple)) else getattr(prot, "id", None)
            for prot in prot_objs
            if (
                isinstance(prot, (list, tuple)) or getattr(prot, "id", None) is not None
            )
        ]

    subject_prot_ids = [
        prot_id for _, prots in prots_in_bgc.items() for prot_id in prots
    ]
    similar_prots = (
        Protein.objects.filter(embedding__isnull=False, id__in=subject_prot_ids)
        .annotate(distance=CosineDistance("embedding", vec))
        .filter(distance__lte=1.0 - threshold)
        .values_list("id", "distance")
    )
    prot_similarity_dict = {pid: 1 - dist for pid, dist in similar_prots}
    log.debug(
        f"Found {len(prot_similarity_dict)} similar proteins with distance < {threshold}."
    )
    matched_bgcs = Bgc.objects.filter(
        is_aggregated_region=True,
        contig__cds__protein_id__in=prot_similarity_dict.keys(),
    ).distinct()
    # keep best similarity per BGC (distance smallest)

    for bgc in matched_bgcs:
        vals = [
            prot_similarity_dict.get(prot_id, 0)
            for prot_id in prots_in_bgc.get(bgc.id, [])
        ]
        similarity_results[bgc.id] = max(vals) if vals else 0.0
    return similarity_results


# --------------------------------------------------------------
# 4.6 – Single-protein HMMER search ----------------------------
# --------------------------------------------------------------
def _protein_hmmer_search(record: SeqRecord, threshold: float) -> Dict[int, float]:
    similarity_results: Dict[int, float] = {}

    query_proteins = [
        (f"query_{ix}", feat.qualifiers["translation"][0])
        for ix, feat in enumerate(record.features)
        if feat.type.upper() == "CDS" and "translation" in feat.qualifiers
    ]
    if not query_proteins:
        raise ValueError(
            "Insufficient data for search: No CDS features with translations found in the record for protein HMMER search."
        )
    query_block = create_block_from_tuples(query_proteins, alphabet="amino")

    bgcs_queryset = (
        Bgc.objects.filter(is_aggregated_region=True).select_related("contig").all()
    )
    prots_in_bgc = {}
    for bgc in bgcs_queryset:
        prot_objs = list(
            iter_protein_tuples_from_bgcs(bgc_queryset=[bgc], yield_objects=True)
        )
        prots_in_bgc[bgc.id] = [
            prot[0] if isinstance(prot, (list, tuple)) else getattr(prot, "id", None)
            for prot in prot_objs
            if (
                isinstance(prot, (list, tuple)) or getattr(prot, "id", None) is not None
            )
        ]
    prots_to_bgc = {
        prot: bgc_id for bgc_id, prots in prots_in_bgc.items() for prot in prots
    }

    all_proteins_block = global_protein_sequence_block()

    for query_tophits in phmmer(
        query_block,
        all_proteins_block,
        cpus=1,  # use 1 thread to avoid parallelism issues
    ):
        for hit in query_tophits:
            if hit.score > threshold:
                query_prot = query_tophits.query.name.decode()
                subject_prot = hit.name.decode()
                try:
                    subject_int = int(subject_prot)
                except Exception:
                    continue
                bgc_id = prots_to_bgc.get(subject_int)
                if bgc_id is None:
                    continue
                similarity_results[bgc_id] = max(
                    similarity_results.get(bgc_id, 0.0), hit.score
                )

    return similarity_results
