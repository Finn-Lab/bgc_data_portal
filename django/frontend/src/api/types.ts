// ── Weight parameters ──────────────────────────────────────────────────────

export interface GenomeWeightParams {
  w_diversity: number;
  w_novelty: number;
  w_density: number;
}

export const GENOME_WEIGHT_DEFAULTS: GenomeWeightParams = {
  w_diversity: 0.3,
  w_novelty: 0.45,
  w_density: 0.25,
};

export interface QueryWeightParams {
  w_similarity: number;
  w_novelty: number;
  w_completeness: number;
  w_domain_novelty: number;
}

export const QUERY_WEIGHT_DEFAULTS: QueryWeightParams = {
  w_similarity: 0.4,
  w_novelty: 0.3,
  w_completeness: 0.15,
  w_domain_novelty: 0.15,
};

// ── Pagination ────────────────────────────────────────────────────────────

export interface PaginationMeta {
  page: number;
  page_size: number;
  total_count: number;
  total_pages: number;
}

// ── Genome schemas ────────────────────────────────────────────────────────

export interface GenomeRosterItem {
  id: number;
  accession: string;
  organism_name: string | null;
  taxonomy_kingdom: string | null;
  taxonomy_phylum: string | null;
  taxonomy_class: string | null;
  taxonomy_order: string | null;
  taxonomy_family: string | null;
  taxonomy_genus: string | null;
  taxonomy_species: string | null;
  is_type_strain: boolean;
  type_strain_catalog_url: string | null;
  bgc_count: number;
  l1_class_count: number;
  bgc_diversity_score: number;
  bgc_novelty_score: number;
  bgc_density: number;
  taxonomic_novelty: number;
  genome_quality: number;
  composite_score: number;
}

export interface PaginatedGenomeResponse {
  items: GenomeRosterItem[];
  pagination: PaginationMeta;
}

export interface GenomeDetail {
  id: number;
  accession: string;
  organism_name: string | null;
  taxonomy_kingdom: string | null;
  taxonomy_phylum: string | null;
  taxonomy_class: string | null;
  taxonomy_order: string | null;
  taxonomy_family: string | null;
  taxonomy_genus: string | null;
  taxonomy_species: string | null;
  is_type_strain: boolean;
  type_strain_catalog_url: string | null;
  genome_size_mb: number | null;
  genome_quality: number | null;
  isolation_source: string | null;
  bgc_count: number;
  l1_class_count: number;
  bgc_diversity_score: number;
  bgc_novelty_score: number;
  bgc_density: number;
  taxonomic_novelty: number;
  composite_score: number;
}

export interface GenomeScatterPoint {
  id: number;
  x: number;
  y: number;
  composite_score: number;
  taxonomy_family: string | null;
  organism_name: string | null;
  is_type_strain: boolean;
}

// ── BGC schemas ───────────────────────────────────────────────────────────

export interface BgcRosterItem {
  id: number;
  accession: string;
  classification_l1: string;
  classification_l2: string | null;
  classification_l3: string | null;
  size_kb: number;
  novelty_score: number;
  domain_novelty: number;
  is_partial: boolean;
  nearest_mibig_accession: string | null;
  nearest_mibig_distance: number | null;
  assembly_accession: string | null;
}

export interface PaginatedBgcRosterResponse {
  items: BgcRosterItem[];
  pagination: PaginationMeta;
}

export interface DomainArchitectureItem {
  domain_acc: string;
  domain_name: string;
  ref_db: string;
  start: number;
  end: number;
  score: number | null;
}

export interface ParentGenomeSummary {
  assembly_id: number;
  accession: string;
  organism_name: string | null;
  taxonomy_family: string | null;
  is_type_strain: boolean;
  genome_quality: number | null;
  isolation_source: string | null;
}

export interface NaturalProductSummary {
  id: number;
  name: string;
  smiles: string;
  smiles_svg: string;
  structure_thumbnail: string;
  chemical_class_l1: string;
  chemical_class_l2: string | null;
  chemical_class_l3: string | null;
}

export interface BgcDetail {
  id: number;
  accession: string;
  classification_l1: string;
  classification_l2: string | null;
  classification_l3: string | null;
  size_kb: number;
  novelty_score: number;
  domain_novelty: number;
  is_partial: boolean;
  nearest_mibig_accession: string | null;
  nearest_mibig_distance: number | null;
  is_validated: boolean;
  domain_architecture: DomainArchitectureItem[];
  parent_genome: ParentGenomeSummary | null;
  natural_products: NaturalProductSummary[];
}

