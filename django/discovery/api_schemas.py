"""Pydantic schemas for the Discovery Platform API."""

from typing import Optional

from ninja import Schema


# ── Pagination ────────────────────────────────────────────────────────────────


class PaginationMeta(Schema):
    page: int
    page_size: int
    total_count: int
    total_pages: int


# ── Assembly schemas ─────────────────────────────────────────────────────────


class AssemblyRosterItem(Schema):
    id: int
    accession: str
    organism_name: str = ""
    source_name: Optional[str] = None
    assembly_type: str = "genome"
    is_type_strain: bool = False
    type_strain_catalog_url: str = ""
    # Scores
    bgc_count: int = 0
    l1_class_count: int = 0
    bgc_diversity_score: float = 0.0
    bgc_novelty_score: float = 0.0
    bgc_density: float = 0.0
    taxonomic_novelty: float = 0.0


class PaginatedAssemblyResponse(Schema):
    items: list[AssemblyRosterItem]
    pagination: PaginationMeta


class AssemblyDetail(Schema):
    id: int
    accession: str
    organism_name: str = ""
    source_name: Optional[str] = None
    assembly_type: str = "genome"
    is_type_strain: bool = False
    type_strain_catalog_url: str = ""
    assembly_size_mb: Optional[float] = None
    biome_path: str = ""
    url: str = ""
    # Scores
    bgc_count: int = 0
    l1_class_count: int = 0
    bgc_diversity_score: float = 0.0
    bgc_novelty_score: float = 0.0
    bgc_density: float = 0.0
    taxonomic_novelty: float = 0.0


class AssemblyScatterPoint(Schema):
    id: int
    x: float
    y: float
    organism_name: Optional[str] = None
    is_type_strain: bool = False


# ── Detector / Region schemas ─────────────────────────────────────────────────


class DetectorOut(Schema):
    id: int
    tool: str
    version: str
    tool_name_code: str


class RegionOut(Schema):
    id: int
    accession: str
    start_position: int
    end_position: int


# ── BGC schemas ───────────────────────────────────────────────────────────────


class BgcRosterItem(Schema):
    id: int
    accession: str
    classification_path: str = ""
    size_kb: float = 0.0
    novelty_score: float = 0.0
    domain_novelty: float = 0.0
    is_partial: bool = False
    nearest_validated_accession: Optional[str] = None
    nearest_validated_distance: Optional[float] = None
    assembly_accession: Optional[str] = None
    detector: Optional[DetectorOut] = None
    region_accession: Optional[str] = None


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
    url: str = ""


class ParentAssemblySummary(Schema):
    assembly_id: int
    accession: str
    organism_name: Optional[str] = None
    source_name: Optional[str] = None
    is_type_strain: bool = False


class ChemOntAnnotationNode(Schema):
    """A node in a ChemOnt classification tree for a natural product.

    Each node is a directly-annotated ChemOnt term with its probability.
    ``children`` holds more specific sub-classifications that were also
    annotated on the same natural product.
    """

    chemont_id: str
    name: str
    depth: int = 0
    probability: float | None = None
    children: list["ChemOntAnnotationNode"] = []


class NaturalProductSummary(Schema):
    id: int
    name: str
    smiles: str
    smiles_svg: str = ""
    structure_thumbnail: str = ""
    np_class_path: str = ""
    chemont_classes: list[ChemOntAnnotationNode] = []


class BgcDetail(Schema):
    id: int
    accession: str
    classification_path: str = ""
    size_kb: float = 0.0
    novelty_score: float = 0.0
    domain_novelty: float = 0.0
    is_partial: bool = False
    nearest_validated_accession: Optional[str] = None
    nearest_validated_distance: Optional[float] = None
    is_validated: bool = False
    domain_architecture: list[DomainArchitectureItem] = []
    parent_assembly: Optional[ParentAssemblySummary] = None
    natural_products: list[NaturalProductSummary] = []
    detector: Optional[DetectorOut] = None
    region_accession: Optional[str] = None


class BgcScatterPoint(Schema):
    id: int
    x: float
    y: float
    bgc_class: str = ""
    is_validated: bool = False
    compound_name: Optional[str] = None
    novelty_score: float = 0.0
    domain_novelty: float = 0.0
    similarity_score: Optional[float] = None


class ValidatedReferencePoint(Schema):
    accession: str
    classification_path: str = ""
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


class ChemOntClassNode(Schema):
    chemont_id: str
    name: str
    count: int
    children: list["ChemOntClassNode"] = []


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


class SequenceQueryRequest(Schema):
    sequence: str
    similarity_threshold: float = 0.7


class DomainCondition(Schema):
    acc: str
    required: bool = True


class DomainQueryRequest(Schema):
    domains: list[DomainCondition]
    logic: str = "and"  # "and" | "or"


