"""Discovery Platform API — Django Ninja Router.

Mounted on the main NinjaAPI at /api/dashboard/.

Fully self-contained: all endpoints query discovery models only.
No imports from mgnify_bgcs.
"""

import csv
import json
import math
from io import StringIO
from typing import Optional

from django.db.models import (
    Avg,
    Case,
    Count,
    ExpressionWrapper,
    F,
    FloatField,
    Max,
    Q,
    Value,
    When,
)
from django.http import HttpResponse
from ninja import Router, Query
from ninja.errors import HttpError
from pgvector.django import CosineDistance

from discovery.models import (
    BgcDomain,
    BgcEmbedding,
    DashboardBgc,
    DashboardBgcClass,
    DashboardCds,
    DashboardDomain,
    DashboardGCF,
    DashboardGenome,
    DashboardMibigReference,
    DashboardNaturalProduct,
    PrecomputedStats,
)
from discovery.services.scoring import compute_composite_priority
from discovery.services.stats import compute_bgc_stats, compute_genome_stats
from discovery.api_schemas import (
    AssessmentAccepted,
    AssessmentStatusResponse,
    BgcClassCount,
    BgcClassOption,
    BgcDetail,
    BgcRegionOut,
    BgcRosterItem,
    BgcScatterPoint,
    BgcStatsResponse,
    ChemicalQueryRequest,
    CoreDomain,
    GenomeStatsResponse,
    PaginatedBgcRosterResponse,
    DomainArchitectureItem,
    DomainOption,
    DomainQueryRequest,
    GenomeDetail,
    GenomeRosterItem,
    GenomeScatterPoint,
    GenomeWeightParams,
    MibigReferencePoint,
    NaturalProductSummary,
    NpClassLevel,
    PaginatedDomainResponse,
    PaginatedGenomeAggregationResponse,
    PaginatedGenomeResponse,
    PaginatedQueryResultResponse,
    PaginationMeta,
    ParentGenomeSummary,
    PfamAnnotationOut,
    QueryResultBgc,
    QueryResultGenomeAggregation,
    QueryWeightParams,
    RegionCdsOut,
    RegionClusterOut,
    RegionDomainOut,
    ScoreDistribution,
    ShortlistExportRequest,
    SunburstNode,
    TaxonomyNode,
)

discovery_router = Router(tags=["Discovery Platform"])

# Default composite weights
_DEFAULT_W_DIVERSITY = 0.30
_DEFAULT_W_NOVELTY = 0.45
_DEFAULT_W_DENSITY = 0.25


# ── Helpers ───────────────────────────────────────────────────────────────────


def _paginate(page: int, page_size: int, total_count: int):
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    total_pages = max(1, math.ceil(total_count / page_size))
    offset = (page - 1) * page_size
    return page, page_size, total_pages, offset


def _is_default_weights(weights: GenomeWeightParams) -> bool:
    return (
        abs(weights.w_diversity - _DEFAULT_W_DIVERSITY) < 1e-6
        and abs(weights.w_novelty - _DEFAULT_W_NOVELTY) < 1e-6
        and abs(weights.w_density - _DEFAULT_W_DENSITY) < 1e-6
    )


def _annotate_custom_composite(qs, weights: GenomeWeightParams):
    """Annotate a DashboardGenome queryset with a SQL-computed composite score."""
    w_sum = weights.w_diversity + weights.w_novelty + weights.w_density
    if w_sum == 0:
        return qs.annotate(custom_composite=Value(0.0, output_field=FloatField()))
    return qs.annotate(
        custom_composite=ExpressionWrapper(
            (
                Value(weights.w_diversity) * F("bgc_diversity_score")
                + Value(weights.w_novelty) * F("bgc_novelty_score")
                + Value(weights.w_density) * F("bgc_density")
            )
            / Value(w_sum),
            output_field=FloatField(),
        )
    )


def _genome_to_roster_item(genome: DashboardGenome, composite: float) -> GenomeRosterItem:
    return GenomeRosterItem(
        id=genome.id,
        accession=genome.assembly_accession,
        organism_name=genome.organism_name,
        taxonomy_kingdom=genome.taxonomy_kingdom,
        taxonomy_phylum=genome.taxonomy_phylum,
        taxonomy_class=genome.taxonomy_class,
        taxonomy_order=genome.taxonomy_order,
        taxonomy_family=genome.taxonomy_family,
        taxonomy_genus=genome.taxonomy_genus,
        taxonomy_species=genome.taxonomy_species,
        is_type_strain=genome.is_type_strain,
        type_strain_catalog_url=genome.type_strain_catalog_url,
        bgc_count=genome.bgc_count,
        l1_class_count=genome.l1_class_count,
        bgc_diversity_score=genome.bgc_diversity_score,
        bgc_novelty_score=genome.bgc_novelty_score,
        bgc_density=genome.bgc_density,
        taxonomic_novelty=genome.taxonomic_novelty,
        genome_quality=genome.genome_quality,
        composite_score=composite,
    )


# ── Shared filter helpers ────────────────────────────────────────────────────


def _apply_genome_filters(
    qs,
    *,
    genome_ids: Optional[str] = None,
    type_strain_only: bool = False,
    taxonomy_kingdom: Optional[str] = None,
    taxonomy_phylum: Optional[str] = None,
    taxonomy_class: Optional[str] = None,
    taxonomy_order: Optional[str] = None,
    taxonomy_family: Optional[str] = None,
    taxonomy_genus: Optional[str] = None,
    search: Optional[str] = None,
    bgc_class: Optional[str] = None,
    biome_lineage: Optional[str] = None,
    bgc_accession: Optional[str] = None,
    assembly_accession: Optional[str] = None,
):
    """Apply common genome filters to a DashboardGenome queryset."""
    if genome_ids:
        ids = [int(x) for x in genome_ids.split(",") if x.strip().isdigit()]
        if ids:
            qs = qs.filter(id__in=ids)
        else:
            qs = qs.none()
    if type_strain_only:
        qs = qs.filter(is_type_strain=True)
    if taxonomy_kingdom:
        qs = qs.filter(taxonomy_kingdom__iexact=taxonomy_kingdom)
    if taxonomy_phylum:
        qs = qs.filter(taxonomy_phylum__iexact=taxonomy_phylum)
    if taxonomy_class:
        qs = qs.filter(taxonomy_class__iexact=taxonomy_class)
    if taxonomy_order:
        qs = qs.filter(taxonomy_order__iexact=taxonomy_order)
    if taxonomy_family:
        qs = qs.filter(taxonomy_family__iexact=taxonomy_family)
    if taxonomy_genus:
        qs = qs.filter(taxonomy_genus__iexact=taxonomy_genus)
    if search:
        qs = qs.filter(
            Q(organism_name__icontains=search)
            | Q(taxonomy_species__icontains=search)
            | Q(taxonomy_genus__icontains=search)
            | Q(taxonomy_family__icontains=search)
            | Q(assembly_accession__icontains=search)
        )
    if bgc_class:
        qs = qs.filter(bgcs__classification_l1__iexact=bgc_class).distinct()
    if biome_lineage:
        qs = qs.filter(biome_path__icontains=biome_lineage)
    if bgc_accession:
        bgc_accession = bgc_accession.strip()
        if bgc_accession.upper().startswith("MGYB"):
            qs = qs.filter(bgcs__bgc_accession__iexact=bgc_accession).distinct()
        else:
            qs = qs.filter(bgcs__bgc_accession__icontains=bgc_accession).distinct()
    if assembly_accession:
        qs = qs.filter(assembly_accession__icontains=assembly_accession)
    return qs


