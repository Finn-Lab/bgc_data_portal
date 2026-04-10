"""Celery tasks for the Evaluate Asset mode.

Each task dispatches to the assessment service, caches the result
in Redis with a 24-hour TTL, and follows the existing set_job_cache
/ get_job_status polling pattern.
"""

from __future__ import annotations

import logging

from celery import shared_task

from discovery.cache_utils import set_job_cache

log = logging.getLogger(__name__)

ASSESSMENT_TTL = 86_400  # 24 hours
KEYWORD_TTL = 300  # 5 minutes
UPLOAD_ASSESSMENT_TTL = 14_400  # 4 hours
CHEMICAL_QUERY_TTL = 3_600  # 1 hour


@shared_task(name="discovery.tasks.keyword_resolve", bind=True, acks_late=True)
def keyword_resolve(self, search_key: str, keyword: str) -> bool:
    """Resolve a landing-page keyword to a dashboard filter and cache the redirect URL."""
    task_id = self.request.id
    set_job_cache(search_key=search_key, task_id=task_id, timeout=KEYWORD_TTL)

    from discovery.services.keyword_resolver import resolve_keyword

    result = resolve_keyword(keyword)

    set_job_cache(
        search_key=search_key,
        results=result,
        task_id=task_id,
        timeout=KEYWORD_TTL,
    )
    log.info("Keyword resolved: %r → %s (task %s)", keyword, result.get("match_type"), task_id)
    return True


@shared_task(name="discovery.tasks.assess_assembly", bind=True, acks_late=True)
def assess_assembly(self, assembly_id: int) -> bool:
    """Run a full assembly assessment and cache the result."""
    task_id = self.request.id
    search_key = f"assess_assembly:{assembly_id}"

    # Mark as pending
    set_job_cache(search_key=search_key, task_id=task_id, timeout=ASSESSMENT_TTL)

    from discovery.services.assessment import compute_assembly_assessment

    result = compute_assembly_assessment(assembly_id)

    set_job_cache(
        search_key=search_key,
        results=result,
        task_id=task_id,
        timeout=ASSESSMENT_TTL,
    )
    log.info("Assembly assessment completed for assembly %s (task %s)", assembly_id, task_id)
    return True


@shared_task(name="discovery.tasks.assess_bgc", bind=True, acks_late=True)
def assess_bgc(self, bgc_id: int) -> bool:
    """Run a full BGC assessment and cache the result."""
    task_id = self.request.id
    search_key = f"assess_bgc:{bgc_id}"

    # Mark as pending
    set_job_cache(search_key=search_key, task_id=task_id, timeout=ASSESSMENT_TTL)

    from discovery.services.assessment import compute_bgc_assessment

    result = compute_bgc_assessment(bgc_id)

    set_job_cache(
        search_key=search_key,
        results=result,
        task_id=task_id,
        timeout=ASSESSMENT_TTL,
    )
    log.info("BGC assessment completed for BGC %s (task %s)", bgc_id, task_id)
    return True


@shared_task(name="discovery.tasks.assess_uploaded_bgc", bind=True, acks_late=True)
def assess_uploaded_bgc(self, upload_key: str) -> bool:
    """Run a full BGC assessment on uploaded (cached) data."""
    from django.core.cache import cache

    task_id = self.request.id
    search_key = f"assess_upload_bgc:{upload_key}"

    set_job_cache(search_key=search_key, task_id=task_id, timeout=UPLOAD_ASSESSMENT_TTL)

    uploaded_data = cache.get(upload_key)
    if not uploaded_data:
        set_job_cache(
            search_key=search_key,
            results={"error": "Upload expired — please re-upload"},
            task_id=task_id,
            timeout=UPLOAD_ASSESSMENT_TTL,
        )
        log.warning("Upload key %s expired before assessment (task %s)", upload_key, task_id)
        return False

    from discovery.services.uploaded_assessment import compute_uploaded_bgc_assessment

    result = compute_uploaded_bgc_assessment(uploaded_data)

    set_job_cache(
        search_key=search_key,
        results=result,
        task_id=task_id,
        timeout=UPLOAD_ASSESSMENT_TTL,
    )
    log.info("Uploaded BGC assessment completed (task %s)", task_id)
    return True


@shared_task(name="discovery.tasks.assess_uploaded_assembly", bind=True, acks_late=True)
def assess_uploaded_assembly(self, upload_key: str) -> bool:
    """Run a full assembly assessment on uploaded (cached) data."""
    from django.core.cache import cache

    task_id = self.request.id
    search_key = f"assess_upload_assembly:{upload_key}"

    set_job_cache(search_key=search_key, task_id=task_id, timeout=UPLOAD_ASSESSMENT_TTL)

    uploaded_data = cache.get(upload_key)
    if not uploaded_data:
        set_job_cache(
            search_key=search_key,
            results={"error": "Upload expired — please re-upload"},
            task_id=task_id,
            timeout=UPLOAD_ASSESSMENT_TTL,
        )
        log.warning("Upload key %s expired before assessment (task %s)", upload_key, task_id)
        return False

    from discovery.services.uploaded_assessment import compute_uploaded_assembly_assessment

    result = compute_uploaded_assembly_assessment(uploaded_data)

    set_job_cache(
        search_key=search_key,
        results=result,
        task_id=task_id,
        timeout=UPLOAD_ASSESSMENT_TTL,
    )
    log.info("Uploaded assembly assessment completed (task %s)", task_id)
    return True


