import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchIbgcDetail, fetchIbgcScatter } from "@/api/ibgcs";
import {
  appliedFiltersToApiParams,
  isAppliedFiltersEmpty,
  useDiscoveryStore,
} from "@/stores/discovery-store";
import type { IbgcDetail, IbgcScatterAxis, IbgcScatterPoint } from "@/api/types";
import { EmptyScopeMessage } from "./EmptyScopeMessage";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Loader2 } from "lucide-react";
import { IbgcScatterPlot } from "./IbgcScatterPlot";

const STABLE_AXES: { value: IbgcScatterAxis; label: string }[] = [
  { value: "novelty_score", label: "Novelty" },
  { value: "domain_novelty", label: "Domain novelty" },
  { value: "size_kb", label: "Size (kb)" },
  { value: "n_cds", label: "# CDS" },
];

/** Axes whose values come from the active-query store maps rather than
 *  the ``/ibgcs/scatter/`` endpoint. The display label of
 *  ``similarity_score`` depends on which advanced-query path produced the
 *  result set — Dice for domain searches, bitscore for sequence searches. */
const QUERY_AXES = new Set<IbgcScatterAxis>([
  "similarity_score",
  "best_pident",
  "best_qcoverage",
]);

function axisOptionsFor(
  searchSource: string | null,
): { value: IbgcScatterAxis; label: string }[] {
  const opts = [...STABLE_AXES];
  // The similarity axis is always available — what it *means* depends on
  // the active search source.
  opts.push({
    value: "similarity_score",
    label:
      searchSource === "sequence"
        ? "Bitscore"
        : searchSource === "domain"
          ? "Domain match (Dice)"
          : "Query similarity",
  });
  if (searchSource === "sequence") {
    opts.push({ value: "best_pident", label: "Identity %" });
    opts.push({ value: "best_qcoverage", label: "Query coverage %" });
  }
  return opts;
}

