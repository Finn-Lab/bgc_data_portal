// ── Pagination ────────────────────────────────────────────────────────────

export interface PaginationMeta {
  page: number;
  page_size: number;
  total_count: number;
  total_pages: number;
}

// ── Assembly schemas ────────────────────────────────────────────────────────

export interface AssemblyRosterItem {
  id: number;
  accession: string;
  organism_name: string | null;
  source_name: string | null;
  assembly_type: string;
  is_type_strain: boolean;
  type_strain_catalog_url: string | null;
  bgc_count: number;
  l1_class_count: number;
  bgc_diversity_score: number;
  bgc_novelty_score: number;
  bgc_density: number;
  taxonomic_novelty: number;
}

export interface PaginatedAssemblyResponse {
  items: AssemblyRosterItem[];
  pagination: PaginationMeta;
}

export interface AssemblyDetail {
  id: number;
  accession: string;
  organism_name: string | null;
  source_name: string | null;
  assembly_type: string;
  is_type_strain: boolean;
  type_strain_catalog_url: string | null;
  assembly_size_mb: number | null;
  biome_path: string;
  url: string;
  bgc_count: number;
  l1_class_count: number;
  bgc_diversity_score: number;
  bgc_novelty_score: number;
  bgc_density: number;
  taxonomic_novelty: number;
}

export interface AssemblyScatterPoint {
  id: number;
  x: number;
  y: number;
  organism_name: string | null;
  is_type_strain: boolean;
}

// ── BGC schemas ───────────────────────────────────────────────────────────