def _apply_bgc_filters(qs, *, genome_ids: Optional[str] = None):
    """Apply common BGC filters to a DashboardBgc queryset."""
    if genome_ids:
        ids = [int(x) for x in genome_ids.split(",") if x.strip().isdigit()]
        if ids:
            qs = qs.filter(genome_id__in=ids)
        else:
            qs = qs.none()
    else:
        qs = qs.none()
    return qs


# ── Genome endpoints ─────────────────────────────────────────────────────────


@discovery_router.get("/genomes/", response=PaginatedGenomeResponse)
def genome_roster(
    request,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "composite_score",
    order: str = "desc",
    search: Optional[str] = None,
    taxonomy_kingdom: Optional[str] = None,
    taxonomy_phylum: Optional[str] = None,
    taxonomy_class: Optional[str] = None,
    taxonomy_order: Optional[str] = None,
    taxonomy_family: Optional[str] = None,
    taxonomy_genus: Optional[str] = None,
    type_strain_only: bool = False,
    bgc_class: Optional[str] = None,
    biome_lineage: Optional[str] = None,
    bgc_accession: Optional[str] = None,
    assembly_accession: Optional[str] = None,
    assembly_ids: Optional[str] = None,
    weights: GenomeWeightParams = Query(...),
):
    qs = DashboardGenome.objects.all()
    qs = _apply_genome_filters(
        qs,
        genome_ids=assembly_ids,
        type_strain_only=type_strain_only,
        taxonomy_kingdom=taxonomy_kingdom,
        taxonomy_phylum=taxonomy_phylum,
        taxonomy_class=taxonomy_class,
        taxonomy_order=taxonomy_order,
        taxonomy_family=taxonomy_family,
        taxonomy_genus=taxonomy_genus,
        search=search,
        bgc_class=bgc_class,
        biome_lineage=biome_lineage,
        bgc_accession=bgc_accession,
        assembly_accession=assembly_accession,
    )

    # Sort in DB — use precomputed composite or SQL expression
    use_default = _is_default_weights(weights)
    score_fields = {
        "composite_score", "bgc_count", "bgc_diversity_score",
        "bgc_novelty_score", "bgc_density", "taxonomic_novelty",
        "l1_class_count",
    }
    reverse = order == "desc"
    prefix = "-" if reverse else ""

    if sort_by == "composite_score":
        if use_default:
            qs = qs.order_by(f"{prefix}composite_score")
        else:
            qs = _annotate_custom_composite(qs, weights)
            qs = qs.order_by(f"{prefix}custom_composite")
    elif sort_by in score_fields:
        qs = qs.order_by(f"{prefix}{sort_by}")
    elif sort_by == "organism_name":
        qs = qs.order_by(f"{prefix}organism_name")
    else:
        if use_default:
            qs = qs.order_by("-composite_score")
        else:
            qs = _annotate_custom_composite(qs, weights)
            qs = qs.order_by("-custom_composite")

    total_count = qs.count()
    page, page_size, total_pages, offset = _paginate(page, page_size, total_count)
    page_qs = qs[offset: offset + page_size]

    items = []
    for genome in page_qs:
        if use_default:
            composite = genome.composite_score
        else:
            composite = getattr(genome, "custom_composite", genome.composite_score)
        items.append(_genome_to_roster_item(genome, composite))

    return PaginatedGenomeResponse(
        items=items,
        pagination=PaginationMeta(
            page=page,
            page_size=page_size,
            total_count=total_count,
            total_pages=total_pages,
        ),
    )


@discovery_router.get("/genomes/{genome_id}/", response=GenomeDetail)
def genome_detail(request, genome_id: int, weights: GenomeWeightParams = Query(...)):
    try:
        genome = DashboardGenome.objects.get(id=genome_id)
    except DashboardGenome.DoesNotExist:
        raise HttpError(404, "Genome not found")

    if _is_default_weights(weights):
        composite = genome.composite_score
    else:
        composite = compute_composite_priority(
            scores={
                "diversity": genome.bgc_diversity_score,
                "novelty": genome.bgc_novelty_score,
                "density": genome.bgc_density,
            },
            weights={
                "diversity": weights.w_diversity,
                "novelty": weights.w_novelty,
                "density": weights.w_density,
            },
        )

    return GenomeDetail(
        id=genome.id,
        accession=genome.assembly_accession,
        organism_name=genome.organism_name,
        taxonomy_kingdom=genome.taxonomy_kingdom,
        taxonomy_phylum=genome.taxonomy_phylum,
        taxonomy_class=genome.taxonomy_class,
        taxonomy_order=genome.taxonomy_order,
        taxonomy_family=genome.taxonomy_family,
        taxonomy_genus=genome.taxonomy_genus,
        taxonomy_species=genome.taxonomy_species,
        is_type_strain=genome.is_type_strain,
        type_strain_catalog_url=genome.type_strain_catalog_url,
        genome_size_mb=genome.genome_size_mb,
        genome_quality=genome.genome_quality,
        isolation_source=genome.isolation_source,
        bgc_count=genome.bgc_count,
        l1_class_count=genome.l1_class_count,
        bgc_diversity_score=genome.bgc_diversity_score,
        bgc_novelty_score=genome.bgc_novelty_score,
        bgc_density=genome.bgc_density,
        taxonomic_novelty=genome.taxonomic_novelty,
        composite_score=composite,
    )


@discovery_router.get("/genomes/{genome_id}/bgcs/", response=list[BgcRosterItem])
def genome_bgc_roster(request, genome_id: int):
    bgcs = DashboardBgc.objects.filter(genome_id=genome_id).order_by("-novelty_score")

    return [
        BgcRosterItem(
            id=bgc.id,
            accession=bgc.bgc_accession,
            classification_l1=bgc.classification_l1,
            classification_l2=bgc.classification_l2 or None,
            classification_l3=bgc.classification_l3 or None,
            size_kb=bgc.size_kb,
            novelty_score=bgc.novelty_score,
            domain_novelty=bgc.domain_novelty,
            is_partial=bgc.is_partial,
            nearest_mibig_accession=bgc.nearest_mibig_accession or None,
            nearest_mibig_distance=bgc.nearest_mibig_distance,
        )
        for bgc in bgcs
    ]


