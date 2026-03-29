import { apiGet } from "./client";
import type {
  BgcRosterItem,
  GenomeDetail,
  GenomeScatterPoint,
  GenomeWeightParams,
  PaginatedGenomeResponse,
} from "./types";

export interface GenomeRosterParams extends Partial<GenomeWeightParams> {
  page?: number;
  page_size?: number;
  sort_by?: string;
  order?: "asc" | "desc";
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
  bgc_accession?: string;
  assembly_accession?: string;
  assembly_ids?: string;
}

export function fetchGenomeRoster(params: GenomeRosterParams = {}) {
  return apiGet<PaginatedGenomeResponse>("/genomes/", params as Record<string, string | number | boolean | undefined>);
}

export function fetchGenomeDetail(assemblyId: number) {
  return apiGet<GenomeDetail>(`/genomes/${assemblyId}/`);
}

export function fetchGenomeBgcs(assemblyId: number) {
  return apiGet<BgcRosterItem[]>(`/genomes/${assemblyId}/bgcs/`);
}

export interface GenomeScatterParams extends Partial<GenomeWeightParams> {
  x_axis?: string;
  y_axis?: string;
  type_strain_only?: boolean;
  taxonomy_family?: string;
  bgc_class?: string;
  assembly_ids?: string;
}

export function fetchGenomeScatter(params: GenomeScatterParams = {}) {
  return apiGet<GenomeScatterPoint[]>("/genome-scatter/", params as Record<string, string | number | boolean | undefined>);
}
