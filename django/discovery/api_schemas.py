"""Pydantic schemas for the discovery dashboard API."""

from typing import Optional

from ninja import Schema


# ── Weight parameters ─────────────────────────────────────────────────────────


class GenomeWeightParams(Schema):
    """Weights for the Explore Genomes composite priority score."""

    w_diversity: float = 0.30
    w_novelty: float = 0.45
    w_density: float = 0.25


class QueryWeightParams(Schema):
    """Weights for the Query mode result relevance score."""

    w_similarity: float = 0.40
    w_novelty: float = 0.30
    w_completeness: float = 0.15
    w_domain_novelty: float = 0.15


# ── Pagination ────────────────────────────────────────────────────────────────


class PaginationMeta(Schema):
    page: int
    page_size: int
    total_count: int
    total_pages: int


# ── Genome schemas ────────────────────────────────────────────────────────────


class GenomeRosterItem(Schema):
    id: int
    accession: str
    organism_name: Optional[str] = None
    taxonomy_kingdom: Optional[str] = None
    taxonomy_phylum: Optional[str] = None
    taxonomy_class: Optional[str] = None
    taxonomy_order: Optional[str] = None
    taxonomy_family: Optional[str] = None
    taxonomy_genus: Optional[str] = None
    taxonomy_species: Optional[str] = None
    is_type_strain: bool = False
    type_strain_catalog_url: Optional[str] = None
    # Scores
    bgc_count: int = 0
    l1_class_count: int = 0
    bgc_diversity_score: float = 0.0
    bgc_novelty_score: float = 0.0
    bgc_density: float = 0.0
    taxonomic_novelty: float = 0.0
    genome_quality: float = 0.0
    composite_score: float = 0.0


class PaginatedGenomeResponse(Schema):
    items: list[GenomeRosterItem]
    pagination: PaginationMeta


class GenomeDetail(Schema):
    id: int
    accession: str
    organism_name: Optional[str] = None
    taxonomy_kingdom: Optional[str] = None
    taxonomy_phylum: Optional[str] = None
    taxonomy_class: Optional[str] = None
    taxonomy_order: Optional[str] = None
    taxonomy_family: Optional[str] = None
    taxonomy_genus: Optional[str] = None
    taxonomy_species: Optional[str] = None
    is_type_strain: bool = False
    type_strain_catalog_url: Optional[str] = None
    genome_size_mb: Optional[float] = None
    genome_quality: Optional[float] = None
    isolation_source: Optional[str] = None
    # Scores
    bgc_count: int = 0
    l1_class_count: int = 0
    bgc_diversity_score: float = 0.0
    bgc_novelty_score: float = 0.0
    bgc_density: float = 0.0
    taxonomic_novelty: float = 0.0
    composite_score: float = 0.0


class GenomeScatterPoint(Schema):
    id: int
    x: float
    y: float
    composite_score: float
    taxonomy_family: Optional[str] = None
    organism_name: Optional[str] = None
    is_type_strain: bool = False


# ── BGC schemas ───────────────────────────────────────────────────────────────


class BgcRosterItem(Schema):
    id: int
    accession: str
    classification_l1: str = ""
    classification_l2: Optional[str] = None
    classification_l3: Optional[str] = None
    size_kb: float = 0.0
    novelty_score: float = 0.0
    domain_novelty: float = 0.0
    is_partial: bool = False
    nearest_mibig_accession: Optional[str] = None
    nearest_mibig_distance: Optional[float] = None
    assembly_accession: Optional[str] = None


class PaginatedBgcRosterResponse(Schema):
    items: list[BgcRosterItem]
    pagination: PaginationMeta


class DomainArchitectureItem(Schema):
    domain_acc: str
    domain_name: str
    ref_db: str
    start: int
    end: int
    score: Optional[float] = None


class ParentGenomeSummary(Schema):
    assembly_id: int
    accession: str
    organism_name: Optional[str] = None
    taxonomy_family: Optional[str] = None
    is_type_strain: bool = False
    genome_quality: Optional[float] = None
    isolation_source: Optional[str] = None


class NaturalProductSummary(Schema):
    id: int
    name: str
    smiles: str
    smiles_svg: str = ""
    structure_thumbnail: str = ""
    chemical_class_l1: str = ""
    chemical_class_l2: Optional[str] = None
    chemical_class_l3: Optional[str] = None


class BgcDetail(Schema):
    id: int
    accession: str
    classification_l1: str = ""
    classification_l2: Optional[str] = None
    classification_l3: Optional[str] = None
    size_kb: float = 0.0
    novelty_score: float = 0.0
    domain_novelty: float = 0.0
    is_partial: bool = False
    nearest_mibig_accession: Optional[str] = None
    nearest_mibig_distance: Optional[float] = None
    is_validated: bool = False
    domain_architecture: list[DomainArchitectureItem] = []
    parent_genome: Optional[ParentGenomeSummary] = None
    natural_products: list[NaturalProductSummary] = []