@discovery_router.get("/bgcs/roster/", response=PaginatedBgcRosterResponse)
def bgc_roster(
    request,
    assembly_ids: Optional[str] = None,
    sort_by: str = "novelty_score",
    order: str = "desc",
    page: int = 1,
    page_size: int = 25,
):
    qs = DashboardBgc.objects.select_related("genome")
    qs = _apply_bgc_filters(qs, genome_ids=assembly_ids)

    sort_map = {
        "novelty_score": "novelty_score",
        "size_kb": "size_kb",
        "domain_novelty": "domain_novelty",
        "classification_l1": "classification_l1",
        "accession": "id",
    }
    order_field = sort_map.get(sort_by, "novelty_score")
    prefix = "-" if order == "desc" else ""
    qs = qs.order_by(f"{prefix}{order_field}")

    total_count = qs.count()
    pg, ps, tp, offset = _paginate(page, page_size, total_count)
    page_qs = qs[offset: offset + ps]

    items = [
        BgcRosterItem(
            id=bgc.id,
            accession=bgc.bgc_accession,
            classification_l1=bgc.classification_l1,
            classification_l2=bgc.classification_l2 or None,
            classification_l3=bgc.classification_l3 or None,
            size_kb=bgc.size_kb,
            novelty_score=bgc.novelty_score,
            domain_novelty=bgc.domain_novelty,
            is_partial=bgc.is_partial,
            nearest_mibig_accession=bgc.nearest_mibig_accession or None,
            nearest_mibig_distance=bgc.nearest_mibig_distance,
            assembly_accession=bgc.genome.assembly_accession if bgc.genome else None,
        )
        for bgc in page_qs
    ]

    return PaginatedBgcRosterResponse(
        items=items,
        pagination=PaginationMeta(page=pg, page_size=ps, total_count=total_count, total_pages=tp),
    )


@discovery_router.get("/bgcs/parent-assemblies/", response=list[int])
def bgc_parent_assemblies(request, bgc_ids: str):
    ids = [int(x) for x in bgc_ids.split(",") if x.strip().isdigit()]
    if not ids:
        return []
    return list(
        DashboardBgc.objects.filter(id__in=ids)
        .values_list("genome_id", flat=True)
        .distinct()
    )


@discovery_router.get("/genome-scatter/", response=list[GenomeScatterPoint])
def genome_scatter(
    request,
    x_axis: str = "bgc_diversity_score",
    y_axis: str = "bgc_novelty_score",
    type_strain_only: bool = False,
    taxonomy_family: Optional[str] = None,
    bgc_class: Optional[str] = None,
    assembly_ids: Optional[str] = None,
    weights: GenomeWeightParams = Query(...),
):
    allowed_axes = {
        "bgc_diversity_score", "bgc_novelty_score", "bgc_density",
        "taxonomic_novelty", "genome_quality",
    }
    if x_axis not in allowed_axes or y_axis not in allowed_axes:
        raise HttpError(400, f"Axis must be one of: {', '.join(sorted(allowed_axes))}")

    qs = DashboardGenome.objects.all()
    if assembly_ids:
        ids = [int(x) for x in assembly_ids.split(",") if x.strip().isdigit()]
        if ids:
            qs = qs.filter(id__in=ids)
    if type_strain_only:
        qs = qs.filter(is_type_strain=True)
    if taxonomy_family:
        qs = qs.filter(taxonomy_family__iexact=taxonomy_family)
    if bgc_class:
        qs = qs.filter(bgcs__classification_l1__iexact=bgc_class).distinct()

    use_default = _is_default_weights(weights)

    points = []
    for genome in qs:
        if use_default:
            composite = genome.composite_score
        else:
            composite = compute_composite_priority(
                scores={
                    "diversity": genome.bgc_diversity_score,
                    "novelty": genome.bgc_novelty_score,
                    "density": genome.bgc_density,
                },
                weights={
                    "diversity": weights.w_diversity,
                    "novelty": weights.w_novelty,
                    "density": weights.w_density,
                },
            )
        points.append(
            GenomeScatterPoint(
                id=genome.id,
                x=getattr(genome, x_axis, 0.0) or 0.0,
                y=getattr(genome, y_axis, 0.0) or 0.0,
                composite_score=composite,
                taxonomy_family=genome.taxonomy_family,
                organism_name=genome.organism_name,
                is_type_strain=genome.is_type_strain,
            )
        )
    return points


# ── BGC endpoints ────────────────────────────────────────────────────────────


@discovery_router.get("/bgcs/{bgc_id}/", response=BgcDetail)
def bgc_detail(request, bgc_id: int):
    try:
        bgc = DashboardBgc.objects.select_related("genome").get(id=bgc_id)
    except DashboardBgc.DoesNotExist:
        raise HttpError(404, "BGC not found")

    # Domain architecture from BgcDomain (no positional data)
    domain_arch = [
        DomainArchitectureItem(
            domain_acc=bd.domain_acc,
            domain_name=bd.domain_name,
            ref_db=bd.ref_db,
            start=0,
            end=0,
            score=None,
        )
        for bd in BgcDomain.objects.filter(bgc=bgc).order_by("domain_acc")
    ]

    # Parent genome
    parent = None
    genome = bgc.genome
    if genome:
        parent = ParentGenomeSummary(
            assembly_id=genome.id,
            accession=genome.assembly_accession,
            organism_name=genome.organism_name,
            taxonomy_family=genome.taxonomy_family,
            is_type_strain=genome.is_type_strain,
            genome_quality=genome.genome_quality,
            isolation_source=genome.isolation_source,
        )

    # Natural products
    np_items = []
    for np_obj in DashboardNaturalProduct.objects.filter(bgc=bgc):
        np_items.append(
            NaturalProductSummary(
                id=np_obj.id,
                name=np_obj.name,
                smiles=np_obj.smiles,
                smiles_svg="",
                structure_thumbnail=np_obj.structure_svg_base64,
                chemical_class_l1=np_obj.chemical_class_l1,
                chemical_class_l2=np_obj.chemical_class_l2 or None,
                chemical_class_l3=np_obj.chemical_class_l3 or None,
            )
        )

    return BgcDetail(
        id=bgc.id,
        accession=bgc.bgc_accession,
        classification_l1=bgc.classification_l1,
        classification_l2=bgc.classification_l2 or None,
        classification_l3=bgc.classification_l3 or None,
        size_kb=bgc.size_kb,
        novelty_score=bgc.novelty_score,
        domain_novelty=bgc.domain_novelty,
        is_partial=bgc.is_partial,
        nearest_mibig_accession=bgc.nearest_mibig_accession or None,
        nearest_mibig_distance=bgc.nearest_mibig_distance,
        is_validated=bgc.is_validated,
        domain_architecture=domain_arch,
        parent_genome=parent,
        natural_products=np_items,
    )


