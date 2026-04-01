"""Discovery Platform API — Django Ninja Router.

Mounted on the main NinjaAPI at /api/dashboard/.
"""

import csv
import json
import math
from io import StringIO
from typing import Optional

from django.db.models import Q, Count, Avg, Max, F, Value, FloatField
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from ninja import Router, Query
from ninja.errors import HttpError

from django.db.models import Prefetch

from mgnify_bgcs.models import (
    Assembly,
    Bgc,
    BgcClass,
    Cds,
    Domain,
    ProteinDomain,
)
from mgnify_bgcs.services.pfam_to_slim.pfam_annots import pfamToGoSlim
from discovery.models import (
    BgcScore,
    GCFMembership,
    GenomeScore,
    MibigReference,
    NaturalProduct,
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


# ── Helpers ───────────────────────────────────────────────────────────────────


def _paginate(page: int, page_size: int, total_count: int):
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    total_pages = max(1, math.ceil(total_count / page_size))
    offset = (page - 1) * page_size
    return page, page_size, total_pages, offset


def _genome_composite(gs: GenomeScore, weights: GenomeWeightParams) -> float:
    return compute_composite_priority(
        scores={
            "diversity": gs.bgc_diversity_score,
            "novelty": gs.bgc_novelty_score,
            "density": gs.bgc_density,
        },
        weights={
            "diversity": weights.w_diversity,
            "novelty": weights.w_novelty,
            "density": weights.w_density,
        },
    )


def _assembly_to_roster_item(assembly: Assembly, composite: float) -> GenomeRosterItem:
    gs = getattr(assembly, "genome_score", None)
    return GenomeRosterItem(
        id=assembly.id,
        accession=assembly.accession,
        organism_name=assembly.organism_name,
        taxonomy_kingdom=assembly.taxonomy_kingdom,
        taxonomy_phylum=assembly.taxonomy_phylum,
        taxonomy_class=assembly.taxonomy_class,
        taxonomy_order=assembly.taxonomy_order,
        taxonomy_family=assembly.taxonomy_family,
        taxonomy_genus=assembly.taxonomy_genus,
        taxonomy_species=assembly.taxonomy_species,
        is_type_strain=assembly.is_type_strain,
        type_strain_catalog_url=assembly.type_strain_catalog_url,
        bgc_count=gs.bgc_count if gs else 0,
        l1_class_count=gs.l1_class_count if gs else 0,
        bgc_diversity_score=gs.bgc_diversity_score if gs else 0.0,
        bgc_novelty_score=gs.bgc_novelty_score if gs else 0.0,
        bgc_density=gs.bgc_density if gs else 0.0,
        taxonomic_novelty=gs.taxonomic_novelty if gs else 0.0,
        genome_quality=gs.genome_quality if gs else 0.0,
        composite_score=composite,
    )


# ── Shared filter helpers ────────────────────────────────────────────────────


def _apply_genome_filters(
    qs,
    *,
    assembly_ids: Optional[str] = None,
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
    """Apply common genome/assembly filters to a queryset."""
    if assembly_ids:
        ids = [int(x) for x in assembly_ids.split(",") if x.strip().isdigit()]
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
            | Q(accession__icontains=search)
        )
    if bgc_class:
        qs = qs.filter(contigs__bgcs__classes__name__iexact=bgc_class).distinct()
    if biome_lineage:
        qs = qs.filter(biome__lineage__icontains=biome_lineage)
    if bgc_accession:
        bgc_accession = bgc_accession.strip()
        if bgc_accession.upper().startswith("MGYB"):
            try:
                bgc_pk = int(bgc_accession[4:])
                qs = qs.filter(contigs__bgcs__id=bgc_pk).distinct()
            except ValueError:
                pass
        else:
            qs = qs.filter(
                contigs__bgcs__identifier__icontains=bgc_accession
            ).distinct()
    if assembly_accession:
        qs = qs.filter(accession__icontains=assembly_accession)
    return qs


def _apply_bgc_filters(qs, *, assembly_ids: Optional[str] = None):
    """Apply common BGC filters to a queryset."""
    if assembly_ids:
        ids = [int(x) for x in assembly_ids.split(",") if x.strip().isdigit()]
        if ids:
            qs = qs.filter(contig__assembly_id__in=ids)
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
    qs = Assembly.objects.select_related("genome_score").filter(
        genome_score__isnull=False
    )
    qs = _apply_genome_filters(
        qs,
        assembly_ids=assembly_ids,
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

    # Materialize with composite scores
    assemblies = list(qs)
    results = []
    for assembly in assemblies:
        gs = assembly.genome_score
        composite = _genome_composite(gs, weights)
        results.append((assembly, composite))

    # Sort
    score_fields = {
        "composite_score", "bgc_count", "bgc_diversity_score",
        "bgc_novelty_score", "bgc_density", "taxonomic_novelty", "genome_quality",
        "l1_class_count",
    }
    reverse = order == "desc"

    if sort_by == "composite_score":
        results.sort(key=lambda x: x[1], reverse=reverse)
    elif sort_by in score_fields:
        results.sort(
            key=lambda x: getattr(x[0].genome_score, sort_by, 0),
            reverse=reverse,
        )
    elif sort_by == "organism_name":
        results.sort(key=lambda x: (x[0].organism_name or ""), reverse=reverse)
    else:
        results.sort(key=lambda x: x[1], reverse=True)

    total_count = len(results)
    page, page_size, total_pages, offset = _paginate(page, page_size, total_count)
    page_results = results[offset : offset + page_size]

    items = [_assembly_to_roster_item(a, c) for a, c in page_results]

    return PaginatedGenomeResponse(
        items=items,
        pagination=PaginationMeta(
            page=page,
            page_size=page_size,
            total_count=total_count,
            total_pages=total_pages,
        ),
    )


@discovery_router.get("/genomes/{assembly_id}/", response=GenomeDetail)
def genome_detail(request, assembly_id: int, weights: GenomeWeightParams = Query(...)):
    try:
        assembly = Assembly.objects.select_related("genome_score").get(id=assembly_id)
    except Assembly.DoesNotExist:
        raise HttpError(404, "Assembly not found")

    gs = getattr(assembly, "genome_score", None)
    composite = _genome_composite(gs, weights) if gs else 0.0

    return GenomeDetail(
        id=assembly.id,
        accession=assembly.accession,
        organism_name=assembly.organism_name,
        taxonomy_kingdom=assembly.taxonomy_kingdom,
        taxonomy_phylum=assembly.taxonomy_phylum,
        taxonomy_class=assembly.taxonomy_class,
        taxonomy_order=assembly.taxonomy_order,
        taxonomy_family=assembly.taxonomy_family,
        taxonomy_genus=assembly.taxonomy_genus,
        taxonomy_species=assembly.taxonomy_species,
        is_type_strain=assembly.is_type_strain,
        type_strain_catalog_url=assembly.type_strain_catalog_url,
        genome_size_mb=assembly.genome_size_mb,
        genome_quality=assembly.genome_quality,
        isolation_source=assembly.isolation_source,
        bgc_count=gs.bgc_count if gs else 0,
        l1_class_count=gs.l1_class_count if gs else 0,
        bgc_diversity_score=gs.bgc_diversity_score if gs else 0.0,
        bgc_novelty_score=gs.bgc_novelty_score if gs else 0.0,
        bgc_density=gs.bgc_density if gs else 0.0,
        taxonomic_novelty=gs.taxonomic_novelty if gs else 0.0,
        composite_score=composite,
    )


@discovery_router.get("/genomes/{assembly_id}/bgcs/", response=list[BgcRosterItem])
def genome_bgc_roster(request, assembly_id: int):
    bgcs = (
        Bgc.objects.filter(contig__assembly_id=assembly_id)
        .select_related("bgc_score")
        .order_by("-bgc_score__novelty_score")
    )

    items = []
    for bgc in bgcs:
        bs = getattr(bgc, "bgc_score", None)
        items.append(
            BgcRosterItem(
                id=bgc.id,
                accession=bgc.accession,
                classification_l1=bs.classification_l1 if bs else "",
                classification_l2=bs.classification_l2 if bs else None,
                classification_l3=bs.classification_l3 if bs else None,
                size_kb=bs.size_kb if bs else 0.0,
                novelty_score=bs.novelty_score if bs else 0.0,
                domain_novelty=bs.domain_novelty if bs else 0.0,
                is_partial=bgc.is_partial,
                nearest_mibig_accession=bs.nearest_mibig_accession if bs else None,
                nearest_mibig_distance=bs.nearest_mibig_distance if bs else None,
            )
        )
    return items


@discovery_router.get("/bgcs/roster/", response=PaginatedBgcRosterResponse)
def bgc_roster(
    request,
    assembly_ids: Optional[str] = None,
    sort_by: str = "novelty_score",
    order: str = "desc",
    page: int = 1,
    page_size: int = 25,
):
    """Paginated BGC roster filtered by assembly IDs, with sorting."""
    qs = (
        Bgc.objects.filter(bgc_score__isnull=False)
        .select_related("bgc_score", "contig__assembly")
    )
    qs = _apply_bgc_filters(qs, assembly_ids=assembly_ids)

    # Sorting
    sort_map = {
        "novelty_score": "bgc_score__novelty_score",
        "size_kb": "bgc_score__size_kb",
        "domain_novelty": "bgc_score__domain_novelty",
        "classification_l1": "bgc_score__classification_l1",
        "accession": "id",  # accession is derived from id
    }
    order_field = sort_map.get(sort_by, "bgc_score__novelty_score")
    if order == "asc":
        qs = qs.order_by(order_field)
    else:
        qs = qs.order_by(f"-{order_field}")

    total_count = qs.count()
    pg, ps, tp, offset = _paginate(page, page_size, total_count)
    page_qs = qs[offset : offset + ps]

    items = []
    for bgc in page_qs:
        bs = bgc.bgc_score
        assembly = bgc.contig.assembly if bgc.contig else None
        items.append(
            BgcRosterItem(
                id=bgc.id,
                accession=bgc.accession,
                classification_l1=bs.classification_l1 if bs else "",
                classification_l2=bs.classification_l2 if bs else None,
                classification_l3=bs.classification_l3 if bs else None,
                size_kb=bs.size_kb if bs else 0.0,
                novelty_score=bs.novelty_score if bs else 0.0,
                domain_novelty=bs.domain_novelty if bs else 0.0,
                is_partial=bgc.is_partial,
                nearest_mibig_accession=bs.nearest_mibig_accession if bs else None,
                nearest_mibig_distance=bs.nearest_mibig_distance if bs else None,
                assembly_accession=assembly.accession if assembly else None,
            )
        )

    return PaginatedBgcRosterResponse(
        items=items,
        pagination=PaginationMeta(
            page=pg, page_size=ps, total_count=total_count, total_pages=tp
        ),
    )


@discovery_router.get("/bgcs/parent-assemblies/", response=list[int])
def bgc_parent_assemblies(request, bgc_ids: str):
    """Return unique parent assembly IDs for the given BGC IDs."""
    ids = [int(x) for x in bgc_ids.split(",") if x.strip().isdigit()]
    if not ids:
        return []
    assembly_ids = (
        Bgc.objects.filter(id__in=ids, contig__assembly__isnull=False)
        .values_list("contig__assembly_id", flat=True)
        .distinct()
    )
    return list(assembly_ids)


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
        "bgc_diversity_score",
        "bgc_novelty_score",
        "bgc_density",
        "taxonomic_novelty",
        "genome_quality",
    }
    if x_axis not in allowed_axes or y_axis not in allowed_axes:
        raise HttpError(400, f"Axis must be one of: {', '.join(sorted(allowed_axes))}")

    qs = Assembly.objects.select_related("genome_score").filter(
        genome_score__isnull=False
    )
    if assembly_ids:
        ids = [int(x) for x in assembly_ids.split(",") if x.strip().isdigit()]
        if ids:
            qs = qs.filter(id__in=ids)
    if type_strain_only:
        qs = qs.filter(is_type_strain=True)
    if taxonomy_family:
        qs = qs.filter(taxonomy_family__iexact=taxonomy_family)
    if bgc_class:
        qs = qs.filter(contigs__bgcs__classes__name__iexact=bgc_class).distinct()

    points = []
    for assembly in qs:
        gs = assembly.genome_score
        composite = _genome_composite(gs, weights)
        points.append(
            GenomeScatterPoint(
                id=assembly.id,
                x=getattr(gs, x_axis, 0.0),
                y=getattr(gs, y_axis, 0.0),
                composite_score=composite,
                taxonomy_family=assembly.taxonomy_family,
                organism_name=assembly.organism_name,
                is_type_strain=assembly.is_type_strain,
            )
        )
    return points


# ── BGC endpoints ─────────────────────────────────────────────────────────────


@discovery_router.get("/bgcs/{bgc_id}/", response=BgcDetail)
def bgc_detail(request, bgc_id: int):
    try:
        bgc = Bgc.objects.select_related(
            "bgc_score", "contig__assembly"
        ).get(id=bgc_id)
    except Bgc.DoesNotExist:
        raise HttpError(404, "BGC not found")

    bs = getattr(bgc, "bgc_score", None)

    # Build domain architecture
    domain_arch = []
    cds_qs = Cds.objects.filter(
        contig=bgc.contig,
        start_position__gte=bgc.start_position,
        end_position__lte=bgc.end_position,
    ).select_related("protein")

    for cds in cds_qs:
        for pd in ProteinDomain.objects.filter(protein=cds.protein).select_related("domain"):
            domain_arch.append(
                DomainArchitectureItem(
                    domain_acc=pd.domain.acc,
                    domain_name=pd.domain.name,
                    ref_db=pd.domain.ref_db,
                    start=pd.start_position,
                    end=pd.end_position,
                    score=pd.score,
                )
            )

    # Parent genome
    parent = None
    assembly = bgc.contig.assembly if bgc.contig else None
    if assembly:
        parent = ParentGenomeSummary(
            assembly_id=assembly.id,
            accession=assembly.accession,
            organism_name=assembly.organism_name,
            taxonomy_family=assembly.taxonomy_family,
            is_type_strain=assembly.is_type_strain,
            genome_quality=assembly.genome_quality,
            isolation_source=assembly.isolation_source,
        )

    # Natural products
    np_items = []
    for np in NaturalProduct.objects.filter(bgc_id=bgc_id):
        svg = ""
        if not np.structure_svg_base64 and np.smiles:
            try:
                from mgnify_bgcs.services.compound_search_utils import smiles_to_svg
                svg = smiles_to_svg(np.smiles) if np.smiles else ""
            except Exception:
                pass
        np_items.append(
            NaturalProductSummary(
                id=np.id,
                name=np.name,
                smiles=np.smiles,
                smiles_svg=svg,
                structure_thumbnail=np.structure_svg_base64,
                chemical_class_l1=np.chemical_class_l1,
                chemical_class_l2=np.chemical_class_l2,
                chemical_class_l3=np.chemical_class_l3,
            )
        )

    return BgcDetail(
        id=bgc.id,
        accession=bgc.accession,
        classification_l1=bs.classification_l1 if bs else "",
        classification_l2=bs.classification_l2 if bs else None,
        classification_l3=bs.classification_l3 if bs else None,
        size_kb=bs.size_kb if bs else 0.0,
        novelty_score=bs.novelty_score if bs else 0.0,
        domain_novelty=bs.domain_novelty if bs else 0.0,
        is_partial=bgc.is_partial,
        nearest_mibig_accession=bs.nearest_mibig_accession if bs else None,
        nearest_mibig_distance=bs.nearest_mibig_distance if bs else None,
        is_validated=bs.is_validated if bs else False,
        domain_architecture=domain_arch,
        parent_genome=parent,
        natural_products=np_items,
    )


@discovery_router.get("/bgcs/{bgc_id}/region/", response=BgcRegionOut)
def bgc_region(request, bgc_id: int):
    """Return CDS, domain, and cluster data for the BGC genomic region."""
    try:
        bgc = Bgc.objects.select_related("contig", "detector").get(id=bgc_id)
    except Bgc.DoesNotExist:
        raise HttpError(404, "BGC not found")

    if not bgc.contig:
        raise HttpError(404, "BGC has no associated contig")

    extended_window = 2000
    window_start = max(0, bgc.start_position - extended_window)
    window_end = bgc.end_position + extended_window
    region_length = window_end - window_start

    # ── CDS within the window ────────────────────────────────────────────
    pfam_domain_prefetch = Prefetch(
        "protein__proteindomain_set",
        queryset=ProteinDomain.objects.select_related("domain").filter(
            domain__ref_db="Pfam"
        ),
        to_attr="pfam_hits",
    )
    cds_qs = (
        Cds.objects.filter(
            contig=bgc.contig,
            start_position__lte=window_end,
            end_position__gte=window_start,
        )
        .select_related("protein", "gene_caller")
        .prefetch_related(pfam_domain_prefetch)
        .order_by("start_position")
    )

    cds_list = []
    domain_list = []

    for cds in cds_qs:
        protein = cds.protein
        protein_id = (
            protein.mgyp or cds.protein_identifier or str(cds.id)
        )
        rep = protein.cluster_representative
        gene_caller_name = cds.gene_caller.name if cds.gene_caller else ""

        # Build Pfam annotation rows
        pfam_rows = []
        for pd in getattr(protein, "pfam_hits", []):
            domain = pd.domain
            go_slims = pfamToGoSlim.get(domain.acc, [])
            go_slim_str = ";".join(go_slims) if go_slims else ""

            pfam_rows.append(
                PfamAnnotationOut(
                    accession=domain.acc,
                    description=domain.description or domain.name or "",
                    go_slim=go_slim_str,
                    envelope_start=pd.start_position,
                    envelope_end=pd.end_position,
                    e_value=str(pd.score) if pd.score is not None else None,
                )
            )

            # Build RegionDomainOut for the SVG overlay
            # Convert AA positions to nucleotide positions on the contig
            if cds.strand >= 0:
                dom_nt_start = cds.start_position + pd.start_position * 3
                dom_nt_end = cds.start_position + pd.end_position * 3
            else:
                dom_nt_start = cds.end_position - pd.end_position * 3
                dom_nt_end = cds.end_position - pd.start_position * 3

            domain_list.append(
                RegionDomainOut(
                    accession=domain.acc,
                    description=domain.description or domain.name or "",
                    start=max(0, dom_nt_start - window_start),
                    end=max(0, dom_nt_end - window_start),
                    strand=cds.strand,
                    score=pd.score,
                    go_slim=go_slims,
                    parent_cds_id=protein_id,
                )
            )

        cds_list.append(
            RegionCdsOut(
                protein_id=protein_id,
                start=cds.start_position - window_start,
                end=cds.end_position - window_start,
                strand=cds.strand,
                protein_length=len(protein.sequence) if protein.sequence else 0,
                gene_caller=gene_caller_name,
                cluster_representative=rep,
                cluster_representative_url=(
                    f"https://www.ebi.ac.uk/metagenomics/proteins/{rep}/"
                    if rep
                    else None
                ),
                sequence=protein.sequence or "",
                pfam=pfam_rows,
            )
        )

    # ── Overlapping BGC clusters ─────────────────────────────────────────
    cluster_list = []
    overlapping_bgcs = Bgc.objects.filter(
        contig=bgc.contig,
        start_position__lte=window_end,
        end_position__gte=window_start,
    ).select_related("detector").prefetch_related("classes")

    for ob in overlapping_bgcs:
        cluster_list.append(
            RegionClusterOut(
                accession=ob.accession,
                start=max(0, ob.start_position - window_start),
                end=max(0, ob.end_position - window_start),
                source=ob.detector.name if ob.detector else "",
                bgc_classes=[c.name for c in ob.classes.all()],
            )
        )

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
    """UMAP scatter data for BGCs, optionally including MIBiG reference points."""
    qs = Bgc.objects.filter(
        metadata__umap_x_coord__isnull=False,
        bgc_score__isnull=False,
    ).select_related("bgc_score")

    if bgc_class:
        qs = qs.filter(classes__name__iexact=bgc_class)
    if bgc_ids:
        ids = [int(x) for x in bgc_ids.split(",") if x.strip().isdigit()]
        if ids:
            qs = qs.filter(id__in=ids)
    elif assembly_ids:
        ids = [int(x) for x in assembly_ids.split(",") if x.strip().isdigit()]
        if ids:
            qs = qs.filter(contig__assembly_id__in=ids)

    # Sample if too many
    total = qs.count()
    if total > max_points:
        qs = qs.order_by("?")[:max_points]

    points = []
    for bgc in qs:
        meta = bgc.metadata or {}
        bs = bgc.bgc_score
        points.append(
            BgcScatterPoint(
                id=bgc.id,
                umap_x=meta.get("umap_x_coord", 0.0),
                umap_y=meta.get("umap_y_coord", 0.0),
                bgc_class=bs.classification_l1 if bs else "",
                is_mibig=False,
                compound_name=None,
            )
        )

    if include_mibig:
        for ref in MibigReference.objects.all():
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


# ── Query mode endpoints ──────────────────────────────────────────────────────


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
    """Find BGCs by protein domain composition and/or sidebar filters."""
    required = [d.acc for d in body.domains if d.required]
    excluded = [d.acc for d in body.domains if not d.required]

    # Find proteins that have the required domains
    qs = Bgc.objects.select_related("bgc_score", "contig__assembly").filter(
        bgc_score__isnull=False
    )

    # Apply sidebar filters
    if type_strain_only:
        qs = qs.filter(contig__assembly__is_type_strain=True)
    if taxonomy_kingdom:
        qs = qs.filter(contig__assembly__taxonomy_kingdom__iexact=taxonomy_kingdom)
    if taxonomy_phylum:
        qs = qs.filter(contig__assembly__taxonomy_phylum__iexact=taxonomy_phylum)
    if taxonomy_class:
        qs = qs.filter(contig__assembly__taxonomy_class__iexact=taxonomy_class)
    if taxonomy_order:
        qs = qs.filter(contig__assembly__taxonomy_order__iexact=taxonomy_order)
    if taxonomy_family:
        qs = qs.filter(contig__assembly__taxonomy_family__iexact=taxonomy_family)
    if taxonomy_genus:
        qs = qs.filter(contig__assembly__taxonomy_genus__iexact=taxonomy_genus)
    if search:
        qs = qs.filter(
            Q(contig__assembly__organism_name__icontains=search)
            | Q(contig__assembly__accession__icontains=search)
        )
    if bgc_class:
        qs = qs.filter(classes__name__iexact=bgc_class).distinct()
    if biome_lineage:
        qs = qs.filter(contig__assembly__biome__lineage__icontains=biome_lineage)
    if assembly_accession:
        qs = qs.filter(contig__assembly__accession__icontains=assembly_accession)
    if bgc_accession:
        bgc_accession = bgc_accession.strip()
        if bgc_accession.upper().startswith("MGYB"):
            try:
                bgc_pk = int(bgc_accession[4:])
                qs = qs.filter(id=bgc_pk)
            except ValueError:
                pass
        else:
            qs = qs.filter(identifier__icontains=bgc_accession)

    if body.logic == "and" and required:
        # BGC must contain proteins with ALL required domains
        for acc in required:
            qs = qs.filter(
                contig__cds__protein__domains__acc=acc
            )
        qs = qs.distinct()
    elif required:
        # BGC must contain proteins with ANY required domain
        qs = qs.filter(
            contig__cds__protein__domains__acc__in=required
        ).distinct()

    if excluded:
        qs = qs.exclude(
            contig__cds__protein__domains__acc__in=excluded
        )

    # Score and paginate
    results = []
    for bgc in qs:
        bs = bgc.bgc_score
        # Simple relevance: combine novelty and domain novelty
        relevance = compute_composite_priority(
            scores={
                "similarity": 1.0,  # domain match is binary
                "novelty": bs.novelty_score if bs else 0.0,
                "completeness": 0.0 if bgc.is_partial else 1.0,
                "domain_novelty": bs.domain_novelty if bs else 0.0,
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
    page_results = results[offset : offset + ps]

    items = []
    for bgc, relevance in page_results:
        bs = bgc.bgc_score
        assembly = bgc.contig.assembly if bgc.contig else None
        items.append(
            QueryResultBgc(
                id=bgc.id,
                accession=bgc.accession,
                classification_l1=bs.classification_l1 if bs else "",
                classification_l2=bs.classification_l2 if bs else None,
                size_kb=bs.size_kb if bs else 0.0,
                novelty_score=bs.novelty_score if bs else 0.0,
                domain_novelty=bs.domain_novelty if bs else 0.0,
                is_partial=bgc.is_partial,
                relevance_score=round(relevance, 4),
                assembly_id=assembly.id if assembly else None,
                assembly_accession=assembly.accession if assembly else None,
                organism_name=assembly.organism_name if assembly else None,
                is_type_strain=assembly.is_type_strain if assembly else False,
            )
        )

    return PaginatedQueryResultResponse(
        items=items,
        pagination=PaginationMeta(
            page=pg, page_size=ps, total_count=total_count, total_pages=tp
        ),
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
    """Find BGCs similar to a given BGC via embedding distance."""
    try:
        source = Bgc.objects.get(id=bgc_id)
    except Bgc.DoesNotExist:
        raise HttpError(404, "BGC not found")

    if source.embedding is None:
        raise HttpError(400, "Source BGC has no embedding")

    from pgvector.django import CosineDistance

    qs = (
        Bgc.objects.exclude(id=bgc_id)
        .filter(embedding__isnull=False, bgc_score__isnull=False)
        .select_related("bgc_score", "contig__assembly")
        .annotate(distance=CosineDistance("embedding", source.embedding))
        .filter(distance__lte=max_distance)
        .order_by("distance")
    )

    # Compute relevance scores
    results = []
    for bgc in qs:
        bs = bgc.bgc_score
        similarity = 1.0 - bgc.distance
        relevance = compute_composite_priority(
            scores={
                "similarity": similarity,
                "novelty": bs.novelty_score if bs else 0.0,
                "completeness": 0.0 if bgc.is_partial else 1.0,
                "domain_novelty": bs.domain_novelty if bs else 0.0,
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
    page_results = results[offset : offset + ps]

    items = []
    for bgc, relevance in page_results:
        bs = bgc.bgc_score
        assembly = bgc.contig.assembly if bgc.contig else None
        items.append(
            QueryResultBgc(
                id=bgc.id,
                accession=bgc.accession,
                classification_l1=bs.classification_l1 if bs else "",
                classification_l2=bs.classification_l2 if bs else None,
                size_kb=bs.size_kb if bs else 0.0,
                novelty_score=bs.novelty_score if bs else 0.0,
                domain_novelty=bs.domain_novelty if bs else 0.0,
                is_partial=bgc.is_partial,
                relevance_score=round(relevance, 4),
                assembly_id=assembly.id if assembly else None,
                assembly_accession=assembly.accession if assembly else None,
                organism_name=assembly.organism_name if assembly else None,
                is_type_strain=assembly.is_type_strain if assembly else False,
            )
        )

    return PaginatedQueryResultResponse(
        items=items,
        pagination=PaginationMeta(
            page=pg, page_size=ps, total_count=total_count, total_pages=tp
        ),
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
    """Find BGCs by chemical structure similarity using NaturalProduct SMILES."""
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

    # Compute similarities against NaturalProduct SMILES
    bgc_similarities: dict[int, float] = {}
    for np_obj in NaturalProduct.objects.filter(bgc__isnull=False).only(
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

    # Fetch matching BGCs
    qs = (
        Bgc.objects.filter(id__in=bgc_similarities.keys(), bgc_score__isnull=False)
        .select_related("bgc_score", "contig__assembly")
    )

    # Apply sidebar filters
    if type_strain_only:
        qs = qs.filter(contig__assembly__is_type_strain=True)
    if taxonomy_kingdom:
        qs = qs.filter(contig__assembly__taxonomy_kingdom__iexact=taxonomy_kingdom)
    if taxonomy_phylum:
        qs = qs.filter(contig__assembly__taxonomy_phylum__iexact=taxonomy_phylum)
    if taxonomy_class:
        qs = qs.filter(contig__assembly__taxonomy_class__iexact=taxonomy_class)
    if taxonomy_order:
        qs = qs.filter(contig__assembly__taxonomy_order__iexact=taxonomy_order)
    if taxonomy_family:
        qs = qs.filter(contig__assembly__taxonomy_family__iexact=taxonomy_family)
    if taxonomy_genus:
        qs = qs.filter(contig__assembly__taxonomy_genus__iexact=taxonomy_genus)
    if search:
        qs = qs.filter(
            Q(contig__assembly__organism_name__icontains=search)
            | Q(contig__assembly__accession__icontains=search)
        )
    if bgc_class:
        qs = qs.filter(classes__name__iexact=bgc_class).distinct()
    if biome_lineage:
        qs = qs.filter(contig__assembly__biome__lineage__icontains=biome_lineage)
    if assembly_accession:
        qs = qs.filter(contig__assembly__accession__icontains=assembly_accession)
    if bgc_accession:
        bgc_accession = bgc_accession.strip()
        if bgc_accession.upper().startswith("MGYB"):
            try:
                bgc_pk = int(bgc_accession[4:])
                qs = qs.filter(id=bgc_pk)
            except ValueError:
                pass
        else:
            qs = qs.filter(identifier__icontains=bgc_accession)

    # Score and paginate
    results = []
    for bgc in qs:
        bs = bgc.bgc_score
        similarity = bgc_similarities.get(bgc.id, 0.0)
        relevance = compute_composite_priority(
            scores={
                "similarity": similarity,
                "novelty": bs.novelty_score if bs else 0.0,
                "completeness": 0.0 if bgc.is_partial else 1.0,
                "domain_novelty": bs.domain_novelty if bs else 0.0,
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
    page_results = results[offset : offset + ps]

    items = []
    for bgc, relevance in page_results:
        bs = bgc.bgc_score
        assembly = bgc.contig.assembly if bgc.contig else None
        items.append(
            QueryResultBgc(
                id=bgc.id,
                accession=bgc.accession,
                classification_l1=bs.classification_l1 if bs else "",
                classification_l2=bs.classification_l2 if bs else None,
                size_kb=bs.size_kb if bs else 0.0,
                novelty_score=bs.novelty_score if bs else 0.0,
                domain_novelty=bs.domain_novelty if bs else 0.0,
                is_partial=bgc.is_partial,
                relevance_score=round(relevance, 4),
                assembly_id=assembly.id if assembly else None,
                assembly_accession=assembly.accession if assembly else None,
                organism_name=assembly.organism_name if assembly else None,
                is_type_strain=assembly.is_type_strain if assembly else False,
            )
        )

    return PaginatedQueryResultResponse(
        items=items,
        pagination=PaginationMeta(
            page=pg, page_size=ps, total_count=total_count, total_pages=tp
        ),
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
    """Aggregate BGC-level query results to genome level.

    bgc_ids: comma-separated list of BGC IDs from a query result.
    """
    ids = [int(x) for x in bgc_ids.split(",") if x.strip().isdigit()]
    if not ids:
        return PaginatedGenomeAggregationResponse(
            items=[],
            pagination=PaginationMeta(page=1, page_size=page_size, total_count=0, total_pages=0),
        )

    bgcs = (
        Bgc.objects.filter(id__in=ids)
        .select_related("bgc_score", "contig__assembly")
    )

    # Group by assembly
    genome_map: dict[int, dict] = {}
    for bgc in bgcs:
        assembly = bgc.contig.assembly if bgc.contig else None
        if not assembly:
            continue
        aid = assembly.id
        if aid not in genome_map:
            genome_map[aid] = {
                "assembly": assembly,
                "hits": [],
            }
        bs = bgc.bgc_score
        genome_map[aid]["hits"].append({
            "novelty": bs.novelty_score if bs else 0.0,
            "is_partial": bgc.is_partial,
        })

    results = []
    for aid, data in genome_map.items():
        assembly = data["assembly"]
        hits = data["hits"]
        novelties = [h["novelty"] for h in hits]
        complete_count = sum(1 for h in hits if not h["is_partial"])

        results.append(
            QueryResultGenomeAggregation(
                assembly_id=assembly.id,
                accession=assembly.accession,
                organism_name=assembly.organism_name,
                taxonomy_family=assembly.taxonomy_family,
                is_type_strain=assembly.is_type_strain,
                hit_count=len(hits),
                max_relevance=round(max(novelties) if novelties else 0.0, 4),
                mean_relevance=round(
                    sum(novelties) / len(novelties) if novelties else 0.0, 4
                ),
                complete_fraction=round(
                    complete_count / len(hits) if hits else 0.0, 4
                ),
            )
        )

    # Sort
    reverse = order == "desc"
    if sort_by in ("max_relevance", "mean_relevance", "hit_count", "complete_fraction"):
        results.sort(key=lambda x: getattr(x, sort_by, 0), reverse=reverse)
    else:
        results.sort(key=lambda x: x.max_relevance, reverse=True)

    total_count = len(results)
    pg, ps, tp, offset = _paginate(page, page_size, total_count)

    return PaginatedGenomeAggregationResponse(
        items=results[offset : offset + ps],
        pagination=PaginationMeta(
            page=pg, page_size=ps, total_count=total_count, total_pages=tp
        ),
    )


# ── Filter endpoints ──────────────────────────────────────────────────────────


@discovery_router.get("/filters/taxonomy/", response=list[TaxonomyNode])
def taxonomy_tree(request):
    """Build a taxonomy tree from assemblies that have genome scores."""
    qs = Assembly.objects.filter(genome_score__isnull=False).values(
        "taxonomy_kingdom",
        "taxonomy_phylum",
        "taxonomy_class",
        "taxonomy_order",
        "taxonomy_family",
        "taxonomy_genus",
    )

    # Build hierarchical tree
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
        BgcClassOption(name=row["name"], count=row["count"])
        for row in BgcClass.objects.annotate(count=Count("bgcs")).values("name", "count")
        if row["count"] > 0
    ]


@discovery_router.get("/filters/np-classes/", response=list[NpClassLevel])
def np_classes(request):
    """NaturalProduct 3-level class hierarchy."""
    qs = NaturalProduct.objects.values(
        "chemical_class_l1", "chemical_class_l2", "chemical_class_l3"
    ).annotate(count=Count("id"))

    # Build tree
    tree: dict = {}
    for row in qs:
        l1 = row["chemical_class_l1"]
        l2 = row["chemical_class_l2"]
        l3 = row["chemical_class_l3"]
        cnt = row["count"]

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
    qs = Domain.objects.annotate(count=Count("proteins")).filter(count__gt=0)

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
            count=d.count,
        )
        for d in qs.order_by("-count")[offset : offset + ps]
    ]

    return PaginatedDomainResponse(
        items=items,
        pagination=PaginationMeta(
            page=pg, page_size=ps, total_count=total_count, total_pages=tp
        ),
    )


# ── Stats endpoints ───────────────────────────────────────────────────────────


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
    """Aggregated statistics for the filtered genome set."""
    qs = Assembly.objects.select_related("genome_score").filter(
        genome_score__isnull=False
    )
    qs = _apply_genome_filters(
        qs,
        assembly_ids=assembly_ids,
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
):
    """Aggregated statistics for the filtered BGC set."""
    qs = Bgc.objects.filter(bgc_score__isnull=False)
    qs = _apply_bgc_filters(qs, assembly_ids=assembly_ids)
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
    """Export genome stats as JSON or TSV."""
    qs = Assembly.objects.select_related("genome_score").filter(
        genome_score__isnull=False
    )
    qs = _apply_genome_filters(
        qs,
        assembly_ids=assembly_ids,
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
):
    """Export BGC stats as JSON or TSV."""
    qs = Bgc.objects.filter(bgc_score__isnull=False)
    qs = _apply_bgc_filters(qs, assembly_ids=assembly_ids)
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
    """Convert a stats dict into a flat TSV download."""
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


# ── Export endpoints ──────────────────────────────────────────────────────────


@discovery_router.post("/shortlist/genome/export/")
def export_genome_shortlist(request, body: ShortlistExportRequest):
    """Export genome shortlist as CSV."""
    if not body.ids:
        raise HttpError(400, "No genome IDs provided")
    if len(body.ids) > 20:
        raise HttpError(400, "Maximum 20 genomes per export")

    assemblies = (
        Assembly.objects.filter(id__in=body.ids)
        .select_related("genome_score")
    )

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "accession",
        "organism_name",
        "taxonomy_kingdom",
        "taxonomy_phylum",
        "taxonomy_class",
        "taxonomy_order",
        "taxonomy_family",
        "taxonomy_genus",
        "taxonomy_species",
        "is_type_strain",
        "type_strain_catalog_url",
        "genome_size_mb",
        "genome_quality",
        "isolation_source",
        "bgc_count",
        "l1_class_count",
        "bgc_diversity_score",
        "bgc_novelty_score",
        "bgc_density",
        "taxonomic_novelty",
    ])

    for a in assemblies:
        gs = getattr(a, "genome_score", None)
        writer.writerow([
            a.accession,
            a.organism_name or "",
            a.taxonomy_kingdom or "",
            a.taxonomy_phylum or "",
            a.taxonomy_class or "",
            a.taxonomy_order or "",
            a.taxonomy_family or "",
            a.taxonomy_genus or "",
            a.taxonomy_species or "",
            a.is_type_strain,
            a.type_strain_catalog_url or "",
            a.genome_size_mb or "",
            a.genome_quality or "",
            a.isolation_source or "",
            gs.bgc_count if gs else 0,
            gs.l1_class_count if gs else 0,
            gs.bgc_diversity_score if gs else 0.0,
            gs.bgc_novelty_score if gs else 0.0,
            gs.bgc_density if gs else 0.0,
            gs.taxonomic_novelty if gs else 0.0,
        ])

    response = HttpResponse(buf.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="genome_shortlist.csv"'
    return response


@discovery_router.post("/shortlist/bgc/export/")
def export_bgc_shortlist(request, body: ShortlistExportRequest):
    """Export BGC shortlist as a multi-record GenBank file."""
    if not body.ids:
        raise HttpError(400, "No BGC IDs provided")
    if len(body.ids) > 20:
        raise HttpError(400, "Maximum 20 BGCs per export")

    from mgnify_bgcs.utils.seqrecord_utils import build_bgc_record

    records = []
    for bgc_id in body.ids:
        try:
            record = build_bgc_record(bgc_id)
            records.append(record.to_gbk())
        except Exception:
            # Skip BGCs that can't be converted
            continue

    if not records:
        raise HttpError(400, "No BGC records could be generated")

    content = "\n".join(records)
    response = HttpResponse(content, content_type="application/genbank")
    response["Content-Disposition"] = 'attachment; filename="bgc_shortlist.gbk"'
    return response


# ── Assessment endpoints ────────────────────────────────────────────────────


@discovery_router.post(
    "/assess/genome/{assembly_id}/",
    response={202: AssessmentAccepted},
    tags=["Assessment"],
)
def assess_genome(request, assembly_id: int, body: GenomeWeightParams = None):
    """Start an async genome assessment task."""
    if not Assembly.objects.filter(pk=assembly_id).exists():
        raise HttpError(404, "Assembly not found")

    weights = {
        "w_diversity": body.w_diversity if body else 0.30,
        "w_novelty": body.w_novelty if body else 0.45,
        "w_density": body.w_density if body else 0.25,
    }

    from discovery.tasks import assess_genome as assess_genome_task

    result = assess_genome_task.delay(assembly_id, weights)
    return 202, AssessmentAccepted(task_id=result.id, asset_type="genome")


@discovery_router.post(
    "/assess/bgc/{bgc_id}/",
    response={202: AssessmentAccepted},
    tags=["Assessment"],
)
def assess_bgc(request, bgc_id: int):
    """Start an async BGC assessment task."""
    if not Bgc.objects.filter(pk=bgc_id).exists():
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
    """Poll for assessment task status and results."""
    from mgnify_bgcs.cache_utils import get_job_status

    status_data = get_job_status(task_id=task_id)
    return AssessmentStatusResponse(
        status=status_data.get("status", "UNKNOWN"),
        result=status_data.get("result"),
    )


@discovery_router.get(
    "/assess/genome/{assembly_id}/similar-genomes/",
    response=list[int],
    tags=["Assessment"],
)
def similar_genomes(request, assembly_id: int):
    """Return top 10 most similar genome IDs for cross-mode navigation."""
    if not Assembly.objects.filter(pk=assembly_id).exists():
        raise HttpError(404, "Assembly not found")

    from discovery.services.assessment import find_similar_genomes

    return find_similar_genomes(assembly_id, k=10)


@discovery_router.get(
    "/assess/export/{task_id}/",
    tags=["Assessment"],
)
def export_assessment(request, task_id: str):
    """Download assessment results as a JSON file."""
    from mgnify_bgcs.cache_utils import get_job_status

    status_data = get_job_status(task_id=task_id)
    if status_data.get("status") != "SUCCESS":
        raise HttpError(404, "Assessment not found or not yet complete")

    result = status_data.get("result", {})
    content = json.dumps(result, indent=2, default=str)
    response = HttpResponse(content, content_type="application/json")
    response["Content-Disposition"] = f'attachment; filename="assessment_{task_id[:8]}.json"'
    return response
