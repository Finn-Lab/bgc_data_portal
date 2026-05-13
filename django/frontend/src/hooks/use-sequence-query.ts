import { useQuery } from "@tanstack/react-query";
import {
  postSequenceQuery,
  getSequenceQueryStatus,
} from "@/api/queries";
import { useQueryStore } from "@/stores/query-store";
import { useFilterStore } from "@/stores/filter-store";
import { useState, useEffect } from "react";

export function useSequenceQuery() {
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState("similarity_score");
  const [order, setOrder] = useState<"asc" | "desc">("desc");

  const sequenceQuery = useQueryStore((s) => s.sequenceQuery);
  const minBitscore = useQueryStore((s) => s.sequenceMinBitscore);
  const minPident = useQueryStore((s) => s.sequenceMinPident);
  const minQcov = useQueryStore((s) => s.sequenceMinQcov);
  const sequenceTaskId = useQueryStore((s) => s.sequenceTaskId);
  const setSequenceTaskId = useQueryStore((s) => s.setSequenceTaskId);
  const sequenceQueryTriggered = useQueryStore((s) => s.sequenceQueryTriggered);
  const setSequenceQueryTriggered = useQueryStore(
    (s) => s.setSequenceQueryTriggered
  );
  const setSequenceResultData = useQueryStore((s) => s.setSequenceResultData);
  const computeIntersection = useQueryStore((s) => s.computeIntersection);
  const filters = useFilterStore();

  const hasQuery =
    sequenceQuery.trim().length > 0 && sequenceQuery.trim().length <= 5000;

  // Phase 1: POST — fires once per trigger, disabled once task_id is stored
  const submitQuery = useQuery({
    queryKey: [
      "sequence-submit",
      sequenceQuery,
      minBitscore,
      minPident,
      minQcov,
    ],
    queryFn: () =>
      postSequenceQuery({
        sequence: sequenceQuery,
        min_bitscore: minBitscore,
        min_pident: minPident,
        min_qcov: minQcov,
      }),
    enabled: sequenceQueryTriggered && hasQuery && !sequenceTaskId,
    retry: false,
  });

  useEffect(() => {
    if (submitQuery.data?.task_id) {
      setSequenceTaskId(submitQuery.data.task_id);
    }
  }, [submitQuery.data, setSequenceTaskId]);

  // Phase 2: poll status until SUCCESS or FAILURE
  const statusQuery = useQuery({
    queryKey: [
      "sequence-status",
      sequenceTaskId,
      page,
      sortBy,
      order,
      filters,
    ],
    queryFn: () =>
      getSequenceQueryStatus(sequenceTaskId!, {
        page,
        page_size: 50,
        sort_by: sortBy,
        order,
        search: filters.search || undefined,
        source_names: filters.sourceNames.length
          ? filters.sourceNames.join(",")
          : undefined,
        detector_tools: filters.detectorTools.length
          ? filters.detectorTools.join(",")
          : undefined,
        taxonomy_path: filters.taxonomyPath || undefined,
        bgc_class: filters.bgcClass || undefined,
        biome_lineage: filters.biomeLineage || undefined,
        assembly_accession: filters.assemblyAccession || undefined,
        bgc_accession: filters.bgcAccession || undefined,
      }),
    enabled: !!sequenceTaskId,
    refetchInterval: (query) =>
      query.state.data?.status === "PENDING" ? 2000 : false,
    retry: false,
  });

  useEffect(() => {
    if (statusQuery.data?.status === "SUCCESS") {
      setSequenceResultData(statusQuery.data.items ?? []);
      computeIntersection();
    }
  }, [statusQuery.data, setSequenceResultData, computeIntersection]);

  const isFetching =
    (sequenceQueryTriggered && submitQuery.isFetching) ||
    statusQuery.data?.status === "PENDING";

  const isError =
    submitQuery.isError || statusQuery.data?.status === "FAILURE";

  const data =
    statusQuery.data?.status === "SUCCESS" ? statusQuery.data : undefined;

  return {
    data,
    isFetching,
    isLoading: isFetching,
    isError,
    page,
    setPage,
    sortBy,
    setSortBy,
    order,
    setOrder,
    hasQuery,
    runQuery: () => {
      setSequenceTaskId(null);
      setSequenceQueryTriggered(true);
    },
  };
}
