"""Pure-function tests for hierarchical Leiden community detection."""

from __future__ import annotations

import pytest

igraph = pytest.importorskip("igraph")
pytest.importorskip("leidenalg")

from discovery.services.clustering.leiden import run_hierarchical_leiden  # noqa: E402


def _two_cliques_graph() -> "igraph.Graph":
    """Two strongly connected cliques joined by a single weak bridge."""
    g = igraph.Graph(n=6, directed=False)
    # Clique A: {0,1,2}; Clique B: {3,4,5}; weak bridge 2–3.
    edges = [(0, 1), (0, 2), (1, 2), (3, 4), (3, 5), (4, 5), (2, 3)]
    weights = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.05]
    g.add_edges(edges)
    g.es["weight"] = weights
    return g


def test_two_cliques_split_at_coarsest_level():
    g = _two_cliques_graph()
    # CPM resolution: smaller than modularity values; 0.1 separates the two
    # cliques across the weak bridge (weight 0.05) cleanly.
    levels = run_hierarchical_leiden(g, resolutions=(0.1,), seed=42)
    assert len(levels) == 1
    labels = levels[0]
    # Cliques should land in different communities.
    a_labels = {labels[v] for v in (0, 1, 2)}
    b_labels = {labels[v] for v in (3, 4, 5)}
    assert len(a_labels) == 1 and len(b_labels) == 1
    assert a_labels != b_labels


def test_strict_nesting_invariant():
    """Vertices that share a label at a finer level must share it at every coarser level."""
    g = _two_cliques_graph()
    levels = run_hierarchical_leiden(g, resolutions=(0.1, 0.3, 0.6), seed=42)
    n = g.vcount()
    for u in range(n):
        for v in range(u + 1, n):
            for d in range(1, len(levels)):
                if levels[d][u] == levels[d][v]:
                    assert levels[d - 1][u] == levels[d - 1][v], (
                        f"nesting broken: vertices {u}, {v} share level {d} label "
                        f"but differ at level {d - 1}"
                    )


def test_empty_graph_returns_empty_labels():
    g = igraph.Graph(directed=False)
    levels = run_hierarchical_leiden(g, resolutions=(0.05, 0.1), seed=0)
    assert levels == [[], []]


def test_min_community_size_pads_uniform_depth():
    """Vertices in a too-small subgraph still receive labels at every level."""
    # Triangle of 3 vertices with weights all 1; min_community_size=4 forces
    # the algorithm to abandon subdivision after level 0.
    g = igraph.Graph(n=3, directed=False)
    g.add_edges([(0, 1), (1, 2), (0, 2)])
    g.es["weight"] = [1.0, 1.0, 1.0]
    levels = run_hierarchical_leiden(
        g, resolutions=(0.05, 0.05, 0.05), seed=0, min_community_size=4
    )
    assert len(levels) == 3
    for d in range(3):
        assert len(levels[d]) == 3
        # Single label across all three vertices at every depth.
        assert len(set(levels[d])) == 1
