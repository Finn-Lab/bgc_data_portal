"""Tests for the composite-Dice architecture search.

The search runs against the cached scoring matrices produced by
``run_clustering_pipeline``. These tests build the matrices in memory by
hand so we don't depend on a fully materialised ClusteringRun on disk.
"""

from __future__ import annotations

import numpy as np
import scipy.sparse as sp

from discovery.services.clustering.architecture_search import (
    architecture_search,
    normalize_architecture_input,
)


def _build_cache(rows_domains, rows_pairs, ibgc_ids):
    """Construct a minimal scoring-cache dict matching ``load_scoring_cache``.

    ``rows_domains`` is a list of (set of accessions) per iBGC row.
    ``rows_pairs`` is a list of (set of canonical sorted (a,b) tuples) per row.
    """
    domain_accs = sorted({a for s in rows_domains for a in s})
    pair_vocab = sorted({p for s in rows_pairs for p in s})
    dom_idx = {a: i for i, a in enumerate(domain_accs)}
    pair_idx = {p: i for i, p in enumerate(pair_vocab)}

    def _build(rows, idx, width):
        ri, ci = [], []
        for r, items in enumerate(rows):
            for it in items:
                ri.append(r)
                ci.append(idx[it])
        data = np.ones(len(ri), dtype=np.uint8)
        return sp.csr_matrix(
            (data, (np.asarray(ri), np.asarray(ci))),
            shape=(len(rows), width), dtype=np.uint8,
        )

    M_dom = _build(rows_domains, dom_idx, len(domain_accs))
    M_pair = _build(rows_pairs, pair_idx, len(pair_vocab))

    return {
        "M_domains": M_dom,
        "M_pairs": M_pair,
        "ibgc_ids": np.asarray(ibgc_ids, dtype=np.int64),
        "domain_accs": np.asarray(domain_accs, dtype=object),
        "pair_vocab": np.asarray(pair_vocab, dtype=object),
        # Unused by architecture_search but the cache loader supplies them.
        "sim": None,
        "leaf_paths": [],
    }


def test_normalize_splits_and_uppercases():
    assert normalize_architecture_input("pf00109, PF02801  pf00501") == [
        "PF00109", "PF02801", "PF00501",
    ]
    assert normalize_architecture_input(["PF00109", "", "  pf02801"]) == [
        "PF00109", "PF02801",
    ]


def test_perfect_match_scores_one_at_weight_one():
    cache = _build_cache(
        rows_domains=[{"A", "B", "C"}, {"A", "B"}],
        rows_pairs=[{("A", "B"), ("B", "C")}, {("A", "B")}],
        ibgc_ids=[10, 20],
    )
    out = architecture_search(
        ["A", "B", "C"], weight=1.0, k=10, cache=cache,
    )
    # weight=1.0 → pure domain Dice. Row 0 is identical → Dice = 1.
    assert out["ibgc_ids"][0] == 10
    assert out["scores"][0] == 1.0


def test_weight_zero_uses_adjacency_only():
    cache = _build_cache(
        rows_domains=[{"A", "B"}, {"A", "B", "C", "D"}],
        rows_pairs=[{("A", "B")}, {("C", "D")}],
        ibgc_ids=[10, 20],
    )
    # Query produces pair (A,B); the second iBGC shares no pair so it scores 0.
    out = architecture_search(
        ["A", "B"], weight=0.0, k=10, cache=cache,
    )
    score_by_id = dict(zip(out["ibgc_ids"], out["scores"]))
    assert score_by_id[10] > 0.0
    assert score_by_id[20] == 0.0


def test_unmatched_accessions_are_reported_not_thrown():
    cache = _build_cache(
        rows_domains=[{"A", "B"}],
        rows_pairs=[{("A", "B")}],
        ibgc_ids=[10],
    )
    out = architecture_search(
        ["A", "ZZZ", "B"], weight=0.5, k=10, cache=cache,
    )
    assert "ZZZ" in out["unmatched"]
    # Single matched pair (A,B) still scored normally.
    assert out["n_query_pairs"] == 1
    assert out["n_query_domains"] == 2


def test_single_domain_input_contributes_zero_adjacency():
    cache = _build_cache(
        rows_domains=[{"A", "B"}, {"A"}],
        rows_pairs=[{("A", "B")}, set()],
        ibgc_ids=[10, 20],
    )
    out = architecture_search(
        ["A"], weight=0.5, k=10, cache=cache,
    )
    assert out["n_query_pairs"] == 0
    # Score must still be deterministic — the search shouldn't crash on an
    # input with no adjacent pairs.
    assert len(out["scores"]) == 2


def test_topk_caps_results():
    cache = _build_cache(
        rows_domains=[{"A", "B"}] * 3,
        rows_pairs=[{("A", "B")}] * 3,
        ibgc_ids=[10, 20, 30],
    )
    out = architecture_search(
        ["A", "B"], weight=0.5, k=2, cache=cache,
    )
    assert len(out["ibgc_ids"]) == 2


def test_empty_input_returns_empty_payload():
    cache = _build_cache(
        rows_domains=[{"A"}], rows_pairs=[set()], ibgc_ids=[1],
    )
    out = architecture_search([], weight=0.5, k=10, cache=cache)
    assert out["ibgc_ids"] == []
    assert out["unmatched"] == []


def test_sig_to_ipr_resolves_pasted_signature_acc():
    """A user pasting raw Pfam accs against an IPR-projected vocab still
    matches via the sig_to_ipr lookup.
    """
    cache = _build_cache(
        rows_domains=[{"IPR000001", "IPR000002"}],
        rows_pairs=[{("IPR000001", "IPR000002")}],
        ibgc_ids=[42],
    )
    cache["sig_to_ipr"] = {"PF00001": "IPR000001", "PF00002": "IPR000002"}

    out = architecture_search(
        ["PF00001", "PF00002"], weight=1.0, k=5, cache=cache,
    )
    # Both signatures resolve to IPR labels in the vocab → perfect match.
    assert out["unmatched"] == []
    assert out["n_query_domains"] == 2
    assert out["scores"][0] == 1.0


def test_unresolved_signature_acc_lands_in_unmatched():
    """A pasted acc with no IPR mapping and not in the vocab is reported."""
    cache = _build_cache(
        rows_domains=[{"IPR000001"}], rows_pairs=[set()], ibgc_ids=[1],
    )
    cache["sig_to_ipr"] = {"PF00001": "IPR000001"}

    out = architecture_search(
        ["PF00001", "PF99999"], weight=1.0, k=5, cache=cache,
    )
    assert "PF99999" in out["unmatched"]
    assert out["n_query_domains"] == 1  # only the resolved one
