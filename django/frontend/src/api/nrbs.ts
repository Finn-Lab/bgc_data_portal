import { apiGet, apiPost } from "./client";
import type {
  NrbDetail,
  NrbScatterAxis,
  NrbScatterPoint,
  NrbUmapPoint,
  PaginatedNrbRosterResponse,
} from "./types";

export interface NrbFilterParams {
  include_partials?: boolean;
  validated_only?: boolean;
  min_length_kb?: number;
  max_length_kb?: number;
  min_novelty?: number;
  max_novelty?: number;
  min_domain_novelty?: number;
  max_domain_novelty?: number;
  source_tools?: string;
  leaf_path_prefix?: string;
  bgc_class?: string;
  assembly_accession?: string;
  organism?: string;
  biome_lineage?: string;
  taxonomy_path?: string;
}

export interface NrbRosterParams extends NrbFilterParams {
  sort_by?:
    | "novelty_score"
    | "domain_novelty"
    | "size_kb"
    | "classification_path"
    | "id";
  order?: "asc" | "desc";
  page?: number;
  page_size?: number;
}

export function fetchNrbRoster(params: NrbRosterParams = {}) {
  return apiGet<PaginatedNrbRosterResponse>(
    "/nrbs/roster/",
    params as Record<string, string | number | boolean | undefined>,
  );
}

// ── NRB-collapsed query endpoints ─────────────────────────────────────────

export interface DomainCondition {
  acc: string;
  required: boolean;
}

export interface DomainQueryRequest {
  domains: DomainCondition[];
  logic: "and" | "or";
}

export interface NrbDomainQueryParams extends NrbFilterParams {
  sort_by?:
    | "novelty_score"
    | "domain_novelty"
    | "size_kb"
    | "classification_path"
    | "similarity_score"
    | "id";
  order?: "asc" | "desc";
  page?: number;
  page_size?: number;
}

export function postNrbDomainQuery(
  body: DomainQueryRequest,
  params: NrbDomainQueryParams = {},
) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const path = qs.toString()
    ? `/query/nrb-domain/?${qs.toString()}`
    : "/query/nrb-domain/";
  return apiPost<PaginatedNrbRosterResponse>(path, body);
}

export interface NrbSequenceStatusParams extends NrbDomainQueryParams {
  // same shape as the domain-query params
}

export function fetchNrbSequenceQueryStatus(
  taskId: string,
  params: NrbSequenceStatusParams = {},
) {
  return apiGet<PaginatedNrbRosterResponse>(
    `/query/nrb-sequence/status/${taskId}/`,
    params as Record<string, string | number | boolean | undefined>,
  );
}

export function fetchNrbDetail(nrbId: number) {
  return apiGet<NrbDetail>(`/nrbs/${nrbId}/`);
}

export interface NrbUmapParams {
  include_partials?: boolean;
  max_points?: number;
}

export function fetchNrbUmap(params: NrbUmapParams = {}) {
  return apiGet<NrbUmapPoint[]>(
    "/nrbs/umap/",
    params as Record<string, string | number | boolean | undefined>,
  );
}

export interface NrbScatterParams {
  x_axis?: NrbScatterAxis;
  y_axis?: NrbScatterAxis;
  include_partials?: boolean;
  max_points?: number;
}

export function fetchNrbScatter(params: NrbScatterParams = {}) {
  return apiGet<NrbScatterPoint[]>(
    "/nrbs/scatter/",
    params as Record<string, string | number | boolean | undefined>,
  );
}

export interface SimilarNrbRequest {
  nrb_id: number;
  k?: number;
}

export function postSimilarNrbQuery(
  body: SimilarNrbRequest,
  page = 1,
  pageSize = 25,
) {
  const qs = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  return apiPost<PaginatedNrbRosterResponse>(
    `/query/similar-nrb/?${qs.toString()}`,
    body,
  );
}
