import { useQuery } from "@tanstack/react-query";
import { fetchGenomeStats, type GenomeStatsParams } from "@/api/genomes";
import { useFilterStore } from "@/stores/filter-store";

export function useGenomeStats(assemblyIds?: string) {
  const filters = useFilterStore();

  const params: GenomeStatsParams = {
    search: filters.search || undefined,
    type_strain_only: filters.typeStrainOnly || undefined,
    taxonomy_kingdom: filters.taxonomyKingdom || undefined,
    taxonomy_phylum: filters.taxonomyPhylum || undefined,
    taxonomy_class: filters.taxonomyClass || undefined,
    taxonomy_order: filters.taxonomyOrder || undefined,
    taxonomy_family: filters.taxonomyFamily || undefined,
    taxonomy_genus: filters.taxonomyGenus || undefined,
    bgc_class: filters.bgcClass || undefined,
    biome_lineage: filters.biomeLineage || undefined,
    bgc_accession: filters.bgcAccession || undefined,
    assembly_accession: filters.assemblyAccession || undefined,
    assembly_ids: assemblyIds,
  };

  return useQuery({
    queryKey: ["genome-stats", params],
    queryFn: () => fetchGenomeStats(params),
    staleTime: 30_000,
  });
}
