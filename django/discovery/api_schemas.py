"""Pydantic schemas for the Discovery Platform API."""

from datetime import datetime
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
    url: str = ""


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


# ── NRB (Non-Redundant BGC) schemas ──────────────────────────────────────────


class NrbRosterItem(Schema):
    """Row in the NRB-level results table.

    NRBs are the primary unit in the v2 Discovery dashboard. Each NRB
    consolidates one or more source ``DashboardBgc`` rows; the table here
    flattens metadata that the UI needs in the roster view.
    """

    id: int
    label: str  # human-facing identifier (e.g. "NRB-12345")
    classification_path: str = ""  # leaf GCF path (gene_cluster_family)
    size_kb: float = 0.0  # (end - start) / 1000
    n_source_bgcs: int = 0
    source_tools: list[str] = []
    novelty_score: Optional[float] = None
    domain_novelty: Optional[float] = None
    is_partial: bool = False
    is_validated: bool = False
    is_type_strain: bool = False  # any source BGC sits on a type-strain assembly
    umap_projected: bool = False
    parent_assembly_id: Optional[int] = None
    parent_assembly_accession: Optional[str] = None
    organism_name: Optional[str] = None
    contig_accession: Optional[str] = None
    similarity_score: Optional[float] = None  # filled by similar-nrb / query
    # Populated only by sequence-protein search responses — the protein_id
    # of the highest-bitscore CDS within the NRB.
    best_hit_protein_id: Optional[str] = None


class PaginatedNrbRosterResponse(Schema):
    items: list[NrbRosterItem]
    pagination: PaginationMeta


class NrbMemberBgc(Schema):
    """Source DashboardBgc contributing to an NRB (drill-down list)."""

    id: int
    accession: str
    detector_name: Optional[str] = None
    is_partial: bool = False
    is_validated: bool = False
    size_kb: float = 0.0


class NrbDetail(Schema):
    id: int
    label: str
    classification_path: str = ""
    size_kb: float = 0.0
    start_position: int = 0
    end_position: int = 0
    contig_accession: Optional[str] = None
    source_tools: list[str] = []
    novelty_score: Optional[float] = None
    domain_novelty: Optional[float] = None
    is_partial: bool = False
    is_validated: bool = False
    is_type_strain: bool = False
    umap_projected: bool = False
    umap_x: Optional[float] = None
    umap_y: Optional[float] = None
    parent_assembly: Optional[ParentAssemblySummary] = None
    representative_bgc_id: Optional[int] = None  # for region/CDS rendering
    member_bgcs: list[NrbMemberBgc] = []
    domain_architecture: list[DomainArchitectureItem] = []
    natural_products: list[NaturalProductSummary] = []


class NrbScatterPoint(Schema):
    """Point for the Variables Map (axes chosen from numeric NRB columns)."""

    id: int
    x: float
    y: float
    classification_path: str = ""
    novelty_score: Optional[float] = None
    domain_novelty: Optional[float] = None
    is_partial: bool = False
    is_validated: bool = False
    is_type_strain: bool = False
    umap_projected: bool = False
    similarity_score: Optional[float] = None


class NrbUmapPoint(Schema):
    """Point for the UMAP tab; ``umap_projected`` flags partial-NRB inferred coords."""

    id: int
    label: str
    umap_x: float
    umap_y: float
    classification_path: str = ""
    novelty_score: Optional[float] = None
    is_partial: bool = False
    is_validated: bool = False
    is_type_strain: bool = False
    umap_projected: bool = False


class SimilarNrbRequest(Schema):
    nrb_id: int
    k: int = 25


# ── Shortlist Report schemas ─────────────────────────────────────────────────


class ReportSnapshotRequest(Schema):
    nrb_ids: list[int]


class ReportSnapshotResponse(Schema):
    token: str
    expires_at: str
    n_nrbs: int


class DomainCompositionEntry(Schema):
    domain_acc: str
    domain_name: str = ""
    domain_description: str = ""
    go_slim: str = ""
    nrb_count: int
    fraction: float
    tier: str  # "core" | "variable" | "rare"


class DomainGoslimDomain(Schema):
    domain_acc: str
    domain_name: str = ""
    domain_description: str = ""


class DomainGoslimCell(Schema):
    category: str
    tier: str  # "core" | "variable" | "rare"
    count: int = 0
    domains: list[DomainGoslimDomain] = []


class DomainGoslimMatrix(Schema):
    categories: list[str] = []
    tiers: list[str] = []
    cells: list[DomainGoslimCell] = []


class DomainCompositionSummary(Schema):
    core_count: int = 0
    variable_count: int = 0
    rare_count: int = 0
    total_unique: int = 0
    rows: list[DomainCompositionEntry] = []


class GcfDistributionEntry(Schema):
    classification_path: str
    nrb_count: int
    fraction: float


class CategoryCount(Schema):
    name: str
    count: int


class LengthBucket(Schema):
    label: str
    count: int


