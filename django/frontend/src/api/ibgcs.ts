import { apiGet, apiGetWithHeaders, apiPost } from "./client";
import type {
  IbgcCountResponse,
  IbgcDetail,
  IbgcIdsResponse,
  IbgcScatterAxis,
  IbgcScatterPoint,
  IbgcUmapPoint,
  PaginatedIbgcRosterResponse,
} from "./types";

export interface IbgcFilterParams {
  include_partials?: boolean;
  validated_only?: boolean;
  min_length_kb?: number;
  max_length_kb?: number;
  min_novelty?: number;
  max_novelty?: number;
  min_domain_novelty?: number;
  max_domain_novelty?: number;
  detector_tools?: string;
  /** @deprecated use detector_tools — kept for backward compat */
  source_tools?: string;
  source_names?: string;
  assembly_type?: string;
  leaf_path_prefix?: string;
  bgc_class?: string;
  chemont_ids?: string;
  bgc_accession?: string;
  assembly_accession?: string;
  assembly_ids?: string;
  organism?: string;
  biome_lineage?: string;
  taxonomy_path?: string;
}

export interface IbgcRosterParams extends IbgcFilterParams {
  sort_by?:
    | "novelty_score"
    | "domain_novelty"
    | "size_kb"
    | "classification_path"
    | "id"
    | "similarity";
  order?: "asc" | "desc";
  page?: number;
  page_size?: number;
  /** Comma-separated iBGC ids — restricts the roster to this allow-list. */
  ibgc_ids?: string;
}

export function fetchIbgcRoster(params: IbgcRosterParams = {}) {
  return apiGet<PaginatedIbgcRosterResponse>(
    "/ibgcs/roster/",
    params as Record<string, string | number | boolean | undefined>,
  );
}

/** Cheap COUNT over the iBGC filter surface. Fired before the heavier
 *  roster/UMAP/scatter calls to drive the empty-state guard and the
 *  "Showing X of Y, sampled" banner. */
export function fetchIbgcCount(params: IbgcFilterParams & { ibgc_ids?: string } = {}) {
  return apiGet<IbgcCountResponse>(
    "/ibgcs/count/",
    params as Record<string, string | number | boolean | undefined>,
  );
}

export interface IbgcIdsParams extends IbgcFilterParams {
  sort_by?: IbgcRosterParams["sort_by"];
  order?: "asc" | "desc";
  ibgc_ids?: string;
  asset_token?: string;
}

/** Bulk iBGC ids matching the active filter surface — capped at 1000
 *  server-side. Powers the roster's "Add all to shortlist" button so we
 *  don't have to walk roster pages just to gather ids. */
export function fetchIbgcIds(params: IbgcIdsParams = {}) {
  return apiGet<IbgcIdsResponse>(
    "/ibgcs/ids/",
    params as Record<string, string | number | boolean | undefined>,
  );
}

// ── iBGC-collapsed query endpoints ─────────────────────────────────────────

export interface DomainCondition {
  acc: string;
  required: boolean;
}

export interface DomainQueryRequest {
  domains: DomainCondition[];
  logic: "and" | "or";
}

export interface IbgcDomainQueryParams extends IbgcFilterParams {
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

export function postIbgcDomainQuery(
  body: DomainQueryRequest,
  params: IbgcDomainQueryParams = {},
) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const path = qs.toString()
    ? `/query/ibgc-domain/?${qs.toString()}`
    : "/query/ibgc-domain/";
  return apiPost<PaginatedIbgcRosterResponse>(path, body);
}

export interface IbgcSequenceStatusParams extends IbgcDomainQueryParams {
  // same shape as the domain-query params
}

export function fetchIbgcSequenceQueryStatus(
  taskId: string,
  params: IbgcSequenceStatusParams = {},
) {
  return apiGet<PaginatedIbgcRosterResponse>(
    `/query/ibgc-sequence/status/${taskId}/`,
    params as Record<string, string | number | boolean | undefined>,
  );
}

export function fetchIbgcDetail(ibgcId: number, assetToken?: string | null) {
  // Negative ids belong to ephemeral asset uploads — the backend resolves
  // them through the ``X-Asset-Token`` header so the URL path stays clean.
  if (ibgcId < 0 && assetToken) {
    return apiGetWithHeaders<IbgcDetail>(
      `/ibgcs/${ibgcId}/`,
      { "X-Asset-Token": assetToken },
    );
  }
  return apiGet<IbgcDetail>(`/ibgcs/${ibgcId}/`);
}

export interface IbgcUmapParams extends IbgcFilterParams {
  max_points?: number;
  /** Comma-separated iBGC ids — restricts the UMAP to this allow-list. */
  ibgc_ids?: string;
}

export function fetchIbgcUmap(params: IbgcUmapParams = {}) {
  return apiGet<IbgcUmapPoint[]>(
    "/ibgcs/umap/",
    params as Record<string, string | number | boolean | undefined>,
  );
}

export interface IbgcScatterParams extends IbgcFilterParams {
  x_axis?: IbgcScatterAxis;
  y_axis?: IbgcScatterAxis;
  max_points?: number;
  /** Comma-separated iBGC ids — restricts the scatter to this allow-list. */
  ibgc_ids?: string;
}

export function fetchIbgcScatter(params: IbgcScatterParams = {}) {
  return apiGet<IbgcScatterPoint[]>(
    "/ibgcs/scatter/",
    params as Record<string, string | number | boolean | undefined>,
  );
}

export interface SimilarIbgcRequest {
  ibgc_id: number;
  k?: number;
}

export function postSimilarIbgcQuery(
  body: SimilarIbgcRequest,
  page = 1,
  pageSize = 25,
) {
  const qs = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  return apiPost<PaginatedIbgcRosterResponse>(
    `/query/similar-ibgc/?${qs.toString()}`,
    body,
  );
}

export interface IbgcArchitectureResponse {
  id: number;
  label: string;
  ordered_accs: string[];
}

/** Pooled positional domain accessions for clipboard / copy actions. */
export function fetchIbgcArchitecture(
  ibgcId: number,
  assetToken?: string | null,
) {
  if (ibgcId < 0 && assetToken) {
    return apiGetWithHeaders<IbgcArchitectureResponse>(
      `/ibgcs/${ibgcId}/architecture/`,
      { "X-Asset-Token": assetToken },
    );
  }
  return apiGet<IbgcArchitectureResponse>(`/ibgcs/${ibgcId}/architecture/`);
}

export interface IbgcArchitectureQueryRequest {
  architecture: string[];
  weight: number;
  k?: number;
}

export function postIbgcArchitectureQuery(
  body: IbgcArchitectureQueryRequest,
  page = 1,
  pageSize = 25,
) {
  const qs = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  return apiPost<PaginatedIbgcRosterResponse>(
    `/query/ibgc-architecture/?${qs.toString()}`,
    body,
  );
}
