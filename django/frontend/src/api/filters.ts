import { apiGet } from "./client";
import type {
  BgcClassOption,
  ChemOntClassNode,
  NpClassLevel,
  PaginatedDomainResponse,
  PaginatedSourceResponse,
  PaginatedDetectorResponse,
  TaxonomyNode,
} from "./types";

export function fetchTaxonomyTree() {
  return apiGet<TaxonomyNode[]>("/filters/taxonomy/");
}

export function fetchBgcClasses() {
  return apiGet<BgcClassOption[]>("/filters/bgc-classes/");
}

export function fetchNpClasses() {
  return apiGet<NpClassLevel[]>("/filters/np-classes/");
}

export function fetchChemOntClasses() {
  return apiGet<ChemOntClassNode[]>("/filters/chemont-classes/");
}

export interface DomainSearchParams {
  search?: string;
  page?: number;
  page_size?: number;
}

export function fetchDomains(params: DomainSearchParams = {}) {
  return apiGet<PaginatedDomainResponse>(
    "/filters/domains/",
    params as Record<string, string | number | boolean | undefined>
  );
}

export interface SourceSearchParams {
  search?: string;
  page?: number;
  page_size?: number;
}

export function fetchSources(params: SourceSearchParams = {}) {
  return apiGet<PaginatedSourceResponse>(
    "/filters/sources/",
    params as Record<string, string | number | boolean | undefined>
  );
}

export interface DetectorSearchParams {
  search?: string;
  page?: number;
  page_size?: number;
}

export function fetchDetectors(params: DetectorSearchParams = {}) {
  return apiGet<PaginatedDetectorResponse>(
    "/filters/detectors/",
    params as Record<string, string | number | boolean | undefined>
  );
}