class ReportNrbRow(Schema):
    id: int
    label: str
    classification_path: str = ""
    size_kb: float = 0.0
    novelty_score: Optional[float] = None
    domain_novelty: Optional[float] = None
    n_source_bgcs: int = 0
    source_tools: list[str] = []
    is_partial: bool = False
    is_validated: bool = False
    parent_assembly_accession: Optional[str] = None
    parent_assembly_id: Optional[int] = None
    organism_name: Optional[str] = None
    biome_path: str = ""
    taxonomy_phylum: Optional[str] = None
    contig_accession: Optional[str] = None


class ReportAssemblyRow(Schema):
    id: int
    accession: str
    organism_name: Optional[str] = None
    source_name: Optional[str] = None
    biome_path: str = ""
    taxonomy_path: str = ""
    taxonomy_phylum: Optional[str] = None
    assembly_size_mb: Optional[float] = None
    total_bgcs_in_assembly: int = 0
    nrbs_in_shortlist: int = 0
    is_type_strain: bool = False


class ReportPayload(Schema):
    token: str
    generated_at: str
    expires_at: str
    n_nrbs: int
    n_assemblies: int
    nrb_rows: list[ReportNrbRow] = []
    domain_composition: DomainCompositionSummary = DomainCompositionSummary()
    gcf_distribution: list[GcfDistributionEntry] = []
    score_distributions: list[dict] = []
    completeness_pie: list[CategoryCount] = []
    bgc_class_pie: list[CategoryCount] = []
    length_histogram: list[LengthBucket] = []
    predictor_distribution: list[CategoryCount] = []
    source_distribution: list[CategoryCount] = []
    assembly_rows: list[ReportAssemblyRow] = []
    assembly_stats: dict = {}
    # NRB-derived taxonomy sunburst (one count per NRB). Items follow the
    # ``SunburstNode`` shape ({id, label, parent, count}); typed as ``dict``
    # because SunburstNode is defined further down in this module.
    taxonomy_sunburst: list[dict] = []
    domain_goslim_matrix: DomainGoslimMatrix = DomainGoslimMatrix()

    # Inner shape is {label: str, values: list[float]} — kept as raw dict to
    # avoid a forward reference to ScoreDistribution defined further down.


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


class SourceOption(Schema):
    name: str
    count: int


class PaginatedSourceResponse(Schema):
    items: list[SourceOption]
    pagination: PaginationMeta


class DetectorOption(Schema):
    tool: str
    count: int


class PaginatedDetectorResponse(Schema):
    items: list[DetectorOption]
    pagination: PaginationMeta


# ── Query mode schemas ────────────────────────────────────────────────────────


class ChemicalQueryRequest(Schema):
    smiles: str
    similarity_threshold: float = 0.5


class SequenceQueryRequest(Schema):
    sequence: str
    # phmmer hit must pass all three thresholds. Defaults are tuned for
    # "clearly a close homolog" (bitscore ≥ 30, ≥70% identity, ≥70% query coverage).
    min_bitscore: float = 30.0
    min_pident: float = 70.0   # percent, 0..100
    min_qcov: float = 70.0     # percent, 0..100


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
    # For sequence queries `similarity_score` carries the best bitscore; for
    # other modes it keeps the mode-specific score (Dice, Tanimoto, etc.).
    similarity_score: float = 0.0
    # Sequence-query-specific metrics (populated only by the protein search).
    best_bitscore: Optional[float] = None
    best_pident: Optional[float] = None     # percent, 0..100
    best_qcoverage: Optional[float] = None  # percent, 0..100
    # Parent assembly summary
    assembly_id: Optional[int] = None
    assembly_accession: Optional[str] = None
    organism_name: Optional[str] = None
    is_type_strain: bool = False
    source_name: Optional[str] = None


class PaginatedQueryResultResponse(Schema):
    items: list[QueryResultBgc]
    pagination: PaginationMeta


class SequenceQueryAccepted(Schema):
    task_id: str


class SequenceQueryStatusResponse(Schema):
    status: str  # "PENDING" | "SUCCESS" | "FAILURE"
    items: list[QueryResultBgc] = []
    pagination: Optional[PaginationMeta] = None


class QueryResultAssemblyAggregation(Schema):
    assembly_id: int
    accession: str
    organism_name: Optional[str] = None
    is_type_strain: bool = False
    source_name: Optional[str] = None
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
    biome_distribution: list[CategoryCount] = []
    source_distribution: list[CategoryCount] = []


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


# Assessment schemas removed in v2 — the Evaluate Asset feature was
# replaced by the Shortlist Report endpoints (ReportPayload above).


# ── Platform overview ─────────────────────────────────────────────────────────


class DiscoveryStatsResponse(Schema):
    genomes: int = 0
    metagenomes: int = 0
    validated_bgcs: int = 0
    regions: int = 0
    total_bgc_predictions: int = 0
    updated_at: Optional[datetime] = None