class QueryResultBgc(Schema):
    id: int
    accession: str
    classification_path: str = ""
    size_kb: float = 0.0
    novelty_score: float = 0.0
    domain_novelty: float = 0.0
    is_partial: bool = False
    similarity_score: float = 0.0
    # Parent assembly summary
    assembly_id: Optional[int] = None
    assembly_accession: Optional[str] = None
    organism_name: Optional[str] = None
    is_type_strain: bool = False


class PaginatedQueryResultResponse(Schema):
    items: list[QueryResultBgc]
    pagination: PaginationMeta


class QueryResultAssemblyAggregation(Schema):
    assembly_id: int
    accession: str
    organism_name: Optional[str] = None
    is_type_strain: bool = False
    hit_count: int = 0
    complete_fraction: float = 0.0


class PaginatedAssemblyAggregationResponse(Schema):
    items: list[QueryResultAssemblyAggregation]
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


class AssemblyStatsResponse(Schema):
    taxonomy_sunburst: list[SunburstNode] = []
    score_distributions: list[ScoreDistribution] = []
    type_strain_count: int = 0
    non_type_strain_count: int = 0
    mean_bgc_per_assembly: float = 0.0
    mean_l1_class_per_assembly: float = 0.0
    total_assemblies: int = 0


class BgcStatsResponse(Schema):
    core_domains: list[CoreDomain] = []
    score_distributions: list[ScoreDistribution] = []
    complete_count: int = 0
    partial_count: int = 0
    np_class_sunburst: list[SunburstNode] = []
    chemont_sunburst: list[SunburstNode] = []
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
    url: str = ""


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
    url: str = ""


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
    asset_type: str  # "assembly" | "bgc"


class AssessmentStatusResponse(Schema):
    status: str  # "PENDING" | "SUCCESS" | "FAILURE"
    result: Optional[dict] = None


# -- Assembly assessment --


class PercentileRank(Schema):
    dimension: str
    label: str
    value: float
    percentile_all: float
    percentile_type_strain: float


class BgcNoveltyItem(Schema):
    bgc_id: int
    accession: str
    classification_path: str = ""
    novelty_vs_validated: float = 0.0
    novelty_vs_db: float = 0.0
    domain_novelty: float = 0.0
    is_partial: bool = False


class RedundancyCell(Schema):
    bgc_id: int
    accession: str
    classification_path: str = ""
    gcf_family_id: Optional[str] = None
    gcf_member_count: int = 0
    gcf_has_validated: bool = False
    gcf_has_type_strain: bool = False
    status: str = "novel_gcf"  # "novel_gcf" | "known_gcf_no_type_strain" | "known_gcf_type_strain"


class AssessChemicalSpacePoint(Schema):
    bgc_id: int
    accession: str
    umap_x: float
    umap_y: float
    classification_path: str = ""
    nearest_validated_distance: float = 0.0
    is_sparse: bool = False


class RadarReference(Schema):
    """DB mean and 90th percentile for each AssemblyScore dimension."""

    dimension: str
    label: str
    db_mean: float
    db_p90: float


class AssemblyAssessmentResponse(Schema):
    assembly_id: int
    accession: str
    organism_name: Optional[str] = None
    is_type_strain: bool = False
    # Percentile ranks
    percentile_ranks: list[PercentileRank] = []
    # DB rank
    db_rank: int = 0
    db_total: int = 0
    # Per-BGC novelty
    bgc_novelty_breakdown: list[BgcNoveltyItem] = []
    # Redundancy matrix
    redundancy_matrix: list[RedundancyCell] = []
    # Chemical space
    chemical_space_points: list[AssessChemicalSpacePoint] = []
    validated_reference_points: list[ValidatedReferencePoint] = []
    mean_nearest_validated_distance: float = 0.0
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
    taxonomy_label: str
    count: int = 0


class GcfMemberPoint(Schema):
    bgc_id: int
    umap_x: float
    umap_y: float
    is_type_strain: bool = False
    accession: str = ""


class GcfContext(Schema):
    gcf_id: int
    family_id: str
    member_count: int = 0
    validated_count: int = 0
    mean_novelty: float = 0.0
    known_chemistry_annotation: Optional[str] = None
    validated_accession: Optional[str] = None
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
    validated_accession: Optional[str] = None
    umap_x: float = 0.0
    umap_y: float = 0.0
    distance: float = 0.0
    label: str = ""
    is_validated: bool = False


class BgcAssessmentResponse(Schema):
    bgc_id: int
    accession: str
    classification_path: str = ""
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
    validated_reference_points: list[ValidatedReferencePoint] = []
    # Domain architecture for comparison
    submitted_domains: list[DomainArchitectureItem] = []
    nearest_validated_accession: Optional[str] = None
    nearest_validated_bgc_id: Optional[int] = None
