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

KEYWORD_TTL = 300  # 5 minutes
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
    IC-based (Resnik / Best Match Average) similarity against each iBGC's
    pooled ChemOnt annotations. iBGC membership is decided by range
    overlap: each CDS contributes to the iBGC whose ``bgc_range`` overlaps
    its ``cds_range`` on the same contig.

    Returns a dict mapping iBGC id → max similarity score.
    """
    from collections import defaultdict

    from common_core.chemont.classifier import classify_smiles
    from common_core.chemont.ontology import get_ontology
    from common_core.chemont.similarity import best_match_average, normalize_similarity
    from django.db import connection

    from discovery.models import PrecomputedStats

    ont = get_ontology()

    query_classes = classify_smiles(smiles.strip(), ontology=ont)
    if not query_classes:
        log.warning("No ChemOnt matches for SMILES: %s", smiles[:50])
        return {}
    query_term_ids = [c.chemont_id for c in query_classes]

    ic_row = PrecomputedStats.objects.filter(key="chemont_ic").first()
    if not ic_row or not ic_row.data:
        log.warning("No precomputed ChemOnt IC values — run recompute_all_scores first")
        return {}
    ic_values: dict[str, float] = ic_row.data

    # Join CDS ChemOnt → CDS → owning iBGC via contig + range overlap.
    # iBGCs are disjoint inside a cBGC and cBGCs are disjoint on a contig,
    # so each CDS overlaps at most one iBGC.
    ibgc_terms: dict[int, set[str]] = defaultdict(set)
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT i.id AS ibgc_id, ch.chemont_id
            FROM discovery_cds_chemont ch
            JOIN discovery_cds c ON c.id = ch.cds_id
            JOIN discovery_ibgc i
              ON i.contig_id = c.contig_id
             AND i.bgc_range && c.cds_range
            """
        )
        for ibgc_id, cid in cur.fetchall():
            ibgc_terms[ibgc_id].add(cid)

    ibgc_similarities: dict[int, float] = {}
    for ibgc_id, np_terms in ibgc_terms.items():
        raw = best_match_average(query_term_ids, list(np_terms), ic_values, ont)
        score = normalize_similarity(raw, ic_values)
        if score >= similarity_threshold:
            ibgc_similarities[ibgc_id] = round(score, 4)

    log.info(
        "Chemical query (ChemOnt): SMILES=%s threshold=%.2f matches=%d",
        smiles[:50], similarity_threshold, len(ibgc_similarities),
    )
    return ibgc_similarities


SEQUENCE_QUERY_TTL = 3_600  # 1 hour
CLUSTERING_TTL = 86_400  # 24 hours

_VALID_AA = set("ACDEFGHIKLMNPQRSTVWY")


# ── Integrated BGC table builder ───────────────────────────────────────────


@shared_task(
    name="discovery.tasks.build_integrated_bgcs",
    bind=True,
    acks_late=True,
)
def build_integrated_bgcs_task(self) -> dict:
    """Rebuild the IntegratedBgc table from latest-version SourceBgcPrediction rows."""
    task_id = self.request.id
    search_key = "integrated_bgcs"
    set_job_cache(search_key=search_key, task_id=task_id, timeout=CLUSTERING_TTL)

    from discovery.services.clustering.integrated import build_integrated_bgcs

    def _progress(phase: str, processed: int, total: int) -> None:
        set_job_cache(
            search_key=search_key,
            results={"phase": phase, "processed": processed, "total": total},
            task_id=task_id,
            timeout=CLUSTERING_TTL,
        )

    result = build_integrated_bgcs(progress_cb=_progress)
    set_job_cache(
        search_key=search_key,
        results={**result, "phase": "complete"},
        task_id=task_id,
        timeout=CLUSTERING_TTL,
    )
    log.info("build_integrated_bgcs complete (task %s): %s", task_id, result)
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
    score_ibgcs: bool = True,
) -> dict:
    """Domain+adjacency hierarchical-CPM-Leiden clustering over iBGCs.

    Runs the orchestrator in ``services.clustering.pipeline``. If ``apply``
    is True, writes leaf paths + umap coords to ``IntegratedBgc``, upserts
    ``DashboardGCF`` rows, and emits MIBiG validation artifacts under
    ``settings.CLUSTERING_ARTIFACTS_DIR / <run.sha256[:12]>/``. Optionally
    chains a reclassify task to assign partial iBGCs and a projection task
    that fills umap / leaf path / novelty for partials.
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
        score_ibgcs=score_ibgcs,
    )

    if apply and auto_reclassify and "run_pk" in result:
        reclassify_kwargs = {
            "clustering_run_pk": result["run_pk"],
            "scope": reclassify_scope,
            "knn_k": result.get("knn_k") or knn_k or 5,
        }
        # Chain projection after reclassify when scoring is on, so partial
        # iBGCs get coordinates + leaf paths populated immediately. Using a
        # link signature keeps the projection task from racing reclassify.
        if score_ibgcs:
            project_sig = project_partial_ibgcs_task.si(
                clustering_run_pk=result["run_pk"],
                knn_k=result.get("knn_k") or knn_k or 5,
            ).set(queue="scores")
            async_result = reclassify_bgcs_task.apply_async(
                kwargs=reclassify_kwargs, queue="scores", link=project_sig,
            )
            result["project_partial_ibgcs_chained"] = True
        else:
            async_result = reclassify_bgcs_task.apply_async(
                kwargs=reclassify_kwargs, queue="scores",
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
    """Assign leaf family paths to partial / non-primary iBGCs against an existing run.

    Re-runnable independently of ``run_bgc_clustering_task``. Updates only
    classification fields on ``IntegratedBgc``; never touches the hierarchy.
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


