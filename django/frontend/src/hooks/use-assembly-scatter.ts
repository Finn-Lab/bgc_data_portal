import { useQuery } from "@tanstack/react-query";
import { fetchGenomeScatter, type GenomeScatterParams } from "@/api/genomes";
import { useFilterStore } from "@/stores/filter-store";
import { useGenomeWeightStore } from "@/stores/genome-weight-store";

export function useGenomeScatter(xAxis: string, yAxis: string) {
  const filters = useFilterStore();
  const weights = useGenomeWeightStore();

  const params: GenomeScatterParams = {
    x_axis: xAxis,
    y_axis: yAxis,
    type_strain_only: filters.typeStrainOnly || undefined,
    taxonomy_family: filters.taxonomyFamily || undefined,
    bgc_class: filters.bgcClass || undefined,
    w_diversity: weights.w_diversity,
    w_novelty: weights.w_novelty,
    w_density: weights.w_density,
  };

  return useQuery({
    queryKey: ["genome-scatter", params],
    queryFn: () => fetchGenomeScatter(params),
  });
}
