"""Orchestrator for the domain + adjacency hierarchical-CPM-Leiden pipeline.

Called by ``run_bgc_clustering_task`` in ``discovery/tasks.py``. Operates on
the ``NonRedundantBGC`` table (built by ``build_non_redundant_bgcs`` before
this runs), restricted to the **clusterable** subset: NRBs whose source
``DashboardBgc`` rows include at least one ``is_partial=False`` or
``is_validated=True`` member. NRBs composed exclusively of partial,
non-validated BGCs are excluded from community detection (they're handled
by ``reclassify_bgcs`` via KNN like before).

When ``apply=True``, the resulting hierarchy is persisted into
``DashboardGCF`` and back-propagated to source ``DashboardBgc`` rows of the
clusterable NRBs, and MIBiG validation artifacts are emitted under
``settings.CLUSTERING_ARTIFACTS_DIR / <run.sha256[:12]>/``.

Partial BGCs and antiSMASH calls absorbed at NRB-build time are routed
through ``reclassify_bgcs`` after the hierarchy is built.
"""

from __future__ import annotations

import hashlib
import logging
import math
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path
from typing import Sequence

log = logging.getLogger(__name__)


DEFAULT_DOMAIN_SOURCES: tuple[str, ...] = ("PFAM", "NCBIFAM")
DEFAULT_SCORE_WEIGHTS: tuple[float, float] = (0.5, 0.5)
DEFAULT_RESOLUTIONS: tuple[float, ...] = (0.03, 0.08, 0.15, 0.25)
KNN_K_FLOOR = 5


def auto_knn_k(n: int) -> int:
    """Heuristic kNN k for ``n`` nodes: ``max(KNN_K_FLOOR, ceil(ln(n)))``.

    Scales gently with graph size while keeping a sensible minimum on small
    runs. n ≤ ~150 stays at 5; n ≈ 10k → 10; n ≈ 1M → 14.
    """
    if n <= 1:
        return KNN_K_FLOOR
    return max(KNN_K_FLOOR, math.ceil(math.log(n)))


def _safe_version(pkg: str) -> str:
    try:
        return _pkg_version(pkg)
    except PackageNotFoundError:
        return ""


