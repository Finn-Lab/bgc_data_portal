import { apiGet } from "./client";
import type {
  BgcRosterItem,
  AssemblyDetail,
  AssemblyScatterPoint,
  AssemblyStatsResponse,
  PaginatedAssemblyResponse,
} from "./types";

export interface AssemblyRosterParams {
  page?: number;
  page_size?: number;
  sort_by?: string;
  order?: "asc" | "desc";
  search?: string;
  source_names?: string;
  detector_tools?: string;
  taxonomy_path?: string;
  bgc_class?: string;
  biome_lineage?: string;
  bgc_accession?: string;
  assembly_accession?: string;
  assembly_ids?: string;
  assembly_type?: string;
}

export function fetchAssemblyRoster(params: AssemblyRosterParams = {}) {
  return apiGet<PaginatedAssemblyResponse>("/assemblies/", params as Record<string, string | number | boolean | undefined>);
}

export function fetchAssemblyDetail(assemblyId: number) {
  return apiGet<AssemblyDetail>(`/assemblies/${assemblyId}/`);
}

export function fetchAssemblyBgcs(assemblyId: number) {
  return apiGet<BgcRosterItem[]>(`/assemblies/${assemblyId}/bgcs/`);
}

export interface AssemblyScatterParams {
  x_axis?: string;
  y_axis?: string;
  source_names?: string;
  detector_tools?: string;
  taxonomy_path?: string;
  bgc_class?: string;
  assembly_ids?: string;
  assembly_type?: string;
}

export function fetchAssemblyScatter(params: AssemblyScatterParams = {}) {
  return apiGet<AssemblyScatterPoint[]>("/assembly-scatter/", params as Record<string, string | number | boolean | undefined>);
}

export interface AssemblyStatsParams {
  search?: string;
  source_names?: string;
  detector_tools?: string;
  taxonomy_path?: string;
  assembly_type?: string;
  bgc_class?: string;
  biome_lineage?: string;
  bgc_accession?: string;
  assembly_accession?: string;
  assembly_ids?: string;
}

export function fetchAssemblyStats(params: AssemblyStatsParams = {}) {
  return apiGet<AssemblyStatsResponse>("/stats/assemblies/", params as Record<string, string | number | boolean | undefined>);
}