export interface BgcScatterPoint {
  id: number;
  umap_x: number;
  umap_y: number;
  bgc_class: string;
  is_mibig: boolean;
  compound_name: string | null;
}

export interface MibigReferencePoint {
  accession: string;
  compound_name: string;
  bgc_class: string;
  umap_x: number;
  umap_y: number;
}

// ── Filter schemas ────────────────────────────────────────────────────────

export interface TaxonomyNode {
  name: string;
  rank: string;
  count: number;
  children: TaxonomyNode[];
}

export interface BgcClassOption {
  name: string;
  count: number;
}

export interface NpClassLevel {
  name: string;
  count: number;
  children: NpClassLevel[];
}

export interface DomainOption {
  acc: string;
  name: string;
  description: string | null;
  count: number;
}

export interface PaginatedDomainResponse {
  items: DomainOption[];
  pagination: PaginationMeta;
}

// ── Query mode schemas ────────────────────────────────────────────────────

export interface DomainCondition {
  acc: string;
  required: boolean;
}

export interface DomainQueryRequest {
  domains: DomainCondition[];
  logic: "and" | "or";
}

export interface QueryResultBgc {
  id: number;
  accession: string;
  classification_l1: string;
  classification_l2: string | null;
  size_kb: number;
  novelty_score: number;
  domain_novelty: number;
  is_partial: boolean;
  relevance_score: number;
  assembly_id: number | null;
  assembly_accession: string | null;
  organism_name: string | null;
  is_type_strain: boolean;
}

export interface PaginatedQueryResultResponse {
  items: QueryResultBgc[];
  pagination: PaginationMeta;
}

export interface QueryResultGenomeAggregation {
  assembly_id: number;
  accession: string;
  organism_name: string | null;
  taxonomy_family: string | null;
  is_type_strain: boolean;
  hit_count: number;
  max_relevance: number;
  mean_relevance: number;
  complete_fraction: number;
}

export interface PaginatedGenomeAggregationResponse {
  items: QueryResultGenomeAggregation[];
  pagination: PaginationMeta;
}

// ── BGC Region schemas ────────────────────────────────────────────────────

export interface PfamAnnotation {
  accession: string;
  description: string;
  go_slim: string;
  envelope_start: number;
  envelope_end: number;
  e_value: string | null;
}

export interface RegionCds {
  protein_id: string;
  start: number;
  end: number;
  strand: number;
  protein_length: number;
  gene_caller: string;
  cluster_representative: string | null;
  cluster_representative_url: string | null;
  sequence: string;
  pfam: PfamAnnotation[];
}

export interface RegionDomain {
  accession: string;
  description: string;
  start: number;
  end: number;
  strand: number;
  score: number | null;
  go_slim: string[];
  parent_cds_id: string;
}

export interface RegionCluster {
  accession: string;
  start: number;
  end: number;
  source: string;
  bgc_classes: string[];
}

export interface BgcRegionData {
  region_length: number;
  window_start: number;
  window_end: number;
  cds_list: RegionCds[];
  domain_list: RegionDomain[];
  cluster_list: RegionCluster[];
}

// ── Stats schemas ─────────────────────────────────────────────────────────

export interface SunburstNode {
  id: string;
  label: string;
  parent: string;
  count: number;
}

export interface ScoreDistribution {
  label: string;
  values: number[];
}

export interface CoreDomain {
  acc: string;
  name: string;
  bgc_count: number;
  fraction: number;
}

export interface BgcClassCount {
  name: string;
  count: number;
}

export interface GenomeStatsResponse {
  taxonomy_sunburst: SunburstNode[];
  score_distributions: ScoreDistribution[];
  type_strain_count: number;
  non_type_strain_count: number;
  mean_bgc_per_genome: number;
  mean_l1_class_per_genome: number;
  total_genomes: number;
}

export interface BgcStatsResponse {
  core_domains: CoreDomain[];
  score_distributions: ScoreDistribution[];
  complete_count: number;
  partial_count: number;
  np_class_sunburst: SunburstNode[];
  bgc_class_distribution: BgcClassCount[];
  total_bgcs: number;
}

// ── Export schemas ─────────────────────────────────────────────────────────

export interface ShortlistExportRequest {
  ids: number[];
}
