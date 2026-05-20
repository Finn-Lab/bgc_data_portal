/**
 * Deprecated — the embedding-based similar-BGC endpoint was retired in the
 * v2 redesign. The new "Find similar iBGCs" action lives in
 * `src/hooks/use-similar-ibgc-query.ts` and uses composite-Dice similarity
 * over IntegratedBGC ids.
 *
 * This shim returns an empty result so legacy components (`QueryActions`,
 * `QueryResultsRoster`) keep building until P2.2 replaces them.
 */

import { useState } from "react";
import { useQueryStore } from "@/stores/query-store";

export function useSimilarBgcQuery() {
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState("similarity_score");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const sourceId = useQueryStore((s) => s.similarBgcSourceId);

  return {
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
    isFetching: false,
    isPending: false,
    isSuccess: false,
    refetch: async () => ({}),
    page,
    setPage,
    sortBy,
    setSortBy,
    order,
    setOrder,
    sourceId,
  };
}
