import { useQuery } from "@tanstack/react-query";
import { postSimilarBgcQuery } from "@/api/queries";
import { useQueryStore } from "@/stores/query-store";
import { useState, useEffect } from "react";

export function useSimilarBgcQuery() {
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState("similarity_score");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const sourceId = useQueryStore((s) => s.similarBgcSourceId);
  const setResultBgcIds = useQueryStore((s) => s.setResultBgcIds);
  const setResultBgcData = useQueryStore((s) => s.setResultBgcData);

  const query = useQuery({
    queryKey: ["similar-bgc-query", sourceId, sortBy, order, page],
    queryFn: () =>
      postSimilarBgcQuery(sourceId!, {
        page,
        page_size: 50,
        sort_by: sortBy,
        order,
      }),
    enabled: sourceId !== null,
  });

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
  };
}