@discovery_router.get("/bgcs/{bgc_id}/region/", response=BgcRegionOut)
def bgc_region(request, bgc_id: int):
    """Return CDS, domain, and cluster data for the BGC genomic region.

    Served entirely from discovery models (DashboardCds, BgcDomain).
    """
    try:
        bgc = DashboardBgc.objects.get(id=bgc_id)
    except DashboardBgc.DoesNotExist:
        raise HttpError(404, "BGC not found")

    extended_window = 2000
    window_start = max(0, bgc.start_position - extended_window)
    window_end = bgc.end_position + extended_window
    region_length = window_end - window_start

    # CDS within the window
    cds_qs = (
        DashboardCds.objects.filter(
            bgc=bgc,
            start_position__lte=window_end,
            end_position__gte=window_start,
        )
        .prefetch_related("domains")
        .order_by("start_position")
    )

    cds_list = []
    domain_list = []

    for cds in cds_qs:
        pfam_rows = []
        for bd in cds.domains.all():
            pfam_rows.append(
                PfamAnnotationOut(
                    accession=bd.domain_acc,
                    description=bd.domain_description or bd.domain_name or "",
                    go_slim="",
                    envelope_start=bd.start_position,
                    envelope_end=bd.end_position,
                    e_value=str(bd.score) if bd.score is not None else None,
                )
            )

            # Convert AA positions to nucleotide positions on the contig
            if cds.strand >= 0:
                dom_nt_start = cds.start_position + bd.start_position * 3
                dom_nt_end = cds.start_position + bd.end_position * 3
            else:
                dom_nt_start = cds.end_position - bd.end_position * 3
                dom_nt_end = cds.end_position - bd.start_position * 3

            domain_list.append(
                RegionDomainOut(
                    accession=bd.domain_acc,
                    description=bd.domain_description or bd.domain_name or "",
                    start=max(0, dom_nt_start - window_start),
                    end=max(0, dom_nt_end - window_start),
                    strand=cds.strand,
                    score=bd.score,
                    go_slim=[],
                    parent_cds_id=cds.protein_id_str,
                )
            )

        rep = cds.cluster_representative
        cds_list.append(
            RegionCdsOut(
                protein_id=cds.protein_id_str,
                start=cds.start_position - window_start,
                end=cds.end_position - window_start,
                strand=cds.strand,
                protein_length=cds.protein_length,
                gene_caller=cds.gene_caller,
                cluster_representative=rep or None,
                cluster_representative_url=(
                    f"https://www.ebi.ac.uk/metagenomics/proteins/{rep}/"
                    if rep
                    else None
                ),
                sequence=cds.sequence,
                pfam=pfam_rows,
            )
        )

    # Overlapping BGC clusters in the same contig region
    overlapping_bgcs = DashboardBgc.objects.filter(
        contig_accession=bgc.contig_accession,
        start_position__lte=window_end,
        end_position__gte=window_start,
    )
    cluster_list = [
        RegionClusterOut(
            accession=ob.bgc_accession,
            start=max(0, ob.start_position - window_start),
            end=max(0, ob.end_position - window_start),
            source=ob.detector_names,
            bgc_classes=[ob.classification_l1] if ob.classification_l1 else [],
        )
        for ob in overlapping_bgcs
    ]

    return BgcRegionOut(
        region_length=region_length,
        window_start=window_start,
        window_end=window_end,
        cds_list=cds_list,
        domain_list=domain_list,
        cluster_list=cluster_list,
    )


@discovery_router.get("/bgc-scatter/", response=list[BgcScatterPoint])
def bgc_scatter(
    request,
    include_mibig: bool = True,
    bgc_class: Optional[str] = None,
    assembly_ids: Optional[str] = None,
    bgc_ids: Optional[str] = None,
    max_points: int = 2000,
):
    qs = DashboardBgc.objects.all()

    if bgc_class:
        qs = qs.filter(classification_l1__iexact=bgc_class)
    if bgc_ids:
        ids = [int(x) for x in bgc_ids.split(",") if x.strip().isdigit()]
        if ids:
            qs = qs.filter(id__in=ids)
    elif assembly_ids:
        ids = [int(x) for x in assembly_ids.split(",") if x.strip().isdigit()]
        if ids:
            qs = qs.filter(genome_id__in=ids)

    total = qs.count()
    if total > max_points:
        qs = qs.order_by("?")[:max_points]

    points = [
        BgcScatterPoint(
            id=bgc.id,
            umap_x=bgc.umap_x,
            umap_y=bgc.umap_y,
            bgc_class=bgc.classification_l1,
            is_mibig=False,
            compound_name=None,
        )
        for bgc in qs
    ]

    if include_mibig:
        for ref in DashboardMibigReference.objects.all():
            points.append(
                BgcScatterPoint(
                    id=ref.id,
                    umap_x=ref.umap_x,
                    umap_y=ref.umap_y,
                    bgc_class=ref.bgc_class,
                    is_mibig=True,
                    compound_name=ref.compound_name,
                )
            )

    return points


# ── Query mode endpoints ─────────────────────────────────────────────────────