def run_clustering_pipeline(
    *,
    domain_sources: Sequence[str] = DEFAULT_DOMAIN_SOURCES,
    score_weights: tuple[float, float] = DEFAULT_SCORE_WEIGHTS,
    knn_k: int | None = None,
    leiden_resolutions: Sequence[float] = DEFAULT_RESOLUTIONS,
    seed: int = 42,
    apply: bool = False,
    score_nrbs: bool = True,
) -> dict:
    """Run the full domain/adjacency clustering pipeline.

    Returns a result dict with ``run_pk``, ``sha256``, counts, and (when
    ``apply=True``) ``artifacts_dir`` pointing at the MIBiG analysis output.
    The caller (Celery task / management command) is responsible for chaining
    a reclassify step.
    """
    from django.db.models import Q
    from django.utils import timezone

    from discovery.models import (
        BgcDomain,
        ClusteringRun,
        DashboardBgc,
        DashboardGCF,
        NonRedundantBGC,
    )
    from discovery.services.clustering.adjacency import (
        build_nrb_adjacency_pair_matrix,
    )
    from discovery.services.clustering.bgc_similarity import (
        compute_composite_similarity,
    )
    from discovery.services.clustering.knn_graph import build_knn_graph
    from discovery.services.clustering.layout import compute_2d_layout
    from discovery.services.clustering.leiden import run_hierarchical_leiden
    from discovery.services.clustering.membership import build_nrb_domain_matrix
    from discovery.services.clustering.paths import build_ltree_paths
    from discovery.services.clustering.representative import pick_medoid

    leiden_resolutions = tuple(leiden_resolutions)
    upper_sources = tuple(sorted({s.upper() for s in domain_sources}))
    weights = (float(score_weights[0]), float(score_weights[1]))

    # ── 0. Pre-flight: NRB table must be populated ───────────────────────
    if not NonRedundantBGC.objects.exists():
        return {"error": "NonRedundantBGC table is empty — run build_non_redundant_bgcs first"}

    # Clusterable subset: NRBs with at least one non-partial-or-validated
    # source BGC. Partial+unvalidated-only NRBs are reclassified via KNN
    # downstream and never drive community detection.
    clusterable_nrb_ids = list(
        DashboardBgc.objects.filter(non_redundant_bgc__isnull=False)
        .filter(Q(is_partial=False) | Q(is_validated=True))
        .values_list("non_redundant_bgc_id", flat=True)
        .distinct()
    )
    if not clusterable_nrb_ids:
        return {"error": "no clusterable NRBs (all NRBs are partial+unvalidated)"}

    # ── 1. Domain matrix ─────────────────────────────────────────────────
    M_domains, nrb_ids, domain_accs = build_nrb_domain_matrix(
        sources=upper_sources, nrb_ids_subset=clusterable_nrb_ids,
    )
    if M_domains.shape[0] == 0:
        return {"error": "no NRBs with selected-source domains found"}

    # ── 2. Adjacency-pair matrix (aligned on nrb_ids) ───────────────────
    M_pairs, nrb_ids_adj, pair_vocab = build_nrb_adjacency_pair_matrix(
        sources=upper_sources,
        nrb_ids_subset=nrb_ids.tolist(),
    )
    M_pairs = _align_rows(M_pairs, nrb_ids_adj, nrb_ids)

    # ── 3. Composite weighted-mean Dice similarity ──────────────────────
    sim = compute_composite_similarity(
        M_domains, M_pairs, weights=weights, prune_below=0.05,
    )

    # ── 4. Union top-k kNN (auto-pick k when not supplied) ──────────────
    effective_k = int(knn_k) if knn_k is not None else auto_knn_k(M_domains.shape[0])
    log.info("kNN k = %d (n_nrbs=%d, supplied=%s)", effective_k, M_domains.shape[0], knn_k)
    graph = build_knn_graph(sim, k=effective_k)

    # ── 5. Hierarchical Leiden under CPM ─────────────────────────────────
    levels = run_hierarchical_leiden(graph, resolutions=leiden_resolutions, seed=seed)

    # ── 6. 2D layout ─────────────────────────────────────────────────────
    coords = compute_2d_layout(graph, sim, seed=seed)

    # ── 7. ltree paths ───────────────────────────────────────────────────
    paths_per_row, gcf_nodes = build_ltree_paths(levels, nrb_ids)

    # ── 8. Run dedup + persist ───────────────────────────────────────────
    n_domain_rows = BgcDomain.objects.filter(ref_db__in=upper_sources).count()
    domain_max_id = (
        BgcDomain.objects.filter(ref_db__in=upper_sources)
        .order_by("-id").values_list("id", flat=True).first()
        or 0
    )
    nrb_max_id = (
        NonRedundantBGC.objects.order_by("-id").values_list("id", flat=True).first() or 0
    )
    sha = _compute_run_sha(
        sources=upper_sources,
        weights=weights,
        knn_k=effective_k,
        leiden_resolutions=leiden_resolutions,
        seed=seed,
        nrb_etag=f"{NonRedundantBGC.objects.count()}:{nrb_max_id}",
        domain_etag=f"{n_domain_rows}:{domain_max_id}",
    )
    run, created = ClusteringRun.objects.update_or_create(
        sha256=sha,
        defaults={
            "domain_sources": list(upper_sources),
            "score_weights": list(weights),
            "knn_k": effective_k,
            "leiden_resolutions": list(leiden_resolutions),
            "seed": seed,
            "n_proteins": 0,  # clustering no longer uses proteins
            "n_nrbs": int(M_domains.shape[0]),
            "n_levels": len(leiden_resolutions),
            "n_root_communities": sum(1 for n in gcf_nodes if n.level == 0),
            "n_leaf_communities": sum(
                1 for n in gcf_nodes if n.level == len(leiden_resolutions) - 1
            ),
            "igraph_version": _safe_version("igraph"),
            "leidenalg_version": _safe_version("leidenalg"),
            "umap_version": _safe_version("umap-learn"),
            "scipy_version": _safe_version("scipy"),
        },
    )
    log.info(
        "%s ClusteringRun pk=%s sha=%s...",
        "Created" if created else "Updated", run.pk, sha[:12],
    )

    # ── 9. Replace DashboardGCF rows; pick medoids ──────────────────────
    DashboardGCF.objects.filter(clustering_run=run).delete()
    gcf_rows: list[DashboardGCF] = []
    for node in gcf_nodes:
        medoid_v = pick_medoid(node.member_indices, sim)
        medoid_nrb_id = int(nrb_ids[medoid_v])
        gcf_rows.append(
            DashboardGCF(
                clustering_run=run,
                family_path=node.family_path,
                parent_path=node.parent_path,
                level=node.level,
                # representative_bgc still FKs DashboardBgc; pick any source
                # BGC of the medoid NRB so the API can surface a concrete BGC.
                representative_bgc_id=_pick_source_bgc(medoid_nrb_id),
                member_count=len(node.member_indices),
                descendant_count=0,
            )
        )
    DashboardGCF.objects.bulk_create(gcf_rows, batch_size=5_000)

    parent_to_children: dict[str, int] = {}
    for node in gcf_nodes:
        if node.parent_path:
            parent_to_children[node.parent_path] = (
                parent_to_children.get(node.parent_path, 0) + 1
            )
    if parent_to_children:
        rows_to_update = list(
            DashboardGCF.objects.filter(
                clustering_run=run, family_path__in=list(parent_to_children.keys()),
            )
        )
        for row in rows_to_update:
            row.descendant_count = parent_to_children.get(row.family_path, 0)
        DashboardGCF.objects.bulk_update(
            rows_to_update, ["descendant_count"], batch_size=5_000,
        )

    # ── 10. Apply: NRB + source DashboardBgc back-propagation ────────────
    gcf_updated = 0
    artifacts_dir = None
    result_extra_scoring: dict | None = None
    leaf_paths: list[str] = [paths_per_row[int(nrb_id)] for nrb_id in nrb_ids.tolist()]
    if apply:
        now = timezone.now()

        # Update NRB rows in batches.
        nrb_lookup = {int(nrb_id): i for i, nrb_id in enumerate(nrb_ids.tolist())}
        nrb_rows = list(NonRedundantBGC.objects.filter(id__in=list(nrb_lookup.keys())))
        for nrb in nrb_rows:
            i = nrb_lookup[nrb.id]
            nrb.gene_cluster_family = leaf_paths[i]
            nrb.umap_x = float(coords[i, 0])
            nrb.umap_y = float(coords[i, 1])
            nrb.classification_run = run
            nrb.classified_at = now
        NonRedundantBGC.objects.bulk_update(
            nrb_rows,
            ["gene_cluster_family", "umap_x", "umap_y", "classification_run", "classified_at"],
            batch_size=5_000,
        )

        # Back-propagate to source DashboardBgcs (one bulk_update per NRB
        # batch so umap_x/y inherit cleanly).
        update_batch: list[DashboardBgc] = []
        source_bgcs = (
            DashboardBgc.objects
            .filter(non_redundant_bgc_id__in=list(nrb_lookup.keys()))
            .only(
                "id", "non_redundant_bgc_id", "umap_x", "umap_y",
                "gene_cluster_family", "classification_source",
                "classification_run_id", "classified_at",
            )
        )
        for bgc in source_bgcs:
            i = nrb_lookup[bgc.non_redundant_bgc_id]
            bgc.umap_x = float(coords[i, 0])
            bgc.umap_y = float(coords[i, 1])
            bgc.gene_cluster_family = leaf_paths[i]
            bgc.classification_source = "primary"
            bgc.classification_run = run
            bgc.classified_at = now
            update_batch.append(bgc)
        DashboardBgc.objects.bulk_update(
            update_batch,
            [
                "umap_x", "umap_y", "gene_cluster_family",
                "classification_source", "classification_run", "classified_at",
            ],
            batch_size=10_000,
        )
        gcf_updated = len(update_batch)

        # ── 11. MIBiG analysis artifacts ─────────────────────────────────
        from discovery.services.clustering.mibig_analysis import emit_run_artifacts

        try:
            artifacts_dir = str(emit_run_artifacts(
                run,
                nrb_ids=nrb_ids.tolist(),
                leaf_paths=leaf_paths,
                coords=coords,
            ))
        except Exception:  # noqa: BLE001 — never block the run on plot errors
            log.exception("MIBiG analysis failed; clustering run is intact")

        # ── 12. NRB scoring (novelty + domain novelty) ───────────────────
        # Reuses the in-memory composite-Dice matrix and the per-row leaf
        # paths produced above. Also persists those matrices so a follow-up
        # standalone scoring run (e.g. after reclassify projects partials)
        # doesn't have to rebuild them.
        if score_nrbs:
            from discovery.services.clustering.nrb_scoring import (
                persist_scoring_cache,
                score_primary_nrbs,
            )

            if artifacts_dir is not None:
                try:
                    persist_scoring_cache(
                        artifacts_dir=Path(artifacts_dir),
                        sim=sim,
                        M_domains=M_domains,
                        M_pairs=M_pairs,
                        nrb_ids=nrb_ids,
                        domain_accs=domain_accs,
                        pair_vocab=pair_vocab,
                        leaf_paths=leaf_paths,
                    )
                except Exception:  # noqa: BLE001 — cache miss is non-fatal
                    log.exception("Failed to persist NRB scoring cache")

            try:
                scoring_result = score_primary_nrbs(
                    sim=sim,
                    M_domains=M_domains,
                    nrb_ids=nrb_ids,
                    leaf_paths=leaf_paths,
                    run=run,
                )
                result_extra_scoring = scoring_result
            except Exception:  # noqa: BLE001 — never block apply on scoring
                log.exception("score_primary_nrbs failed; NRB rows left unscored")
                result_extra_scoring = None
        else:
            result_extra_scoring = None

    result = {
        "run_pk": run.pk,
        "created": created,
        "sha256": sha,
        "n_nrbs": int(M_domains.shape[0]),
        "n_domains": int(M_domains.shape[1]),
        "n_pairs_vocab": int(M_pairs.shape[1]),
        "knn_k": effective_k,
        "n_levels": len(leiden_resolutions),
        "n_leaf_communities": sum(
            1 for n in gcf_nodes if n.level == len(leiden_resolutions) - 1
        ),
        "gcf_updated": gcf_updated,
    }
    if artifacts_dir is not None:
        result["artifacts_dir"] = artifacts_dir
    if result_extra_scoring is not None:
        result["nrb_scoring"] = result_extra_scoring
    return result