@shared_task(name="discovery.tasks.recompute_scores", bind=True, acks_late=True)
def recompute_scores_task(self) -> bool:
    """Recompute all discovery scores (novelty, assembly, GCF, catalogs, UMAP)."""
    from discovery.services.scores import recompute_all_scores

    recompute_all_scores()
    log.info("Score recomputation complete (task %s)", self.request.id)
    return True


@shared_task(name="discovery.tasks.chemical_similarity_search", bind=True, acks_late=True)
def chemical_similarity_search(self, smiles: str, similarity_threshold: float) -> dict[int, float]:
    """Compute ChemOnt ontology-based semantic similarity of a SMILES query.

    Classifies the query SMILES into ChemOnt terms, then computes
    IC-based (Resnik / Best Match Average) similarity against each BGC's
    natural product ChemOnt annotations.

    Returns a dict mapping BGC id → max similarity score.
    Runs in the Celery worker where RDKit is available.
    """
    from collections import defaultdict

    from common_core.chemont.classifier import classify_smiles
    from common_core.chemont.ontology import get_ontology
    from common_core.chemont.similarity import best_match_average, normalize_similarity

    from discovery.models import NaturalProductChemOntClass, PrecomputedStats

    ont = get_ontology()

    # Step 1: Classify query SMILES into ChemOnt terms.
    query_classes = classify_smiles(smiles.strip(), ontology=ont)
    if not query_classes:
        log.warning("No ChemOnt matches for SMILES: %s", smiles[:50])
        return {}
    query_term_ids = [c.chemont_id for c in query_classes]

    # Step 2: Load precomputed IC values.
    ic_row = PrecomputedStats.objects.filter(key="chemont_ic").first()
    if not ic_row or not ic_row.data:
        log.warning("No precomputed ChemOnt IC values — run recompute_all_scores first")
        return {}
    ic_values: dict[str, float] = ic_row.data

    # Step 3: Load all NP ChemOnt annotations grouped by BGC.
    np_chemont = (
        NaturalProductChemOntClass.objects
        .filter(natural_product__bgc__isnull=False)
        .values_list("natural_product__bgc_id", "chemont_id")
    )
    bgc_terms: dict[int, set[str]] = defaultdict(set)
    for bgc_id, cid in np_chemont:
        bgc_terms[bgc_id].add(cid)

    # Step 4: Compute similarity per BGC.
    bgc_similarities: dict[int, float] = {}
    for bgc_id, np_terms in bgc_terms.items():
        raw = best_match_average(query_term_ids, list(np_terms), ic_values, ont)
        score = normalize_similarity(raw, ic_values)
        if score >= similarity_threshold:
            bgc_similarities[bgc_id] = round(score, 4)

    log.info(
        "Chemical query (ChemOnt): SMILES=%s threshold=%.2f matches=%d",
        smiles[:50], similarity_threshold, len(bgc_similarities),
    )
    return bgc_similarities


SEQUENCE_QUERY_TTL = 3_600  # 1 hour

_VALID_AA = set("ACDEFGHIKLMNPQRSTVWY")


@shared_task(name="discovery.tasks.sequence_similarity_search", bind=True, acks_late=True)
def sequence_similarity_search(self, sequence: str, similarity_threshold: float) -> dict[int, float]:
    """Embed a protein sequence with ESM-C and find BGCs with similar proteins.

    Returns a dict mapping BGC id → max cosine similarity score.
    Runs in the Celery worker where torch + ESM are available.
    """
    import numpy as np
    from django.db import connection

    from discovery.models import DashboardCds

    # Validate
    seq = sequence.strip().upper()
    if not seq:
        log.warning("Empty sequence passed to sequence_similarity_search")
        return {}
    if len(seq) > 5000:
        log.warning("Sequence too long (%d AA), max 5000", len(seq))
        return {}
    invalid = set(seq) - _VALID_AA
    if invalid:
        log.warning("Invalid amino acid characters: %s", invalid)
        return {}

    # Embed
    from common_core.esmc_embedder import embed_sequences

    results = embed_sequences([seq])
    if not results or results[0] is None:
        log.error("ESM-C embedding failed for sequence (len=%d)", len(seq))
        return {}

    # Extract layer 29 (penultimate) → 1152-dim vector
    embedding = results[0][29].astype(np.float32)
    vec_str = "[" + ",".join(str(float(v)) for v in embedding) + "]"

    # pgvector cosine distance search
    max_distance = 1.0 - similarity_threshold
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT protein_sha256, (vector <=> %s::halfvec(1152)) AS distance
            FROM discovery_protein_embedding
            WHERE (vector <=> %s::halfvec(1152)) <= %s
            """,
            [vec_str, vec_str, max_distance],
        )
        rows = cursor.fetchall()

    if not rows:
        log.info("Sequence query: no protein matches at threshold=%.2f", similarity_threshold)
        return {}

    # Map matched protein_sha256 → BGC ids via DashboardCds
    matched_sha256s = {r[0]: 1.0 - r[1] for r in rows}  # sha256 → similarity
    cds_qs = (
        DashboardCds.objects.filter(protein_sha256__in=matched_sha256s.keys())
        .values_list("bgc_id", "protein_sha256")
    )

    bgc_similarities: dict[int, float] = {}
    for bgc_id, sha256 in cds_qs:
        sim = matched_sha256s[sha256]
        existing = bgc_similarities.get(bgc_id, 0.0)
        bgc_similarities[bgc_id] = max(existing, sim)

    log.info(
        "Sequence query: len=%d threshold=%.2f protein_matches=%d bgc_matches=%d",
        len(seq), similarity_threshold, len(rows), len(bgc_similarities),
    )
    return bgc_similarities
