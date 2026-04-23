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
  const setChemicalResultData = useQueryStore((s) => s.setChemicalResultData);
  const computeIntersection = useQueryStore((s) => s.computeIntersection);
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
          source_names: filters.sourceNames.length ? filters.sourceNames.join(",") : undefined,
          detector_tools: filters.detectorTools.length ? filters.detectorTools.join(",") : undefined,
          taxonomy_path: filters.taxonomyPath || undefined,
          assembly_type: filters.assemblyType || undefined,
          bgc_class: filters.bgcClass || undefined,
          biome_lineage: filters.biomeLineage || undefined,
          assembly_accession: filters.assemblyAccession || undefined,
          bgc_accession: filters.bgcAccession || undefined,
          chemont_ids: filters.chemontIds.length > 0 ? filters.chemontIds.join(",") : undefined,
        }
      ),
    enabled: chemicalQueryTriggered && hasQuery,
  });

  // Store results and compute intersection
  useEffect(() => {
    if (query.data) {
      setChemicalResultData(query.data.items);
      computeIntersection();
    }
  }, [query.data, setChemicalResultData, computeIntersection]);

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
