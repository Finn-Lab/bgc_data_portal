import { useQuery } from "@tanstack/react-query";
import { fetchGenomeScatter, type GenomeScatterParams } from "@/api/genomes";
import { useGenomeWeightStore } from "@/stores/genome-weight-store";

export function useQueryGenomeScatter(
  xAxis: string,
  yAxis: string,
  assemblyIds: number[]
) {
  const weights = useGenomeWeightStore();

  const params: GenomeScatterParams = {
    x_axis: xAxis,
    y_axis: yAxis,
    assembly_ids: assemblyIds.length > 0 ? assemblyIds.join(",") : undefined,
    w_diversity: weights.w_diversity,
    w_novelty: weights.w_novelty,
    w_density: weights.w_density,
  };

  return useQuery({
    queryKey: ["query-genome-scatter", params],
    queryFn: () => fetchGenomeScatter(params),
    enabled: assemblyIds.length > 0,
  });
}
