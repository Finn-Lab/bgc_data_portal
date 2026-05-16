import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchReport, postReportSnapshot } from "@/api/report";
import { ApiError } from "@/api/client";

/**
 * Fetch a Report payload by token. If the cache entry has expired (404),
 * callers can re-mint a token via ``useReportSnapshot``.
 */
export function useReport(token: string | null) {
  return useQuery({
    queryKey: ["report", token],
    queryFn: () => fetchReport(token as string),
    enabled: token !== null,
    retry: (failureCount, error) => {
      if (error instanceof ApiError && error.status === 404) return false;
      return failureCount < 2;
    },
    staleTime: 60_000,
  });
}

/**
 * Mint a fresh Report snapshot. The returned ``token`` is deterministic for
 * a given shortlist, so re-running for the same ids resolves to the same
 * cached entry server-side.
 */
export interface ReportSnapshotVariables {
  nrbIds: number[];
  assetToken?: string | null;
}

export function useReportSnapshot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ nrbIds, assetToken }: ReportSnapshotVariables) =>
      postReportSnapshot(nrbIds, assetToken),
    onSuccess: (resp) => {
      qc.invalidateQueries({ queryKey: ["report", resp.token] });
    },
  });
}
