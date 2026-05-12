"""Post-clustering MIBiG validation artifacts.

After a clustering run has been applied (NRBs + DashboardBgcs updated with
their gene_cluster_family and umap coords), this module emits three files
under ``settings.CLUSTERING_ARTIFACTS_DIR / <run_sha[:12]>/``:

* ``mibig_validation.tsv``                  — one row per MIBiG DashboardBgc
* ``umap_scatter.html``                     — Plotly UMAP, MIBiG colored by class
* ``mibig_class_cluster_heatmap.html``      — Plotly heatmap (class × leaf cluster)

The TSV captures cluster assignments + purity metrics for each MIBiG entry,
giving a direct quality check against curated MIBiG taxonomies. The
visualizations are interactive (Plotly HTML, plotly.js loaded from CDN) so
the run dir stays compact.

The gray-background trace in the UMAP plot is capped at
``MAX_BACKGROUND_NRBS`` randomly sampled non-MIBiG NRBs (deterministic via
the run seed); every MIBiG NRB is always drawn through its colored per-class
overlay, so visual focus is preserved as datasets scale into the hundreds
of thousands.

If a dataset has no MIBiG entries at all the function logs a warning and
emits only a monochrome UMAP — no error is raised.
"""

from __future__ import annotations

import logging
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

TOP_N_CLUSTERS_FOR_HEATMAP = 50
MAX_BACKGROUND_NRBS = 5_000


def emit_run_artifacts(run, *, nrb_ids, leaf_paths, coords) -> Path:
    """Materialize the TSV + two HTML files for an applied ClusteringRun.

    Parameters
    ----------
    run : ClusteringRun
        The just-completed run (must already have ``sha256`` populated).
    nrb_ids : sequence[int]
        Row-aligned NRB ids — matches ``leaf_paths`` and ``coords`` indices.
    leaf_paths : sequence[str]
        Leaf cluster path per NRB (``DashboardGCF.family_path``-style ltree).
    coords : ndarray (n, 2)
        UMAP coords per NRB.

    Returns
    -------
    Path
        Absolute path to the artifact directory.
    """
    from django.conf import settings

    out_dir = Path(settings.CLUSTERING_ARTIFACTS_DIR) / run.sha256[:12]
    out_dir.mkdir(parents=True, exist_ok=True)

    nrb_lookup = {
        int(nrb_id): (leaf_paths[i], float(coords[i, 0]), float(coords[i, 1]))
        for i, nrb_id in enumerate(nrb_ids)
    }
    mibig_rows = _collect_mibig_rows(nrb_lookup)

    if mibig_rows:
        _build_mibig_validation_tsv(mibig_rows, out_dir / "mibig_validation.tsv")
        _build_confusion_heatmap_html(
            mibig_rows, out_dir / "mibig_class_cluster_heatmap.html",
            run_sha=run.sha256,
        )
    else:
        log.warning(
            "emit_run_artifacts: no MIBiG entries (is_validated=True with NRB) — "
            "skipping TSV and heatmap; emitting monochrome UMAP only"
        )

    _build_umap_plot_html(
        nrb_lookup, mibig_rows, out_dir / "umap_scatter.html",
        run_sha=run.sha256,
        seed=int(run.seed or 0),
    )

    log.info("emit_run_artifacts: wrote artifacts to %s", out_dir)
    return out_dir


def _collect_mibig_rows(
    nrb_lookup: dict[int, tuple[str, float, float]],
) -> list[dict[str, Any]]:
    """Pull MIBiG DashboardBgc rows and join with their NRB cluster info."""
    from discovery.models import DashboardBgc

    rows: list[dict[str, Any]] = []
    qs = (
        DashboardBgc.objects
        .filter(is_validated=True, non_redundant_bgc__isnull=False)
        .select_related("detector")
        .values_list(
            "bgc_accession",
            "id",
            "detector__tool",
            "non_redundant_bgc_id",
            "classification_path",
        )
    )
    for accession, dbgc_id, detector_tool, nrb_id, class_path in qs:
        cluster_info = nrb_lookup.get(int(nrb_id))
        if cluster_info is None:
            # NRB exists but isn't in the current run's vocabulary — skip.
            continue
        leaf_path, ux, uy = cluster_info
        class_path = class_path or ""
        class_top = class_path.split(".", 1)[0] if class_path else "unclassified"
        rows.append({
            "mibig_accession": accession,
            "dashboard_bgc_id": int(dbgc_id),
            "detector_tool": detector_tool or "",
            "non_redundant_bgc_id": int(nrb_id),
            "leaf_cluster_path": leaf_path,
            "umap_x": ux,
            "umap_y": uy,
            "mibig_class_top": class_top,
            "mibig_class_full_path": class_path,
        })
    return rows


