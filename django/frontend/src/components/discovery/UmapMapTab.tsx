import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchNrbUmap } from "@/api/nrbs";
import { Loader2 } from "lucide-react";
import {
  appliedFiltersToApiParams,
  useDiscoveryStore,
} from "@/stores/discovery-store";
import { NrbScatterPlot } from "./NrbScatterPlot";

export function UmapMapTab() {
  const resultNrbIds = useDiscoveryStore((s) => s.resultNrbIds);
  const resultSimilarityById = useDiscoveryStore(
    (s) => s.resultSimilarityById,
  );
  const applied = useDiscoveryStore((s) => s.appliedFilters);

  const filterParams = appliedFiltersToApiParams(applied, resultNrbIds);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["nrb-umap", filterParams],
    queryFn: () =>
      fetchNrbUmap({ include_partials: true, ...filterParams }),
  });

  const points = useMemo(() => {
    if (!data) return [];
    return data.map((p) => ({
      id: p.id,
      x: p.umap_x,
      y: p.umap_y,
      is_partial: p.is_partial,
      is_validated: p.is_validated,
      is_type_strain: p.is_type_strain,
      umap_projected: p.umap_projected,
      classification_path: p.classification_path,
      novelty_score: p.novelty_score,
      label: p.label,
      similarity_score: resultSimilarityById?.[p.id] ?? null,
    }));
  }, [data, resultSimilarityById]);

  return (
    <div className="flex h-full flex-col p-3">
      <div className="flex flex-1 items-stretch overflow-hidden rounded border bg-card">
        {isLoading ? (
          <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
            <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
            Loading UMAP…
          </div>
        ) : isError ? (
          <div className="flex flex-1 items-center justify-center text-sm text-destructive">
            {(error as Error)?.message ?? "Failed to load UMAP"}
          </div>
        ) : (
          <NrbScatterPlot
            points={points}
            xLabel="UMAP 1"
            yLabel="UMAP 2"
          />
        )}
      </div>
    </div>
  );
}
