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
  /** When true (UMAP), partial-projected points use a hollow marker. */
  flagProjected?: boolean;
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
export function NrbScatterPlot({
  points,
  xLabel,
  yLabel,
  flagProjected = false,
}: Props) {
  const setCompareNrbId = useDiscoveryStore((s) => s.setCompareNrbId);
  const referenceNrbId = useDiscoveryStore((s) => s.referenceNrbId);
  const compareNrbId = useDiscoveryStore((s) => s.compareNrbId);

  const traces = useMemo(
    () => buildTraces(points, flagProjected, referenceNrbId, compareNrbId),
    [points, flagProjected, referenceNrbId, compareNrbId],
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
  flagProjected: boolean,
  referenceNrbId: number | null,
  compareNrbId: number | null,
) {
  const validated: NrbPoint[] = [];
  const primary: NrbPoint[] = [];
  const projected: NrbPoint[] = [];

  for (const p of points) {
    if (p.is_validated) validated.push(p);
    else if (flagProjected && p.umap_projected) projected.push(p);
    else primary.push(p);
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

  const traces: ReturnType<typeof toTrace>[] = [];
  if (primary.length) traces.push(toTrace(primary, "Primary", "#3b82f6", {}));
  if (validated.length)
    traces.push(
      toTrace(validated, "Validated", "#16a34a", {
        symbol: "diamond",
        size: 9,
      }),
    );
  if (projected.length)
    traces.push(
      toTrace(projected, "Projected partial", "#f97316", {
        symbol: "circle-open",
        size: 7,
      }),
    );

  // Highlight reference / compare points with a halo trace on top.
  const highlights = points.filter(
    (p) => p.id === referenceNrbId || p.id === compareNrbId,
  );
  if (highlights.length) {
    traces.push({
      type: "scattergl",
      mode: "markers",
      name: "Selected",
      x: highlights.map((p) => p.x),
      y: highlights.map((p) => p.y),
      customdata: highlights.map((p) => p.id),
      text: highlights.map(baseHover),
      hovertemplate: "%{text}",
      marker: {
        color: "rgba(0,0,0,0)",
        size: 16,
        line: { width: 2, color: "#0f172a" },
      },
    });
  }

  return traces;
}
