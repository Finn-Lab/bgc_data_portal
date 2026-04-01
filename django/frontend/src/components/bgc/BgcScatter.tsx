import { useMemo, useState, useCallback } from "react";
import Plot from "react-plotly.js";
import { useBgcScatter } from "@/hooks/use-bgc-scatter";
import { useSelectionStore } from "@/stores/selection-store";
import { useShortlistStore } from "@/stores/shortlist-store";
import { useModeStore } from "@/stores/mode-store";
import { useQueryStore } from "@/stores/query-store";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";

const BGC_CLASS_COLORS: Record<string, string> = {
  Polyketide: "#3b82f6",
  NRP: "#ef4444",
  RiPP: "#22c55e",
  Terpene: "#f97316",
  Saccharide: "#a855f7",
  Alkaloid: "#14b8a6",
  Other: "#6b7280",
};

interface BgcScatterProps {
  assemblyIdsOverride?: number[];
  bgcIdsOverride?: number[];
  highlightBgcId?: number;
  markerSymbol?: string;
}

export function BgcScatter({ assemblyIdsOverride, bgcIdsOverride, highlightBgcId, markerSymbol }: BgcScatterProps = {}) {
  const [showMibig, setShowMibig] = useState(true);
  const mode = useModeStore((s) => s.mode);
  const activeGenomeId = useSelectionStore((s) => s.activeGenomeId);
  const activeBgcId = useSelectionStore((s) => s.activeBgcId);
  const setActiveBgcId = useSelectionStore((s) => s.setActiveBgcId);
  const genomeShortlist = useShortlistStore((s) => s.genomes);
  const resultBgcIds = useQueryStore((s) => s.resultBgcIds);

  // When bgcIdsOverride is provided (e.g. assess mode), use it directly
  const assemblyIds = bgcIdsOverride
    ? undefined
    : assemblyIdsOverride
      ? assemblyIdsOverride
      : mode === "explore"
        ? genomeShortlist.length > 0
          ? genomeShortlist.map((g) => g.id)
          : activeGenomeId
            ? [activeGenomeId]
            : []
        : undefined;

  // Query mode: filter by query result BGC IDs
  const bgcIds = bgcIdsOverride
    ? bgcIdsOverride
    : !assemblyIdsOverride && mode === "query" ? resultBgcIds : undefined;
  const hasQueryResults = mode === "query" && resultBgcIds.length > 0;

  const hasData = bgcIdsOverride
    ? bgcIdsOverride.length > 0
    : assemblyIdsOverride
      ? assemblyIdsOverride.length > 0
      : mode === "explore"
        ? (genomeShortlist.length > 0 || activeGenomeId != null)
        : hasQueryResults;

  const { data: points, isLoading } = useBgcScatter({
    assemblyIds: assemblyIds as number[] | undefined,
    bgcIds,
    includeMibig: showMibig,
    enabled: hasData,
  });

  const traces = useMemo(() => {
    if (!points?.length) return [];

    const mibigPts = points.filter((p) => p.is_mibig);
    const bgcPts = points.filter((p) => !p.is_mibig);

    // Group BGC points by class
    const groups = new Map<string, typeof bgcPts>();
    for (const pt of bgcPts) {
      const cls = pt.bgc_class || "Other";
      const existing = groups.get(cls);
      if (existing) {
        existing.push(pt);
      } else {
        groups.set(cls, [pt]);
      }
    }

    const result: Plotly.Data[] = [];

    // MIBiG reference trace
    if (mibigPts.length > 0 && showMibig) {
      result.push({
        type: "scatter" as const,
        mode: "markers" as const,
        name: "MIBiG references",
        x: mibigPts.map((p) => p.umap_x),
        y: mibigPts.map((p) => p.umap_y),
        customdata: mibigPts.map((p) => p.id),
        text: mibigPts.map((p) => p.compound_name ?? p.bgc_class),
        hoverinfo: "text" as const,
        marker: {
          symbol: "triangle-up",
          color: "#d1d5db",
          size: 10,
          opacity: 0.7,
        },
      });
    }

    // BGC traces per class
    for (const [cls, pts] of groups) {
      result.push({
        type: "scatter" as const,
        mode: "markers" as const,
        name: cls,
        x: pts.map((p) => p.umap_x),
        y: pts.map((p) => p.umap_y),
        customdata: pts.map((p) => p.id),
        text: pts.map((p) => `${p.bgc_class}<br>ID: ${p.id}`),
        hoverinfo: "text" as const,
        marker: {
          symbol: markerSymbol || "circle",
          color: BGC_CLASS_COLORS[cls] ?? "#6b7280",
          size: markerSymbol ? 10 : 8,
          opacity: 0.7,
          line: {
            color: pts.map((p) =>
              p.id === activeBgcId ? "#000" : "transparent"
            ),
            width: pts.map((p) => (p.id === activeBgcId ? 2 : 0)),
          },
        },
      });
    }

    // Highlight trace for assessed BGC (star overlay)
    if (highlightBgcId && points) {
      const hp = points.find((p) => p.id === highlightBgcId);
      if (hp) {
        result.push({
          type: "scatter" as const,
          mode: "markers" as const,
          name: "Assessed BGC",
          x: [hp.umap_x],
          y: [hp.umap_y],
          customdata: [hp.id],
          text: [`Assessed: ${hp.bgc_class}<br>ID: ${hp.id}`],
          hoverinfo: "text" as const,
          marker: {
            symbol: "star",
            size: 18,
            color: "#3b82f6",
            line: { color: "black", width: 1.5 },
          },
        });
      }
    }

    return result;
  }, [points, activeBgcId, showMibig, highlightBgcId]);

  const handleClick = useCallback(
    (event: Plotly.PlotMouseEvent) => {
      const point = event.points[0];
      if (point?.customdata) {
        setActiveBgcId(point.customdata as number);
      }
    },
    [setActiveBgcId]
  );

  if (!hasData) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        {mode === "query"
          ? "Run a query to see results"
          : "Select or shortlist genomes to view their BGC chemical space"}
      </p>
    );
  }

  if (isLoading) {
    return <Skeleton className="h-64 w-full" />;
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Checkbox
          id="show-mibig"
          checked={showMibig}
          onCheckedChange={(v) => setShowMibig(v === true)}
        />
        <Label htmlFor="show-mibig" className="text-xs cursor-pointer">
          Show MIBiG references
        </Label>
      </div>
      <Plot
        data={traces}
        layout={{
          autosize: true,
          height: 300,
          margin: { l: 40, r: 10, t: 10, b: 40 },
          xaxis: { title: { text: "UMAP 1", font: { size: 11 } } },
          yaxis: { title: { text: "UMAP 2", font: { size: 11 } } },
          showlegend: true,
          legend: { font: { size: 9 }, orientation: "h" as const, y: -0.3 },
          hovermode: "closest" as const,
        }}
        config={{ displayModeBar: false, responsive: true }}
        style={{ width: "100%" }}
        onClick={handleClick}
      />
    </div>
  );
}
