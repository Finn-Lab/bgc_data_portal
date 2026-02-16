from __future__ import annotations
from typing import Dict, List, Tuple

import plotly.graph_objects as go
import plotly.io as pio


try:
    # If seaborn is available we can generate palette-driven colors
    from seaborn import color_palette  # type: ignore
except Exception:  # pragma: no cover
    color_palette = None  # type: ignore

try:
    from Bio.SeqFeature import SeqFeature
except Exception:  # pragma: no cover
    SeqFeature = object  # type: ignore

from .pfam_to_slim.pfam_annots import pfamToGoSlim

import colorsys
import hashlib


def _rgb_str_from_unit_rgb(r, g, b):
    return f"rgb({int(r*255)}, {int(g*255)}, {int(b*255)})"


def make_distinct_color_map(
    keys, seed=0.12, lightness_pair=(0.60, 0.66), saturation_pair=(0.78, 0.86)
):
    """
    Deterministic, non-repeating colors for arbitrary N.
    Uses golden-angle spacing in HLS space and alternates L/S for contrast.
    """
    phi = 0.618033988749895  # golden ratio conjugate
    klist = list(dict.fromkeys(sorted(keys)))  # stable, unique
    L0, L1 = lightness_pair
    S0, S1 = saturation_pair
    out = {}
    for i, k in enumerate(klist):
        h = (seed + i * phi) % 1.0
        l = L0 if (i % 2 == 0) else L1
        s = S0 if ((i // 2) % 2 == 0) else S1
        r, g, b = colorsys.hls_to_rgb(h, l, s)
        out[k] = _rgb_str_from_unit_rgb(r, g, b)
    return out


def color_for_unknown_label(label, l=0.62, s=0.82):
    """
    Deterministic fallback for labels not in the precomputed map.
    Hash -> hue; keeps mapping stable across runs.
    """
    h = (int(hashlib.md5(label.encode("utf-8")).hexdigest()[:6], 16) % 360) / 360.0
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return _rgb_str_from_unit_rgb(r, g, b)


# ---------- Arrow polygon helper ----------
def create_trace_data(
    start: int,
    end: int,
    strand: int,
    height: float = 0.6,  # visual thickness of the arrow band (y-units)
    _type: str = "CDS",
    level_spacing: float = 1.5,
    arrow_prop: float = 0.15,
) -> tuple:
    """
    Produce polygon coordinates (xs, ys) for an arrow; to be used with
    plotly Scatter(..., fill='toself').
    """
    arrow_prop = 0 if strand == 0 else arrow_prop
    h = height / 2.0 * (1.7 if "CDS" in _type else 1)  # CDS a bit taller
    x1, x2 = (start, end) if strand >= 0 else (end, start)
    arrow_length = abs(x2 - x1)
    delta = min(arrow_length * arrow_prop, 300)
    head_base = max(x1, x2 - delta) if strand >= 0 else min(x1, x2 + delta)
    level_offset = 0.0  # single level; we shift later by the track baseline

    ys = [
        level_offset - h,  # bottom
        level_offset + h,  # top
        level_offset + h,  # to head base
        level_offset,  # tip
        level_offset - h,  # bottom to head base
        level_offset - h,  # close polygon
    ]
    xs = [x1, x1, head_base, x2, head_base, x1]
    return xs, ys, _type


# ---------- Helpers ----------
def _qtext(qualifiers: Dict[str, List[str]]) -> str:
    """Format qualifiers dict into HTML lines for hover."""
    return "<br>".join(f"<b>{k}</b>: {', '.join(v)}" for k, v in qualifiers.items())


def _rect_coords(x1: int, x2: int, height: float) -> Tuple[List[int], List[float]]:
    xs = [x1, x2, x2, x1, x1]
    ys = [-height / 2, -height / 2, height / 2, height / 2, -height / 2]
    return xs, ys


def _assign_nonoverlap_lanes(intervals: List[Tuple[int, int]]) -> List[int]:
    """Greedy lane assignment so rectangles never overlap on the same lane."""
    lanes_end: List[int] = []
    lane_idx: List[int] = []
    for sidx, (start, end) in sorted(list(enumerate(intervals)), key=lambda t: t[1][0]):
        placed = False
        for ln, last_end in enumerate(lanes_end):
            if start >= last_end:
                lanes_end[ln] = end
                lane_idx.append((sidx, ln))
                placed = True
                break
        if not placed:
            lanes_end.append(end)
            lane_idx.append((sidx, len(lanes_end) - 1))
    lane_idx.sort()
    return [ln for _, ln in lane_idx]


# ---------- Seaborn → Plotly color helpers & palettes ----------
def seaborn_to_rgb_string(color):
    return f"rgb({int(color[0] * 255)}, {int(color[1] * 255)}, {int(color[2] * 255)})"


# Defaults (work even if seaborn is not installed)
DEFAULT_CDS_COLOR = "#ffffff"
DEFAULT_ANNOT_COLOR = "#cfcfcf"
DEFAULT_BGC_COLOR = "#c8c8c8"

# If seaborn is present, compute palette-driven colors as requested
DETECTOR_COLORS: Dict[str, str] = {}

if color_palette is not None:
    # DEFAULT_ANNOT_COLOR from Set3[2]
    try:
        DEFAULT_ANNOT_COLOR = seaborn_to_rgb_string(color_palette("Set3")[2])
    except Exception:
        pass

    # Build GO slim colors if a pfamToGoSlim mapping is available in the runtime
    # (expected: Dict[str, Set[str]]). We gracefully skip if it's missing.
    try:
        sorted_go_slims = sorted(
            {slim for slim_set in pfamToGoSlim.values() for slim in slim_set}
        )
    except Exception:
        sorted_go_slims = []

    GO_SLIM_COLORS = make_distinct_color_map(sorted_go_slims)

    # Detector/source colors (normalized to lowercase keys)
    try:
        set3 = color_palette("Set3")
        DETECTOR_COLORS = {
            "mibig": seaborn_to_rgb_string(set3[8]),
            "sanntis": seaborn_to_rgb_string(set3[0]),
            "gecco": seaborn_to_rgb_string(set3[1]),
            "antismash": seaborn_to_rgb_string(set3[3]),
        }
    except Exception:
        DETECTOR_COLORS = {
            "mibig": "#b3de69",
            "sanntis": "#8dd3c7",
            "gecco": "#ffffb3",
            "antismash": "#bebada",
        }


# ---------- Main plotting function ----------
def plot_bgc_region(
    record,
    height: int = 520,
    bgc_height_factor: float = 0.2,
    bgc_baseline_offset: float = -0.09,
    bgc_lane_gap_factor: float = 1.0,
) -> go.Figure:
    """
    Build an interactive Plotly figure for a genomic region encoded in a SeqRecord
    constructed by build_gff_dataframe (features: CLUSTER, CDS, ANNOT).

    Hover shows feature qualifiers; CDS is white w/ black edge, ANNOT colored
    by GO-slim w/ black edge; BGCs occupy non-overlapping lanes.
    """
    # Split features
    clusters = [f for f in record.features if getattr(f, "type", "") == "CLUSTER"]
    cdss = [f for f in record.features if getattr(f, "type", "") == "CDS"]
    annots = [f for f in record.features if getattr(f, "type", "") == "ANNOT"]

    fig = go.Figure()

    # ---- Track baselines
    # CDS and ANNOT share the SAME baseline so ANNOT sits centered over CDS.
    base_y_cds = 0.6
    base_y_annot = base_y_cds  # <-- critical alignment
    base_y_bgc0 = float(bgc_baseline_offset)
    lane_gap = 0.05

    xlen = len(record.seq)
    # default x-axis fractional position (0..1, measured from bottom of plot area)
    xaxis_pos = 0.05

    # ---- Background bands (drawn BELOW; they never block hover)
    fig.add_shape(
        type="rect",
        x0=0,
        x1=xlen,
        y0=base_y_cds - 0.45,
        y1=base_y_cds + 0.45,
        fillcolor="#f8f8f8",
        line=dict(width=0),
        layer="below",
    )

    # ---- BGCs (non-overlapping lanes + background)
    if clusters:
        intervals = [(int(f.location.start), int(f.location.end)) for f in clusters]
        lanes = _assign_nonoverlap_lanes(intervals)
        max_lane = max(lanes) if lanes else 0

        # Scale background band and bar heights by bgc_height_factor so callers
        # can make the BGC bars much thinner (e.g. 0.2 = one-fifth height).
        bgc_band_half = 0.35 * float(
            bgc_height_factor
        )  # half-height for background band
        cluster_height = 0.55 * float(
            bgc_height_factor
        )  # full height for cluster polygon

        # Ensure lane spacing prevents overlap; allow callers to scale the
        # default lane gap via bgc_lane_gap_factor (<1.0 makes lanes closer).
        requested_gap = lane_gap * float(bgc_lane_gap_factor)
        min_needed = 2 * bgc_band_half + 0.05
        bgc_lane_gap = max(requested_gap, min_needed)

        for ln in range(max_lane + 1):
            y0 = base_y_bgc0 - ln * bgc_lane_gap - bgc_band_half
            y1 = base_y_bgc0 - ln * bgc_lane_gap + bgc_band_half
            fig.add_shape(
                type="rect",
                x0=0,
                x1=xlen,
                y0=y0,
                y1=y1,
                fillcolor="#fdf6e3",
                line=dict(width=0),
                layer="below",
            )

        shown_sources = set()
        for f, lane in zip(clusters, lanes):
            s, e = int(f.location.start), int(f.location.end)
            raw_src = f.qualifiers.get("source", ["Unknown detector"])[0]
            src_key = (raw_src or "").strip().lower()
            color = DETECTOR_COLORS.get(src_key, DEFAULT_BGC_COLOR)
            xs, ys = _rect_coords(s, e, height=cluster_height)
            ys = [y + (base_y_bgc0 - lane * bgc_lane_gap) for y in ys]
            qtxt = _qtext(f.qualifiers)

            legend_name = raw_src
            legend_group = "BGC"

            # build per-vertex customdata so point.customdata exists in click events
            trace_custom = [{"type": "BGC", "id": None} for _ in xs]
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    mode="lines",
                    fill="toself",
                    line=dict(width=0),
                    fillcolor=color,
                    hoveron="fills",
                    text=qtxt,  # hover = qualifiers
                    hovertemplate="%{text}<extra></extra>",
                    legendgroup=legend_group,
                    legendgrouptitle_text=legend_group,
                    name=legend_name,
                    showlegend=(legend_name not in shown_sources),
                    customdata=trace_custom,
                )
            )
            shown_sources.add(legend_name)

        # compute an x-axis vertical position so tick labels sit just above
        # the BGC band area (map desired y to fractional position)
        try:
            # determine the vertical span of the plotted area
            y_min = base_y_bgc0 - 1.2
            y_max = base_y_cds + 1.0

            # top and bottom of the BGC block (respecting lane count and gap)
            top_bgc = base_y_bgc0 + bgc_band_half
            bottom_bgc = base_y_bgc0 - max_lane * bgc_lane_gap - bgc_band_half
            # Simplify: place tick labels exactly one lane gap below the lowest BGC
            desired_y = bottom_bgc - bgc_lane_gap

            if y_max > y_min:
                xaxis_pos = float((desired_y - y_min) / (y_max - y_min))
                xaxis_pos = max(0.0, min(1.0, xaxis_pos))
        except Exception:
            # keep default if anything goes wrong
            pass

    # ---- CDS (white fill + black edge)
    cds_shown = False
    for f in cdss:
        s, e = int(f.location.start), int(f.location.end)
        strand = int(f.location.strand or 0)
        xs, ys, _ = create_trace_data(s, e, strand, height=0.6, _type="CDS")
        ys = [y + base_y_cds for y in ys]
        qtxt = _qtext(
            {
                k: v
                for k, v in f.qualifiers.items()
                if v and k not in ("translation", "gene_caller")
            }
        )
        # per-vertex customdata for CDS
        trace_custom = [
            {"type": "CDS", "id": f.qualifiers.get("ID", [""])[0]} for _ in xs
        ]
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines",
                fill="toself",
                line=dict(color="black", width=1.2),
                fillcolor=DEFAULT_CDS_COLOR,
                hoveron="fills",
                text=qtxt,
                hovertemplate="%{text}<extra></extra>",
                legendgroup="CDS",
                legendgrouptitle_text="CDS",
                name="",
                showlegend=(not cds_shown),
                customdata=trace_custom,
            )
        )
        cds_shown = True

    # ---- ANNOT (colored by GO-slim + black edge) — added AFTER CDS to sit on top
    annot_legend_keys = set()
    for f in annots:
        s, e = int(f.location.start), int(f.location.end)
        strand = int(f.location.strand or 0)
        try:
            gos = f.qualifiers.get("GOslim") or []
        except Exception:
            gos = []
        go_name = gos[0] if gos else "Unknown GO"
        fillcol = GO_SLIM_COLORS.get(go_name, DEFAULT_ANNOT_COLOR)

        xs, ys, _ = create_trace_data(s, e, strand, height=0.6, _type="ANNOT")
        ys = [y + base_y_annot for y in ys]  # same baseline as CDS
        qtxt = _qtext(f.qualifiers)

        legend_group = "Pfam - GO slim"
        legend_name = go_name.capitalize()

        # per-vertex customdata for ANNOT
        trace_custom = [
            {"type": "ANNOT", "id": f.qualifiers.get("ID", [""])[0]} for _ in xs
        ]
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines",
                fill="toself",
                line=dict(color="black", width=0.9),
                fillcolor=fillcol,
                hoveron="fills",
                text=qtxt,
                hovertemplate="%{text}<extra></extra>",
                legendgroup=legend_group,
                legendgrouptitle_text=legend_group,
                name=legend_name,
                showlegend=(go_name not in annot_legend_keys),
                customdata=trace_custom,
            )
        )
        annot_legend_keys.add(go_name)

    # ---- Layout
    fig.update_layout(
        height=height,
        template="simple_white",
        hovermode="closest",  # ensures polygon hover works as expected
        margin=dict(l=60, r=20, t=20, b=50),
        xaxis=dict(
            showgrid=False,
            range=[0, len(record.seq)],
            zeroline=False,
            showline=False,
            ticks="",
            position=xaxis_pos,
        ),
        yaxis=dict(
            range=[base_y_bgc0 - 1.2, base_y_cds + 1.0],
            visible=False,  # hide axis line, ticks, and labels
            showticklabels=False,
            showline=False,
            zeroline=False,
            showgrid=False,
            ticks="",
        ),
        clickmode="event+select",
        showlegend=True,
    )
    return fig


def plot_contig_region(record) -> str:
    """Save the interactive figure to HTML."""
    fig = plot_bgc_region(record)
    html_str = pio.to_html(fig, full_html=False, div_id="bgc-plot")
    return html_str
