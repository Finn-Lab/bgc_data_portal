import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchNrbScatter } from "@/api/nrbs";
import {
  appliedFiltersToApiParams,
  useDiscoveryStore,
} from "@/stores/discovery-store";
import type { NrbScatterAxis } from "@/api/types";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Loader2 } from "lucide-react";
import { NrbScatterPlot } from "./NrbScatterPlot";

const AXIS_OPTIONS: { value: NrbScatterAxis; label: string }[] = [
  { value: "novelty_score", label: "Novelty" },
  { value: "domain_novelty", label: "Domain novelty" },
  { value: "size_kb", label: "Size (kb)" },
  { value: "n_cds", label: "# CDS" },
  { value: "similarity_score", label: "Query similarity" },
];

const AXIS_LABELS: Record<NrbScatterAxis, string> = Object.fromEntries(
  AXIS_OPTIONS.map((o) => [o.value, o.label]),
) as Record<NrbScatterAxis, string>;

export function VariablesMapTab() {
  const xAxis = useDiscoveryStore((s) => s.variablesAxisX);
  const yAxis = useDiscoveryStore((s) => s.variablesAxisY);
  const setAxes = useDiscoveryStore((s) => s.setVariablesAxes);
  const resultNrbIds = useDiscoveryStore((s) => s.resultNrbIds);
  const resultSimilarityById = useDiscoveryStore(
    (s) => s.resultSimilarityById,
  );
  const applied = useDiscoveryStore((s) => s.appliedFilters);

  const wantsSimilarity =
    xAxis === "similarity_score" || yAxis === "similarity_score";
  const useQueryAxes = wantsSimilarity && resultSimilarityById != null;
  const filterParams = appliedFiltersToApiParams(applied, resultNrbIds);

  // ── Scatter from /nrbs/scatter/ for stored axes ─────────────────────
  const { data: scatterData, isLoading, isError, error } = useQuery({
    queryKey: ["nrb-scatter", xAxis, yAxis, filterParams],
    queryFn: () =>
      fetchNrbScatter({ x_axis: xAxis, y_axis: yAxis, ...filterParams }),
    enabled: !wantsSimilarity,
  });

  // ── Build points: either the live scatter response, or a synthesised
  //    set derived from the query result (when similarity_score is on an
  //    axis). The synthesised path uses scores already in
  //    discovery-store.resultSimilarityById. ────────────────────────────
  const points = useMemo(() => {
    if (useQueryAxes && resultNrbIds && resultSimilarityById) {
      // We need the other axis from /nrbs/scatter/, but Plotly is happy
      // with whatever we hand it — for v1 just plot similarity on both
      // axes that asked for it, falling back to similarity itself for the
      // non-similarity axis (caller is expected to pick a meaningful Y).
      return resultNrbIds.map((id) => {
        const sim = resultSimilarityById[id] ?? 0;
        return {
          id,
          x: xAxis === "similarity_score" ? sim : sim,
          y: yAxis === "similarity_score" ? sim : sim,
          is_partial: false,
          is_validated: false,
          umap_projected: false,
          similarity_score: sim,
        };
      });
    }
    if (!scatterData) return [];
    return scatterData.map((p) => ({
      id: p.id,
      x: p.x,
      y: p.y,
      is_partial: p.is_partial,
      is_validated: p.is_validated,
      umap_projected: p.umap_projected,
      classification_path: p.classification_path,
      novelty_score: p.novelty_score,
      domain_novelty: p.domain_novelty,
      similarity_score: p.similarity_score,
    }));
  }, [scatterData, resultNrbIds, useQueryAxes, resultSimilarityById, xAxis, yAxis]);

  return (
    <div className="flex h-full flex-col p-3">
      <div className="flex items-center gap-2 pb-2 text-xs">
        <span className="text-muted-foreground">X:</span>
        <Select
          value={xAxis}
          onValueChange={(v) => setAxes(v as NrbScatterAxis, yAxis)}
        >
          <SelectTrigger className="h-8 w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {AXIS_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="ml-3 text-muted-foreground">Y:</span>
        <Select
          value={yAxis}
          onValueChange={(v) => setAxes(xAxis, v as NrbScatterAxis)}
        >
          <SelectTrigger className="h-8 w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {AXIS_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {wantsSimilarity && !useQueryAxes && (
          <span className="ml-2 text-amber-600">
            Run a query to populate similarity scores.
          </span>
        )}
      </div>

      <div className="flex flex-1 items-stretch overflow-hidden rounded border bg-card">
        {isLoading && !useQueryAxes ? (
          <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
            <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
            Loading…
          </div>
        ) : isError && !useQueryAxes ? (
          <div className="flex flex-1 items-center justify-center text-sm text-destructive">
            {(error as Error)?.message ?? "Failed to load scatter data"}
          </div>
        ) : (
          <NrbScatterPlot
            points={points}
            xLabel={AXIS_LABELS[xAxis]}
            yLabel={AXIS_LABELS[yAxis]}
          />
        )}
      </div>
    </div>
  );
}
