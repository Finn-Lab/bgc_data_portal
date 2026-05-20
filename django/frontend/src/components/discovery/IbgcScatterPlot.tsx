import { useMemo } from "react";
import Plot from "react-plotly.js";
import { useDiscoveryStore } from "@/stores/discovery-store";
import { IbgcContextMenu } from "./IbgcContextMenu";

interface IbgcPoint {
  id: number;
  x: number;
  y: number;
  is_partial: boolean;
  is_validated: boolean;
  is_type_strain: boolean;
  umap_projected: boolean;
  /** Negative-id iBGC sourced from an ephemeral asset upload — rendered
   *  with a distinct marker so the user spots their submitted data. */
  is_asset?: boolean;
  classification_path?: string | null;
  novelty_score?: number | null;
  domain_novelty?: number | null;
  similarity_score?: number | null;
  label?: string;
}

interface Props {
  points: IbgcPoint[];
  xLabel: string;
  yLabel: string;
}

/**
 * Shared Plotly scatter for both Variables Map and UMAP tabs.
 *
 *  - Left click → set compare slot
 *  - Right click on the focused point → opens the shared context menu via
 *    a 1×1 invisible overlay; this hands the chosen iBGC id to the same
 *    `<IbgcContextMenu>` used by the roster, so the menu behaviour is
 *    identical across tabs.
 *  - Hover tooltips show id + label + scores
 *
 *  Plotly events fire with the point's `customdata` so we route every
 *  click through the underlying iBGC id.
 */
export function IbgcScatterPlot({ points, xLabel, yLabel }: Props) {
  const setCompareIbgcId = useDiscoveryStore((s) => s.setCompareIbgcId);
  const referenceIbgcId = useDiscoveryStore((s) => s.referenceIbgcId);
  const compareIbgcId = useDiscoveryStore((s) => s.compareIbgcId);

  const traces = useMemo(
    () => buildTraces(points, referenceIbgcId, compareIbgcId),
    [points, referenceIbgcId, compareIbgcId],
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
            setCompareIbgcId(Number(pt.customdata));
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
      <CtxMenuOverlay ibgcId={compareIbgcId} />
    </div>
  );
}

function CtxMenuOverlay({ ibgcId }: { ibgcId: number | null }) {
  if (ibgcId == null) return null;
  // A 0×0 invisible trigger that captures the right-click on the plot
  // surface — the menu is wired through to the focused (left-clicked) iBGC
  // so the "right-click on the same point" gesture lands the menu on the
  // correct id. Users can still issue all menu actions from the roster row.
  return (
    <IbgcContextMenu ibgcId={ibgcId} ibgcLabel={`iBGC-${ibgcId}`}>
      <div className="pointer-events-none absolute inset-0" />
    </IbgcContextMenu>
  );
}

function buildTraces(
  points: IbgcPoint[],
  referenceIbgcId: number | null,
  compareIbgcId: number | null,
) {
  // Four mutually-exclusive classes — asset > validated > type strain >
  // other — so submitted iBGCs always render on top with their distinctive
  // marker regardless of their other flags.
  const asset: IbgcPoint[] = [];
  const validated: IbgcPoint[] = [];
  const typeStrain: IbgcPoint[] = [];
  const other: IbgcPoint[] = [];

  for (const p of points) {
    if (p.is_asset) asset.push(p);
    else if (p.is_validated) validated.push(p);
    else if (p.is_type_strain) typeStrain.push(p);
    else other.push(p);
  }

  const baseHover = (p: IbgcPoint) =>
    `<b>${p.label ?? `iBGC-${p.id}`}</b>` +
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
    arr: IbgcPoint[],
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
  if (asset.length)
    traces.push(
      toTrace(asset, "Submitted asset", "#b45309", {
        symbol: "star",
        size: 13,
        line: { width: 1.5, color: "#1e293b" },
        opacity: 0.95,
      }),
    );

  // Highlight reference / compare points with halo traces on top. The two
  // slots get distinct rings + legend entries so users can tell the pinned
  // reference apart from the left-click "compare" slot — same convention
  // across UMAP and Variables Map. The compare halo draws first so that when
  // the same iBGC is both reference and compare, the reference ring wins.
  const compareOnly = points.filter(
    (p) => p.id === compareIbgcId && p.id !== referenceIbgcId,
  );
  if (compareOnly.length) {
    traces.push({
      type: "scattergl",
      mode: "markers",
      name: "Selected iBGC",
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

  const reference = points.filter((p) => p.id === referenceIbgcId);
  if (reference.length) {
    traces.push({
      type: "scattergl",
      mode: "markers",
      name: "Reference iBGC",
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
