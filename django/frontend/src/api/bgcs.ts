import { apiGet } from "./client";
import type { BgcDetail, BgcRegionData, BgcScatterPoint, BgcStatsResponse, PaginatedBgcRosterResponse } from "./types";

export function fetchBgcDetail(bgcId: number) {
  return apiGet<BgcDetail>(`/bgcs/${bgcId}/`);
}

export function fetchBgcRegion(bgcId: number) {
  return apiGet<BgcRegionData>(`/bgcs/${bgcId}/region/`);
}

export interface BgcScatterParams {
  include_validated?: boolean;
  bgc_class?: string;
  assembly_ids?: string;
  bgc_ids?: string;
  max_points?: number;
  xAxis?: string;
  yAxis?: string;
}

export function fetchBgcScatter(params: BgcScatterParams = {}) {
  const { xAxis, yAxis, ...rest } = params;
  const queryParams: Record<string, string | number | boolean | undefined> = {
    ...rest,
    ...(xAxis !== undefined && { x_axis: xAxis }),
    ...(yAxis !== undefined && { y_axis: yAxis }),
  };
  return apiGet<BgcScatterPoint[]>("/bgc-scatter/", queryParams);
}

export interface BgcRosterParams {
  assembly_ids?: string;
  sort_by?: string;
  order?: "asc" | "desc";
  page?: number;
  page_size?: number;
}

export function fetchBgcRoster(params: BgcRosterParams = {}) {
  return apiGet<PaginatedBgcRosterResponse>("/bgcs/roster/", params as Record<string, string | number | boolean | undefined>);
}

export function fetchParentAssemblies(bgcIds: number[]) {
  return apiGet<number[]>("/bgcs/parent-assemblies/", { bgc_ids: bgcIds.join(",") });
}

export interface BgcStatsParams {
  assembly_ids?: string;
  bgc_ids?: string;
}

export function fetchBgcStats(params: BgcStatsParams = {}) {
  return apiGet<BgcStatsResponse>("/stats/bgcs/", params as Record<string, string | number | boolean | undefined>);
}
