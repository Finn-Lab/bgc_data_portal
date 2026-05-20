"""Pure-array tests for ``compute_novelty_array`` and ``compute_domain_novelty_array``.

Exercises the math on small synthetic matrices without touching the DB.
The DB-writing path (``score_primary_ibgcs``) is covered by an integration
test that runs the full pipeline; here we just lock the formulas in place.
"""

from __future__ import annotations

import numpy as np
import pytest

scipy_sparse = pytest.importorskip("scipy.sparse")

from discovery.services.clustering.ibgc_scoring import (  # noqa: E402
    compute_domain_novelty_array,
    compute_novelty_array,
)


def _coo(rows: list[list[int]], n_cols: int) -> "scipy_sparse.csr_matrix":
    coords_r: list[int] = []
    coords_c: list[int] = []
    for r, cols in enumerate(rows):
        for c in cols:
            coords_r.append(r)
            coords_c.append(c)
    data = np.ones(len(coords_r), dtype=np.uint8)
    return scipy_sparse.csr_matrix(
        (data, (coords_r, coords_c)),
        shape=(len(rows), n_cols),
        dtype=np.uint8,
    )


def _sym_sim(values: dict[tuple[int, int], float], n: int) -> "scipy_sparse.csr_matrix":
    """Build a symmetric float similarity from upper-triangle entries."""
    rows: list[int] = []
    cols: list[int] = []
    data: list[float] = []
    for (i, j), v in values.items():
        rows += [i, j]
        cols += [j, i]
        data += [v, v]
    return scipy_sparse.csr_matrix(
        (data, (rows, cols)), shape=(n, n), dtype=np.float32
    )


# ── novelty ──────────────────────────────────────────────────────────────


def test_novelty_no_validated_columns_returns_nans():
    sim = _sym_sim({(0, 1): 0.4, (0, 2): 0.2, (1, 2): 0.9}, n=3)
    out = compute_novelty_array(sim, validated_cols=[])
    assert out.shape == (3,)
    assert np.all(np.isnan(out))


def test_novelty_uses_max_sim_to_validated_column():
    # rows 0,1 are queries; column 2 is the only validated iBGC.
    sim = _sym_sim({(0, 2): 0.7, (1, 2): 0.2, (0, 1): 0.95}, n=3)
    out = compute_novelty_array(sim, validated_cols=[2])
    # novelty(0) = 1 - 0.7 = 0.3   (sim(0,1) is irrelevant; col 1 not validated)
    # novelty(1) = 1 - 0.2 = 0.8
    # novelty(2) = 1 - 0   = 1.0   (diagonal zero, no other validated)
    assert out[0] == pytest.approx(0.3, abs=1e-6)
    assert out[1] == pytest.approx(0.8, abs=1e-6)
    assert out[2] == pytest.approx(1.0, abs=1e-6)


def test_novelty_validated_vs_other_validated_uses_diagonal_zero():
    sim = _sym_sim({(0, 1): 0.6, (0, 2): 0.1, (1, 2): 0.4}, n=3)
    # rows 0 and 1 are both validated; row 0's novelty must come from sim(0,1).
    out = compute_novelty_array(sim, validated_cols=[0, 1])
    assert out[0] == pytest.approx(1.0 - 0.6, abs=1e-6)
    assert out[1] == pytest.approx(1.0 - 0.6, abs=1e-6)
    assert out[2] == pytest.approx(1.0 - 0.4, abs=1e-6)


# ── domain novelty ───────────────────────────────────────────────────────


def test_domain_novelty_singleton_path_is_nan():
    M = _coo([[0, 1, 2]], n_cols=3)
    out = compute_domain_novelty_array(M, leaf_paths=["cluster.0.0.0.0"])
    assert np.isnan(out[0])


def test_domain_novelty_empty_path_is_nan():
    M = _coo([[0, 1], [1, 2]], n_cols=3)
    out = compute_domain_novelty_array(M, leaf_paths=["", ""])
    assert np.isnan(out).all()


def test_domain_novelty_unique_fraction_within_leaf():
    # Three rows in the same leaf path.
    #   row 0 domains: {0, 1}     → 0 shared with 1 (col 1), 1 unique (col 0)
    #   row 1 domains: {1, 2}     → 1 shared (col 1), 1 unique (col 2)
    #   row 2 domains: {3}        → 1 unique (col 3)
    M = _coo([[0, 1], [1, 2], [3]], n_cols=4)
    paths = ["cluster.0.0.0.0"] * 3
    out = compute_domain_novelty_array(M, paths)
    assert out[0] == pytest.approx(1 / 2, abs=1e-6)
    assert out[1] == pytest.approx(1 / 2, abs=1e-6)
    assert out[2] == pytest.approx(1.0, abs=1e-6)


def test_domain_novelty_separates_distinct_leaf_groups():
    # Two leaf groups; uniqueness must NOT cross the boundary.
    # Group A: rows 0,1 both have domain 0  → 0 unique for each
    # Group B: row 2 alone in group         → singleton → NaN
    M = _coo([[0], [0], [0]], n_cols=1)
    paths = ["cluster.A", "cluster.A", "cluster.B"]
    out = compute_domain_novelty_array(M, paths)
    assert out[0] == pytest.approx(0.0, abs=1e-6)
    assert out[1] == pytest.approx(0.0, abs=1e-6)
    assert np.isnan(out[2])


def test_domain_novelty_row_with_no_domains_is_nan():
    # Row 0 has no domains at all; row 1 has one.
    M = _coo([[], [0]], n_cols=2)
    out = compute_domain_novelty_array(M, leaf_paths=["cluster.0", "cluster.0"])
    assert np.isnan(out[0])
    # Row 1's lone domain is unique within the group of {row 0 (empty), row 1}
    # because row 0 contributes nothing to col_sums.
    assert out[1] == pytest.approx(1.0, abs=1e-6)


def test_domain_novelty_length_mismatch_raises():
    M = _coo([[0]], n_cols=1)
    with pytest.raises(ValueError):
        compute_domain_novelty_array(M, leaf_paths=["a", "b"])
