import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { postSimilarNrbQuery } from "@/api/nrbs";

/**
 * Top-K NRBs by composite-Dice similarity to a seed NRB id. Replaces the
 * retired embedding-based `useSimilarBgcQuery`. The seed must be a primary
 * NRB in the latest ClusteringRun (the backend rejects partials in v1).
 */
export function useSimilarNrbQuery(seedNrbId: number | null, k = 25) {
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);

  const query = useQuery({
    queryKey: ["similar-nrb", seedNrbId, k, page, pageSize],
    queryFn: () =>
      postSimilarNrbQuery(
        { nrb_id: seedNrbId as number, k },
        page,
        pageSize,
      ),
    enabled: seedNrbId !== null,
  });

  return { ...query, page, setPage, pageSize };
}
