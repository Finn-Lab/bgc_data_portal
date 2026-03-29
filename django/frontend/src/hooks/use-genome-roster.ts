import { useQuery } from "@tanstack/react-query";
import { fetchGenomeRoster, type GenomeRosterParams } from "@/api/genomes";
import { useFilterStore } from "@/stores/filter-store";
import { useGenomeWeightStore } from "@/stores/genome-weight-store";
import { useState } from "react";

export function useGenomeRoster() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [sortBy, setSortBy] = useState("composite_score");
  const [order, setOrder] = useState<"asc" | "desc">("desc");

  const filters = useFilterStore();
  const weights = useGenomeWeightStore();

  const params: GenomeRosterParams = {
    page,
    page_size: pageSize,
    sort_by: sortBy,
    order,
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
    w_diversity: weights.w_diversity,
    w_novelty: weights.w_novelty,
    w_density: weights.w_density,
  };

  const query = useQuery({
    queryKey: ["genome-roster", params],
    queryFn: () => fetchGenomeRoster(params),
  });

  return {
    ...query,
    page,
    setPage,
    pageSize,
    setPageSize,
    sortBy,
    setSortBy,
    order,
    setOrder,
  };
}
