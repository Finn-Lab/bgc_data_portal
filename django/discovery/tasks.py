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
CLUSTERING_TTL = 86_400  # 24 hours

_VALID_AA = set("ACDEFGHIKLMNPQRSTVWY")


# ── Non-Redundant BGC table builder ───────────────────────────────────────────


@shared_task(
    name="discovery.tasks.build_non_redundant_bgcs",
    bind=True,
    acks_late=True,
)
def build_non_redundant_bgcs_task(self) -> dict:
    """Rebuild the NonRedundantBGC table from latest-version BGC predictions."""
    task_id = self.request.id
    search_key = "non_redundant_bgcs"
    set_job_cache(search_key=search_key, task_id=task_id, timeout=CLUSTERING_TTL)

    from discovery.services.clustering.non_redundant import build_non_redundant_bgcs

    def _progress(phase: str, processed: int, total: int) -> None:
        set_job_cache(
            search_key=search_key,
            results={"phase": phase, "processed": processed, "total": total},
            task_id=task_id,
            timeout=CLUSTERING_TTL,
        )

    result = build_non_redundant_bgcs(progress_cb=_progress)
    set_job_cache(
        search_key=search_key,
        results={**result, "phase": "complete"},
        task_id=task_id,
        timeout=CLUSTERING_TTL,
    )
    log.info("build_non_redundant_bgcs complete (task %s): %s", task_id, result)
    return result


# ── BGC clustering pipeline ───────────────────────────────────────────────────


@shared_task(name="discovery.tasks.run_bgc_clustering", bind=True, acks_late=True)
def run_bgc_clustering_task(
    self,
    *,
    domain_sources: list[str] | None = None,
    score_weights: list[float] | None = None,
    knn_k: int | None = None,
    leiden_resolutions: list[float] | tuple[float, ...] | None = None,
    seed: int = 42,
    apply: bool = False,
    auto_reclassify: bool = True,
    reclassify_scope: str = "all_non_primary",
) -> dict:
    """Domain+adjacency hierarchical-CPM-Leiden clustering over NRBs.

    Runs the orchestrator in ``services.clustering.pipeline``; if ``apply``
    is True, writes leaf paths + umap coords to NonRedundantBGC and
    back-propagates to source DashboardBgc rows, upserts DashboardGCF rows,
    and emits MIBiG validation artifacts under
    ``settings.CLUSTERING_ARTIFACTS_DIR / <run.sha256[:12]>/``. Optionally
    chains a reclassify task to assign partial / late BGCs.
    """
    task_id = self.request.id
    search_key = f"bgc_clustering:{task_id}"
    set_job_cache(search_key=search_key, task_id=task_id, timeout=CLUSTERING_TTL)

    from discovery.services.clustering.pipeline import (
        DEFAULT_DOMAIN_SOURCES,
        DEFAULT_RESOLUTIONS,
        DEFAULT_SCORE_WEIGHTS,
        run_clustering_pipeline,
    )

    sources = tuple(s.upper() for s in (domain_sources or DEFAULT_DOMAIN_SOURCES))
    weights = (
        (float(score_weights[0]), float(score_weights[1]))
        if score_weights else DEFAULT_SCORE_WEIGHTS
    )
    resolutions = tuple(leiden_resolutions) if leiden_resolutions else DEFAULT_RESOLUTIONS

    result = run_clustering_pipeline(
        domain_sources=sources,
        score_weights=weights,
        knn_k=knn_k,
        leiden_resolutions=resolutions,
        seed=seed,
        apply=apply,
    )

    if apply and auto_reclassify and "run_pk" in result:
        async_result = reclassify_bgcs_task.apply_async(
            kwargs={
                "clustering_run_pk": result["run_pk"],
                "scope": reclassify_scope,
                "knn_k": result.get("knn_k") or knn_k or 5,
            },
            queue="scores",
        )
        result["reclassify_task_id"] = async_result.id

    set_job_cache(
        search_key=search_key,
        results=result,
        task_id=task_id,
        timeout=CLUSTERING_TTL,
    )
    log.info("run_bgc_clustering complete (task %s): %s", task_id, result)
    return result


# ── Reclassification of partial / late BGCs ───────────────────────────────────