def _build_mibig_validation_tsv(mibig_rows: list[dict[str, Any]], out_path: Path) -> None:
    import pandas as pd

    if not mibig_rows:
        return

    # Per-leaf-cluster counts for purity columns.
    leaf_size: Counter[str] = Counter()
    leaf_class_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in mibig_rows:
        leaf_size[row["leaf_cluster_path"]] += 1
        leaf_class_counts[row["leaf_cluster_path"]][row["mibig_class_top"]] += 1

    enriched = []
    for row in mibig_rows:
        leaf = row["leaf_cluster_path"]
        cls_top = row["mibig_class_top"]
        mibig_count_in_leaf = leaf_size[leaf]
        same_class = leaf_class_counts[leaf][cls_top]
        purity = same_class / mibig_count_in_leaf if mibig_count_in_leaf else 0.0
        # ltree level decomposition.
        level_parts = leaf.split(".") if leaf else []
        enriched.append({
            "mibig_accession": row["mibig_accession"],
            "dashboard_bgc_id": row["dashboard_bgc_id"],
            "detector_tool": row["detector_tool"],
            "non_redundant_bgc_id": row["non_redundant_bgc_id"],
            "leaf_cluster_path": leaf,
            "level_0_cluster": level_parts[0] if len(level_parts) > 0 else "",
            "level_1_cluster": level_parts[1] if len(level_parts) > 1 else "",
            "level_2_cluster": level_parts[2] if len(level_parts) > 2 else "",
            "level_3_cluster": level_parts[3] if len(level_parts) > 3 else "",
            "umap_x": row["umap_x"],
            "umap_y": row["umap_y"],
            "mibig_class_top": cls_top,
            "mibig_class_full_path": row["mibig_class_full_path"],
            "leaf_cluster_mibig_count": mibig_count_in_leaf,
            "leaf_cluster_mibig_purity": purity,
            "n_neighbors_same_class_in_cluster": same_class - 1,
        })

    df = pd.DataFrame(enriched).sort_values(
        ["leaf_cluster_path", "mibig_class_top", "mibig_accession"]
    )
    df.to_csv(out_path, sep="\t", index=False)
    log.info("MIBiG validation TSV: %d rows → %s", len(df), out_path)


def _sample_background_coords(
    nrb_lookup: dict[int, tuple[str, float, float]],
    mibig_nrb_ids: set[int],
    *,
    cap: int,
    seed: int,
) -> tuple[list[tuple[float, float]], int]:
    """Pick the gray-background NRBs: random sample of non-MIBiG, capped at ``cap``.

    Returns ``(sampled_xy_pairs, total_non_mibig)`` so the caller can label
    the trace with how many points the cloud represents vs. the full set.
    MIBiG NRBs are excluded here because they are always drawn separately
    via the per-class colored overlays.
    """
    items = [
        (x, y) for nrb_id, (_path, x, y) in nrb_lookup.items()
        if nrb_id not in mibig_nrb_ids
    ]
    total = len(items)
    if cap > 0 and total > cap:
        rng = random.Random(seed)
        items = rng.sample(items, cap)
    return items, total


