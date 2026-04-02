import { useQuery } from "@tanstack/react-query";
import { fetchQueryResultGenomes } from "@/api/queries";
import { useQueryStore } from "@/stores/query-store";
import { useState } from "react";

export function useGenomeAggregation() {
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState("max_relevance");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const resultBgcIds = useQueryStore((s) => s.resultBgcIds);

  const hasResults = resultBgcIds.length > 0;

  const query = useQuery({
    queryKey: ["genome-aggregation", resultBgcIds, page, sortBy, order],
    queryFn: () =>
      fetchQueryResultGenomes({
        bgc_ids: resultBgcIds.join(","),
        page,
        page_size: 25,
        sort_by: sortBy,
        order,
      }),
    enabled: hasResults,
  });

  return { ...query, page, setPage, sortBy, setSortBy, order, setOrder, hasResults };
}