def _align_rows(M_pairs, nrb_ids_adj, nrb_ids_target):
    """Project ``M_pairs`` onto the row ordering of ``nrb_ids_target``.

    The adjacency builder can return fewer rows than the domain builder (an
    NRB may have no source CDS-linked domains, producing an empty adjacency
    sequence). Missing rows become all-zero in the aligned matrix.
    """
    import numpy as np
    import scipy.sparse as sp

    n_target = len(nrb_ids_target)
    n_cols = M_pairs.shape[1]

    if M_pairs.shape[0] == n_target and (
        n_target == 0 or np.array_equal(nrb_ids_adj, nrb_ids_target)
    ):
        return M_pairs

    target_index = {int(x): i for i, x in enumerate(nrb_ids_target.tolist())}
    row_map = {i: target_index[int(x)] for i, x in enumerate(nrb_ids_adj.tolist())
               if int(x) in target_index}

    if not row_map:
        return sp.csr_matrix((n_target, n_cols), dtype=M_pairs.dtype)

    coo = M_pairs.tocoo(copy=False)
    keep = np.fromiter((r in row_map for r in coo.row), dtype=bool, count=coo.nnz)
    new_rows = np.fromiter(
        (row_map[r] for r in coo.row[keep]),
        dtype=np.int64,
        count=int(keep.sum()),
    )
    return sp.csr_matrix(
        (coo.data[keep], (new_rows, coo.col[keep])),
        shape=(n_target, n_cols),
        dtype=M_pairs.dtype,
    )


def _pick_source_bgc(nrb_id: int) -> int | None:
    """Pick the lowest-id source DashboardBgc for an NRB (deterministic)."""
    from discovery.models import DashboardBgc

    return (
        DashboardBgc.objects.filter(non_redundant_bgc_id=nrb_id)
        .order_by("id")
        .values_list("id", flat=True)
        .first()
    )


def _compute_run_sha(
    *,
    sources: tuple[str, ...],
    weights: tuple[float, float],
    knn_k: int,
    leiden_resolutions: tuple[float, ...],
    seed: int,
    nrb_etag: str,
    domain_etag: str,
) -> str:
    """Return a stable sha256 hex digest for ``ClusteringRun.update_or_create``."""
    payload = "|".join([
        f"sources={','.join(sources)}",
        f"weights={weights[0]:.6f},{weights[1]:.6f}",
        f"k={knn_k}",
        "res=" + ",".join(f"{r:.6f}" for r in leiden_resolutions),
        f"seed={seed}",
        f"nrb_etag={nrb_etag}",
        f"domain_etag={domain_etag}",
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
