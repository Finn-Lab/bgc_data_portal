import { apiGet, apiPost } from "./client";
import type {
  DomainQueryRequest,
  PaginatedAssemblyAggregationResponse,
  PaginatedQueryResultResponse,
} from "./types";

export interface DomainQueryParams {
  page?: number;
  page_size?: number;
  sort_by?: string;
  order?: "asc" | "desc";
  search?: string;
  source_names?: string;
  detector_tools?: string;
  taxonomy_path?: string;
  assembly_type?: string;
  bgc_class?: string;
  biome_lineage?: string;
  assembly_accession?: string;
  bgc_accession?: string;
}

export function postDomainQuery(
  body: DomainQueryRequest,
  params: DomainQueryParams = {}
) {
  const queryString = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) queryString.set(key, String(value));
  }
  const qs = queryString.toString();
  return apiPost<PaginatedQueryResultResponse>(
    `/query/domain/${qs ? `?${qs}` : ""}`,
    body
  );
}

export interface SimilarBgcParams {
  max_distance?: number;
  page?: number;
  page_size?: number;
  sort_by?: string;
  order?: "asc" | "desc";
}

export function postSimilarBgcQuery(
  bgcId: number,
  params: SimilarBgcParams = {}
) {
  const queryString = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) queryString.set(key, String(value));
  }
  const qs = queryString.toString();
  return apiPost<PaginatedQueryResultResponse>(
    `/query/similar-bgc/${bgcId}/${qs ? `?${qs}` : ""}`,
    {}
  );
}

export interface ChemicalQueryRequest {
  smiles: string;
  similarity_threshold: number;
}

export interface ChemicalQueryParams {
  page?: number;
  page_size?: number;
  sort_by?: string;
  order?: "asc" | "desc";
  search?: string;
  source_names?: string;
  detector_tools?: string;
  taxonomy_path?: string;
  assembly_type?: string;
  bgc_class?: string;
  biome_lineage?: string;
  assembly_accession?: string;
  bgc_accession?: string;
  chemont_ids?: string;
}

export function postChemicalQuery(
  body: ChemicalQueryRequest,
  params: ChemicalQueryParams = {}
) {
  const queryString = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) queryString.set(key, String(value));
  }
  const qs = queryString.toString();
  return apiPost<PaginatedQueryResultResponse>(
    `/query/chemical/${qs ? `?${qs}` : ""}`,
    body
  );
}

export interface SequenceQueryRequest {
  sequence: string;
  similarity_threshold: number;
}

export interface SequenceQueryParams {
  page?: number;
  page_size?: number;
  sort_by?: string;
  order?: "asc" | "desc";
  search?: string;
  source_names?: string;
  detector_tools?: string;
  taxonomy_path?: string;
  assembly_type?: string;
  bgc_class?: string;
  biome_lineage?: string;
  assembly_accession?: string;
  bgc_accession?: string;
}

export function postSequenceQuery(
  body: SequenceQueryRequest,
  params: SequenceQueryParams = {}
) {
  const queryString = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) queryString.set(key, String(value));
  }
  const qs = queryString.toString();
  return apiPost<PaginatedQueryResultResponse>(
    `/query/sequence/${qs ? `?${qs}` : ""}`,
    body
  );
}

export interface AssemblyAggregationParams {
  bgc_ids: string;
  page?: number;
  page_size?: number;
  sort_by?: string;
  order?: "asc" | "desc";
}

export function fetchQueryResultAssemblies(params: AssemblyAggregationParams) {
  return apiGet<PaginatedAssemblyAggregationResponse>(
    "/query-results/assemblies/",
    params as unknown as Record<string, string | number | boolean | undefined>
  );
}
