"""Post-hoc KNN reclassification for non-primary BGCs.

The primary clustering pass operates on the *clusterable* subset of
``NonRedundantBGC`` rows — those with at least one non-partial or validated
source BGC. This module assigns family paths to every other ``DashboardBgc``
via the same composite Dice metric: compute similarity between each query
BGC and every primary NRB of a given ``ClusteringRun``, take top-K, and
inherit the most common leaf family path weighted by similarity.

Re-runnable independently — never reshapes the hierarchy and never modifies
``DashboardBgc.non_redundant_bgc`` (partials keep the NRB row assigned by
``build_non_redundant_bgcs``; this step only writes their family path).
"""

from __future__ import annotations

import logging
from collections import Counter

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
    """Assign a leaf family path to every DashboardBgc matching ``scope``.

    Parameters
    ----------
    clustering_run_pk:
        ``ClusteringRun`` pk whose hierarchy to inherit.
    scope:
        Which DashboardBgcs to (re)classify — see ``SCOPE_*`` constants.
    knn_k:
        Number of nearest primary NRBs whose leaf paths vote for the
        assignment.
    min_total_similarity:
        Minimum sum of top-K similarities required to commit an assignment.
        Below this the BGC remains ``classification_source="unclassified"``.
    """
    import numpy as np
    import scipy.sparse as sp
    from django.utils import timezone

    from discovery.models import (
        ClusteringRun,
        DashboardBgc,
        NonRedundantBGC,
    )
    from discovery.services.clustering.adjacency import (
        build_nrb_adjacency_pair_matrix,
    )
    from discovery.services.clustering.bgc_similarity import (
        compute_composite_similarity,
    )
    from discovery.services.clustering.membership import build_nrb_domain_matrix

    if scope not in ALLOWED_SCOPES:
        raise ValueError(f"scope must be one of {ALLOWED_SCOPES}, got {scope!r}")

    run = ClusteringRun.objects.get(pk=clustering_run_pk)
    sources = tuple(run.domain_sources) or ("PFAM", "NCBIFAM","TIGRFAM")
    weights = tuple(run.score_weights) if run.score_weights else (0.5, 0.5)

    # ── 1. Determine query DashboardBgcs ─────────────────────────────────
    qs = DashboardBgc.objects.all()
    if scope == SCOPE_PARTIAL:
        # Validated partials are admitted as primary NRBs upstream, so exclude
        # them here to avoid clobbering classification_source='primary' with 'knn'.
        qs = qs.filter(is_partial=True, is_validated=False).exclude(
            classification_run_id=run.pk
        )
    elif scope == SCOPE_STALE:
        qs = qs.filter(non_redundant_bgc__isnull=True, is_partial=False).exclude(
            classification_run_id=run.pk
        )
    elif scope == SCOPE_ALL_NON_PRIMARY:
        qs = qs.exclude(
            classification_source="primary", classification_run_id=run.pk
        )

    query_bgc_ids = list(qs.values_list("id", flat=True))
    if not query_bgc_ids:
        log.info("reclassify_bgcs: no BGCs to classify (scope=%s)", scope)
        return _result(run.pk, scope, 0, 0, 0)

    # ── 2. Primary NRB ids + their leaf paths from this run ──────────────
    primary_qs = NonRedundantBGC.objects.filter(
        classification_run_id=run.pk,
    ).exclude(gene_cluster_family="")
    primary_ids = list(primary_qs.values_list("id", flat=True))
    primary_paths = dict(primary_qs.values_list("id", "gene_cluster_family"))

    if not primary_ids:
        log.warning(
            "reclassify_bgcs: ClusteringRun pk=%s has no primary NRBs", run.pk
        )
        return _result(run.pk, scope, 0, 0, len(query_bgc_ids))

    # ── 3. Build primary matrices once ───────────────────────────────────
    M_dom_pri, pri_row_ids, dom_accs = build_nrb_domain_matrix(
        sources=sources, nrb_ids_subset=primary_ids,
    )
    if M_dom_pri.shape[0] == 0:
        return _result(run.pk, scope, 0, 0, len(query_bgc_ids))

    M_pair_pri, pri_row_ids_adj, pair_vocab = build_nrb_adjacency_pair_matrix(
        sources=sources, nrb_ids_subset=primary_ids,
    )
    M_pair_pri = _align_rows(M_pair_pri, pri_row_ids_adj, pri_row_ids, ncols_keep=True)

    pri_path_arr = np.asarray(
        [primary_paths.get(int(pid), "") for pid in pri_row_ids.tolist()],
        dtype=object,
    )

    # ── 4. Walk query DashboardBgcs in chunks ────────────────────────────
    classified = 0
    unclassified = 0
    update_batch: list[DashboardBgc] = []
    now = timezone.now()
    n_primary = M_dom_pri.shape[0]

    for start in range(0, len(query_bgc_ids), chunk_size):
        chunk_ids = query_bgc_ids[start : start + chunk_size]
        M_dom_q, q_row_ids_dom, _ = build_nrb_domain_matrix(
            sources=sources,
            domain_accs_subset=dom_accs.tolist(),
            extra_bgc_ids=chunk_ids,
            nrb_ids_subset=[],  # only the extra rows
        )
        # extra rows carry negative ids; primary rows carry positive ids.
        q_mask = q_row_ids_dom < 0
        if not q_mask.any():
            unclassified += len(chunk_ids)
            continue
        M_dom_q = M_dom_q[q_mask]
        q_row_ids = q_row_ids_dom[q_mask]

        M_pair_q, q_row_ids_pair, _ = build_nrb_adjacency_pair_matrix(
            sources=sources,
            pair_vocab_subset=pair_vocab.tolist(),
            extra_bgc_ids=chunk_ids,
            nrb_ids_subset=[],
        )
        q_pair_mask = q_row_ids_pair < 0
        M_pair_q = M_pair_q[q_pair_mask] if q_pair_mask.any() else sp.csr_matrix(
            (M_dom_q.shape[0], M_pair_pri.shape[1]), dtype=M_pair_pri.dtype,
        )
        q_pair_ids = q_row_ids_pair[q_pair_mask] if q_pair_mask.any() else np.empty(0, dtype=np.int64)
        M_pair_q = _align_rows(M_pair_q, q_pair_ids, q_row_ids, ncols_keep=True)

        # Stack [primary; query] for both matrices.
        M_dom_full = sp.vstack([M_dom_pri, M_dom_q], format="csr")
        M_pair_full = sp.vstack([M_pair_pri, M_pair_q], format="csr")

        sim_full = compute_composite_similarity(
            M_dom_full, M_pair_full, weights=weights, prune_below=0.0,
        )
        sim_block = sim_full[n_primary:, :n_primary].tocsr()

        for q_row in range(M_dom_q.shape[0]):
            qid = -int(q_row_ids[q_row])  # convert back to positive DashboardBgc id
            start_p = sim_block.indptr[q_row]
            end_p = sim_block.indptr[q_row + 1]
            if start_p == end_p:
                unclassified += 1
                continue
            cols = sim_block.indices[start_p:end_p]
            vals = sim_block.data[start_p:end_p]
            order = np.argsort(-vals)[:knn_k]
            top_cols = cols[order]
            top_vals = vals[order]
            if float(top_vals.sum()) < min_total_similarity:
                unclassified += 1
                continue
            votes: Counter[str] = Counter()
            for col, val in zip(top_cols.tolist(), top_vals.tolist()):
                path = pri_path_arr[col]
                if not path:
                    continue
                votes[str(path)] += float(val)
            if not votes:
                unclassified += 1
                continue
            best_path, _ = votes.most_common(1)[0]
            update_batch.append(
                DashboardBgc(
                    id=qid,
                    gene_cluster_family=best_path,
                    classification_source="knn",
                    classification_run=run,
                    classified_at=now,
                )
            )
            classified += 1

        if progress_cb is not None:
            progress_cb({
                "scope": scope,
                "processed": min(start + chunk_size, len(query_bgc_ids)),
                "total": len(query_bgc_ids),
                "classified": classified,
                "unclassified": unclassified,
            })

    # ── 5. Persist classified + mark unclassified ────────────────────────
    if update_batch:
        DashboardBgc.objects.bulk_update(
            update_batch,
            [
                "gene_cluster_family", "classification_source",
                "classification_run", "classified_at",
            ],
            batch_size=5_000,
        )
    classified_ids = {b.id for b in update_batch}
    unclassified_ids = [qid for qid in query_bgc_ids if qid not in classified_ids]
    if unclassified_ids:
        DashboardBgc.objects.filter(id__in=unclassified_ids).update(
            gene_cluster_family="",
            classification_source="unclassified",
            classification_run=run,
            classified_at=now,
        )

    _refresh_gcf_aggregates(run.pk)

    log.info(
        "reclassify_bgcs: run=%s scope=%s classified=%d unclassified=%d",
        run.pk, scope, classified, unclassified + len(unclassified_ids),
    )
    return _result(run.pk, scope, classified, unclassified + len(unclassified_ids), 0)


