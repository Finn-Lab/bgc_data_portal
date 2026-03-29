import { apiGet } from "./client";
import type { BgcDetail, BgcRegionData, BgcScatterPoint, PaginatedBgcRosterResponse } from "./types";

export function fetchBgcDetail(bgcId: number) {
  return apiGet<BgcDetail>(`/bgcs/${bgcId}/`);
}

export function fetchBgcRegion(bgcId: number) {
  return apiGet<BgcRegionData>(`/bgcs/${bgcId}/region/`);
}

export interface BgcScatterParams {
  include_mibig?: boolean;
  bgc_class?: string;
  assembly_ids?: string;
  max_points?: number;
}

export function fetchBgcScatter(params: BgcScatterParams = {}) {
  return apiGet<BgcScatterPoint[]>("/bgc-scatter/", params as Record<string, string | number | boolean | undefined>);
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
