import { useMemo, useState, useCallback, useEffect } from "react";
import Plot from "react-plotly.js";
import { useBgcScatter } from "@/hooks/use-bgc-scatter";
import { useSelectionStore } from "@/stores/selection-store";
import { useShortlistStore } from "@/stores/shortlist-store";
import { useModeStore } from "@/stores/mode-store";
import { useQueryStore } from "@/stores/query-store";
import type { BgcScatterPoint } from "@/api/types";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const BGC_CLASS_COLORS: Record<string, string> = {
  Polyketide: "#3b82f6",
  NRP: "#ef4444",
  RiPP: "#22c55e",
  Terpene: "#f97316",
  Saccharide: "#a855f7",
  Alkaloid: "#14b8a6",
  Other: "#6b7280",
};

const QUERY_AXIS_OPTIONS = [
  { value: "similarity_score", label: "Query Similarity" },
  { value: "novelty_score", label: "Novelty" },
  { value: "domain_novelty", label: "Domain Novelty" },
];

const EXPLORE_AXIS_OPTIONS = [
  { value: "novelty_score", label: "Novelty" },
  { value: "domain_novelty", label: "Domain Novelty" },
];

function getAxisOptions(mode: string) {
  return mode === "query" ? QUERY_AXIS_OPTIONS : EXPLORE_AXIS_OPTIONS;
}

function getDefaultAxes(mode: string, hasSmilesQuery: boolean) {
  if (mode === "query" && hasSmilesQuery) {
    return { x: "similarity_score", y: "novelty_score" };
  }
  if (mode === "query") {
    return { x: "domain_novelty", y: "novelty_score" };
  }
  return { x: "novelty_score", y: "domain_novelty" };
}

interface BgcScatterProps {
  assemblyIdsOverride?: number[];
  bgcIdsOverride?: number[];
  highlightBgcId?: number;
  markerSymbol?: string;
}

