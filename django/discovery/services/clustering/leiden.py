"""Strictly nested hierarchical Leiden community detection.

Naive multi-resolution Leiden runs are *not* nested — a vertex can swap
parents between coarser and finer runs. We enforce nesting top-down by
inducing a subgraph for each parent community and partitioning *within*
that subgraph at the next resolution. Communities below
``min_community_size`` are not subdivided further; their leaf labels pad
downward so the path depth is uniform.

Labels at each level are globally unique within that level (they form a
partition of the vertex set). Paths are derived in ``paths.py`` by reading
the per-level label of each vertex; nesting is guaranteed by construction
so two vertices that share a level-d label always share their level-(d-1)
label.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import igraph as ig

log = logging.getLogger(__name__)


def run_hierarchical_leiden(
    graph: "ig.Graph",
    resolutions: tuple[float, ...] = (0.03, 0.08, 0.15, 0.25),
    *,
    seed: int = 42,
    min_community_size: int = 2,
) -> list[list[int]]:
    """Partition ``graph`` at each resolution top-down within each parent.

    Returns
    -------
    levels:
        ``levels[level][vertex_idx]`` is the integer label for that vertex
        at that depth. Length ``len(resolutions)``. Level 0 is coarsest; the
        last is finest. Two vertices share a label at level d iff they share
        all labels at levels 0..d.
    """
    import leidenalg as la

    n = graph.vcount()
    if n == 0:
        return [[] for _ in resolutions]

    n_levels = len(resolutions)
    levels: list[list[int]] = [[0] * n for _ in range(n_levels)]
    # Per-level monotonically-increasing label counters.
    next_label_at = [0] * n_levels

    def _emit_singleton_subtree(vertices: list[int], depth: int) -> None:
        """Assign one new label per level at depths >= ``depth`` to all ``vertices``.

        Used when a subgraph is too small to subdivide further: its members
        share one label at the current level and one label per level below
        it (all the same set of members), preserving the strict nesting
        invariant while keeping the leaf path well-defined.
        """
        for sublevel in range(depth, n_levels):
            label = next_label_at[sublevel]
            next_label_at[sublevel] += 1
            for v in vertices:
                levels[sublevel][v] = label

    def _partition(vertices: list[int], depth: int) -> None:
        if depth >= n_levels or not vertices:
            return
        sub = graph.subgraph(vertices)
        if sub.vcount() < min_community_size:
            _emit_singleton_subtree(vertices, depth)
            return
        weights = sub.es["weight"] if "weight" in sub.es.attributes() else None
        partition = la.find_partition(
            sub,
            la.CPMVertexPartition,
            weights=weights,
            resolution_parameter=resolutions[depth],
            seed=seed + depth,
        )
        # Stable-sort communities: largest first, ties broken by smallest
        # member index so paths are reproducible across runs.
        sorted_communities = sorted(
            partition, key=lambda c: (-len(c), min(c) if c else 0)
        )
        for community_sub in sorted_communities:
            if not community_sub:
                continue
            members_global = [vertices[v] for v in community_sub]
            label = next_label_at[depth]
            next_label_at[depth] += 1
            for v in members_global:
                levels[depth][v] = label
            _partition(members_global, depth + 1)

    _partition(list(range(n)), depth=0)
    log.info(
        "run_hierarchical_leiden: %d vertices, %d levels (counts per level=%s)",
        n, n_levels, next_label_at,
    )
    return levels
