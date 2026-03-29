import { apiGet, apiPost } from "./client";
import type {
  DomainQueryRequest,
  PaginatedGenomeAggregationResponse,
  PaginatedQueryResultResponse,
  QueryWeightParams,
} from "./types";

export interface DomainQueryParams extends Partial<QueryWeightParams> {
  page?: number;
  page_size?: number;
  search?: string;
  type_strain_only?: boolean;
  taxonomy_kingdom?: string;
  taxonomy_phylum?: string;
  taxonomy_class?: string;
  taxonomy_order?: string;
  taxonomy_family?: string;
  taxonomy_genus?: string;
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

export interface SimilarBgcParams extends Partial<QueryWeightParams> {
  max_distance?: number;
  page?: number;
  page_size?: number;
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

export interface ChemicalQueryParams extends Partial<QueryWeightParams> {
  page?: number;
  page_size?: number;
  search?: string;
  type_strain_only?: boolean;
  taxonomy_kingdom?: string;
  taxonomy_phylum?: string;
  taxonomy_class?: string;
  taxonomy_order?: string;
  taxonomy_family?: string;
  taxonomy_genus?: string;
  bgc_class?: string;
  biome_lineage?: string;
  assembly_accession?: string;
  bgc_accession?: string;
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

export interface GenomeAggregationParams {
  bgc_ids: string;
  page?: number;
  page_size?: number;
  sort_by?: string;
  order?: "asc" | "desc";
}

export function fetchQueryResultGenomes(params: GenomeAggregationParams) {
  return apiGet<PaginatedGenomeAggregationResponse>(
    "/query-results/genomes/",
    params as unknown as Record<string, string | number | boolean | undefined>
  );
}
