import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { postSimilarIbgcQuery } from "@/api/ibgcs";

/**
 * Top-K iBGCs by composite-Dice similarity to a seed iBGC id. Replaces the
 * retired embedding-based `useSimilarBgcQuery`. The seed must be a primary
 * iBGC in the latest ClusteringRun (the backend rejects partials in v1).
 */
export function useSimilarIbgcQuery(seedIbgcId: number | null, k = 25) {
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);

  const query = useQuery({
    queryKey: ["similar-ibgc", seedIbgcId, k, page, pageSize],
    queryFn: () =>
      postSimilarIbgcQuery(
        { ibgc_id: seedIbgcId as number, k },
        page,
        pageSize,
      ),
    enabled: seedIbgcId !== null,
  });

  return { ...query, page, setPage, pageSize };
}