class BgcScatterPoint(Schema):
    id: int
    umap_x: float
    umap_y: float
    bgc_class: str = ""
    is_mibig: bool = False
    compound_name: Optional[str] = None


class MibigReferencePoint(Schema):
    accession: str
    compound_name: str
    bgc_class: str
    umap_x: float
    umap_y: float


# ── Filter schemas ────────────────────────────────────────────────────────────


class TaxonomyNode(Schema):
    name: str
    rank: str
    count: int
    children: list["TaxonomyNode"] = []


class BgcClassOption(Schema):
    name: str
    count: int


class NpClassLevel(Schema):
    name: str
    count: int
    children: list["NpClassLevel"] = []


class DomainOption(Schema):
    acc: str
    name: str
    description: Optional[str] = None
    count: int


class PaginatedDomainResponse(Schema):
    items: list[DomainOption]
    pagination: PaginationMeta


# ── Query mode schemas ────────────────────────────────────────────────────────


class ChemicalQueryRequest(Schema):
    smiles: str
    similarity_threshold: float = 0.5


class DomainCondition(Schema):
    acc: str
    required: bool = True


class DomainQueryRequest(Schema):
    domains: list[DomainCondition]
    logic: str = "and"  # "and" | "or"


class QueryResultBgc(Schema):
    id: int
    accession: str
    classification_l1: str = ""
    classification_l2: Optional[str] = None
    size_kb: float = 0.0
    novelty_score: float = 0.0
    domain_novelty: float = 0.0
    is_partial: bool = False
    relevance_score: float = 0.0
    # Parent genome summary
    assembly_id: Optional[int] = None
    assembly_accession: Optional[str] = None
    organism_name: Optional[str] = None
    is_type_strain: bool = False


class PaginatedQueryResultResponse(Schema):
    items: list[QueryResultBgc]
    pagination: PaginationMeta


class QueryResultGenomeAggregation(Schema):
    assembly_id: int
    accession: str
    organism_name: Optional[str] = None
    taxonomy_family: Optional[str] = None
    is_type_strain: bool = False
    hit_count: int = 0
    max_relevance: float = 0.0
    mean_relevance: float = 0.0
    complete_fraction: float = 0.0


class PaginatedGenomeAggregationResponse(Schema):
    items: list[QueryResultGenomeAggregation]
    pagination: PaginationMeta


# ── Stats schemas ────────────────────────────────────────────────────────────


class SunburstNode(Schema):
    id: str
    label: str
    parent: str = ""
    count: int = 0


class ScoreDistribution(Schema):
    label: str
    values: list[float] = []


class CoreDomain(Schema):
    acc: str
    name: str
    bgc_count: int = 0
    fraction: float = 0.0


class BgcClassCount(Schema):
    name: str
    count: int = 0


class GenomeStatsResponse(Schema):
    taxonomy_sunburst: list[SunburstNode] = []
    score_distributions: list[ScoreDistribution] = []
    type_strain_count: int = 0
    non_type_strain_count: int = 0
    mean_bgc_per_genome: float = 0.0
    mean_l1_class_per_genome: float = 0.0
    total_genomes: int = 0


class BgcStatsResponse(Schema):
    core_domains: list[CoreDomain] = []
    score_distributions: list[ScoreDistribution] = []
    complete_count: int = 0
    partial_count: int = 0
    np_class_sunburst: list[SunburstNode] = []
    bgc_class_distribution: list[BgcClassCount] = []
    total_bgcs: int = 0


# ── Export schemas ────────────────────────────────────────────────────────────


class ShortlistExportRequest(Schema):
    ids: list[int]


# ── BGC Region schemas ───────────────────────────────────────────────────────


class PfamAnnotationOut(Schema):
    accession: str
    description: str = ""
    go_slim: str = ""
    envelope_start: int = 0
    envelope_end: int = 0
    e_value: Optional[str] = None


class RegionCdsOut(Schema):
    protein_id: str
    start: int
    end: int
    strand: int
    protein_length: int
    gene_caller: str = ""
    cluster_representative: Optional[str] = None
    cluster_representative_url: Optional[str] = None
    sequence: str = ""
    pfam: list[PfamAnnotationOut] = []


class RegionDomainOut(Schema):
    accession: str
    description: str = ""
    start: int
    end: int
    strand: int
    score: Optional[float] = None
    go_slim: list[str] = []
    parent_cds_id: str = ""


class RegionClusterOut(Schema):
    accession: str
    start: int
    end: int
    source: str = ""
    bgc_classes: list[str] = []


class BgcRegionOut(Schema):
    region_length: int
    window_start: int
    window_end: int
    cds_list: list[RegionCdsOut] = []
    domain_list: list[RegionDomainOut] = []
    cluster_list: list[RegionClusterOut] = []