def _build_umap_plot_html(
    nrb_lookup: dict[int, tuple[str, float, float]],
    mibig_rows: list[dict[str, Any]],
    out_path: Path,
    *,
    run_sha: str,
    seed: int,
) -> None:
    import plotly.graph_objects as go

    fig = go.Figure()
    # Background trace: random sample of non-MIBiG NRBs (capped). All MIBiG
    # NRBs are always plotted via the per-class colored overlays below, so
    # excluding them here avoids double-drawing.
    mibig_nrb_ids = {int(row["non_redundant_bgc_id"]) for row in mibig_rows}
    bg_items, total_non_mibig = _sample_background_coords(
        nrb_lookup, mibig_nrb_ids, cap=MAX_BACKGROUND_NRBS, seed=seed,
    )
    if bg_items:
        xs = [x for x, _ in bg_items]
        ys = [y for _, y in bg_items]
        if total_non_mibig > len(bg_items):
            bg_name = (
                f"non-MIBiG NRBs (sample of {len(bg_items):,}"
                f" / {total_non_mibig:,})"
            )
        else:
            bg_name = f"non-MIBiG NRBs ({len(bg_items):,})"
        fig.add_trace(
            go.Scattergl(
                x=xs, y=ys, mode="markers",
                marker=dict(size=4, color="lightgray", opacity=0.5),
                name=bg_name,
                hoverinfo="skip",
            )
        )

    # Per-class MIBiG overlays.
    if mibig_rows:
        rows_by_class: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in mibig_rows:
            rows_by_class[row["mibig_class_top"]].append(row)
        for class_top in sorted(rows_by_class):
            cluster_rows = rows_by_class[class_top]
            fig.add_trace(
                go.Scatter(
                    x=[r["umap_x"] for r in cluster_rows],
                    y=[r["umap_y"] for r in cluster_rows],
                    mode="markers",
                    marker=dict(size=7),
                    name=class_top,
                    text=[
                        f"{r['mibig_accession']}<br>"
                        f"{r['mibig_class_full_path']}<br>"
                        f"cluster={r['leaf_cluster_path']}"
                        for r in cluster_rows
                    ],
                    hoverinfo="text",
                )
            )

    fig.update_layout(
        title=f"MIBiG cluster overlay — run {run_sha[:12]}",
        xaxis_title="UMAP-1",
        yaxis_title="UMAP-2",
        yaxis=dict(scaleanchor="x", scaleratio=1),
        legend=dict(orientation="v", x=1.02, y=1.0),
        template="plotly_white",
    )
    fig.write_html(out_path, include_plotlyjs="cdn")
    log.info("UMAP scatter HTML → %s", out_path)


def _build_confusion_heatmap_html(
    mibig_rows: list[dict[str, Any]],
    out_path: Path,
    *,
    run_sha: str,
) -> None:
    import numpy as np
    import plotly.graph_objects as go

    if not mibig_rows:
        return

    # Aggregate counts per (class_top, leaf_path).
    counts: dict[tuple[str, str], int] = Counter()
    leaf_totals: Counter[str] = Counter()
    classes: set[str] = set()
    for row in mibig_rows:
        cls = row["mibig_class_top"]
        leaf = row["leaf_cluster_path"]
        counts[(cls, leaf)] += 1
        leaf_totals[leaf] += 1
        classes.add(cls)

    # Pick top-N leaves by total MIBiG count.
    top_leaves = [leaf for leaf, _ in leaf_totals.most_common(TOP_N_CLUSTERS_FOR_HEATMAP)]
    classes_sorted = sorted(classes)

    matrix = np.zeros((len(classes_sorted), len(top_leaves)), dtype=int)
    for ci, cls in enumerate(classes_sorted):
        for li, leaf in enumerate(top_leaves):
            matrix[ci, li] = counts.get((cls, leaf), 0)

    annotate = matrix.shape[0] <= 30 and matrix.shape[1] <= 30
    fig = go.Figure(
        data=go.Heatmap(
            z=matrix,
            x=top_leaves,
            y=classes_sorted,
            colorscale="Viridis",
            colorbar=dict(title="MIBiG count"),
            hovertemplate="class=%{y}<br>cluster=%{x}<br>count=%{z}<extra></extra>",
            text=matrix if annotate else None,
            texttemplate="%{text}" if annotate else None,
        )
    )
    fig.update_layout(
        title=(
            f"MIBiG class × leaf cluster — top {len(top_leaves)} clusters — "
            f"run {run_sha[:12]}"
        ),
        xaxis_title="leaf cluster path",
        yaxis_title="MIBiG class (top)",
        xaxis=dict(tickangle=-45),
        template="plotly_white",
    )
    fig.write_html(out_path, include_plotlyjs="cdn")
    log.info("MIBiG heatmap HTML → %s", out_path)
