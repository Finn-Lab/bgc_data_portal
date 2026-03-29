import { useQuery } from "@tanstack/react-query";
import { postChemicalQuery } from "@/api/queries";
import { useQueryStore } from "@/stores/query-store";
import { useQueryWeightStore } from "@/stores/query-weight-store";
import { useFilterStore } from "@/stores/filter-store";
import { useState, useEffect } from "react";

export function useChemicalQuery() {
  const [page, setPage] = useState(1);
  const [enabled, setEnabled] = useState(false);
  const smilesQuery = useQueryStore((s) => s.smilesQuery);
  const similarityThreshold = useQueryStore((s) => s.similarityThreshold);
  const setResultBgcIds = useQueryStore((s) => s.setResultBgcIds);
  const weights = useQueryWeightStore();
  const filters = useFilterStore();

  const hasQuery = smilesQuery.trim().length > 0;

  const query = useQuery({
    queryKey: [
      "chemical-query",
      smilesQuery,
      similarityThreshold,
      weights,
      filters,
      page,
    ],
    queryFn: () =>
      postChemicalQuery(
        { smiles: smilesQuery, similarity_threshold: similarityThreshold },
        {
          page,
          page_size: 50,
          w_similarity: weights.w_similarity,
          w_novelty: weights.w_novelty,
          w_completeness: weights.w_completeness,
          w_domain_novelty: weights.w_domain_novelty,
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
          assembly_accession: filters.assemblyAccession || undefined,
          bgc_accession: filters.bgcAccession || undefined,
        }
      ),
    enabled: enabled && hasQuery,
  });

  // Store result IDs for genome aggregation
  useEffect(() => {
    if (query.data) {
      setResultBgcIds(query.data.items.map((r) => r.id));
    }
  }, [query.data, setResultBgcIds]);

  return {
    ...query,
    page,
    setPage,
    runQuery: () => setEnabled(true),
    hasQuery,
  };
}
