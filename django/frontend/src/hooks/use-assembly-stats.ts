import { useQuery } from "@tanstack/react-query";
import { fetchAssemblyStats, type AssemblyStatsParams } from "@/api/assemblies";
import { useFilterStore } from "@/stores/filter-store";

export function useAssemblyStats(assemblyIds?: string, enabled: boolean = true) {
  const filters = useFilterStore();

  const params: AssemblyStatsParams = {
    search: filters.search || undefined,
    source_names: filters.sourceNames.length ? filters.sourceNames.join(",") : undefined,
    detector_tools: filters.detectorTools.length ? filters.detectorTools.join(",") : undefined,
    taxonomy_path: filters.taxonomyPath || undefined,
    assembly_type: filters.assemblyType || undefined,
    bgc_class: filters.bgcClass || undefined,
    biome_lineage: filters.biomeLineage || undefined,
    bgc_accession: filters.bgcAccession || undefined,
    assembly_accession: filters.assemblyAccession || undefined,
    assembly_ids: assemblyIds,
  };

  return useQuery({
    queryKey: ["assembly-stats", params],
    queryFn: () => fetchAssemblyStats(params),
    staleTime: 30_000,
    enabled,
  });
}