@discovery_router.post("/query/domain/", response=PaginatedQueryResultResponse)
def domain_query(
    request,
    body: DomainQueryRequest,
    page: int = 1,
    page_size: int = 25,
    search: Optional[str] = None,
    taxonomy_kingdom: Optional[str] = None,
    taxonomy_phylum: Optional[str] = None,
    taxonomy_class: Optional[str] = None,
    taxonomy_order: Optional[str] = None,
    taxonomy_family: Optional[str] = None,
    taxonomy_genus: Optional[str] = None,
    type_strain_only: bool = False,
    bgc_class: Optional[str] = None,
    biome_lineage: Optional[str] = None,
    assembly_accession: Optional[str] = None,
    bgc_accession: Optional[str] = None,
    weights: QueryWeightParams = Query(...),
):
    required = [d.acc for d in body.domains if d.required]
    excluded = [d.acc for d in body.domains if not d.required]

    qs = DashboardBgc.objects.select_related("genome")

    # Sidebar filters via parent genome
    if type_strain_only:
        qs = qs.filter(genome__is_type_strain=True)
    if taxonomy_kingdom:
        qs = qs.filter(genome__taxonomy_kingdom__iexact=taxonomy_kingdom)
    if taxonomy_phylum:
        qs = qs.filter(genome__taxonomy_phylum__iexact=taxonomy_phylum)
    if taxonomy_class:
        qs = qs.filter(genome__taxonomy_class__iexact=taxonomy_class)
    if taxonomy_order:
        qs = qs.filter(genome__taxonomy_order__iexact=taxonomy_order)
    if taxonomy_family:
        qs = qs.filter(genome__taxonomy_family__iexact=taxonomy_family)
    if taxonomy_genus:
        qs = qs.filter(genome__taxonomy_genus__iexact=taxonomy_genus)
    if search:
        qs = qs.filter(
            Q(genome__organism_name__icontains=search)
            | Q(genome__assembly_accession__icontains=search)
        )
    if bgc_class:
        qs = qs.filter(classification_l1__iexact=bgc_class)
    if biome_lineage:
        qs = qs.filter(genome__biome_path__icontains=biome_lineage)
    if assembly_accession:
        qs = qs.filter(genome__assembly_accession__icontains=assembly_accession)
    if bgc_accession:
        bgc_accession = bgc_accession.strip()
        qs = qs.filter(bgc_accession__icontains=bgc_accession)

    # Domain filtering via BgcDomain (single join instead of 5)
    if body.logic == "and" and required:
        for acc in required:
            qs = qs.filter(bgc_domains__domain_acc=acc)
        qs = qs.distinct()
    elif required:
        qs = qs.filter(bgc_domains__domain_acc__in=required).distinct()

    if excluded:
        qs = qs.exclude(bgc_domains__domain_acc__in=excluded)

    # Compute relevance in SQL
    w_sum = (
        weights.w_similarity + weights.w_novelty
        + weights.w_completeness + weights.w_domain_novelty
    )
    if w_sum > 0:
        qs = qs.annotate(
            relevance=ExpressionWrapper(
                (
                    Value(weights.w_similarity) * Value(1.0)
                    + Value(weights.w_novelty) * F("novelty_score")
                    + Value(weights.w_completeness)
                    * Case(When(is_partial=True, then=0.0), default=1.0, output_field=FloatField())
                    + Value(weights.w_domain_novelty) * F("domain_novelty")
                )
                / Value(w_sum),
                output_field=FloatField(),
            )
        ).order_by("-relevance")
    else:
        qs = qs.annotate(relevance=Value(0.0, output_field=FloatField()))

    total_count = qs.count()
    pg, ps, tp, offset = _paginate(page, page_size, total_count)
    page_qs = qs[offset: offset + ps]

    items = [
        QueryResultBgc(
            id=bgc.id,
            accession=bgc.bgc_accession,
            classification_l1=bgc.classification_l1,
            classification_l2=bgc.classification_l2 or None,
            size_kb=bgc.size_kb,
            novelty_score=bgc.novelty_score,
            domain_novelty=bgc.domain_novelty,
            is_partial=bgc.is_partial,
            relevance_score=round(bgc.relevance, 4),
            genome_id=bgc.genome_id,
            assembly_accession=bgc.genome.assembly_accession if bgc.genome else None,
            organism_name=bgc.genome.organism_name if bgc.genome else None,
            is_type_strain=bgc.genome.is_type_strain if bgc.genome else False,
        )
        for bgc in page_qs
    ]

    return PaginatedQueryResultResponse(
        items=items,
        pagination=PaginationMeta(page=pg, page_size=ps, total_count=total_count, total_pages=tp),
    )


@discovery_router.post(
    "/query/similar-bgc/{bgc_id}/", response=PaginatedQueryResultResponse
)
def similar_bgc_query(
    request,
    bgc_id: int,
    page: int = 1,
    page_size: int = 25,
    max_distance: float = 0.5,
    weights: QueryWeightParams = Query(...),
):
    try:
        source_emb = BgcEmbedding.objects.get(bgc_id=bgc_id)
    except BgcEmbedding.DoesNotExist:
        raise HttpError(400, "Source BGC has no embedding")

    # ANN search on the lean embedding table
    emb_qs = (
        BgcEmbedding.objects.exclude(bgc_id=bgc_id)
        .annotate(distance=CosineDistance("vector", source_emb.vector))
        .filter(distance__lte=max_distance)
        .order_by("distance")
        .select_related("bgc__genome")
    )

    # Materialize similarity scores and compute relevance
    results = []
    for emb in emb_qs:
        bgc = emb.bgc
        similarity = 1.0 - float(emb.distance)
        relevance = compute_composite_priority(
            scores={
                "similarity": similarity,
                "novelty": bgc.novelty_score,
                "completeness": 0.0 if bgc.is_partial else 1.0,
                "domain_novelty": bgc.domain_novelty,
            },
            weights={
                "similarity": weights.w_similarity,
                "novelty": weights.w_novelty,
                "completeness": weights.w_completeness,
                "domain_novelty": weights.w_domain_novelty,
            },
        )
        results.append((bgc, relevance))

    results.sort(key=lambda x: x[1], reverse=True)
    total_count = len(results)
    pg, ps, tp, offset = _paginate(page, page_size, total_count)
    page_results = results[offset: offset + ps]

    items = [
        QueryResultBgc(
            id=bgc.id,
            accession=bgc.bgc_accession,
            classification_l1=bgc.classification_l1,
            classification_l2=bgc.classification_l2 or None,
            size_kb=bgc.size_kb,
            novelty_score=bgc.novelty_score,
            domain_novelty=bgc.domain_novelty,
            is_partial=bgc.is_partial,
            relevance_score=round(relevance, 4),
            genome_id=bgc.genome_id,
            assembly_accession=bgc.genome.assembly_accession if bgc.genome else None,
            organism_name=bgc.genome.organism_name if bgc.genome else None,
            is_type_strain=bgc.genome.is_type_strain if bgc.genome else False,
        )
        for bgc, relevance in page_results
    ]

    return PaginatedQueryResultResponse(
        items=items,
        pagination=PaginationMeta(page=pg, page_size=ps, total_count=total_count, total_pages=tp),
    )