export function BgcScatter({ assemblyIdsOverride, bgcIdsOverride, highlightBgcId, markerSymbol }: BgcScatterProps = {}) {
  const [showValidated, setShowValidated] = useState(true);
  const mode = useModeStore((s) => s.mode);
  const activeAssemblyId = useSelectionStore((s) => s.activeAssemblyId);
  const activeBgcId = useSelectionStore((s) => s.activeBgcId);
  const setActiveBgcId = useSelectionStore((s) => s.setActiveBgcId);
  const assemblyShortlist = useShortlistStore((s) => s.assemblies);
  const resultBgcIds = useQueryStore((s) => s.resultBgcIds);
  const resultBgcData = useQueryStore((s) => s.resultBgcData);
  const smilesQuery = useQueryStore((s) => s.smilesQuery);
  const hasSmilesQuery = smilesQuery.trim().length > 0;

  const defaults = getDefaultAxes(mode, hasSmilesQuery);
  const [xAxis, setXAxis] = useState(defaults.x);
  const [yAxis, setYAxis] = useState(defaults.y);

  // Reset axes to defaults when mode or SMILES query changes
  useEffect(() => {
    const d = getDefaultAxes(mode, hasSmilesQuery);
    setXAxis(d.x);
    setYAxis(d.y);
  }, [mode, hasSmilesQuery]);

  const axisOptions = getAxisOptions(mode);

  // When bgcIdsOverride is provided (e.g. assess mode), use it directly
  const assemblyIds = bgcIdsOverride
    ? undefined
    : assemblyIdsOverride
      ? assemblyIdsOverride
      : mode === "explore"
        ? assemblyShortlist.length > 0
          ? assemblyShortlist.map((g) => g.id)
          : activeAssemblyId
            ? [activeAssemblyId]
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
        ? (assemblyShortlist.length > 0 || activeAssemblyId != null)
        : hasQueryResults;

  // When similarity_score is an axis, the scatter API can't provide it
  // (it's computed per-query). Use query result data directly instead.
  const useSimilarityAxis = mode === "query" && (xAxis === "similarity_score" || yAxis === "similarity_score");

  const { data: apiPoints, isLoading: apiLoading } = useBgcScatter({
    xAxis,
    yAxis,
    assemblyIds: assemblyIds as number[] | undefined,
    bgcIds,
    includeValidated: showValidated,
    enabled: hasData && !useSimilarityAxis,
  });

  const queryDerivedPoints = useMemo((): BgcScatterPoint[] | undefined => {
    if (!useSimilarityAxis || resultBgcData.length === 0) return undefined;
    const axisValue = (item: typeof resultBgcData[0], axis: string): number => {
      if (axis === "similarity_score") return item.similarity_score;
      if (axis === "novelty_score") return item.novelty_score;
      if (axis === "domain_novelty") return item.domain_novelty;
      return 0;
    };
    return resultBgcData.map((item) => ({
      id: item.id,
      x: axisValue(item, xAxis),
      y: axisValue(item, yAxis),
      bgc_class: item.classification_path?.split('.')[0] || 'Other',
      is_validated: false,
      compound_name: null,
      novelty_score: item.novelty_score,
      domain_novelty: item.domain_novelty,
      similarity_score: item.similarity_score,
    }));
  }, [useSimilarityAxis, resultBgcData, xAxis, yAxis]);

  const points = useSimilarityAxis ? queryDerivedPoints : apiPoints;
  const isLoading = useSimilarityAxis ? false : apiLoading;

  const traces = useMemo(() => {
    if (!points?.length) return [];

    const validatedPts = points.filter((p) => p.is_validated);
    const bgcPts = points.filter((p) => !p.is_validated);

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

    // Validated reference trace
    if (validatedPts.length > 0 && showValidated) {
      result.push({
        type: "scatter" as const,
        mode: "markers" as const,
        name: "Validated references",
        x: validatedPts.map((p) => p.x),
        y: validatedPts.map((p) => p.y),
        customdata: validatedPts.map((p) => p.id),
        text: validatedPts.map((p) => p.compound_name ?? p.bgc_class),
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
        x: pts.map((p) => p.x),
        y: pts.map((p) => p.y),
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
          x: [hp.x],
          y: [hp.y],
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
  }, [points, activeBgcId, showValidated, highlightBgcId]);

  const handleClick = useCallback(
    (event: Plotly.PlotMouseEvent) => {
      const point = event.points[0];
      if (point?.customdata) {
        setActiveBgcId(point.customdata as number);
      }
    },
    [setActiveBgcId]
  );

  const xLabel = axisOptions.find((o) => o.value === xAxis)?.label ?? xAxis;
  const yLabel = axisOptions.find((o) => o.value === yAxis)?.label ?? yAxis;

  if (!hasData) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        {mode === "query"
          ? "Run a query to see results"
          : "Select or shortlist assemblies to view their BGC chemical space"}
      </p>
    );
  }

  if (isLoading) {
    return <Skeleton className="h-64 w-full" />;
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground">X:</span>
        <Select value={xAxis} onValueChange={setXAxis}>
          <SelectTrigger className="h-7 w-28 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {axisOptions.map((o) => (
              <SelectItem key={o.value} value={o.value} className="text-xs">
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground">Y:</span>
        <Select value={yAxis} onValueChange={setYAxis}>
          <SelectTrigger className="h-7 w-28 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {axisOptions.map((o) => (
              <SelectItem key={o.value} value={o.value} className="text-xs">
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Checkbox
          id="show-validated"
          checked={showValidated}
          onCheckedChange={(v) => setShowValidated(v === true)}
        />
        <Label htmlFor="show-validated" className="text-xs cursor-pointer">
          Show validated references
        </Label>
      </div>
      <Plot
        data={traces}
        layout={{
          autosize: true,
          height: 300,
          margin: { l: 40, r: 10, t: 10, b: 40 },
          xaxis: { title: { text: xLabel, font: { size: 11 } } },
          yaxis: { title: { text: yLabel, font: { size: 11 } } },
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