def _result(run_pk, scope, classified, unclassified, skipped):
    return {
        "clustering_run_pk": run_pk,
        "scope": scope,
        "classified": classified,
        "unclassified": unclassified,
        "skipped": skipped,
    }


def _align_rows(M, source_ids, target_ids, *, ncols_keep=False):
    """Re-key a sparse matrix's row labels to a target ordering."""
    import numpy as np
    import scipy.sparse as sp

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
    """Recount ``member_count`` / ``validated_count`` / ``mean_novelty`` for the run."""
    from discovery.models import DashboardBgc, DashboardGCF

    gcf_qs = DashboardGCF.objects.filter(clustering_run_id=clustering_run_pk)
    nodes = list(gcf_qs.values_list("id", "family_path"))
    if not nodes:
        return

    bgc_rows = list(
        DashboardBgc.objects.exclude(gene_cluster_family="").values_list(
            "id", "gene_cluster_family", "is_validated", "novelty_score"
        )
    )

    counts: dict[str, list[tuple[bool, float]]] = {}
    for _, leaf_path, is_validated, novelty in bgc_rows:
        parts = leaf_path.split(".")
        for d in range(1, len(parts) + 1):
            prefix = ".".join(parts[:d])
            counts.setdefault(prefix, []).append((bool(is_validated), float(novelty)))

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