# ── Assessment schemas ──────────────────────────────────────────────────────


class AssessmentAccepted(Schema):
    task_id: str
    asset_type: str  # "genome" | "bgc"


class AssessmentStatusResponse(Schema):
    status: str  # "PENDING" | "SUCCESS" | "FAILURE"
    result: Optional[dict] = None


# -- Genome assessment --


class PercentileRank(Schema):
    dimension: str
    label: str
    value: float
    percentile_all: float
    percentile_type_strain: float


class BgcNoveltyItem(Schema):
    bgc_id: int
    accession: str
    classification_l1: str = ""
    novelty_vs_mibig: float = 0.0
    novelty_vs_db: float = 0.0
    domain_novelty: float = 0.0


class RedundancyCell(Schema):
    bgc_id: int
    accession: str
    classification_l1: str = ""
    gcf_family_id: Optional[str] = None
    gcf_member_count: int = 0
    gcf_has_mibig: bool = False
    gcf_has_type_strain: bool = False
    status: str = "novel_gcf"  # "novel_gcf" | "known_gcf_no_type_strain" | "known_gcf_type_strain"


class AssessChemicalSpacePoint(Schema):
    bgc_id: int
    accession: str
    umap_x: float
    umap_y: float
    classification_l1: str = ""
    nearest_mibig_distance: float = 0.0
    is_sparse: bool = False


class RadarReference(Schema):
    """DB mean and 90th percentile for each GenomeScore dimension."""

    dimension: str
    label: str
    db_mean: float
    db_p90: float


class GenomeAssessmentResponse(Schema):
    assembly_id: int
    accession: str
    organism_name: Optional[str] = None
    is_type_strain: bool = False
    # Percentile ranks
    percentile_ranks: list[PercentileRank] = []
    # DB rank
    db_rank: int = 0
    db_total: int = 0
    composite_score: float = 0.0
    # Per-BGC novelty
    bgc_novelty_breakdown: list[BgcNoveltyItem] = []
    # Redundancy matrix
    redundancy_matrix: list[RedundancyCell] = []
    # Chemical space
    chemical_space_points: list[AssessChemicalSpacePoint] = []
    mibig_reference_points: list[MibigReferencePoint] = []
    mean_nearest_mibig_distance: float = 0.0
    sparse_fraction: float = 0.0
    # Radar chart reference data
    radar_references: list[RadarReference] = []


# -- BGC assessment --


class GcfDomainFrequency(Schema):
    domain_acc: str
    domain_name: str
    description: Optional[str] = None
    frequency: float = 0.0
    category: str = ""  # "core" | "variable" | "rare"


class GcfTaxonomyCount(Schema):
    taxonomy_family: str
    count: int = 0


class GcfMemberPoint(Schema):
    bgc_id: int
    umap_x: float
    umap_y: float
    is_type_strain: bool = False
    distance_to_representative: float = 0.0
    accession: str = ""


class GcfContext(Schema):
    gcf_id: int
    family_id: str
    member_count: int = 0
    mibig_count: int = 0
    mean_novelty: float = 0.0
    known_chemistry_annotation: Optional[str] = None
    mibig_accession: Optional[str] = None
    domain_frequency: list[GcfDomainFrequency] = []
    taxonomy_distribution: list[GcfTaxonomyCount] = []
    member_points: list[GcfMemberPoint] = []


class DomainDifferential(Schema):
    domain_acc: str
    domain_name: str
    in_submitted: bool = True
    gcf_frequency: float = 0.0
    category: str = ""  # "core" | "variable" | "absent"


class NoveltyDecomposition(Schema):
    sequence_novelty: float = 0.0
    chemistry_novelty: float = 0.0
    architecture_novelty: float = 0.0


class AssessNearestNeighborPoint(Schema):
    bgc_id: Optional[int] = None
    mibig_accession: Optional[str] = None
    umap_x: float = 0.0
    umap_y: float = 0.0
    distance: float = 0.0
    label: str = ""
    is_mibig: bool = False


class BgcAssessmentResponse(Schema):
    bgc_id: int
    accession: str
    classification_l1: str = ""
    classification_l2: Optional[str] = None
    # GCF placement
    gcf_context: Optional[GcfContext] = None
    distance_to_gcf_representative: Optional[float] = None
    is_novel_singleton: bool = False
    # Domain differential
    domain_differential: list[DomainDifferential] = []
    # Novelty decomposition
    novelty: NoveltyDecomposition = NoveltyDecomposition()
    # Chemical space
    submitted_point: Optional[AssessChemicalSpacePoint] = None
    nearest_neighbors: list[AssessNearestNeighborPoint] = []
    mibig_reference_points: list[MibigReferencePoint] = []
    # Domain architecture for comparison
    submitted_domains: list[DomainArchitectureItem] = []
    nearest_mibig_accession: Optional[str] = None
    nearest_mibig_bgc_id: Optional[int] = None