@discovery_router.post("/query/chemical/", response=PaginatedQueryResultResponse)
def chemical_query(
    request,
    body: ChemicalQueryRequest,
    page: int = 1,
    page_size: int = 25,
    search: Optional[str] = None,
    taxonomy_kingdom: Optional[str] = None,
    taxonomy_phylum: Optional[str] = None,
    taxonomy_class: Optional[str] = None,
    taxonomy_order: Optional[str] = None,
    taxonomy_family: Optional[str] = None,
    taxonomy_genus: Optional[str] = None,
    type_strain_only: bool = False,
    bgc_class: Optional[str] = None,
    biome_lineage: Optional[str] = None,
    assembly_accession: Optional[str] = None,
    bgc_accession: Optional[str] = None,
    weights: QueryWeightParams = Query(...),
):
    if not body.smiles or not body.smiles.strip():
        raise HttpError(400, "SMILES string is required")

    try:
        from rdkit import Chem
        from rdkit.Chem import AllChem, DataStructs
    except ImportError:
        raise HttpError(500, "RDKit is not available")

    query_mol = Chem.MolFromSmiles(body.smiles.strip())
    if query_mol is None:
        raise HttpError(400, "Invalid SMILES string")

    query_fp = AllChem.GetMorganFingerprintAsBitVect(query_mol, 2, nBits=2048)

    # Tanimoto similarity against DashboardNaturalProduct
    bgc_similarities: dict[int, float] = {}
    for np_obj in DashboardNaturalProduct.objects.filter(bgc__isnull=False).only(
        "bgc_id", "smiles"
    ):
        if not np_obj.smiles:
            continue
        try:
            mol = Chem.MolFromSmiles(np_obj.smiles)
            if mol is None:
                continue
            fp = AllChem.GetMorganFingerprintAsBitVect(mol, 2, nBits=2048)
            similarity = DataStructs.TanimotoSimilarity(query_fp, fp)
            if similarity >= body.similarity_threshold:
                existing = bgc_similarities.get(np_obj.bgc_id, 0.0)
                bgc_similarities[np_obj.bgc_id] = max(existing, similarity)
        except Exception:
            continue

    if not bgc_similarities:
        return PaginatedQueryResultResponse(
            items=[],
            pagination=PaginationMeta(page=1, page_size=page_size, total_count=0, total_pages=0),
        )

    qs = DashboardBgc.objects.filter(id__in=bgc_similarities.keys()).select_related("genome")

    # Sidebar filters
    if type_strain_only:
        qs = qs.filter(genome__is_type_strain=True)
    if taxonomy_kingdom:
        qs = qs.filter(genome__taxonomy_kingdom__iexact=taxonomy_kingdom)
    if taxonomy_phylum:
        qs = qs.filter(genome__taxonomy_phylum__iexact=taxonomy_phylum)
    if taxonomy_class:
        qs = qs.filter(genome__taxonomy_class__iexact=taxonomy_class)
    if taxonomy_order:
        qs = qs.filter(genome__taxonomy_order__iexact=taxonomy_order)
    if taxonomy_family:
        qs = qs.filter(genome__taxonomy_family__iexact=taxonomy_family)
    if taxonomy_genus:
        qs = qs.filter(genome__taxonomy_genus__iexact=taxonomy_genus)
    if search:
        qs = qs.filter(
            Q(genome__organism_name__icontains=search)
            | Q(genome__assembly_accession__icontains=search)
        )
    if bgc_class:
        qs = qs.filter(classification_l1__iexact=bgc_class)
    if biome_lineage:
        qs = qs.filter(genome__biome_path__icontains=biome_lineage)
    if assembly_accession:
        qs = qs.filter(genome__assembly_accession__icontains=assembly_accession)
    if bgc_accession:
        qs = qs.filter(bgc_accession__icontains=bgc_accession.strip())

    results = []
    for bgc in qs:
        similarity = bgc_similarities.get(bgc.id, 0.0)
        relevance = compute_composite_priority(
            scores={
                "similarity": similarity,
                "novelty": bgc.novelty_score,
                "completeness": 0.0 if bgc.is_partial else 1.0,
                "domain_novelty": bgc.domain_novelty,
            },
            weights={
                "similarity": weights.w_similarity,
                "novelty": weights.w_novelty,
                "completeness": weights.w_completeness,
                "domain_novelty": weights.w_domain_novelty,
            },
        )
        results.append((bgc, relevance))

    results.sort(key=lambda x: x[1], reverse=True)
    total_count = len(results)
    pg, ps, tp, offset = _paginate(page, page_size, total_count)
    page_results = results[offset: offset + ps]

    items = [
        QueryResultBgc(
            id=bgc.id,
            accession=bgc.bgc_accession,
            classification_l1=bgc.classification_l1,
            classification_l2=bgc.classification_l2 or None,
            size_kb=bgc.size_kb,
            novelty_score=bgc.novelty_score,
            domain_novelty=bgc.domain_novelty,
            is_partial=bgc.is_partial,
            relevance_score=round(relevance, 4),
            genome_id=bgc.genome_id,
            assembly_accession=bgc.genome.assembly_accession if bgc.genome else None,
            organism_name=bgc.genome.organism_name if bgc.genome else None,
            is_type_strain=bgc.genome.is_type_strain if bgc.genome else False,
        )
        for bgc, relevance in page_results
    ]

    return PaginatedQueryResultResponse(
        items=items,
        pagination=PaginationMeta(page=pg, page_size=ps, total_count=total_count, total_pages=tp),
    )


@discovery_router.get(
    "/query-results/genomes/", response=PaginatedGenomeAggregationResponse
)
def query_results_genome_aggregation(
    request,
    bgc_ids: str,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "max_relevance",
    order: str = "desc",
):
    ids = [int(x) for x in bgc_ids.split(",") if x.strip().isdigit()]
    if not ids:
        return PaginatedGenomeAggregationResponse(
            items=[],
            pagination=PaginationMeta(page=1, page_size=page_size, total_count=0, total_pages=0),
        )

    # SQL aggregation instead of Python grouping
    genome_agg = (
        DashboardBgc.objects.filter(id__in=ids)
        .values(
            "genome__id",
            "genome__assembly_accession",
            "genome__organism_name",
            "genome__taxonomy_family",
            "genome__is_type_strain",
        )
        .annotate(
            hit_count=Count("id"),
            max_relevance=Max("novelty_score"),
            mean_relevance=Avg("novelty_score"),
            complete_fraction=Avg(
                Case(
                    When(is_partial=False, then=1.0),
                    default=0.0,
                    output_field=FloatField(),
                )
            ),
        )
    )

    # Sort
    sort_map = {
        "max_relevance": "max_relevance",
        "mean_relevance": "mean_relevance",
        "hit_count": "hit_count",
        "complete_fraction": "complete_fraction",
    }
    order_field = sort_map.get(sort_by, "max_relevance")
    prefix = "-" if order == "desc" else ""
    genome_agg = genome_agg.order_by(f"{prefix}{order_field}")

    total_count = genome_agg.count()
    pg, ps, tp, offset = _paginate(page, page_size, total_count)
    page_agg = genome_agg[offset: offset + ps]

    items = [
        QueryResultGenomeAggregation(
            genome_id=row["genome__id"],
            accession=row["genome__assembly_accession"],
            organism_name=row["genome__organism_name"],
            taxonomy_family=row["genome__taxonomy_family"],
            is_type_strain=row["genome__is_type_strain"],
            hit_count=row["hit_count"],
            max_relevance=round(row["max_relevance"] or 0.0, 4),
            mean_relevance=round(row["mean_relevance"] or 0.0, 4),
            complete_fraction=round(row["complete_fraction"] or 0.0, 4),
        )
        for row in page_agg
    ]

    return PaginatedGenomeAggregationResponse(
        items=items,
        pagination=PaginationMeta(page=pg, page_size=ps, total_count=total_count, total_pages=tp),
    )


# ── Filter endpoints ─────────────────────────────────────────────────────────


@discovery_router.get("/filters/taxonomy/", response=list[TaxonomyNode])
def taxonomy_tree(request):
    qs = DashboardGenome.objects.values(
        "taxonomy_kingdom",
        "taxonomy_phylum",
        "taxonomy_class",
        "taxonomy_order",
        "taxonomy_family",
        "taxonomy_genus",
    )

    tree: dict = {}
    for row in qs:
        ranks = [
            ("kingdom", row["taxonomy_kingdom"]),
            ("phylum", row["taxonomy_phylum"]),
            ("class", row["taxonomy_class"]),
            ("order", row["taxonomy_order"]),
            ("family", row["taxonomy_family"]),
            ("genus", row["taxonomy_genus"]),
        ]
        node = tree
        for rank, name in ranks:
            if not name:
                break
            if name not in node:
                node[name] = {"_rank": rank, "_count": 0, "_children": {}}
            node[name]["_count"] += 1
            node = node[name]["_children"]

    def _build_nodes(level: dict) -> list[TaxonomyNode]:
        nodes = []
        for name, data in sorted(level.items()):
            if name.startswith("_"):
                continue
            nodes.append(
                TaxonomyNode(
                    name=name,
                    rank=data["_rank"],
                    count=data["_count"],
                    children=_build_nodes(data["_children"]),
                )
            )
        return nodes

    return _build_nodes(tree)