# ── Partial-iBGC projection (umap coords + scores for non-primary iBGCs) ───────


@shared_task(
    name="discovery.tasks.project_partial_ibgcs", bind=True, acks_late=True,
)
def project_partial_ibgcs_task(
    self,
    *,
    clustering_run_pk: int,
    knn_k: int = 5,
    min_total_similarity: float = 0.1,
) -> dict:
    """Project partial / non-primary iBGCs onto a ClusteringRun's UMAP.

    Writes ``umap_x`` / ``umap_y`` (similarity-weighted average of top-K
    primary neighbours), ``gene_cluster_family``, ``novelty_score``, and
    ``domain_novelty`` on every ``IntegratedBgc`` whose ``classification_run``
    differs from the target run. Marks ``umap_projected = True``.
    """
    task_id = self.request.id
    search_key = f"bgc_project_partial:{clustering_run_pk}"
    set_job_cache(search_key=search_key, task_id=task_id, timeout=CLUSTERING_TTL)

    from discovery.services.clustering.ibgc_scoring import project_partial_ibgcs

    def _progress(payload: dict) -> None:
        set_job_cache(
            search_key=search_key,
            results={**payload, "phase": "running"},
            task_id=task_id,
            timeout=CLUSTERING_TTL,
        )

    result = project_partial_ibgcs(
        clustering_run_pk=clustering_run_pk,
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
    log.info(
        "project_partial_ibgcs complete (task %s): %s", task_id, result
    )
    return result


@shared_task(name="discovery.tasks.sequence_similarity_search", bind=True, acks_late=True)
def sequence_similarity_search(
    self,
    sequence: str,
    min_bitscore: float = 30.0,
    min_pident: float = 70.0,
    min_qcov: float = 70.0,
) -> dict[int, dict[str, float | str]]:
    """Run phmmer for a query protein against the on-disk reference DB and
    return iBGCs that contain a matching protein passing all three filters.

    Returns ``{ibgc_id: {"bitscore": ..., "pident": ..., "qcoverage": ...,
    "protein_id": ...}}`` where the values come from the highest-bitscore
    matched protein within that iBGC. The DESC sort on ``similarity_score``
    continues to work — ``similarity_score`` is set to ``bitscore`` at the
    API layer.

    A CDS belongs to an iBGC by genomic-range overlap on its contig
    (iBGCs are disjoint within a cBGC, so each CDS overlaps at most one iBGC).
    """
    from django.db import connection

    from discovery.services.protein_search import phmmer_search
    from discovery.services.protein_search.index import IndexNotBuiltError

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

    try:
        sha256_metrics = phmmer_search(
            seq,
            min_bitscore=min_bitscore,
            min_pident=min_pident,
            min_qcov=min_qcov,
            cpus=1,
        )
    except IndexNotBuiltError:
        log.error(
            "Protein search index not built; "
            "run `python manage.py build_protein_search_index --rebuild`."
        )
        raise

    if not sha256_metrics:
        log.info(
            "Sequence query: no protein hits (min_bitscore=%g, min_pident=%g, min_qcov=%g)",
            min_bitscore, min_pident, min_qcov,
        )
        return {}

    # Join matched CDS to their owning iBGC via contig + range overlap.
    sha_list = list(sha256_metrics.keys())
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT i.id, c.protein_sha256, c.protein_id_str
            FROM discovery_cds c
            JOIN discovery_ibgc i
              ON i.contig_id = c.contig_id
             AND i.bgc_range && c.cds_range
            WHERE c.protein_sha256 = ANY(%s::text[])
            """,
            [sha_list],
        )
        rows = cur.fetchall()

    ibgc_best: dict[int, tuple["ProteinHitMetrics", str]] = {}
    for ibgc_id, sha256, protein_id in rows:
        m = sha256_metrics[sha256]
        existing = ibgc_best.get(ibgc_id)
        if existing is None or m.bitscore > existing[0].bitscore:
            ibgc_best[ibgc_id] = (m, protein_id)

    ibgc_scores: dict[int, dict[str, float | str]] = {
        ibgc_id: {
            "bitscore": float(m.bitscore),
            "pident": float(m.pident),
            "qcoverage": float(m.qcoverage),
            "protein_id": protein_id,
        }
        for ibgc_id, (m, protein_id) in ibgc_best.items()
    }

    log.info(
        "Sequence query: len=%d min_bitscore=%g min_pident=%g min_qcov=%g protein_hits=%d ibgc_matches=%d",
        len(seq), min_bitscore, min_pident, min_qcov,
        len(sha256_metrics), len(ibgc_scores),
    )
    return ibgc_scores


@shared_task(name="discovery.tasks.update_protein_search_index", bind=True, acks_late=True)
def update_protein_search_index_task(self, rebuild: bool = False) -> dict:
    """Append new proteins to the on-disk phmmer index (or rebuild from scratch).

    Enqueued automatically at the end of ``load_discovery_data``; can also be
    invoked manually via ``python manage.py build_protein_search_index``.
    """
    from discovery.services.protein_search.build import rebuild_index, update_index

    stats = rebuild_index() if rebuild else update_index()
    log.info(
        "update_protein_search_index_task: total=%d added=%d elapsed=%.1fs version=%d",
        stats.total_in_db, stats.newly_added, stats.elapsed_seconds, stats.version,
    )
    return {
        "total_in_db": stats.total_in_db,
        "already_indexed": stats.already_indexed,
        "newly_added": stats.newly_added,
        "elapsed_seconds": stats.elapsed_seconds,
        "version": stats.version,
    }


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


# ── Ephemeral asset upload ──────────────────────────────────────────────────


@shared_task(name="discovery.tasks.process_asset_upload", bind=True, acks_late=True)
def process_asset_upload_task(self, token: str) -> dict:
    """Validate, parse, build virtual iBGCs and project an uploaded asset.

    The upload bytes are read from Redis (``asset:{token}:upload``) — the API
    handler parks them there because the worker runs in a separate pod with
    its own filesystem. The key is dropped in ``finally`` so a successful
    run doesn't pin ~100 MB until the TTL elapses.
    """
    from discovery.services.asset_upload import cache as asset_cache
    from discovery.services.asset_upload.parse import parse_asset_tar
    from discovery.services.asset_upload.project import project_asset
    from discovery.services.asset_upload.validate import (
        AssetValidationError,
        inspect_tarball,
    )

    task_id = self.request.id
    asset_cache.mark_running(token, task_id=task_id, progress={"step": "validate"})

    try:
        raw = asset_cache.read_upload(token)
        if raw is None:
            error = "Upload bytes missing from cache (token expired or evicted)"
            asset_cache.mark_failed(token, task_id=task_id, error=error)
            return {"token": token, "state": "FAILED", "error": error}

        try:
            validated = inspect_tarball(raw)
            asset_cache.mark_running(token, task_id=task_id, progress={"step": "parse"})
            data = parse_asset_tar(validated)
        except AssetValidationError as exc:
            asset_cache.mark_failed(token, task_id=task_id, error=str(exc))
            return {"token": token, "state": "FAILED", "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 — never let the UI hang on a 5-min poll timeout
            log.exception("process_asset_upload: unexpected error during validate/parse")
            asset_cache.mark_failed(
                token,
                task_id=task_id,
                error=f"Could not parse upload: {exc}",
            )
            return {"token": token, "state": "FAILED", "error": str(exc)}

        asset_cache.mark_running(token, task_id=task_id, progress={"step": "project"})
        try:
            summary = project_asset(token, data, task_id=task_id)
        except Exception as exc:  # noqa: BLE001 — surface to caller via cache
            log.exception("process_asset_upload: projection failed")
            asset_cache.mark_failed(token, task_id=task_id, error=str(exc))
            return {"token": token, "state": "FAILED", "error": str(exc)}

        return {"token": token, "state": "SUCCESS", "summary": summary}
    finally:
        asset_cache.evict_upload(token)