@shared_task(name="discovery.tasks.reclassify_bgcs", bind=True, acks_late=True)
def reclassify_bgcs_task(
    self,
    *,
    clustering_run_pk: int,
    scope: str = "partial",
    knn_k: int = 5,
    min_total_similarity: float = 0.1,
) -> dict:
    """Assign leaf family paths to non-primary BGCs against an existing run.

    Re-runnable independently of ``run_bgc_clustering_task``. Updates only
    classification fields on ``DashboardBgc``; never touches the hierarchy.
    """
    task_id = self.request.id
    search_key = f"bgc_reclassify:{clustering_run_pk}"
    set_job_cache(search_key=search_key, task_id=task_id, timeout=CLUSTERING_TTL)

    from discovery.services.clustering.reclassify import reclassify_bgcs

    def _progress(payload: dict) -> None:
        set_job_cache(
            search_key=search_key,
            results={**payload, "phase": "running"},
            task_id=task_id,
            timeout=CLUSTERING_TTL,
        )

    result = reclassify_bgcs(
        clustering_run_pk=clustering_run_pk,
        scope=scope,
        knn_k=knn_k,
        min_total_similarity=min_total_similarity,
        progress_cb=_progress,
    )
    set_job_cache(
        search_key=search_key,
        results={**result, "phase": "complete"},
        task_id=task_id,
        timeout=CLUSTERING_TTL,
    )
    log.info("reclassify_bgcs complete (task %s): %s", task_id, result)
    return result


# ── Single-BGC classifier (used by uploaded BGC assessment) ───────────────────


def _classify_uploaded_bgc(embedding: list[float]) -> dict:
    """Place an ad-hoc uploaded BGC under the latest ClusteringRun's hierarchy.

    Uses BGC embedding nearest-neighbour against the run's primary BGCs
    (no pair-table lookup is possible without protein sha256s). Returns a
    dict with the inherited leaf path plus the source ClusteringRun id.
    """
    import numpy as np
    from pgvector.django import CosineDistance

    from discovery.models import BgcEmbedding, ClusteringRun, DashboardBgc

    run = ClusteringRun.objects.order_by("-created_at").first()
    if run is None:
        return {}

    nearest = (
        BgcEmbedding.objects.filter(
            bgc__classification_run_id=run.pk,
            bgc__classification_source="primary",
        )
        .annotate(distance=CosineDistance("vector", embedding))
        .order_by("distance")
        .values_list("bgc_id", "distance")
        .first()
    )
    if nearest is None:
        return {"run_id": run.pk}

    nearest_bgc_id, distance = nearest
    bgc = (
        DashboardBgc.objects.filter(pk=nearest_bgc_id)
        .values("gene_cluster_family")
        .first()
    )
    leaf = (bgc or {}).get("gene_cluster_family") or ""
    return {
        "cluster_label": leaf,
        "run_id": run.pk,
        "distance": float(distance) if distance is not None else None,
        "assigned_by_knn": True,
    }


# Backwards-compatible alias for callers that haven't been updated yet.
_classify_with_knn = _classify_uploaded_bgc


@shared_task(name="discovery.tasks.sequence_similarity_search", bind=True, acks_late=True)
def sequence_similarity_search(self, sequence: str, similarity_threshold: float) -> dict[int, float]:
    """Embed a protein sequence with ESM-C and find BGCs with similar proteins.

    Returns a dict mapping BGC id → max cosine similarity score.
    Runs in the Celery worker where torch + ESM are available.
    """
    import numpy as np
    from django.db import connection

    from discovery.models import EMBEDDING_DIM, DashboardCds

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

    # Extract final layer → 960-dim vector (matches bgc_embedding_aggregator vec[-1])
    embedding = results[0][-1].astype(np.float32)
    vec_str = "[" + ",".join(str(float(v)) for v in embedding) + "]"

    # pgvector cosine distance search
    max_distance = 1.0 - similarity_threshold
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT protein_sha256, (vector <=> %s::halfvec({EMBEDDING_DIM})) AS distance
            FROM discovery_protein_embedding
            WHERE (vector <=> %s::halfvec({EMBEDDING_DIM})) <= %s
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


@shared_task(name="discovery.tasks.update_discovery_stats", bind=True, acks_late=True)
def update_discovery_stats_task(self) -> bool:
    """Recompute platform-overview counts and append a new DiscoveryStats row."""
    from django.db import transaction

    from discovery.models import DiscoveryStats
    from discovery.services.stats import generate_discovery_stats

    stats = generate_discovery_stats()
    with transaction.atomic():
        ds = DiscoveryStats.objects.create(stats=stats)
    log.info("DiscoveryStats id=%s created: %s", ds.pk, stats)
    return True