export interface BgcRosterItem {
  id: number;
  accession: string;
  classification_path: string;
  size_kb: number;
  novelty_score: number;
  domain_novelty: number;
  is_partial: boolean;
  nearest_validated_accession: string | null;
  nearest_validated_distance: number | null;
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

export interface ParentAssemblySummary {
  assembly_id: number;
  accession: string;
  organism_name: string | null;
  source_name: string | null;
  is_type_strain: boolean;
}

export interface ChemOntAnnotationNode {
  chemont_id: string;
  name: string;
  depth: number;
  probability: number | null; // null for intermediate (unannotated) ancestors
  children: ChemOntAnnotationNode[];
}

export interface NaturalProductSummary {
  id: number;
  name: string;
  smiles: string;
  smiles_svg: string;
  structure_thumbnail: string;
  np_class_path: string;
  chemont_classes: ChemOntAnnotationNode[];
}

export interface BgcDetail {
  id: number;
  accession: string;
  classification_path: string;
  size_kb: number;
  novelty_score: number;
  domain_novelty: number;
  is_partial: boolean;
  nearest_validated_accession: string | null;
  nearest_validated_distance: number | null;
  is_validated: boolean;
  domain_architecture: DomainArchitectureItem[];
  parent_assembly: ParentAssemblySummary | null;
  natural_products: NaturalProductSummary[];
}

export interface BgcScatterPoint {
  id: number;
  x: number;
  y: number;
  bgc_class: string;
  is_validated: boolean;
  compound_name: string | null;
  novelty_score: number;
  domain_novelty: number;
  similarity_score: number | null;
}

export interface ValidatedReferencePoint {
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

export interface ChemOntClassNode {
  chemont_id: string;
  name: string;
  count: number;
  children: ChemOntClassNode[];
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
  classification_path: string;
  size_kb: number;
  novelty_score: number;
  domain_novelty: number;
  is_partial: boolean;
  similarity_score: number;
  assembly_id: number | null;
  assembly_accession: string | null;
  organism_name: string | null;
  is_type_strain: boolean;
  source_name: string | null;
}

export interface PaginatedQueryResultResponse {
  items: QueryResultBgc[];
  pagination: PaginationMeta;
}

export interface QueryResultAssemblyAggregation {
  assembly_id: number;
  accession: string;
  organism_name: string | null;
  is_type_strain: boolean;
  source_name: string | null;
  hit_count: number;
  complete_fraction: number;
}

export interface PaginatedAssemblyAggregationResponse {
  items: QueryResultAssemblyAggregation[];
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
  url: string;
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

export interface AssemblyStatsResponse {
  taxonomy_sunburst: SunburstNode[];
  score_distributions: ScoreDistribution[];
  type_strain_count: number;
  non_type_strain_count: number;
  mean_bgc_per_assembly: number;
  mean_l1_class_per_assembly: number;
  total_assemblies: number;
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

// ── Assessment schemas ───────────────────────────────────────────────────

export interface AssessmentAccepted {
  task_id: string;
  asset_type: "assembly" | "bgc";
}

export interface AssessmentStatusResponse {
  status: "PENDING" | "SUCCESS" | "FAILURE" | "UNKNOWN";
  result: AssemblyAssessmentResult | BgcAssessmentResult | null;
}

// -- Assembly assessment --

export interface PercentileRank {
  dimension: string;
  label: string;
  value: number;
  percentile_all: number;
  percentile_type_strain: number;
}

export interface BgcNoveltyItem {
  bgc_id: number;
  accession: string;
  classification_path: string;
  novelty_vs_validated: number;
  novelty_vs_db: number;
  domain_novelty: number;
  is_partial: boolean;
  size_kb: number;
  nearest_validated_accession: string | null;
  nearest_validated_distance: number | null;
}

export interface RedundancyCell {
  bgc_id: number;
  accession: string;
  classification_path: string;
  gcf_family_id: string | null;
  gcf_member_count: number;
  gcf_has_validated: boolean;
  gcf_has_type_strain: boolean;
  status: "novel_gcf" | "known_gcf_no_type_strain" | "known_gcf_type_strain";
}

export interface AssessChemicalSpacePoint {
  bgc_id: number;
  accession: string;
  umap_x: number;
  umap_y: number;
  classification_path: string;
  nearest_validated_distance: number;
  is_sparse: boolean;
}

export interface RadarReference {
  dimension: string;
  label: string;
  db_mean: number;
  db_p90: number;
}

export interface AssemblyAssessmentResult {
  assembly_id: number;
  accession: string;
  organism_name: string | null;
  is_type_strain: boolean;
  percentile_ranks: PercentileRank[];
  db_rank: number;
  db_total: number;
  bgc_novelty_breakdown: BgcNoveltyItem[];
  redundancy_matrix: RedundancyCell[];
  chemical_space_points: AssessChemicalSpacePoint[];
  validated_reference_points: ValidatedReferencePoint[];
  mean_nearest_validated_distance: number;
  sparse_fraction: number;
  radar_references: RadarReference[];
}

// -- BGC assessment --

export interface GcfDomainFrequency {
  domain_acc: string;
  domain_name: string;
  description: string | null;
  frequency: number;
  category: "core" | "variable" | "rare";
}

export interface GcfTaxonomyCount {
  taxonomy_label: string;
  count: number;
}

export interface GcfTaxonomyNode {
  id: string;
  label: string;
  parent: string;
  count: number;
  rank: string;
}


export interface GcfMemberPoint {
  bgc_id: number;
  umap_x: number;
  umap_y: number;
  is_type_strain: boolean;
  accession: string;
  distance_to_representative: number;
}

export interface GcfContext {
  gcf_id: number;
  family_id: string;
  member_count: number;
  validated_count: number;
  mean_novelty: number;
  known_chemistry_annotation: string | null;
  validated_accession: string | null;
  domain_frequency: GcfDomainFrequency[];
  taxonomy_distribution: GcfTaxonomyCount[];
  taxonomy_hierarchy: GcfTaxonomyNode[];
  member_points: GcfMemberPoint[];
}

export interface DomainDifferential {
  domain_acc: string;
  domain_name: string;
  in_submitted: boolean;
  gcf_frequency: number;
  category: "core" | "variable" | "absent";
}

export interface NoveltyDecomposition {
  sequence_novelty: number;
  chemistry_novelty: number;
  architecture_novelty: number;
}

export interface AssessNearestNeighborPoint {
  bgc_id: number | null;
  validated_accession: string | null;
  umap_x: number;
  umap_y: number;
  distance: number;
  label: string;
  is_validated: boolean;
}

export interface BgcAssessmentResult {
  bgc_id: number;
  accession: string;
  classification_path: string;
  gcf_context: GcfContext | null;
  distance_to_gcf_representative: number | null;
  is_novel_singleton: boolean;
  domain_differential: DomainDifferential[];
  novelty: NoveltyDecomposition;
  submitted_point: AssessChemicalSpacePoint | null;
  nearest_neighbors: AssessNearestNeighborPoint[];
  validated_reference_points: ValidatedReferencePoint[];
  submitted_domains: DomainArchitectureItem[];
  nearest_validated_accession: string | null;
  nearest_validated_bgc_id: number | null;
}
