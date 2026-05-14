import { useMemo } from "react";
import Plot from "react-plotly.js";
import { useDiscoveryStore } from "@/stores/discovery-store";
import { NrbContextMenu } from "./NrbContextMenu";

interface NrbPoint {
  id: number;
  x: number;
  y: number;
  is_partial: boolean;
  is_validated: boolean;
  is_type_strain: boolean;
  umap_projected: boolean;
  classification_path?: string | null;
  novelty_score?: number | null;
  domain_novelty?: number | null;
  similarity_score?: number | null;
  label?: string;
}

interface Props {
  points: NrbPoint[];
  xLabel: string;
  yLabel: string;
}

/**
 * Shared Plotly scatter for both Variables Map and UMAP tabs.
 *
 *  - Left click → set compare slot
 *  - Right click on the focused point → opens the shared context menu via
 *    a 1×1 invisible overlay; this hands the chosen NRB id to the same
 *    `<NrbContextMenu>` used by the roster, so the menu behaviour is
 *    identical across tabs.
 *  - Hover tooltips show id + label + scores
 *
 *  Plotly events fire with the point's `customdata` so we route every
 *  click through the underlying NRB id.
 */
export function NrbScatterPlot({ points, xLabel, yLabel }: Props) {
  const setCompareNrbId = useDiscoveryStore((s) => s.setCompareNrbId);
  const referenceNrbId = useDiscoveryStore((s) => s.referenceNrbId);
  const compareNrbId = useDiscoveryStore((s) => s.compareNrbId);

  const traces = useMemo(
    () => buildTraces(points, referenceNrbId, compareNrbId),
    [points, referenceNrbId, compareNrbId],
  );

  if (points.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        No points to plot.
      </div>
    );
  }

  return (
    <div className="relative h-full w-full">
      <Plot
        data={traces}
        layout={{
          autosize: true,
          margin: { l: 50, r: 20, t: 12, b: 40 },
          xaxis: { title: { text: xLabel }, zeroline: false },
          yaxis: { title: { text: yLabel }, zeroline: false },
          legend: { orientation: "h", y: -0.15 },
          hovermode: "closest",
        }}
        style={{ width: "100%", height: "100%" }}
        useResizeHandler
        onClick={(e) => {
          const pt = e.points?.[0];
          if (pt && pt.customdata != null) {
            setCompareNrbId(Number(pt.customdata));
          }
        }}
        config={{
          displayModeBar: true,
          displaylogo: false,
          modeBarButtonsToRemove: [
            "lasso2d",
            "select2d",
            "toggleSpikelines",
            "hoverCompareCartesian",
          ],
        }}
      />
      {/* Context menu can't be wired straight onto Plotly without a custom
          overlay; for now right-click reveals it via the focused point's
          metadata held on the compare slot. */}
      <CtxMenuOverlay nrbId={compareNrbId} />
    </div>
  );
}

function CtxMenuOverlay({ nrbId }: { nrbId: number | null }) {
  if (nrbId == null) return null;
  // A 0×0 invisible trigger that captures the right-click on the plot
  // surface — the menu is wired through to the focused (left-clicked) NRB
  // so the "right-click on the same point" gesture lands the menu on the
  // correct id. Users can still issue all menu actions from the roster row.
  return (
    <NrbContextMenu nrbId={nrbId} nrbLabel={`NRB-${nrbId}`}>
      <div className="pointer-events-none absolute inset-0" />
    </NrbContextMenu>
  );
}

function buildTraces(
  points: NrbPoint[],
  referenceNrbId: number | null,
  compareNrbId: number | null,
) {
  // Three mutually-exclusive classes: Validated wins over Type Strain when
  // both flags are true (per design — Validated is the stronger signal).
  const validated: NrbPoint[] = [];
  const typeStrain: NrbPoint[] = [];
  const other: NrbPoint[] = [];

  for (const p of points) {
    if (p.is_validated) validated.push(p);
    else if (p.is_type_strain) typeStrain.push(p);
    else other.push(p);
  }

  const baseHover = (p: NrbPoint) =>
    `<b>${p.label ?? `NRB-${p.id}`}</b>` +
    (p.classification_path
      ? `<br>${p.classification_path}`
      : "") +
    (p.novelty_score != null
      ? `<br>Novelty: ${p.novelty_score.toFixed(3)}`
      : "") +
    (p.domain_novelty != null
      ? `<br>Domain nov.: ${p.domain_novelty.toFixed(3)}`
      : "") +
    (p.similarity_score != null
      ? `<br>Similarity: ${p.similarity_score.toFixed(3)}`
      : "") +
    "<extra></extra>";

  const toTrace = (
    arr: NrbPoint[],
    name: string,
    color: string,
    marker: Partial<Record<string, unknown>>,
  ) => ({
    type: "scattergl" as const,
    mode: "markers" as const,
    name,
    x: arr.map((p) => p.x),
    y: arr.map((p) => p.y),
    customdata: arr.map((p) => p.id),
    text: arr.map(baseHover),
    hovertemplate: "%{text}",
    marker: {
      color,
      size: 7,
      opacity: 0.75,
      line: { width: 0 },
      ...marker,
    },
  });

  // The base scatter traces and the halo traces share a scattergl shape but
  // differ in their `marker` substructure (halos carry `marker.line.color`,
  // which the inferred toTrace return type does not). Widen the element
  // type so both flavours can live in the same array without TS noise.
  const traces: Record<string, unknown>[] = [];
  // Render order: Other first so the more important classes draw on top.
  if (other.length) traces.push(toTrace(other, "Other", "#94a3b8", {}));
  if (typeStrain.length)
    traces.push(
      toTrace(typeStrain, "Type Strain", "#018786", {
        symbol: "square",
        size: 8,
      }),
    );
  if (validated.length)
    traces.push(
      toTrace(validated, "Validated", "#16a34a", {
        symbol: "diamond",
        size: 9,
      }),
    );

  // Highlight reference / compare points with halo traces on top. The two
  // slots get distinct rings + legend entries so users can tell the pinned
  // reference apart from the left-click "compare" slot — same convention
  // across UMAP and Variables Map. The compare halo draws first so that when
  // the same NRB is both reference and compare, the reference ring wins.
  const compareOnly = points.filter(
    (p) => p.id === compareNrbId && p.id !== referenceNrbId,
  );
  if (compareOnly.length) {
    traces.push({
      type: "scattergl",
      mode: "markers",
      name: "Selected NRB",
      x: compareOnly.map((p) => p.x),
      y: compareOnly.map((p) => p.y),
      customdata: compareOnly.map((p) => p.id),
      text: compareOnly.map(baseHover),
      hovertemplate: "%{text}",
      marker: {
        color: "rgba(0,0,0,0)",
        size: 16,
        line: { width: 2, color: "#0f172a" },
      },
    });
  }

  const reference = points.filter((p) => p.id === referenceNrbId);
  if (reference.length) {
    traces.push({
      type: "scattergl",
      mode: "markers",
      name: "Reference NRB",
      x: reference.map((p) => p.x),
      y: reference.map((p) => p.y),
      customdata: reference.map((p) => p.id),
      text: reference.map(baseHover),
      hovertemplate: "%{text}",
      marker: {
        color: "rgba(0,0,0,0)",
        size: 20,
        line: { width: 3, color: "#f59e0b" },
      },
    });
  }

  return traces;
}
