import { useQuery } from "@tanstack/react-query";
import { fetchAssemblyScatter, type AssemblyScatterParams } from "@/api/assemblies";
import { useFilterStore } from "@/stores/filter-store";

export function useAssemblyScatter(xAxis: string, yAxis: string) {
  const filters = useFilterStore();

  const params: AssemblyScatterParams = {
    x_axis: xAxis,
    y_axis: yAxis,
    source_names: filters.sourceNames.length ? filters.sourceNames.join(",") : undefined,
    detector_tools: filters.detectorTools.length ? filters.detectorTools.join(",") : undefined,
    taxonomy_path: filters.taxonomyPath || undefined,
    assembly_type: filters.assemblyType || undefined,
    bgc_class: filters.bgcClass || undefined,
  };

  return useQuery({
    queryKey: ["assembly-scatter", params],
    queryFn: () => fetchAssemblyScatter(params),
    enabled: filters.exploreQueryTriggered,
  });
}
