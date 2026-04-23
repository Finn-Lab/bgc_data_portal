import { useQuery } from "@tanstack/react-query";
import { postSequenceQuery } from "@/api/queries";
import { useQueryStore } from "@/stores/query-store";
import { useFilterStore } from "@/stores/filter-store";
import { useState, useEffect } from "react";

export function useSequenceQuery() {
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState("similarity_score");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const sequenceQuery = useQueryStore((s) => s.sequenceQuery);
  const sequenceThreshold = useQueryStore((s) => s.sequenceThreshold);
  const setSequenceResultData = useQueryStore((s) => s.setSequenceResultData);
  const computeIntersection = useQueryStore((s) => s.computeIntersection);
  const sequenceQueryTriggered = useQueryStore(
    (s) => s.sequenceQueryTriggered
  );
  const setSequenceQueryTriggered = useQueryStore(
    (s) => s.setSequenceQueryTriggered
  );
  const filters = useFilterStore();

  const hasQuery = sequenceQuery.trim().length > 0;

  const query = useQuery({
    queryKey: [
      "sequence-query",
      sequenceQuery,
      sequenceThreshold,
      filters,
      sortBy,
      order,
      page,
    ],
    queryFn: () =>
      postSequenceQuery(
        {
          sequence: sequenceQuery,
          similarity_threshold: sequenceThreshold,
        },
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
        }
      ),
    enabled: sequenceQueryTriggered && hasQuery,
  });

  // Store results and compute intersection
  useEffect(() => {
    if (query.data) {
      setSequenceResultData(query.data.items);
      computeIntersection();
    }
  }, [query.data, setSequenceResultData, computeIntersection]);

  return {
    ...query,
    page,
    setPage,
    sortBy,
    setSortBy,
    order,
    setOrder,
    runQuery: () => setSequenceQueryTriggered(true),
    hasQuery,
  };
}
