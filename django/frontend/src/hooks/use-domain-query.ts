import { useQuery } from "@tanstack/react-query";
import { postDomainQuery } from "@/api/queries";
import { useQueryStore } from "@/stores/query-store";
import { useFilterStore } from "@/stores/filter-store";
import { useState, useEffect } from "react";

export function useDomainQuery() {
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState("novelty_score");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const conditions = useQueryStore((s) => s.domainConditions);
  const logic = useQueryStore((s) => s.logic);
  const setDomainResultData = useQueryStore((s) => s.setDomainResultData);
  const computeIntersection = useQueryStore((s) => s.computeIntersection);
  const domainQueryTriggered = useQueryStore((s) => s.domainQueryTriggered);
  const setDomainQueryTriggered = useQueryStore((s) => s.setDomainQueryTriggered);
  const filters = useFilterStore();

  const hasConditions = conditions.length > 0;

  const query = useQuery({
    queryKey: ["domain-query", conditions, logic, filters, sortBy, order, page],
    queryFn: () =>
      postDomainQuery(
        { domains: conditions, logic },
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
    enabled: domainQueryTriggered,
  });

  // Store results and compute intersection
  useEffect(() => {
    if (query.data) {
      setDomainResultData(query.data.items);
      computeIntersection();
    }
  }, [query.data, setDomainResultData, computeIntersection]);

  return {
    ...query,
    page,
    setPage,
    sortBy,
    setSortBy,
    order,
    setOrder,
    runQuery: () => setDomainQueryTriggered(true),
    hasConditions,
  };
}