@discovery_router.get("/filters/bgc-classes/", response=list[BgcClassOption])
def bgc_classes(request):
    return [
        BgcClassOption(name=row.name, count=row.bgc_count)
        for row in DashboardBgcClass.objects.filter(bgc_count__gt=0).order_by("-bgc_count")
    ]


@discovery_router.get("/filters/np-classes/", response=list[NpClassLevel])
def np_classes(request):
    qs = (
        DashboardNaturalProduct.objects.values(
            "chemical_class_l1", "chemical_class_l2", "chemical_class_l3"
        )
        .annotate(count=Count("id"))
    )

    tree: dict = {}
    for row in qs:
        l1 = row["chemical_class_l1"]
        l2 = row["chemical_class_l2"]
        l3 = row["chemical_class_l3"]
        cnt = row["count"]

        if not l1:
            continue
        if l1 not in tree:
            tree[l1] = {"count": 0, "children": {}}
        tree[l1]["count"] += cnt

        if l2:
            if l2 not in tree[l1]["children"]:
                tree[l1]["children"][l2] = {"count": 0, "children": {}}
            tree[l1]["children"][l2]["count"] += cnt

            if l3:
                if l3 not in tree[l1]["children"][l2]["children"]:
                    tree[l1]["children"][l2]["children"][l3] = {"count": 0, "children": {}}
                tree[l1]["children"][l2]["children"][l3]["count"] += cnt

    def _build(level: dict) -> list[NpClassLevel]:
        return [
            NpClassLevel(
                name=name,
                count=data["count"],
                children=_build(data["children"]),
            )
            for name, data in sorted(level.items())
        ]

    return _build(tree)


@discovery_router.get("/filters/domains/", response=PaginatedDomainResponse)
def domain_list(
    request,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
):
    qs = DashboardDomain.objects.filter(bgc_count__gt=0)

    if search:
        qs = qs.filter(
            Q(acc__icontains=search)
            | Q(name__icontains=search)
            | Q(description__icontains=search)
        )

    total_count = qs.count()
    pg, ps, tp, offset = _paginate(page, page_size, total_count)

    items = [
        DomainOption(
            acc=d.acc,
            name=d.name,
            description=d.description,
            count=d.bgc_count,
        )
        for d in qs.order_by("-bgc_count")[offset: offset + ps]
    ]

    return PaginatedDomainResponse(
        items=items,
        pagination=PaginationMeta(page=pg, page_size=ps, total_count=total_count, total_pages=tp),
    )


# ── Stats endpoints ──────────────────────────────────────────────────────────


@discovery_router.get("/stats/genomes/", response=GenomeStatsResponse)
def genome_stats(
    request,
    search: Optional[str] = None,
    taxonomy_kingdom: Optional[str] = None,
    taxonomy_phylum: Optional[str] = None,
    taxonomy_class: Optional[str] = None,
    taxonomy_order: Optional[str] = None,
    taxonomy_family: Optional[str] = None,
    taxonomy_genus: Optional[str] = None,
    type_strain_only: bool = False,
    bgc_class: Optional[str] = None,
    biome_lineage: Optional[str] = None,
    bgc_accession: Optional[str] = None,
    assembly_accession: Optional[str] = None,
    assembly_ids: Optional[str] = None,
):
    qs = DashboardGenome.objects.all()
    qs = _apply_genome_filters(
        qs,
        genome_ids=assembly_ids,
        type_strain_only=type_strain_only,
        taxonomy_kingdom=taxonomy_kingdom,
        taxonomy_phylum=taxonomy_phylum,
        taxonomy_class=taxonomy_class,
        taxonomy_order=taxonomy_order,
        taxonomy_family=taxonomy_family,
        taxonomy_genus=taxonomy_genus,
        search=search,
        bgc_class=bgc_class,
        biome_lineage=biome_lineage,
        bgc_accession=bgc_accession,
        assembly_accession=assembly_accession,
    )
    return compute_genome_stats(qs)


@discovery_router.get("/stats/bgcs/", response=BgcStatsResponse)
def bgc_stats(
    request,
    assembly_ids: Optional[str] = None,
    bgc_ids: Optional[str] = None,
):
    qs = DashboardBgc.objects.all()
    if bgc_ids:
        ids = [int(x) for x in bgc_ids.split(",") if x.strip().isdigit()]
        qs = qs.filter(id__in=ids) if ids else qs.none()
    else:
        qs = _apply_bgc_filters(qs, genome_ids=assembly_ids)
    return compute_bgc_stats(qs)


@discovery_router.get("/stats/genomes/export/")
def genome_stats_export(
    request,
    format: str = "json",
    search: Optional[str] = None,
    taxonomy_kingdom: Optional[str] = None,
    taxonomy_phylum: Optional[str] = None,
    taxonomy_class: Optional[str] = None,
    taxonomy_order: Optional[str] = None,
    taxonomy_family: Optional[str] = None,
    taxonomy_genus: Optional[str] = None,
    type_strain_only: bool = False,
    bgc_class: Optional[str] = None,
    biome_lineage: Optional[str] = None,
    bgc_accession: Optional[str] = None,
    assembly_accession: Optional[str] = None,
    assembly_ids: Optional[str] = None,
):
    qs = DashboardGenome.objects.all()
    qs = _apply_genome_filters(
        qs,
        genome_ids=assembly_ids,
        type_strain_only=type_strain_only,
        taxonomy_kingdom=taxonomy_kingdom,
        taxonomy_phylum=taxonomy_phylum,
        taxonomy_class=taxonomy_class,
        taxonomy_order=taxonomy_order,
        taxonomy_family=taxonomy_family,
        taxonomy_genus=taxonomy_genus,
        search=search,
        bgc_class=bgc_class,
        biome_lineage=biome_lineage,
        bgc_accession=bgc_accession,
        assembly_accession=assembly_accession,
    )
    stats = compute_genome_stats(qs)

    if format == "tsv":
        return _stats_to_tsv_response(stats, "genome_stats.tsv")

    response = HttpResponse(
        json.dumps(stats, default=str),
        content_type="application/json",
    )
    response["Content-Disposition"] = 'attachment; filename="genome_stats.json"'
    return response


