import { apiGet, apiPost } from "./client";
import type { ReportPayload, ReportSnapshotResponse } from "./types";

/**
 * Materialise a shortlist Report and obtain its token. The same shortlist
 * always resolves to the same token, so re-opening the report tab is cheap.
 */
export function postReportSnapshot(
  ibgcIds: number[],
  assetToken?: string | null,
) {
  // ``asset_token`` is required by the backend whenever any negative id
  // (asset iBGC) is present; harmless when only positive ids are sent.
  const body: { ibgc_ids: number[]; asset_token?: string } = {
    ibgc_ids: ibgcIds,
  };
  if (assetToken) body.asset_token = assetToken;
  return apiPost<ReportSnapshotResponse>("/report/snapshot/", body);
}

/**
 * Fetch the cached payload for a Report token. 404 means the cache entry
 * has expired and the client should re-POST the snapshot.
 */
export function fetchReport(token: string) {
  return apiGet<ReportPayload>(`/report/${token}/`);
}
