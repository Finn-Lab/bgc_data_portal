"""Composite-Dice search over a user-supplied domain architecture.

Builds a single binary query row against the latest ClusteringRun's cached
``M_domains`` and ``M_pairs`` vocabs, then scores it against every primary
iBGC without rebuilding the matrices:

    score(r) = w · Dice(q_dom, M_domains[r]) + (1 - w) · Dice(q_pair, M_pairs[r])

Dice for binary vectors collapses to ``2·|q ∩ r| / (|q| + |r|)`` — the
numerator is a single sparse-matrix×vector product and the denominator is
row sums (cached on the matrix) plus a scalar.

Unknown accessions (not in the cache's domain vocab) are silently dropped.
Adjacent pairs are formed via sliding window of size 2 over the input,
canonicalized as sorted tuples to match the column layout in ``pair_vocab``
(see :mod:`discovery.services.clustering.adjacency`).
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    import numpy as np
    import scipy.sparse as sp


log = logging.getLogger(__name__)

_TOKEN_SPLIT = re.compile(r"[,\s]+")


def normalize_architecture_input(raw: Sequence[str] | str) -> list[str]:
    """Split + upper-case the user-supplied accession list.

    Accepts either a list of tokens or a single comma/whitespace-separated
    string. Empty tokens are dropped. Tokens are upper-cased so the user
    can paste mixed-case input freely.
    """
    if isinstance(raw, str):
        tokens = _TOKEN_SPLIT.split(raw)
    else:
        tokens = []
        for s in raw:
            tokens.extend(_TOKEN_SPLIT.split(s))
    return [t.strip().upper() for t in tokens if t and t.strip()]


def _build_query_vectors(
    accs_ordered: Sequence[str],
    domain_accs: "np.ndarray",
    pair_vocab: "np.ndarray",
) -> tuple["sp.csr_matrix", "sp.csr_matrix", list[str]]:
    """Return (q_dom 1×D, q_pair 1×P, unmatched_accs)."""
    import numpy as np
    import scipy.sparse as sp

    dom_idx = {str(a).upper(): i for i, a in enumerate(domain_accs.tolist())}
    pair_idx = {tuple(p): i for i, p in enumerate(pair_vocab.tolist())}

    matched: list[int] = []
    unmatched: list[str] = []
    seen_cols: set[int] = set()
    for acc in accs_ordered:
        col = dom_idx.get(acc)
        if col is None:
            unmatched.append(acc)
            continue
        if col in seen_cols:
            continue
        seen_cols.add(col)
        matched.append(col)

    n_dom = len(domain_accs)
    if matched:
        q_dom = sp.csr_matrix(
            (
                np.ones(len(matched), dtype=np.uint8),
                (np.zeros(len(matched), dtype=np.int64),
                 np.asarray(matched, dtype=np.int64)),
            ),
            shape=(1, n_dom),
            dtype=np.uint8,
        )
    else:
        q_dom = sp.csr_matrix((1, n_dom), dtype=np.uint8)

    # Adjacent pairs over the ordered sequence after dropping unknown
    # accessions. Mirrors the adjacency builder, which filters by ref_db
    # *before* sorting — non-vocab tokens never appear in the sequence
    # and therefore do not interrupt the adjacency chain.
    in_vocab = [acc for acc in accs_ordered if acc in dom_idx]
    pair_cols: set[int] = set()
    for i in range(len(in_vocab) - 1):
        pair = tuple(sorted((in_vocab[i], in_vocab[i + 1])))
        ci = pair_idx.get(pair)
        if ci is not None:
            pair_cols.add(ci)

    n_pair = len(pair_vocab)
    if pair_cols:
        cols = sorted(pair_cols)
        q_pair = sp.csr_matrix(
            (
                np.ones(len(cols), dtype=np.uint8),
                (np.zeros(len(cols), dtype=np.int64),
                 np.asarray(cols, dtype=np.int64)),
            ),
            shape=(1, n_pair),
            dtype=np.uint8,
        )
    else:
        q_pair = sp.csr_matrix((1, n_pair), dtype=np.uint8)

    return q_dom, q_pair, unmatched


def architecture_search(
    accs_ordered: Sequence[str],
    *,
    weight: float,
    k: int,
    cache: dict,
) -> dict:
    """Return top-K iBGCs by composite-Dice to the supplied architecture.

    Parameters
    ----------
    accs_ordered:
        Ordered domain accessions (upper-cased, already split).
    weight:
        Sørensen-Dice share in ``[0, 1]``; ``1 - weight`` is the adjacency
        Dice share. Values outside the range are clamped.
    k:
        Maximum iBGCs returned. Clamped to ``[1, 500]`` to mirror
        ``/query/similar-ibgc/``.
    cache:
        Output of :func:`discovery.services.clustering.ibgc_scoring.load_scoring_cache`.

    Returns
    -------
    dict with:
        * ``ibgc_ids``: list[int] — top-K iBGC ids (descending similarity)
        * ``scores``: list[float] — composite scores aligned to ``ibgc_ids``
        * ``unmatched``: list[str] — input accessions not in the cache vocab
        * ``n_query_domains``: int — accessions that matched the vocab
        * ``n_query_pairs``: int — adjacency pairs that matched the vocab
    """
    import numpy as np

    if not accs_ordered:
        return {
            "ibgc_ids": [],
            "scores": [],
            "unmatched": [],
            "n_query_domains": 0,
            "n_query_pairs": 0,
        }

    w = max(0.0, min(1.0, float(weight)))
    w_a = 1.0 - w
    k = max(1, min(int(k), 500))

    M_dom = cache["M_domains"].tocsr()
    M_pair = cache["M_pairs"].tocsr()
    ibgc_ids = cache["ibgc_ids"]
    domain_accs = cache["domain_accs"]
    pair_vocab = cache["pair_vocab"]

    q_dom, q_pair, unmatched = _build_query_vectors(
        accs_ordered, domain_accs, pair_vocab,
    )

    n_q_dom = int(q_dom.nnz)
    n_q_pair = int(q_pair.nnz)

    n_rows = M_dom.shape[0]
    dice_d = np.zeros(n_rows, dtype=np.float32)
    dice_a = np.zeros(n_rows, dtype=np.float32)

    if w > 0.0 and n_q_dom > 0:
        # |q ∩ r| as 1×n vector
        num_d = np.asarray((q_dom @ M_dom.T).todense()).reshape(-1).astype(np.float32)
        row_sums_d = np.asarray(M_dom.sum(axis=1)).reshape(-1).astype(np.float32)
        denom_d = row_sums_d + float(n_q_dom)
        with np.errstate(divide="ignore", invalid="ignore"):
            dice_d = np.where(denom_d > 0, 2.0 * num_d / denom_d, 0.0).astype(np.float32)

    if w_a > 0.0 and n_q_pair > 0:
        num_a = np.asarray((q_pair @ M_pair.T).todense()).reshape(-1).astype(np.float32)
        row_sums_a = np.asarray(M_pair.sum(axis=1)).reshape(-1).astype(np.float32)
        denom_a = row_sums_a + float(n_q_pair)
        with np.errstate(divide="ignore", invalid="ignore"):
            dice_a = np.where(denom_a > 0, 2.0 * num_a / denom_a, 0.0).astype(np.float32)

    score = (w * dice_d) + (w_a * dice_a)

    # Top-K by descending score. argpartition is O(n); a final sort over
    # the K selected rows orders them for the UI.
    k_eff = min(k, n_rows)
    if k_eff == 0:
        return {
            "ibgc_ids": [],
            "scores": [],
            "unmatched": unmatched,
            "n_query_domains": n_q_dom,
            "n_query_pairs": n_q_pair,
        }
    top_partition = np.argpartition(-score, k_eff - 1)[:k_eff]
    top_sorted = top_partition[np.argsort(-score[top_partition])]

    out_ids = [int(ibgc_ids[i]) for i in top_sorted.tolist()]
    out_scores = [float(score[i]) for i in top_sorted.tolist()]

    log.info(
        "architecture_search: q_dom=%d q_pair=%d unmatched=%d top_k=%d (w=%.2f)",
        n_q_dom, n_q_pair, len(unmatched), k_eff, w,
    )

    return {
        "ibgc_ids": out_ids,
        "scores": out_scores,
        "unmatched": unmatched,
        "n_query_domains": n_q_dom,
        "n_query_pairs": n_q_pair,
    }