@discovery_router.get("/stats/bgcs/export/")
def bgc_stats_export(
    request,
    format: str = "json",
    assembly_ids: Optional[str] = None,
    bgc_ids: Optional[str] = None,
):
    qs = DashboardBgc.objects.all()
    if bgc_ids:
        ids = [int(x) for x in bgc_ids.split(",") if x.strip().isdigit()]
        qs = qs.filter(id__in=ids) if ids else qs.none()
    else:
        qs = _apply_bgc_filters(qs, genome_ids=assembly_ids)
    stats = compute_bgc_stats(qs)

    if format == "tsv":
        return _stats_to_tsv_response(stats, "bgc_stats.tsv")

    response = HttpResponse(
        json.dumps(stats, default=str),
        content_type="application/json",
    )
    response["Content-Disposition"] = 'attachment; filename="bgc_stats.json"'
    return response


def _stats_to_tsv_response(stats: dict, filename: str) -> HttpResponse:
    buf = StringIO()
    writer = csv.writer(buf, delimiter="\t")
    writer.writerow(["section", "key", "value"])

    for key, value in stats.items():
        if isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    for k, v in item.items():
                        writer.writerow([key, f"{i}.{k}", v])
                else:
                    writer.writerow([key, str(i), item])
        else:
            writer.writerow(["summary", key, value])

    response = HttpResponse(buf.getvalue(), content_type="text/tab-separated-values")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ── Export endpoints ─────────────────────────────────────────────────────────


@discovery_router.post("/shortlist/genome/export/")
def export_genome_shortlist(request, body: ShortlistExportRequest):
    if not body.ids:
        raise HttpError(400, "No genome IDs provided")
    if len(body.ids) > 20:
        raise HttpError(400, "Maximum 20 genomes per export")

    genomes = DashboardGenome.objects.filter(id__in=body.ids)

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "accession", "organism_name",
        "taxonomy_kingdom", "taxonomy_phylum", "taxonomy_class",
        "taxonomy_order", "taxonomy_family", "taxonomy_genus", "taxonomy_species",
        "is_type_strain", "type_strain_catalog_url",
        "genome_size_mb", "genome_quality", "isolation_source",
        "bgc_count", "l1_class_count",
        "bgc_diversity_score", "bgc_novelty_score", "bgc_density", "taxonomic_novelty",
    ])

    for g in genomes:
        writer.writerow([
            g.assembly_accession,
            g.organism_name,
            g.taxonomy_kingdom, g.taxonomy_phylum, g.taxonomy_class,
            g.taxonomy_order, g.taxonomy_family, g.taxonomy_genus, g.taxonomy_species,
            g.is_type_strain, g.type_strain_catalog_url,
            g.genome_size_mb or "", g.genome_quality or "", g.isolation_source,
            g.bgc_count, g.l1_class_count,
            g.bgc_diversity_score, g.bgc_novelty_score, g.bgc_density, g.taxonomic_novelty,
        ])

    response = HttpResponse(buf.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="genome_shortlist.csv"'
    return response


@discovery_router.post("/shortlist/bgc/export/")
def export_bgc_shortlist(request, body: ShortlistExportRequest):
    """Export BGC shortlist as CSV with scores and classification."""
    if not body.ids:
        raise HttpError(400, "No BGC IDs provided")
    if len(body.ids) > 20:
        raise HttpError(400, "Maximum 20 BGCs per export")

    bgcs = DashboardBgc.objects.filter(id__in=body.ids).select_related("genome")

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "bgc_accession", "classification_l1", "classification_l2", "classification_l3",
        "size_kb", "novelty_score", "domain_novelty", "is_partial",
        "nearest_mibig_accession", "nearest_mibig_distance",
        "umap_x", "umap_y",
        "assembly_accession", "organism_name", "taxonomy_family",
        "contig_accession", "start_position", "end_position",
    ])

    for bgc in bgcs:
        genome = bgc.genome
        writer.writerow([
            bgc.bgc_accession,
            bgc.classification_l1, bgc.classification_l2, bgc.classification_l3,
            bgc.size_kb, bgc.novelty_score, bgc.domain_novelty, bgc.is_partial,
            bgc.nearest_mibig_accession, bgc.nearest_mibig_distance,
            bgc.umap_x, bgc.umap_y,
            genome.assembly_accession if genome else "",
            genome.organism_name if genome else "",
            genome.taxonomy_family if genome else "",
            bgc.contig_accession, bgc.start_position, bgc.end_position,
        ])

    response = HttpResponse(buf.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="bgc_shortlist.csv"'
    return response


# ── Assessment endpoints ─────────────────────────────────────────────────────


@discovery_router.post(
    "/assess/genome/{genome_id}/",
    response={202: AssessmentAccepted},
    tags=["Assessment"],
)
def assess_genome(request, genome_id: int, body: GenomeWeightParams = None):
    if not DashboardGenome.objects.filter(pk=genome_id).exists():
        raise HttpError(404, "Genome not found")

    weights = {
        "w_diversity": body.w_diversity if body else 0.30,
        "w_novelty": body.w_novelty if body else 0.45,
        "w_density": body.w_density if body else 0.25,
    }

    from discovery.tasks import assess_genome as assess_genome_task

    result = assess_genome_task.delay(genome_id, weights)
    return 202, AssessmentAccepted(task_id=result.id, asset_type="genome")


@discovery_router.post(
    "/assess/bgc/{bgc_id}/",
    response={202: AssessmentAccepted},
    tags=["Assessment"],
)
def assess_bgc(request, bgc_id: int):
    if not DashboardBgc.objects.filter(pk=bgc_id).exists():
        raise HttpError(404, "BGC not found")

    from discovery.tasks import assess_bgc as assess_bgc_task

    result = assess_bgc_task.delay(bgc_id)
    return 202, AssessmentAccepted(task_id=result.id, asset_type="bgc")


@discovery_router.get(
    "/assess/status/{task_id}/",
    response=AssessmentStatusResponse,
    tags=["Assessment"],
)
def assess_status(request, task_id: str):
    from discovery.cache_utils import get_job_status

    status_data = get_job_status(task_id=task_id)
    return AssessmentStatusResponse(
        status=status_data.get("status", "UNKNOWN"),
        result=status_data.get("result"),
    )


@discovery_router.get(
    "/assess/genome/{genome_id}/similar-genomes/",
    response=list[int],
    tags=["Assessment"],
)
def similar_genomes(request, genome_id: int):
    if not DashboardGenome.objects.filter(pk=genome_id).exists():
        raise HttpError(404, "Genome not found")

    from discovery.services.assessment import find_similar_genomes

    return find_similar_genomes(genome_id, k=10)


@discovery_router.get(
    "/assess/export/{task_id}/",
    tags=["Assessment"],
)
def export_assessment(request, task_id: str):
    from discovery.cache_utils import get_job_status

    status_data = get_job_status(task_id=task_id)
    if status_data.get("status") != "SUCCESS":
        raise HttpError(404, "Assessment not found or not yet complete")

    result = status_data.get("result", {})
    content = json.dumps(result, indent=2, default=str)
    response = HttpResponse(content, content_type="application/json")
    response["Content-Disposition"] = f'attachment; filename="assessment_{task_id[:8]}.json"'
    return response
