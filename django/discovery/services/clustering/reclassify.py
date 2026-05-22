"""Post-hoc KNN reclassification for non-primary iBGCs.

The primary clustering pass operates on the *clusterable* subset of
``IntegratedBgc`` rows — those whose ``SourceBgcPrediction`` set contains at
least one non-partial or validated member. Partial-only iBGCs are handled
here via KNN projection against the run's primary iBGCs.

In the v2 schema, leaf path / UMAP / novelty fields live on
``IntegratedBgc`` (not on the per-tool ``SourceBgcPrediction``), so the
projection target is the iBGC. The actual numerical work is shared with
the inline post-clustering hook and lives in
:func:`discovery.services.clustering.ibgc_scoring.project_partial_ibgcs`.
This module wraps that call so a management command can:

  * project partials against an arbitrary ``ClusteringRun``, and
  * refresh ``DashboardGCF`` aggregates against the now-complete iBGC
    classification.

Re-runnable independently — never reshapes the hierarchy.
"""

from __future__ import annotations

import logging
from collections import defaultdict

log = logging.getLogger(__name__)


SCOPE_PARTIAL = "partial"
SCOPE_STALE = "stale"
SCOPE_ALL_NON_PRIMARY = "all_non_primary"
ALLOWED_SCOPES = (SCOPE_PARTIAL, SCOPE_STALE, SCOPE_ALL_NON_PRIMARY)


def reclassify_bgcs(
    *,
    clustering_run_pk: int,
    scope: str = SCOPE_PARTIAL,
    knn_k: int = 5,
    min_total_similarity: float = 0.1,
    chunk_size: int = 256,
    progress_cb=None,
) -> dict:
    """Project non-primary iBGCs against the primary set of ``clustering_run_pk``.

    ``scope`` is retained as an interface contract for the management
    command. In practice all three scopes collapse to the same set in the
    v2 schema (iBGCs not currently tied to the run via
    ``classification_run_id``), so the parameter is validated but does not
    branch the implementation. The actual numerical work is delegated to
    :func:`discovery.services.clustering.ibgc_scoring.project_partial_ibgcs`.
    """
    from discovery.services.clustering.ibgc_scoring import project_partial_ibgcs

    if scope not in ALLOWED_SCOPES:
        raise ValueError(f"scope must be one of {ALLOWED_SCOPES}, got {scope!r}")

    result = project_partial_ibgcs(
        clustering_run_pk=clustering_run_pk,
        knn_k=knn_k,
        min_total_similarity=min_total_similarity,
        chunk_size=chunk_size,
        progress_cb=progress_cb,
    )

    _refresh_gcf_aggregates(clustering_run_pk)

    return {
        "clustering_run_pk": result["clustering_run_pk"],
        "scope": scope,
        "classified": result["projected"],
        "unclassified": result["skipped"],
        "skipped": 0,
    }


def _align_rows(M, source_ids, target_ids, *, ncols_keep=False):
    """Re-key a sparse matrix's row labels to a target ordering.

    ``ncols_keep`` is retained for backwards-compatible callers (it had no
    effect on output in either schema — column count is fixed by ``M``).
    """
    import numpy as np
    import scipy.sparse as sp

    del ncols_keep  # unused; kept for signature compatibility

    n_target = len(target_ids)
    n_cols = M.shape[1]
    if M.shape[0] == n_target and (
        n_target == 0 or np.array_equal(source_ids, target_ids)
    ):
        return M

    target_index = {int(x): i for i, x in enumerate(target_ids.tolist())}
    row_map = {i: target_index[int(x)] for i, x in enumerate(source_ids.tolist())
               if int(x) in target_index}
    if not row_map:
        return sp.csr_matrix((n_target, n_cols), dtype=M.dtype)

    coo = M.tocoo(copy=False)
    keep = np.fromiter((r in row_map for r in coo.row), dtype=bool, count=coo.nnz)
    new_rows = np.fromiter(
        (row_map[r] for r in coo.row[keep]),
        dtype=np.int64,
        count=int(keep.sum()),
    )
    return sp.csr_matrix(
        (coo.data[keep], (new_rows, coo.col[keep])),
        shape=(n_target, n_cols),
        dtype=M.dtype,
    )


def _refresh_gcf_aggregates(clustering_run_pk: int) -> None:
    """Recount ``member_count`` / ``validated_count`` / ``mean_novelty`` for the run.

    Members are now ``IntegratedBgc`` rows (one row per iBGC). An iBGC is
    "validated" if any of its ``SourceBgcPrediction`` rows is validated.
    """
    from discovery.models import (
        DashboardGCF,
        IntegratedBgc,
        SourceBgcPrediction,
    )

    gcf_qs = DashboardGCF.objects.filter(clustering_run_id=clustering_run_pk)
    nodes = list(gcf_qs.values_list("id", "family_path"))
    if not nodes:
        return

    validated_ibgc_ids = set(
        SourceBgcPrediction.objects.filter(
            is_validated=True, integrated_bgc__isnull=False,
        ).values_list("integrated_bgc_id", flat=True)
    )

    ibgc_rows = list(
        IntegratedBgc.objects.exclude(gene_cluster_family="").values_list(
            "id", "gene_cluster_family", "novelty_score",
        )
    )

    counts: dict[str, list[tuple[bool, float]]] = defaultdict(list)
    for ibgc_id, leaf_path, novelty in ibgc_rows:
        is_validated = ibgc_id in validated_ibgc_ids
        novelty_val = float(novelty) if novelty is not None else 0.0
        parts = leaf_path.split(".")
        for d in range(1, len(parts) + 1):
            prefix = ".".join(parts[:d])
            counts[prefix].append((is_validated, novelty_val))

    update_batch: list[DashboardGCF] = []
    for gcf_id, family_path in nodes:
        members = counts.get(family_path, [])
        member_count = len(members)
        validated_count = sum(1 for v, _ in members if v)
        mean_novelty = (
            sum(n for _, n in members) / member_count if member_count else 0.0
        )
        update_batch.append(
            DashboardGCF(
                id=gcf_id,
                member_count=member_count,
                validated_count=validated_count,
                mean_novelty=mean_novelty,
            )
        )

    if update_batch:
        DashboardGCF.objects.bulk_update(
            update_batch,
            ["member_count", "validated_count", "mean_novelty"],
            batch_size=5_000,
        )
