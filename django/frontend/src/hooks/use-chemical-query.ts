import { useQuery } from "@tanstack/react-query";
import { postChemicalQuery } from "@/api/queries";
import { useQueryStore } from "@/stores/query-store";
import { useFilterStore } from "@/stores/filter-store";
import { useState, useEffect } from "react";

export function useChemicalQuery() {
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState("similarity_score");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const smilesQuery = useQueryStore((s) => s.smilesQuery);
  const similarityThreshold = useQueryStore((s) => s.similarityThreshold);
  const setResultBgcIds = useQueryStore((s) => s.setResultBgcIds);
  const setResultBgcData = useQueryStore((s) => s.setResultBgcData);
  const chemicalQueryTriggered = useQueryStore((s) => s.chemicalQueryTriggered);
  const setChemicalQueryTriggered = useQueryStore((s) => s.setChemicalQueryTriggered);
  const filters = useFilterStore();

  const hasQuery = smilesQuery.trim().length > 0;

  const query = useQuery({
    queryKey: [
      "chemical-query",
      smilesQuery,
      similarityThreshold,
      filters,
      sortBy,
      order,
      page,
    ],
    queryFn: () =>
      postChemicalQuery(
        { smiles: smilesQuery, similarity_threshold: similarityThreshold },
        {
          page,
          page_size: 50,
          sort_by: sortBy,
          order,
          search: filters.search || undefined,
          type_strain_only: filters.typeStrainOnly || undefined,
          taxonomy_path: filters.taxonomyPath || undefined,
          assembly_type: filters.assemblyType || undefined,
          bgc_class: filters.bgcClass || undefined,
          biome_lineage: filters.biomeLineage || undefined,
          assembly_accession: filters.assemblyAccession || undefined,
          bgc_accession: filters.bgcAccession || undefined,
        }
      ),
    enabled: chemicalQueryTriggered && hasQuery,
  });

  // Store result IDs and data for scatter/assembly aggregation
  useEffect(() => {
    if (query.data) {
      setResultBgcIds(query.data.items.map((r) => r.id));
      setResultBgcData(query.data.items);
    }
  }, [query.data, setResultBgcIds, setResultBgcData]);

  return {
    ...query,
    page,
    setPage,
    sortBy,
    setSortBy,
    order,
    setOrder,
    runQuery: () => setChemicalQueryTriggered(true),
    hasQuery,
  };
}
