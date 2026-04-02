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
  const setResultBgcIds = useQueryStore((s) => s.setResultBgcIds);
  const setResultBgcData = useQueryStore((s) => s.setResultBgcData);
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
          type_strain_only: filters.typeStrainOnly || undefined,
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
    runQuery: () => setDomainQueryTriggered(true),
    hasConditions,
  };
}
