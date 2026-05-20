"""Per-iBGC scoring (novelty + domain novelty) over the composite-Dice matrix.

Designed to be called inline at the end of ``run_clustering_pipeline`` with
the already-built primary-iBGC matrices in memory, or independently from a
management command after rehydrating the cached matrices from disk
(see ``services/clustering/pipeline.py``).

Score definitions (locked in the v2 redesign):

* ``novelty_score`` = ``1 − max(composite_dice_sim(this, v))`` for ``v`` in
  the set of validated iBGCs in the same clustering run. Validated iBGCs are
  scored against the other validated iBGCs (their own self-similarity is
  zero on the diagonal, so this falls out naturally). When the run has no
  validated iBGCs the value is NULL.

* ``domain_novelty`` = ``|domains unique within leaf GCF| / |domains(this)|``
  where the leaf GCF is the row's ``family_path``. Singleton leaf GCFs and
  iBGCs whose source-domain count is zero yield NULL (rendered as "—" in
  the UI), to avoid the misleading 1.0 that the formula would otherwise
  return for a one-member community.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import scipy.sparse as sp

    from discovery.models import ClusteringRun

log = logging.getLogger(__name__)

SCORING_CACHE_SUBDIR = "scoring_cache"
DOMAINS_FILE = "M_domains.npz"
PAIRS_FILE = "M_pairs.npz"
IBGC_IDS_FILE = "ibgc_ids.npy"
DOMAIN_ACCS_FILE = "domain_accs.npy"
PAIR_VOCAB_FILE = "pair_vocab.npy"
LEAF_PATHS_FILE = "leaf_paths.json"
SIG_TO_IPR_FILE = "sig_to_ipr.json"


def persist_scoring_cache(
    *,
    artifacts_dir: Path,
    M_domains: sp.csr_matrix,
    M_pairs: sp.csr_matrix,
    ibgc_ids: np.ndarray,
    domain_accs: np.ndarray,
    pair_vocab: np.ndarray,
    leaf_paths: list[str],
    sig_to_ipr: dict[str, str] | None = None,
) -> Path:
    """Write the small per-iBGC signature matrices needed by on-demand similarity.

    The full N×N composite-Dice matrix is no longer persisted — both
    Find Similar and ARCH compute composite-Dice on demand against
    ``M_domains`` / ``M_pairs`` via
    :mod:`discovery.services.clustering.similarity_on_demand`.

    ``sig_to_ipr`` (signature_acc → ipr_entry_acc) lets the architecture
    search resolve user-pasted raw Pfam/NCBIFAM/TIGRFAM accessions onto
    the IPR-projected vocabulary; persisted as JSON next to the matrices.

    Returns the cache directory path.
    """
    import scipy.sparse as sp

    cache_dir = Path(artifacts_dir) / SCORING_CACHE_SUBDIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    sp.save_npz(cache_dir / DOMAINS_FILE, M_domains)
    sp.save_npz(cache_dir / PAIRS_FILE, M_pairs)
    np.save(cache_dir / IBGC_IDS_FILE, np.asarray(ibgc_ids))
    np.save(cache_dir / DOMAIN_ACCS_FILE, np.asarray(domain_accs, dtype=object))
    np.save(cache_dir / PAIR_VOCAB_FILE, np.asarray(pair_vocab, dtype=object))
    (cache_dir / LEAF_PATHS_FILE).write_text(json.dumps(list(leaf_paths)))
    (cache_dir / SIG_TO_IPR_FILE).write_text(json.dumps(sig_to_ipr or {}))
    # Purge any sim.npz left over from a previous schema — keeps the PVC tidy.
    legacy_sim = cache_dir / "sim.npz"
    if legacy_sim.exists():
        try:
            legacy_sim.unlink()
        except OSError:  # pragma: no cover
            log.warning("Could not delete legacy sim.npz at %s", legacy_sim)
    log.info("Wrote iBGC scoring cache to %s", cache_dir)
    return cache_dir


def load_scoring_cache(artifacts_dir: Path) -> dict:
    """Return ``M_domains``, ``M_pairs``, ``ibgc_ids``, ``domain_accs``,
    ``pair_vocab``, ``leaf_paths``, ``sig_to_ipr``.

    ``sim`` is no longer materialised — callers should use
    :mod:`discovery.services.clustering.similarity_on_demand` for similarity
    queries. ``sig_to_ipr`` is an empty dict for caches written before the
    IPR projection rolled out.
    """
    import scipy.sparse as sp

    cache_dir = Path(artifacts_dir) / SCORING_CACHE_SUBDIR
    sig_path = cache_dir / SIG_TO_IPR_FILE
    sig_to_ipr = json.loads(sig_path.read_text()) if sig_path.exists() else {}
    return {
        "M_domains": sp.load_npz(cache_dir / DOMAINS_FILE),
        "M_pairs": sp.load_npz(cache_dir / PAIRS_FILE),
        "ibgc_ids": np.load(cache_dir / IBGC_IDS_FILE, allow_pickle=True),
        "domain_accs": np.load(cache_dir / DOMAIN_ACCS_FILE, allow_pickle=True),
        "pair_vocab": np.load(cache_dir / PAIR_VOCAB_FILE, allow_pickle=True),
        "leaf_paths": json.loads((cache_dir / LEAF_PATHS_FILE).read_text()),
        "sig_to_ipr": sig_to_ipr,
    }


def compute_novelty_array(
    sim: sp.csr_matrix,
    validated_cols: list[int],
) -> np.ndarray:
    """Return novelty per row: ``1 − max(sim_to_validated)``.

    Rows for which ``validated_cols`` is empty receive NaN (caller persists
    as NULL). Self-similarity is zero on the diagonal so validated iBGCs are
    scored against the *other* validated iBGCs naturally.
    """
    n_rows = sim.shape[0]
    if not validated_cols:
        return np.full(n_rows, np.nan, dtype=np.float32)

    sim_to_validated = sim[:, validated_cols]
    max_sim = np.asarray(sim_to_validated.max(axis=1).todense()).reshape(-1)
    return (1.0 - max_sim).astype(np.float32)


def compute_domain_novelty_array(
    M_domains: sp.csr_matrix,
    leaf_paths: list[str],
) -> np.ndarray:
    """Return per-row fraction of domains unique within the row's leaf GCF.

    NaN for singleton leaf GCFs (`< 2` members), for empty leaf paths, and
    for rows with zero source-domain hits — surfaced as NULL in the UI.
    """
    n_rows = M_domains.shape[0]
    if len(leaf_paths) != n_rows:
        raise ValueError(
            f"leaf_paths length {len(leaf_paths)} ≠ M_domains row count {n_rows}"
        )

    path_to_rows: dict[str, list[int]] = defaultdict(list)
    for i, p in enumerate(leaf_paths):
        path_to_rows[p].append(i)

    out = np.full(n_rows, np.nan, dtype=np.float32)
    for path, rows in path_to_rows.items():
        if not path or len(rows) < 2:
            continue
        sub = M_domains[rows].tocsr()
        col_sums = np.asarray(sub.sum(axis=0)).reshape(-1)
        for local_i, abs_row in enumerate(rows):
            start = sub.indptr[local_i]
            end = sub.indptr[local_i + 1]
            if start == end:
                continue
            domain_cols = sub.indices[start:end]
            n_domains = int(end - start)
            n_unique = int((col_sums[domain_cols] == 1).sum())
            out[abs_row] = n_unique / n_domains
    return out


def score_primary_ibgcs(
    *,
    sim: sp.csr_matrix,
    M_domains: sp.csr_matrix,
    ibgc_ids: np.ndarray,
    leaf_paths: list[str],
    run: ClusteringRun,
) -> dict:
    """Write ``novelty_score`` and ``domain_novelty`` on the primary iBGCs of ``run``.

    Parameters
    ----------
    sim:
        Symmetric composite-Dice similarity over the primary iBGC set. Row /
        column order matches ``ibgc_ids``.
    M_domains:
        Binary iBGC × domain matrix used to count domain occurrences within
        leaf-GCF groups. Row order matches ``ibgc_ids``.
    ibgc_ids:
        Ordering of iBGC primary-key ids for rows of ``sim`` / ``M_domains``.
    leaf_paths:
        Per-row ``gene_cluster_family`` leaf path (length matches ``ibgc_ids``).
    run:
        The ``ClusteringRun`` whose primary iBGCs are being scored.
    """
    from discovery.models import DashboardBgc, IntegratedBGC

    n_rows = sim.shape[0]
    if n_rows == 0:
        return {"scored": 0, "validated_count": 0}

    ids_list = [int(x) for x in ibgc_ids.tolist()]
    id_to_row = {nid: i for i, nid in enumerate(ids_list)}

    validated_ibgc_ids = set(
        DashboardBgc.objects.filter(
            is_validated=True, integrated_bgc__isnull=False
        ).values_list("integrated_bgc_id", flat=True)
    )
    validated_cols = sorted(
        id_to_row[nid] for nid in validated_ibgc_ids if nid in id_to_row
    )
    if not validated_cols:
        log.warning(
            "score_primary_ibgcs: no validated iBGCs in run pk=%s — leaving "
            "novelty_score NULL on all primary iBGCs",
            run.pk,
        )

    novelty = compute_novelty_array(sim, validated_cols)
    domain_novelty = compute_domain_novelty_array(M_domains, leaf_paths)

    ibgc_rows = list(IntegratedBGC.objects.filter(id__in=ids_list))
    for ibgc in ibgc_rows:
        i = id_to_row[ibgc.id]
        nv = float(novelty[i])
        ibgc.novelty_score = None if np.isnan(nv) else nv
        dn = float(domain_novelty[i])
        ibgc.domain_novelty = None if np.isnan(dn) else dn
        ibgc.umap_projected = False

    IntegratedBGC.objects.bulk_update(
        ibgc_rows,
        ["novelty_score", "domain_novelty", "umap_projected"],
        batch_size=5_000,
    )

    log.info(
        "score_primary_ibgcs: run=%s scored=%d validated=%d singletons_or_empty=%d",
        run.pk,
        len(ibgc_rows),
        len(validated_cols),
        int(np.isnan(domain_novelty).sum()),
    )

    return {
        "scored": len(ibgc_rows),
        "validated_count": len(validated_cols),
        "domain_novelty_null": int(np.isnan(domain_novelty).sum()),
    }


# ── Partial-iBGC projection ───────────────────────────────────────────────


def project_partial_ibgcs(
    *,
    clustering_run_pk: int,
    knn_k: int = 5,
    min_total_similarity: float = 0.1,
    chunk_size: int = 256,
    progress_cb=None,
) -> dict:
    """Project iBGCs that were not part of the primary clustering pass.

    For every ``IntegratedBGC`` whose ``classification_run_id`` differs from
    the run identified by ``clustering_run_pk`` (partial-only iBGCs and stale
    rows from earlier runs), compute composite-Dice similarity to every
    primary iBGC of the run and derive:

      * ``umap_x`` / ``umap_y`` — weighted average of the top-K primary
        neighbours' coordinates (similarity-weighted).
      * ``gene_cluster_family`` — leaf path of the weighted-majority primary
        neighbour vote (mirrors :mod:`discovery.services.clustering.reclassify`).
      * ``novelty_score`` — ``1 − max(sim to validated primary iBGC)``.
      * ``domain_novelty`` — fraction of this iBGC's domains not present in any
        primary member of the inherited leaf GCF. NULL when the iBGC carries
        no source-vocabulary domains.
      * ``umap_projected`` = True; ``classification_run`` set to the target
        run; ``classified_at`` updated.

    iBGCs whose top-K similarity sum is below ``min_total_similarity`` (or that
    have no overlapping vocabulary with the primary set) are left unprojected
    and counted as ``skipped``.
    """
    import scipy.sparse as sp
    from django.utils import timezone

    from discovery.models import (
        ClusteringRun,
        DashboardBgc,
        IntegratedBGC,
    )
    from discovery.services.clustering.adjacency import (
        build_ibgc_adjacency_pair_matrix,
    )
    from discovery.services.clustering.bgc_similarity import (
        compute_composite_similarity,
    )
    from discovery.services.clustering.membership import build_ibgc_domain_matrix
    from discovery.services.clustering.reclassify import _align_rows

    run = ClusteringRun.objects.get(pk=clustering_run_pk)
    sources = tuple(run.domain_sources) or ("PFAM", "NCBIFAM","TIGRFAM")
    weights = tuple(run.score_weights) if run.score_weights else (0.5, 0.5)

    # ── 1. Identify partials ─────────────────────────────────────────────
    partial_ibgc_ids = list(
        IntegratedBGC.objects.exclude(classification_run_id=run.pk)
        .order_by("id")
        .values_list("id", flat=True)
    )
    if not partial_ibgc_ids:
        log.info("project_partial_ibgcs: no partials to project (run=%s)", run.pk)
        return {
            "clustering_run_pk": run.pk,
            "projected": 0,
            "skipped": 0,
            "scope": 0,
        }

    primary_ids = list(
        IntegratedBGC.objects.filter(classification_run_id=run.pk)
        .order_by("id")
        .values_list("id", flat=True)
    )
    if not primary_ids:
        log.warning(
            "project_partial_ibgcs: run=%s has no primary iBGCs — nothing to "
            "project against",
            run.pk,
        )
        return {
            "clustering_run_pk": run.pk,
            "projected": 0,
            "skipped": len(partial_ibgc_ids),
            "scope": len(partial_ibgc_ids),
        }

    # ── 2. Primary matrices (rebuilt fresh; cache exists for parity only) ─
    M_dom_pri, pri_row_ids, dom_accs = build_ibgc_domain_matrix(
        sources=sources, ibgc_ids_subset=primary_ids,
    )
    if M_dom_pri.shape[0] == 0:
        return {
            "clustering_run_pk": run.pk,
            "projected": 0,
            "skipped": len(partial_ibgc_ids),
            "scope": len(partial_ibgc_ids),
        }
    M_pair_pri, pri_row_ids_adj, pair_vocab = build_ibgc_adjacency_pair_matrix(
        sources=sources, ibgc_ids_subset=primary_ids,
    )
    M_pair_pri = _align_rows(M_pair_pri, pri_row_ids_adj, pri_row_ids)
    n_primary = M_dom_pri.shape[0]

    pri_id_to_row = {int(x): i for i, x in enumerate(pri_row_ids.tolist())}

    primary_meta = {
        ibgc.id: (ibgc.umap_x, ibgc.umap_y, ibgc.gene_cluster_family)
        for ibgc in IntegratedBGC.objects.filter(
            id__in=primary_ids
        ).only("id", "umap_x", "umap_y", "gene_cluster_family")
    }
    pri_coords = np.array(
        [
            [
                primary_meta[int(x)][0] if primary_meta[int(x)][0] is not None else 0.0,
                primary_meta[int(x)][1] if primary_meta[int(x)][1] is not None else 0.0,
            ]
            for x in pri_row_ids.tolist()
        ],
        dtype=np.float32,
    )
    pri_leaf_paths = [primary_meta[int(x)][2] for x in pri_row_ids.tolist()]

    validated_ids = set(
        DashboardBgc.objects.filter(
            is_validated=True, integrated_bgc__isnull=False
        ).values_list("integrated_bgc_id", flat=True)
    )
    validated_col_set = {pri_id_to_row[v] for v in validated_ids if v in pri_id_to_row}

    # Per-leaf column-sums on the primary domain matrix (for domain_novelty).
    leaf_to_rows: dict[str, list[int]] = defaultdict(list)
    for i, p in enumerate(pri_leaf_paths):
        if p:
            leaf_to_rows[p].append(i)
    leaf_col_sums: dict[str, np.ndarray] = {
        leaf: np.asarray(M_dom_pri[rows].sum(axis=0)).reshape(-1)
        for leaf, rows in leaf_to_rows.items()
    }

    # ── 3. Walk partials in chunks ───────────────────────────────────────
    now = timezone.now()
    update_batch: list[IntegratedBGC] = []

    for start in range(0, len(partial_ibgc_ids), chunk_size):
        chunk_ids = partial_ibgc_ids[start : start + chunk_size]
        M_dom_q, q_row_ids, _ = build_ibgc_domain_matrix(
            sources=sources,
            domain_accs_subset=dom_accs.tolist(),
            ibgc_ids_subset=chunk_ids,
        )
        if M_dom_q.shape[0] == 0:
            continue

        M_pair_q, q_pair_ids, _ = build_ibgc_adjacency_pair_matrix(
            sources=sources,
            pair_vocab_subset=pair_vocab.tolist(),
            ibgc_ids_subset=chunk_ids,
        )
        M_pair_q = _align_rows(M_pair_q, q_pair_ids, q_row_ids)

        M_dom_full = sp.vstack([M_dom_pri, M_dom_q], format="csr")
        M_pair_full = sp.vstack([M_pair_pri, M_pair_q], format="csr")
        sim_full = compute_composite_similarity(
            M_dom_full, M_pair_full, weights=weights, prune_below=0.0,
        )
        sim_block = sim_full[n_primary:, :n_primary].tocsr()
        M_dom_q_csr = M_dom_q.tocsr()

        for q_row, q_ibgc_id in enumerate(q_row_ids.tolist()):
            sp_start = sim_block.indptr[q_row]
            sp_end = sim_block.indptr[q_row + 1]
            if sp_start == sp_end:
                continue
            cols = sim_block.indices[sp_start:sp_end]
            vals = sim_block.data[sp_start:sp_end]
            order = np.argsort(-vals)[:knn_k]
            top_cols = cols[order]
            top_vals = vals[order]
            top_sum = float(top_vals.sum())
            if top_sum < min_total_similarity:
                continue

            weights_norm = top_vals / top_sum
            umap_x = float((pri_coords[top_cols, 0] * weights_norm).sum())
            umap_y = float((pri_coords[top_cols, 1] * weights_norm).sum())

            votes: Counter[str] = Counter()
            for col, val in zip(top_cols.tolist(), top_vals.tolist()):
                p = pri_leaf_paths[col]
                if p:
                    votes[p] += float(val)
            if not votes:
                continue
            best_leaf, _ = votes.most_common(1)[0]

            # Novelty: max sim restricted to validated primary cols within this
            # row's non-zero entries. Diagonal is already zeroed on sim, so
            # validated-vs-self is naturally excluded for any partial that
            # happens to also be validated (those are admitted as primary iBGCs
            # by build_integrated_bgcs, so this shouldn't occur in
            # practice — guard kept for safety).
            if validated_col_set:
                max_sim_validated = 0.0
                for col, val in zip(cols.tolist(), vals.tolist()):
                    if col in validated_col_set and val > max_sim_validated:
                        max_sim_validated = float(val)
                novelty = 1.0 - max_sim_validated
            else:
                novelty = None

            q_dom_start = M_dom_q_csr.indptr[q_row]
            q_dom_end = M_dom_q_csr.indptr[q_row + 1]
            n_dom = int(q_dom_end - q_dom_start)
            domain_novelty: float | None
            if n_dom == 0:
                domain_novelty = None
            else:
                col_sums_L = leaf_col_sums.get(best_leaf)
                if col_sums_L is None:
                    domain_novelty = None
                else:
                    domain_cols = M_dom_q_csr.indices[q_dom_start:q_dom_end]
                    n_unique = int((col_sums_L[domain_cols] == 0).sum())
                    domain_novelty = n_unique / n_dom

            update_batch.append(
                IntegratedBGC(
                    id=int(q_ibgc_id),
                    umap_x=umap_x,
                    umap_y=umap_y,
                    umap_projected=True,
                    gene_cluster_family=best_leaf,
                    novelty_score=novelty,
                    domain_novelty=domain_novelty,
                    classification_run=run,
                    classified_at=now,
                )
            )

        if progress_cb is not None:
            progress_cb({
                "processed": min(start + chunk_size, len(partial_ibgc_ids)),
                "total": len(partial_ibgc_ids),
                "projected": len(update_batch),
            })

    if update_batch:
        IntegratedBGC.objects.bulk_update(
            update_batch,
            [
                "umap_x", "umap_y", "umap_projected",
                "gene_cluster_family", "novelty_score", "domain_novelty",
                "classification_run", "classified_at",
            ],
            batch_size=5_000,
        )

    projected = len(update_batch)
    skipped = len(partial_ibgc_ids) - projected
    log.info(
        "project_partial_ibgcs: run=%s projected=%d skipped=%d scope=%d",
        run.pk, projected, skipped, len(partial_ibgc_ids),
    )
    return {
        "clustering_run_pk": run.pk,
        "projected": projected,
        "skipped": skipped,
        "scope": len(partial_ibgc_ids),
    }