export function VariablesMapTab() {
  const xAxis = useDiscoveryStore((s) => s.variablesAxisX);
  const yAxis = useDiscoveryStore((s) => s.variablesAxisY);
  const setAxes = useDiscoveryStore((s) => s.setVariablesAxes);
  const resultIbgcIds = useDiscoveryStore((s) => s.resultIbgcIds);
  const resultSimilarityById = useDiscoveryStore(
    (s) => s.resultSimilarityById,
  );
  const resultPidentById = useDiscoveryStore((s) => s.resultPidentById);
  const resultQcoverageById = useDiscoveryStore(
    (s) => s.resultQcoverageById,
  );
  const searchSource = useDiscoveryStore((s) => s.searchSource);
  const applied = useDiscoveryStore((s) => s.appliedFilters);
  const referenceIbgcId = useDiscoveryStore((s) => s.referenceIbgcId);

  const axisOptions = axisOptionsFor(searchSource);
  const axisLabel = (axis: IbgcScatterAxis): string =>
    axisOptions.find((o) => o.value === axis)?.label ?? axis;

  const xIsQuery = QUERY_AXES.has(xAxis);
  const yIsQuery = QUERY_AXES.has(yAxis);
  const anyStableAxis = !xIsQuery || !yIsQuery;
  const anyQueryAxis = xIsQuery || yIsQuery;
  // Need a query result for any query axis to plot.
  const queryAxesUnplottable = anyQueryAxis && resultSimilarityById == null;

  const assetToken = useDiscoveryStore((s) => s.assetToken);
  const filterParams = appliedFiltersToApiParams(
    applied,
    resultIbgcIds,
    assetToken,
  );
  const hasActiveScope =
    !isAppliedFiltersEmpty(applied) ||
    resultIbgcIds !== null ||
    assetToken !== null;

  // When at least one axis is stable, fetch ``/ibgcs/scatter/`` for it. If
  // only one axis is stable, request it on both x and y so we get the
  // value back regardless of which slot it ends up in.
  const scatterX: IbgcScatterAxis = xIsQuery
    ? yIsQuery
      ? "novelty_score"
      : yAxis
    : xAxis;
  const scatterY: IbgcScatterAxis = yIsQuery
    ? xIsQuery
      ? "novelty_score"
      : xAxis
    : yAxis;

  const { data: scatterData, isLoading, isError, error } = useQuery({
    queryKey: ["ibgc-scatter", scatterX, scatterY, filterParams],
    queryFn: () =>
      fetchIbgcScatter({
        x_axis: scatterX,
        y_axis: scatterY,
        ...filterParams,
      }),
    enabled: anyStableAxis && hasActiveScope,
  });

  // ── Reference iBGC detail ────────────────────────────────────────────
  // The scatter endpoint drops iBGCs with NULL axis values (e.g.
  // domain_novelty is NULL for singleton GCFs) and also honours the
  // `ibgc_ids` allow-list from the active query. Either of those can hide
  // the pinned reference. We refetch its detail and inject it manually so
  // the reference halo is always rendered.
  const { data: refDetail } = useQuery({
    queryKey: [
      "ibgc-detail",
      referenceIbgcId,
      referenceIbgcId !== null && referenceIbgcId < 0 ? assetToken : null,
    ],
    queryFn: () => fetchIbgcDetail(referenceIbgcId as number, assetToken),
    enabled: referenceIbgcId !== null && hasActiveScope,
  });

  const points = useMemo(() => {
    if (queryAxesUnplottable) return [];

    // Index scatter points by id and remember which slot held what so the
    // resolver below can pluck the right scalar back out.
    const stableById = new Map<number, IbgcScatterPoint>();
    if (scatterData) {
      for (const p of scatterData) stableById.set(p.id, p);
    }

    function resolveAxis(axis: IbgcScatterAxis, id: number): number | null {
      if (axis === "similarity_score") {
        return resultSimilarityById?.[id] ?? null;
      }
      if (axis === "best_pident") {
        return resultPidentById?.[id] ?? null;
      }
      if (axis === "best_qcoverage") {
        return resultQcoverageById?.[id] ?? null;
      }
      const sp = stableById.get(id);
      if (!sp) return null;
      if (axis === scatterX) return sp.x;
      if (axis === scatterY) return sp.y;
      return null;
    }

    // Candidate ids: active-query allow-list when present, otherwise the
    // full scatter response.
    const candidateIds = resultIbgcIds ?? Array.from(stableById.keys());

    type PlotPoint = {
      id: number;
      x: number;
      y: number;
      is_partial: boolean;
      is_validated: boolean;
      is_type_strain: boolean;
      umap_projected: boolean;
      is_asset: boolean;
      classification_path?: string | null;
      novelty_score?: number | null;
      domain_novelty?: number | null;
      similarity_score?: number | null;
    };

    const base: PlotPoint[] = [];
    for (const id of candidateIds) {
      const x = resolveAxis(xAxis, id);
      const y = resolveAxis(yAxis, id);
      if (x == null || y == null) continue;
      const sp = stableById.get(id);
      base.push({
        id,
        x,
        y,
        is_partial: sp?.is_partial ?? false,
        is_validated: sp?.is_validated ?? false,
        is_type_strain: sp?.is_type_strain ?? false,
        umap_projected: sp?.umap_projected ?? false,
        is_asset: sp?.is_asset ?? id < 0,
        classification_path: sp?.classification_path,
        novelty_score: sp?.novelty_score,
        domain_novelty: sp?.domain_novelty,
        similarity_score: resultSimilarityById?.[id] ?? null,
      });
    }

    // Inject the pinned reference iBGC if it was dropped by the scatter
    // endpoint (NULL axis value or outside the query allow-list).
    if (
      referenceIbgcId != null &&
      refDetail &&
      refDetail.id === referenceIbgcId &&
      !base.some((p) => p.id === referenceIbgcId)
    ) {
      const x = axisValueFromDetail(
        refDetail,
        xAxis,
        resultSimilarityById,
        resultPidentById,
        resultQcoverageById,
      );
      const y = axisValueFromDetail(
        refDetail,
        yAxis,
        resultSimilarityById,
        resultPidentById,
        resultQcoverageById,
      );
      if (x != null && y != null) {
        base.push({
          id: refDetail.id,
          x,
          y,
          is_partial: refDetail.is_partial,
          is_validated: refDetail.is_validated,
          is_type_strain: refDetail.is_type_strain,
          umap_projected: refDetail.umap_projected,
          is_asset: refDetail.id < 0,
          classification_path: refDetail.classification_path,
          novelty_score: refDetail.novelty_score,
          domain_novelty: refDetail.domain_novelty,
          similarity_score: resultSimilarityById?.[refDetail.id] ?? null,
        });
      }
    }

    return base;
  }, [
    scatterData,
    resultIbgcIds,
    resultSimilarityById,
    resultPidentById,
    resultQcoverageById,
    xAxis,
    yAxis,
    scatterX,
    scatterY,
    referenceIbgcId,
    refDetail,
    queryAxesUnplottable,
  ]);

  if (!hasActiveScope) {
    return (
      <div className="flex h-full flex-col p-3">
        <div className="flex flex-1 items-stretch overflow-hidden rounded border bg-card">
          <EmptyScopeMessage surface="Variables map" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col p-3">
      <div className="flex items-center gap-2 pb-2 text-xs">
        <span className="text-muted-foreground">X:</span>
        <Select
          value={xAxis}
          onValueChange={(v) => setAxes(v as IbgcScatterAxis, yAxis)}
        >
          <SelectTrigger className="h-8 w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {axisOptions.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="ml-3 text-muted-foreground">Y:</span>
        <Select
          value={yAxis}
          onValueChange={(v) => setAxes(xAxis, v as IbgcScatterAxis)}
        >
          <SelectTrigger className="h-8 w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {axisOptions.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {queryAxesUnplottable && (
          <span className="ml-2 text-amber-600">
            Run a query to populate this axis.
          </span>
        )}
      </div>

      <div className="flex flex-1 items-stretch overflow-hidden rounded border bg-card">
        {isLoading && anyStableAxis ? (
          <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
            <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
            Loading…
          </div>
        ) : isError && anyStableAxis ? (
          <div className="flex flex-1 items-center justify-center text-sm text-destructive">
            {(error as Error)?.message ?? "Failed to load scatter data"}
          </div>
        ) : (
          <IbgcScatterPlot
            points={points}
            xLabel={axisLabel(xAxis)}
            yLabel={axisLabel(yAxis)}
          />
        )}
      </div>
    </div>
  );
}

function axisValueFromDetail(
  d: IbgcDetail,
  axis: IbgcScatterAxis,
  resultSimilarityById: Record<number, number> | null,
  resultPidentById: Record<number, number> | null,
  resultQcoverageById: Record<number, number> | null,
): number | null {
  // IbgcDetail does not carry `n_cds`; if that axis is selected and the
  // reference is missing from the scatter response there is nothing
  // meaningful to inject — skip the halo rather than guess a coordinate.
  switch (axis) {
    case "novelty_score":
      return d.novelty_score ?? null;
    case "domain_novelty":
      return d.domain_novelty ?? null;
    case "size_kb":
      return d.size_kb ?? null;
    case "similarity_score":
      return resultSimilarityById?.[d.id] ?? null;
    case "best_pident":
      return resultPidentById?.[d.id] ?? null;
    case "best_qcoverage":
      return resultQcoverageById?.[d.id] ?? null;
    case "n_cds":
      return null;
    default:
      return null;
  }
}
