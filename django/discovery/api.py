"""Discovery Platform API — Django Ninja Router.

Mounted on the main NinjaAPI at /api/dashboard/.

Fully self-contained: all endpoints query discovery models only.
No imports from mgnify_bgcs.
"""

import csv
import json
import logging
import math
from io import StringIO
from typing import Optional

from django.db.models import (
    Avg,
    Case,
    Count,
    F,
    FloatField,
    Q,
    Value,
    When,
)
from django.http import HttpResponse
from ninja import Router
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
    DashboardAssembly,
    DashboardNaturalProduct,
    DiscoveryStats,
    NaturalProductChemOntClass,
    PrecomputedStats,
)
from discovery.services.stats import compute_bgc_stats, compute_assembly_stats
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
    SequenceQueryRequest,
    CoreDomain,
    DetectorOut,
    AssemblyStatsResponse,
    PaginatedBgcRosterResponse,
    DomainArchitectureItem,
    DomainOption,
    DomainQueryRequest,
    AssemblyDetail,
    AssemblyRosterItem,
    AssemblyScatterPoint,
    ValidatedReferencePoint,
    ChemOntAnnotationNode,
    ChemOntClassNode,
    DiscoveryStatsResponse,
    NaturalProductSummary,
    NpClassLevel,
    PaginatedDomainResponse,
    PaginatedAssemblyAggregationResponse,
    PaginatedAssemblyResponse,
    PaginatedQueryResultResponse,
    PaginationMeta,
    ParentAssemblySummary,
    PfamAnnotationOut,
    QueryResultBgc,
    QueryResultAssemblyAggregation,
    RegionCdsOut,
    RegionClusterOut,
    RegionDomainOut,
    ScoreDistribution,
    ShortlistExportRequest,
    SunburstNode,
    TaxonomyNode,
)

logger = logging.getLogger(__name__)

discovery_router = Router(tags=["Discovery Platform"])


# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_chemont_annotation_tree(chemont_qs) -> list[ChemOntAnnotationNode]:
    """Organise an NP's flat ChemOnt annotations into a hierarchy.

    Since the ETL stores full lineage paths (every ancestor along the path
    is an annotation row), the annotations for a single NP already encode
    the tree structure.  We infer parent-child relationships by probability
    ordering: higher-probability nodes are more general ancestors of
    lower-probability nodes.

    When the ChemOnt OBO ontology is available, uses real ``parent_ids``
    for accurate hierarchy.  Otherwise falls back to a probability-based
    heuristic that works because the ETL produces monotonically decreasing
    probabilities along each lineage path.
    """
    annotations = list(chemont_qs)
    if not annotations:
        return []

    prob_map: dict[str, float] = {a.chemont_id: a.probability for a in annotations}
    name_map: dict[str, str] = {a.chemont_id: a.chemont_name for a in annotations}
    annotated_ids = set(prob_map.keys())

    # Try loading the ontology for accurate hierarchy.
    ont = None
    try:
        from common_core.chemont.ontology import get_ontology
        ont = get_ontology()
    except (FileNotFoundError, ImportError):
        pass

    children_of: dict[str, list[str]] = {}
    roots: list[str] = []
    depth_map: dict[str, int] = {}

    if ont is not None:
        # Ontology available: use real parent_ids.
        # Include unannotated ancestors that connect annotated terms.
        all_ids: set[str] = set(annotated_ids)
        for cid in annotated_ids:
            for anc in ont.get_ancestors(cid):
                all_ids.add(anc.id)
                if anc.id not in name_map:
                    name_map[anc.id] = anc.name

        def _has_annotated_descendant(tid: str, visited: set[str]) -> bool:
            if tid in annotated_ids:
                return True
            visited.add(tid)
            for child_id in ont._children.get(tid, []):
                if child_id in all_ids and child_id not in visited:
                    if _has_annotated_descendant(child_id, visited):
                        return True
            return False

        relevant: set[str] = set()
        for tid in all_ids:
            if _has_annotated_descendant(tid, set()):
                relevant.add(tid)

        for tid in relevant:
            term = ont.get_term(tid)
            if term is None:
                if tid in annotated_ids:
                    roots.append(tid)
                continue
            depth_map[tid] = term.depth
            has_relevant_parent = False
            for pid in term.parent_ids:
                if pid in relevant:
                    children_of.setdefault(pid, []).append(tid)
                    has_relevant_parent = True
            if not has_relevant_parent:
                roots.append(tid)
    else:
        # No ontology: infer hierarchy from probability ordering.
        # The ETL stores annotations with decreasing probabilities along
        # each lineage (general=high, specific=low).  Sort by probability
        # descending — each node's parent is the annotated node with the
        # smallest probability that is still higher than its own.
        sorted_anns = sorted(annotations, key=lambda a: a.probability, reverse=True)
        for i, ann in enumerate(sorted_anns):
            parent_found = False
            for j in range(i - 1, -1, -1):
                candidate = sorted_anns[j]
                if candidate.probability > ann.probability:
                    children_of.setdefault(candidate.chemont_id, []).append(ann.chemont_id)
                    parent_found = True
                    break
            if not parent_found:
                roots.append(ann.chemont_id)

        for depth_idx, ann in enumerate(sorted_anns):
            depth_map[ann.chemont_id] = depth_idx

    def _to_node(tid: str) -> ChemOntAnnotationNode:
        kids = sorted(children_of.get(tid, []), key=lambda c: name_map.get(c, c))
        return ChemOntAnnotationNode(
            chemont_id=tid,
            name=name_map.get(tid, tid),
            depth=depth_map.get(tid, 0),
            probability=prob_map.get(tid),  # None for intermediate (unannotated) ancestors
            children=[_to_node(c) for c in kids],
        )

    return sorted(
        [_to_node(r) for r in roots],
        key=lambda n: n.name,
    )


def _paginate(page: int, page_size: int, total_count: int):
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    total_pages = max(1, math.ceil(total_count / page_size))
    offset = (page - 1) * page_size
    return page, page_size, total_pages, offset


def _assembly_to_roster_item(assembly: DashboardAssembly) -> AssemblyRosterItem:
    return AssemblyRosterItem(
        id=assembly.id,
        accession=assembly.assembly_accession,
        organism_name=assembly.organism_name,
        source_name=assembly.source.name if assembly.source else None,
        assembly_type=assembly.get_assembly_type_display(),
        is_type_strain=assembly.is_type_strain,
        type_strain_catalog_url=assembly.type_strain_catalog_url,
        bgc_count=assembly.bgc_count,
        l1_class_count=assembly.l1_class_count,
        bgc_diversity_score=assembly.bgc_diversity_score,
        bgc_novelty_score=assembly.bgc_novelty_score,
        bgc_density=assembly.bgc_density,
        taxonomic_novelty=assembly.taxonomic_novelty,
    )


# ── Shared filter helpers ────────────────────────────────────────────────────


def _apply_assembly_filters(
    qs,
    *,
    assembly_ids: Optional[str] = None,
    assembly_type: Optional[str] = None,
    type_strain_only: bool = False,
    taxonomy_path: Optional[str] = None,
    search: Optional[str] = None,
    bgc_class: Optional[str] = None,
    biome_lineage: Optional[str] = None,
    bgc_accession: Optional[str] = None,
    assembly_accession: Optional[str] = None,
):
    """Apply common assembly filters to a DashboardAssembly queryset."""
    if assembly_ids:
        ids = [int(x) for x in assembly_ids.split(",") if x.strip().isdigit()]
        if ids:
            qs = qs.filter(id__in=ids)
        else:
            qs = qs.none()
    if assembly_type:
        from discovery.models import AssemblyType
        type_map = {v.label: v.value for v in AssemblyType}
        if assembly_type.lower() in type_map:
            qs = qs.filter(assembly_type=type_map[assembly_type.lower()])
    if type_strain_only:
        qs = qs.filter(is_type_strain=True)
    if taxonomy_path:
        from discovery.ltree import filter_contigs_by_taxonomy
        matching_contigs = filter_contigs_by_taxonomy(taxonomy_path)
        qs = qs.filter(contigs__in=matching_contigs).distinct()
    if search:
        qs = qs.filter(
            Q(organism_name__icontains=search)
            | Q(assembly_accession__icontains=search)
        )
    if bgc_class:
        qs = qs.filter(
            Q(bgcs__classification_path__istartswith=bgc_class + ".")
            | Q(bgcs__classification_path__iexact=bgc_class)
        ).distinct()
    if biome_lineage:
        qs = qs.filter(biome_path__icontains=biome_lineage)
    if bgc_accession:
        bgc_accession = bgc_accession.strip()
        upper = bgc_accession.upper()
        if "." in upper and upper.startswith("MGYB"):
            # Structured accession: exact match
            qs = qs.filter(bgcs__bgc_accession__iexact=bgc_accession).distinct()
        elif upper.startswith("MGYB") and "." not in upper:
            # Region-only accession: match BGCs in that region
            from discovery.models import DashboardRegion, RegionAccessionAlias

            region_ids = set()
            try:
                region_pk = int(upper.lstrip("MGYB"))
                region_ids.add(region_pk)
            except ValueError:
                pass
            # Also check aliases
            alias_qs = RegionAccessionAlias.objects.filter(
                alias_accession__iexact=upper
            ).values_list("region_id", flat=True)
            region_ids.update(alias_qs)
            if region_ids:
                qs = qs.filter(bgcs__region_id__in=region_ids).distinct()
            else:
                qs = qs.filter(bgcs__bgc_accession__icontains=bgc_accession).distinct()
        else:
            qs = qs.filter(bgcs__bgc_accession__icontains=bgc_accession).distinct()
    if assembly_accession:
        qs = qs.filter(assembly_accession__icontains=assembly_accession)
    return qs


def _apply_bgc_filters(
    qs,
    *,
    assembly_ids: Optional[str] = None,
    bgc_ids: Optional[str] = None,
    tools: Optional[str] = None,
    include_all_versions: bool = False,
):
    """Apply common BGC filters to a DashboardBgc queryset.

    Parameters
    ----------
    assembly_ids:
        Comma-separated DashboardAssembly pks. Restricts to BGCs belonging
        to those assemblies.
    bgc_ids:
        Comma-separated DashboardBgc pks. Restricts to that exact set. Used
        by callers (e.g. Evaluate Asset's BGC Roster) that want to show a
        specific list of sibling BGCs without knowing their assembly.
    tools:
        Comma-separated tool names to filter by (e.g. "antiSMASH,GECCO").
    include_all_versions:
        If False (default), only the latest detector version per tool per
        contig is returned.
    """
    if not assembly_ids and not bgc_ids:
        # At least one primary identifier filter is required — the roster
        # endpoint must never fall through and return every BGC in the DB.
        return qs.none()

    if assembly_ids:
        ids = [int(x) for x in assembly_ids.split(",") if x.strip().isdigit()]
        if ids:
            qs = qs.filter(assembly_id__in=ids)
        else:
            qs = qs.none()

    if bgc_ids:
        ids = [int(x) for x in bgc_ids.split(",") if x.strip().isdigit()]
        if ids:
            qs = qs.filter(id__in=ids)
        else:
            qs = qs.none()

    if tools:
        tool_list = [t.strip() for t in tools.split(",") if t.strip()]
        if tool_list:
            qs = qs.filter(detector__tool__in=tool_list)

    if not include_all_versions:
        from discovery.querysets import latest_version_bgcs

        qs = latest_version_bgcs(qs)

    return qs


# ── Assembly endpoints ───────────────────────────────────────────────────────


@discovery_router.get("/assemblies/", response=PaginatedAssemblyResponse)
def assembly_roster(
    request,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "bgc_novelty_score",
    order: str = "desc",
    search: Optional[str] = None,
    taxonomy_path: Optional[str] = None,
    type_strain_only: bool = False,
    bgc_class: Optional[str] = None,
    biome_lineage: Optional[str] = None,
    bgc_accession: Optional[str] = None,
    assembly_accession: Optional[str] = None,
    assembly_ids: Optional[str] = None,
    assembly_type: Optional[str] = None,
):
    qs = DashboardAssembly.objects.select_related("source").all()
    qs = _apply_assembly_filters(
        qs,
        assembly_ids=assembly_ids,
        assembly_type=assembly_type,
        type_strain_only=type_strain_only,
        taxonomy_path=taxonomy_path,
        search=search,
        bgc_class=bgc_class,
        biome_lineage=biome_lineage,
        bgc_accession=bgc_accession,
        assembly_accession=assembly_accession,
    )

    score_fields = {
        "bgc_count", "bgc_diversity_score",
        "bgc_novelty_score", "bgc_density", "taxonomic_novelty",
        "l1_class_count",
    }
    prefix = "-" if order == "desc" else ""

    if sort_by in score_fields:
        qs = qs.order_by(f"{prefix}{sort_by}")
    elif sort_by == "organism_name":
        qs = qs.order_by(f"{prefix}organism_name")
    else:
        qs = qs.order_by("-bgc_novelty_score")

    total_count = qs.count()
    page, page_size, total_pages, offset = _paginate(page, page_size, total_count)
    page_qs = qs[offset: offset + page_size]

    items = [_assembly_to_roster_item(assembly) for assembly in page_qs]

    return PaginatedAssemblyResponse(
        items=items,
        pagination=PaginationMeta(
            page=page,
            page_size=page_size,
            total_count=total_count,
            total_pages=total_pages,
        ),
    )


@discovery_router.get("/assemblies/{assembly_id}/", response=AssemblyDetail)
def assembly_detail(request, assembly_id: int):
    try:
        assembly = DashboardAssembly.objects.select_related("source").get(id=assembly_id)
    except DashboardAssembly.DoesNotExist:
        raise HttpError(404, "Assembly not found")

    return AssemblyDetail(
        id=assembly.id,
        accession=assembly.assembly_accession,
        organism_name=assembly.organism_name,
        source_name=assembly.source.name if assembly.source else None,
        assembly_type=assembly.get_assembly_type_display(),
        is_type_strain=assembly.is_type_strain,
        type_strain_catalog_url=assembly.type_strain_catalog_url,
        assembly_size_mb=assembly.assembly_size_mb,
        biome_path=assembly.biome_path,
        url=assembly.url,
        bgc_count=assembly.bgc_count,
        l1_class_count=assembly.l1_class_count,
        bgc_diversity_score=assembly.bgc_diversity_score,
        bgc_novelty_score=assembly.bgc_novelty_score,
        bgc_density=assembly.bgc_density,
        taxonomic_novelty=assembly.taxonomic_novelty,
    )


@discovery_router.get("/assemblies/{assembly_id}/bgcs/", response=list[BgcRosterItem])
def assembly_bgc_roster(request, assembly_id: int):
    bgcs = DashboardBgc.objects.filter(assembly_id=assembly_id).order_by("-novelty_score")

    return [
        BgcRosterItem(
            id=bgc.id,
            accession=bgc.bgc_accession,
            classification_path=bgc.classification_path,
            size_kb=bgc.size_kb,
            novelty_score=bgc.novelty_score,
            domain_novelty=bgc.domain_novelty,
            is_partial=bgc.is_partial,
            nearest_validated_accession=bgc.nearest_validated_accession or None,
            nearest_validated_distance=bgc.nearest_validated_distance,
        )
        for bgc in bgcs
    ]


@discovery_router.get("/bgcs/roster/", response=PaginatedBgcRosterResponse)
def bgc_roster(
    request,
    assembly_ids: Optional[str] = None,
    bgc_ids: Optional[str] = None,
    sort_by: str = "novelty_score",
    order: str = "desc",
    page: int = 1,
    page_size: int = 25,
    tools: Optional[str] = None,
    include_all_versions: bool = False,
):
    qs = DashboardBgc.objects.select_related("assembly")
    qs = _apply_bgc_filters(
        qs,
        assembly_ids=assembly_ids,
        bgc_ids=bgc_ids,
        tools=tools,
        include_all_versions=include_all_versions,
    )

    sort_map = {
        "novelty_score": "novelty_score",
        "size_kb": "size_kb",
        "domain_novelty": "domain_novelty",
        "classification_path": "classification_path",
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
            classification_path=bgc.classification_path,
            size_kb=bgc.size_kb,
            novelty_score=bgc.novelty_score,
            domain_novelty=bgc.domain_novelty,
            is_partial=bgc.is_partial,
            nearest_validated_accession=bgc.nearest_validated_accession or None,
            nearest_validated_distance=bgc.nearest_validated_distance,
            assembly_accession=bgc.assembly.assembly_accession if bgc.assembly else None,
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
        .values_list("assembly_id", flat=True)
        .distinct()
    )


@discovery_router.get("/assembly-scatter/", response=list[AssemblyScatterPoint])
def assembly_scatter(
    request,
    x_axis: str = "bgc_diversity_score",
    y_axis: str = "bgc_novelty_score",
    type_strain_only: bool = False,
    taxonomy_path: Optional[str] = None,
    bgc_class: Optional[str] = None,
    assembly_ids: Optional[str] = None,
):
    allowed_axes = {
        "bgc_diversity_score", "bgc_novelty_score", "bgc_density",
        "taxonomic_novelty",
    }
    if x_axis not in allowed_axes or y_axis not in allowed_axes:
        raise HttpError(400, f"Axis must be one of: {', '.join(sorted(allowed_axes))}")

    qs = DashboardAssembly.objects.all()
    if assembly_ids:
        ids = [int(x) for x in assembly_ids.split(",") if x.strip().isdigit()]
        if ids:
            qs = qs.filter(id__in=ids)
    if type_strain_only:
        qs = qs.filter(is_type_strain=True)
    if taxonomy_path:
        from discovery.ltree import filter_contigs_by_taxonomy
        matching_contigs = filter_contigs_by_taxonomy(taxonomy_path)
        qs = qs.filter(contigs__in=matching_contigs).distinct()
    if bgc_class:
        qs = qs.filter(
            Q(bgcs__classification_path__istartswith=bgc_class + ".")
            | Q(bgcs__classification_path__iexact=bgc_class)
        ).distinct()

    return [
        AssemblyScatterPoint(
            id=assembly.id,
            x=getattr(assembly, x_axis, 0.0) or 0.0,
            y=getattr(assembly, y_axis, 0.0) or 0.0,
            organism_name=assembly.organism_name,
            is_type_strain=assembly.is_type_strain,
        )
        for assembly in qs
    ]


# ── BGC endpoints ────────────────────────────────────────────────────────────


@discovery_router.get("/bgcs/{bgc_id}/", response=BgcDetail)
def bgc_detail(request, bgc_id: int):
    try:
        bgc = DashboardBgc.objects.select_related(
            "assembly", "assembly__source", "detector", "region",
        ).get(id=bgc_id)
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
            url=bd.url,
        )
        for bd in BgcDomain.objects.filter(bgc=bgc).order_by("domain_acc")
    ]

    # Parent assembly
    parent = None
    assembly = bgc.assembly
    if assembly:
        parent = ParentAssemblySummary(
            assembly_id=assembly.id,
            accession=assembly.assembly_accession,
            organism_name=assembly.organism_name,
            source_name=assembly.source.name if assembly.source else None,
            is_type_strain=assembly.is_type_strain,
        )

    # Natural products
    np_items = []
    np_qs = DashboardNaturalProduct.objects.filter(bgc=bgc).prefetch_related(
        "chemont_classes"
    )
    for np_obj in np_qs:
        chemont_tree = _build_chemont_annotation_tree(np_obj.chemont_classes.all())
        np_items.append(
            NaturalProductSummary(
                id=np_obj.id,
                name=np_obj.name,
                smiles=np_obj.smiles,
                smiles_svg="",
                structure_thumbnail=np_obj.structure_svg_base64,
                np_class_path=np_obj.np_class_path,
                chemont_classes=chemont_tree,
            )
        )

    detector_out = None
    if bgc.detector:
        detector_out = DetectorOut(
            id=bgc.detector.id,
            tool=bgc.detector.tool,
            version=bgc.detector.version,
            tool_name_code=bgc.detector.tool_name_code,
        )

    region_acc = bgc.region.accession if bgc.region else None

    return BgcDetail(
        id=bgc.id,
        accession=bgc.bgc_accession,
        classification_path=bgc.classification_path,
        size_kb=bgc.size_kb,
        novelty_score=bgc.novelty_score,
        domain_novelty=bgc.domain_novelty,
        is_partial=bgc.is_partial,
        nearest_validated_accession=bgc.nearest_validated_accession or None,
        nearest_validated_distance=bgc.nearest_validated_distance,
        is_validated=bgc.is_validated,
        domain_architecture=domain_arch,
        parent_assembly=parent,
        natural_products=np_items,
        detector=detector_out,
        region_accession=region_acc,
    )


def _build_bgc_region_data(bgc: DashboardBgc) -> BgcRegionOut:
    """Build a BgcRegionOut for a single DB-ingested BGC.

    Extracted from the ``bgc_region`` endpoint so the assessment services
    and the batched regions endpoint can reuse the same query logic.
    """
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
        .prefetch_related("domains", "seq")
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
                    url=bd.url,
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
                    url=bd.url,
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
                sequence=cds.seq.get_sequence() if hasattr(cds, "seq") else "",
                pfam=pfam_rows,
            )
        )

    # Overlapping BGC clusters in the same contig region
    overlapping_bgcs = DashboardBgc.objects.filter(
        contig=bgc.contig,
        start_position__lte=window_end,
        end_position__gte=window_start,
    ).select_related("detector")
    cluster_list = [
        RegionClusterOut(
            accession=ob.bgc_accession,
            start=max(0, ob.start_position - window_start),
            end=max(0, ob.end_position - window_start),
            source=ob.detector.name if ob.detector else "",
            bgc_classes=[ob.classification_path.split(".")[0]] if ob.classification_path else [],
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


@discovery_router.get("/bgcs/{bgc_id}/region/", response=BgcRegionOut)
def bgc_region(request, bgc_id: int):
    """Return CDS, domain, and cluster data for the BGC genomic region.

    Served entirely from discovery models (DashboardCds, BgcDomain).
    """
    try:
        bgc = DashboardBgc.objects.get(id=bgc_id)
    except DashboardBgc.DoesNotExist:
        raise HttpError(404, "BGC not found")
    return _build_bgc_region_data(bgc)


@discovery_router.get("/bgcs/{bgc_id}/download/")
def download_bgc(request, bgc_id: int, format: str = "gbk"):
    """Download a single BGC in GBK, FNA, FAA, or JSON format."""
    valid_formats = {"gbk", "fna", "faa", "json"}
    fmt = format.lower()
    if fmt not in valid_formats:
        raise HttpError(400, f"Invalid format '{format}'. Use: {', '.join(sorted(valid_formats))}")

    try:
        bgc = (
            DashboardBgc.objects.select_related("assembly", "contig", "contig__seq")
            .prefetch_related("cds_list", "cds_list__seq", "bgc_domains")
            .get(id=bgc_id)
        )
    except DashboardBgc.DoesNotExist:
        raise HttpError(404, "BGC not found")

    accession = bgc.bgc_accession

    if fmt == "gbk":
        from discovery.services.gbk import build_bgc_genbank_record
        from io import StringIO
        from Bio import SeqIO

        record = build_bgc_genbank_record(bgc)
        handle = StringIO()
        SeqIO.write([record], handle, "genbank")
        content = handle.getvalue()
        return HttpResponse(
            content,
            content_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{accession}.gbk"'},
        )

    if fmt == "fna":
        from discovery.services.export import build_bgc_fna

        content = build_bgc_fna(bgc)
        return HttpResponse(
            content,
            content_type="text/plain",
            headers={"Content-Disposition": f'attachment; filename="{accession}.fna"'},
        )

    if fmt == "faa":
        from discovery.services.export import build_bgc_faa

        content = build_bgc_faa(bgc)
        return HttpResponse(
            content,
            content_type="text/plain",
            headers={"Content-Disposition": f'attachment; filename="{accession}.faa"'},
        )

    # json
    from discovery.services.export import build_bgc_json

    data = build_bgc_json(bgc)
    return HttpResponse(
        json.dumps(data, indent=2),
        content_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{accession}.json"'},
    )


@discovery_router.get("/bgc-scatter/", response=list[BgcScatterPoint])
def bgc_scatter(
    request,
    x_axis: str = "novelty_score",
    y_axis: str = "domain_novelty",
    include_validated: bool = True,
    bgc_class: Optional[str] = None,
    assembly_ids: Optional[str] = None,
    bgc_ids: Optional[str] = None,
    max_points: int = 2000,
):
    allowed_axes = {"novelty_score", "domain_novelty"}
    if x_axis not in allowed_axes or y_axis not in allowed_axes:
        raise HttpError(400, f"Axis must be one of: {', '.join(sorted(allowed_axes))}")

    qs = DashboardBgc.objects.all()

    if bgc_class:
        qs = qs.filter(
            Q(classification_path__istartswith=bgc_class + ".")
            | Q(classification_path__iexact=bgc_class)
        )
    if bgc_ids:
        ids = [int(x) for x in bgc_ids.split(",") if x.strip().isdigit()]
        if ids:
            qs = qs.filter(id__in=ids)
    elif assembly_ids:
        ids = [int(x) for x in assembly_ids.split(",") if x.strip().isdigit()]
        if ids:
            qs = qs.filter(assembly_id__in=ids)

    total = qs.count()
    if total > max_points:
        qs = qs.order_by("?")[:max_points]

    points = [
        BgcScatterPoint(
            id=bgc.id,
            x=getattr(bgc, x_axis, 0.0) or 0.0,
            y=getattr(bgc, y_axis, 0.0) or 0.0,
            bgc_class=bgc.classification_path.split(".")[0] if bgc.classification_path else "",
            is_validated=bgc.is_validated,
            compound_name=None,
            novelty_score=bgc.novelty_score,
            domain_novelty=bgc.domain_novelty,
        )
        for bgc in qs
    ]

    return points


# ── Query mode endpoints ─────────────────────────────────────────────────────


@discovery_router.post("/query/domain/", response=PaginatedQueryResultResponse)
def domain_query(
    request,
    body: DomainQueryRequest,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "novelty_score",
    order: str = "desc",
    search: Optional[str] = None,
    taxonomy_path: Optional[str] = None,
    type_strain_only: bool = False,
    bgc_class: Optional[str] = None,
    biome_lineage: Optional[str] = None,
    assembly_accession: Optional[str] = None,
    bgc_accession: Optional[str] = None,
):
    required = [d.acc for d in body.domains if d.required]
    excluded = [d.acc for d in body.domains if not d.required]

    qs = DashboardBgc.objects.select_related("assembly")

    # Sidebar filters via parent assembly
    if type_strain_only:
        qs = qs.filter(assembly__is_type_strain=True)
    if taxonomy_path:
        from discovery.ltree import filter_contigs_by_taxonomy
        qs = qs.filter(contig__in=filter_contigs_by_taxonomy(taxonomy_path)).distinct()
    if search:
        qs = qs.filter(
            Q(assembly__organism_name__icontains=search)
            | Q(assembly__assembly_accession__icontains=search)
        )
    if bgc_class:
        qs = qs.filter(
            Q(classification_path__istartswith=bgc_class + ".")
            | Q(classification_path__iexact=bgc_class)
        )
    if biome_lineage:
        qs = qs.filter(assembly__biome_path__icontains=biome_lineage)
    if assembly_accession:
        qs = qs.filter(assembly__assembly_accession__icontains=assembly_accession)
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

    # Domain queries use similarity_score=1.0 (domain match is binary)
    # Sort
    sort_map = {
        "novelty_score": "novelty_score",
        "domain_novelty": "domain_novelty",
        "size_kb": "size_kb",
        "classification_path": "classification_path",
        "accession": "id",
    }
    order_field = sort_map.get(sort_by, "novelty_score")
    prefix = "-" if order == "desc" else ""
    qs = qs.order_by(f"{prefix}{order_field}")

    total_count = qs.count()
    pg, ps, tp, offset = _paginate(page, page_size, total_count)
    page_qs = qs[offset: offset + ps]

    items = [
        QueryResultBgc(
            id=bgc.id,
            accession=bgc.bgc_accession,
            classification_path=bgc.classification_path,
            size_kb=bgc.size_kb,
            novelty_score=bgc.novelty_score,
            domain_novelty=bgc.domain_novelty,
            is_partial=bgc.is_partial,
            similarity_score=1.0,
            assembly_id=bgc.assembly_id,
            assembly_accession=bgc.assembly.assembly_accession if bgc.assembly else None,
            organism_name=bgc.assembly.organism_name if bgc.assembly else None,
            is_type_strain=bgc.assembly.is_type_strain if bgc.assembly else False,
            source_name=bgc.assembly.source.name if bgc.assembly and bgc.assembly.source else None,
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
    sort_by: str = "similarity_score",
    order: str = "desc",
    max_distance: float = 0.5,
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
        .select_related("bgc__assembly")
    )

    # Materialize similarity scores
    results = []
    for emb in emb_qs:
        bgc = emb.bgc
        similarity = round(1.0 - float(emb.distance), 4)
        results.append((bgc, similarity))

    # Sort
    sort_key_map = {
        "similarity_score": lambda x: x[1],
        "novelty_score": lambda x: x[0].novelty_score,
        "domain_novelty": lambda x: x[0].domain_novelty,
        "size_kb": lambda x: x[0].size_kb,
    }
    key_fn = sort_key_map.get(sort_by, sort_key_map["similarity_score"])
    results.sort(key=key_fn, reverse=(order == "desc"))

    total_count = len(results)
    pg, ps, tp, offset = _paginate(page, page_size, total_count)
    page_results = results[offset: offset + ps]

    items = [
        QueryResultBgc(
            id=bgc.id,
            accession=bgc.bgc_accession,
            classification_path=bgc.classification_path,
            size_kb=bgc.size_kb,
            novelty_score=bgc.novelty_score,
            domain_novelty=bgc.domain_novelty,
            is_partial=bgc.is_partial,
            similarity_score=similarity,
            assembly_id=bgc.assembly_id,
            assembly_accession=bgc.assembly.assembly_accession if bgc.assembly else None,
            organism_name=bgc.assembly.organism_name if bgc.assembly else None,
            is_type_strain=bgc.assembly.is_type_strain if bgc.assembly else False,
            source_name=bgc.assembly.source.name if bgc.assembly and bgc.assembly.source else None,
        )
        for bgc, similarity in page_results
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
    sort_by: str = "similarity_score",
    order: str = "desc",
    search: Optional[str] = None,
    taxonomy_path: Optional[str] = None,
    type_strain_only: bool = False,
    bgc_class: Optional[str] = None,
    biome_lineage: Optional[str] = None,
    assembly_accession: Optional[str] = None,
    bgc_accession: Optional[str] = None,
    chemont_ids: Optional[str] = None,
):
    if not body.smiles or not body.smiles.strip():
        raise HttpError(400, "SMILES string is required")

    from discovery.tasks import chemical_similarity_search

    # Dispatch ChemOnt similarity computation to Celery worker
    async_result = chemical_similarity_search.delay(
        body.smiles.strip(), body.similarity_threshold
    )
    try:
        raw_result = async_result.get(timeout=120)
        # Celery JSON serialization converts int keys to strings; convert back
        bgc_similarities: dict[int, float] = {int(k): v for k, v in raw_result.items()}
    except Exception as e:
        logger.error("Chemical similarity search failed: %s", e)
        raise HttpError(500, "Chemical similarity search failed")

    if not bgc_similarities:
        return PaginatedQueryResultResponse(
            items=[],
            pagination=PaginationMeta(page=1, page_size=page_size, total_count=0, total_pages=0),
        )

    qs = DashboardBgc.objects.filter(id__in=bgc_similarities.keys()).select_related("assembly")

    # Sidebar filters
    if type_strain_only:
        qs = qs.filter(assembly__is_type_strain=True)
    if taxonomy_path:
        from discovery.ltree import filter_contigs_by_taxonomy
        qs = qs.filter(contig__in=filter_contigs_by_taxonomy(taxonomy_path)).distinct()
    if search:
        qs = qs.filter(
            Q(assembly__organism_name__icontains=search)
            | Q(assembly__assembly_accession__icontains=search)
        )
    if bgc_class:
        qs = qs.filter(
            Q(classification_path__istartswith=bgc_class + ".")
            | Q(classification_path__iexact=bgc_class)
        )
    if biome_lineage:
        qs = qs.filter(assembly__biome_path__icontains=biome_lineage)
    if assembly_accession:
        qs = qs.filter(assembly__assembly_accession__icontains=assembly_accession)
    if bgc_accession:
        qs = qs.filter(bgc_accession__icontains=bgc_accession.strip())
    if chemont_ids:
        cid_list = [c.strip() for c in chemont_ids.split(",") if c.strip()]
        if cid_list:
            qs = qs.filter(
                natural_products__chemont_classes__chemont_id__in=cid_list
            ).distinct()

    results = []
    for bgc in qs:
        similarity = round(bgc_similarities.get(bgc.id, 0.0), 4)
        results.append((bgc, similarity))

    # Sort
    sort_key_map = {
        "similarity_score": lambda x: x[1],
        "novelty_score": lambda x: x[0].novelty_score,
        "domain_novelty": lambda x: x[0].domain_novelty,
        "size_kb": lambda x: x[0].size_kb,
    }
    key_fn = sort_key_map.get(sort_by, sort_key_map["similarity_score"])
    results.sort(key=key_fn, reverse=(order == "desc"))

    total_count = len(results)
    pg, ps, tp, offset = _paginate(page, page_size, total_count)
    page_results = results[offset: offset + ps]

    items = [
        QueryResultBgc(
            id=bgc.id,
            accession=bgc.bgc_accession,
            classification_path=bgc.classification_path,
            size_kb=bgc.size_kb,
            novelty_score=bgc.novelty_score,
            domain_novelty=bgc.domain_novelty,
            is_partial=bgc.is_partial,
            similarity_score=similarity,
            assembly_id=bgc.assembly_id,
            assembly_accession=bgc.assembly.assembly_accession if bgc.assembly else None,
            organism_name=bgc.assembly.organism_name if bgc.assembly else None,
            is_type_strain=bgc.assembly.is_type_strain if bgc.assembly else False,
            source_name=bgc.assembly.source.name if bgc.assembly and bgc.assembly.source else None,
        )
        for bgc, similarity in page_results
    ]

    return PaginatedQueryResultResponse(
        items=items,
        pagination=PaginationMeta(page=pg, page_size=ps, total_count=total_count, total_pages=tp),
    )


@discovery_router.post("/query/sequence/", response=PaginatedQueryResultResponse)
def sequence_query(
    request,
    body: SequenceQueryRequest,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "similarity_score",
    order: str = "desc",
    search: Optional[str] = None,
    taxonomy_path: Optional[str] = None,
    type_strain_only: bool = False,
    bgc_class: Optional[str] = None,
    biome_lineage: Optional[str] = None,
    assembly_accession: Optional[str] = None,
    bgc_accession: Optional[str] = None,
):
    # Strip FASTA header if present
    lines = body.sequence.strip().splitlines()
    cleaned = "".join(l.strip() for l in lines if not l.startswith(">"))
    if not cleaned:
        raise HttpError(400, "Protein sequence is required")
    if len(cleaned) > 5000:
        raise HttpError(400, "Sequence exceeds maximum length of 5,000 amino acids")

    from discovery.tasks import sequence_similarity_search

    async_result = sequence_similarity_search.delay(
        cleaned, body.similarity_threshold
    )
    try:
        raw_result = async_result.get(timeout=180)
        bgc_similarities: dict[int, float] = {int(k): v for k, v in raw_result.items()}
    except Exception as e:
        logger.error("Sequence similarity search failed: %s", e)
        raise HttpError(500, "Sequence similarity search failed")

    if not bgc_similarities:
        return PaginatedQueryResultResponse(
            items=[],
            pagination=PaginationMeta(page=1, page_size=page_size, total_count=0, total_pages=0),
        )

    qs = DashboardBgc.objects.filter(id__in=bgc_similarities.keys()).select_related("assembly")

    # Sidebar filters
    if type_strain_only:
        qs = qs.filter(assembly__is_type_strain=True)
    if taxonomy_path:
        from discovery.ltree import filter_contigs_by_taxonomy
        qs = qs.filter(contig__in=filter_contigs_by_taxonomy(taxonomy_path)).distinct()
    if search:
        qs = qs.filter(
            Q(assembly__organism_name__icontains=search)
            | Q(assembly__assembly_accession__icontains=search)
        )
    if bgc_class:
        qs = qs.filter(
            Q(classification_path__istartswith=bgc_class + ".")
            | Q(classification_path__iexact=bgc_class)
        )
    if biome_lineage:
        qs = qs.filter(assembly__biome_path__icontains=biome_lineage)
    if assembly_accession:
        qs = qs.filter(assembly__assembly_accession__icontains=assembly_accession)
    if bgc_accession:
        qs = qs.filter(bgc_accession__icontains=bgc_accession.strip())

    results = []
    for bgc in qs:
        similarity = round(bgc_similarities.get(bgc.id, 0.0), 4)
        results.append((bgc, similarity))

    # Sort
    sort_key_map = {
        "similarity_score": lambda x: x[1],
        "novelty_score": lambda x: x[0].novelty_score,
        "domain_novelty": lambda x: x[0].domain_novelty,
        "size_kb": lambda x: x[0].size_kb,
    }
    key_fn = sort_key_map.get(sort_by, sort_key_map["similarity_score"])
    results.sort(key=key_fn, reverse=(order == "desc"))

    total_count = len(results)
    pg, ps, tp, offset = _paginate(page, page_size, total_count)
    page_results = results[offset: offset + ps]

    items = [
        QueryResultBgc(
            id=bgc.id,
            accession=bgc.bgc_accession,
            classification_path=bgc.classification_path,
            size_kb=bgc.size_kb,
            novelty_score=bgc.novelty_score,
            domain_novelty=bgc.domain_novelty,
            is_partial=bgc.is_partial,
            similarity_score=similarity,
            assembly_id=bgc.assembly_id,
            assembly_accession=bgc.assembly.assembly_accession if bgc.assembly else None,
            organism_name=bgc.assembly.organism_name if bgc.assembly else None,
            is_type_strain=bgc.assembly.is_type_strain if bgc.assembly else False,
            source_name=bgc.assembly.source.name if bgc.assembly and bgc.assembly.source else None,
        )
        for bgc, similarity in page_results
    ]

    return PaginatedQueryResultResponse(
        items=items,
        pagination=PaginationMeta(page=pg, page_size=ps, total_count=total_count, total_pages=tp),
    )


@discovery_router.get(
    "/query-results/assemblies/", response=PaginatedAssemblyAggregationResponse
)
def query_results_assembly_aggregation(
    request,
    bgc_ids: str,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "hit_count",
    order: str = "desc",
):
    ids = [int(x) for x in bgc_ids.split(",") if x.strip().isdigit()]
    if not ids:
        return PaginatedAssemblyAggregationResponse(
            items=[],
            pagination=PaginationMeta(page=1, page_size=page_size, total_count=0, total_pages=0),
        )

    # SQL aggregation instead of Python grouping
    assembly_agg = (
        DashboardBgc.objects.filter(id__in=ids)
        .values(
            "assembly__id",
            "assembly__assembly_accession",
            "assembly__organism_name",
            "assembly__is_type_strain",
            "assembly__source__name",
        )
        .annotate(
            hit_count=Count("id"),
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
        "hit_count": "hit_count",
        "complete_fraction": "complete_fraction",
    }
    order_field = sort_map.get(sort_by, "hit_count")
    prefix = "-" if order == "desc" else ""
    assembly_agg = assembly_agg.order_by(f"{prefix}{order_field}")

    total_count = assembly_agg.count()
    pg, ps, tp, offset = _paginate(page, page_size, total_count)
    page_agg = assembly_agg[offset: offset + ps]

    items = [
        QueryResultAssemblyAggregation(
            assembly_id=row["assembly__id"],
            accession=row["assembly__assembly_accession"],
            organism_name=row["assembly__organism_name"],
            is_type_strain=row["assembly__is_type_strain"],
            source_name=row.get("assembly__source__name"),
            hit_count=row["hit_count"],
            complete_fraction=round(row["complete_fraction"] or 0.0, 4),
        )
        for row in page_agg
    ]

    return PaginatedAssemblyAggregationResponse(
        items=items,
        pagination=PaginationMeta(page=pg, page_size=ps, total_count=total_count, total_pages=tp),
    )


# ── Filter endpoints ─────────────────────────────────────────────────────────


@discovery_router.get("/filters/taxonomy/", response=list[TaxonomyNode])
def taxonomy_tree(request):
    from discovery.models import DashboardContig

    RANK_NAMES = ["kingdom", "phylum", "class", "order", "family", "genus", "species"]

    qs = DashboardContig.objects.exclude(taxonomy_path="").values_list(
        "taxonomy_path", flat=True
    )

    tree: dict = {}
    for path in qs:
        parts = path.split(".")
        node = tree
        for depth, label in enumerate(parts):
            rank = RANK_NAMES[depth] if depth < len(RANK_NAMES) else f"rank_{depth}"
            if label not in node:
                node[label] = {"_rank": rank, "_count": 0, "_children": {}}
            node[label]["_count"] += 1
            node = node[label]["_children"]

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
    paths = (
        DashboardNaturalProduct.objects
        .exclude(np_class_path="")
        .values_list("np_class_path", flat=True)
    )

    tree: dict = {}
    for path in paths:
        parts = path.split(".")
        l1 = parts[0] if len(parts) > 0 else ""
        l2 = parts[1] if len(parts) > 1 else ""
        l3 = parts[2] if len(parts) > 2 else ""

        if not l1:
            continue
        if l1 not in tree:
            tree[l1] = {"count": 0, "children": {}}
        tree[l1]["count"] += 1

        if l2:
            if l2 not in tree[l1]["children"]:
                tree[l1]["children"][l2] = {"count": 0, "children": {}}
            tree[l1]["children"][l2]["count"] += 1

            if l3:
                if l3 not in tree[l1]["children"][l2]["children"]:
                    tree[l1]["children"][l2]["children"][l3] = {"count": 0, "children": {}}
                tree[l1]["children"][l2]["children"][l3]["count"] += 1

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


@discovery_router.get("/filters/chemont-classes/", response=list[ChemOntClassNode])
def chemont_classes(request):
    """Return a hierarchical tree of ChemOnt classes with BGC counts.

    Uses the ChemOnt OBO ontology when available, otherwise falls back to
    building the tree from co-occurrence in the database (since the ingestion
    pipeline stores full lineage paths, every ancestor is present as a row).
    """
    # Direct annotation counts grouped by chemont_id.
    rows = list(
        NaturalProductChemOntClass.objects
        .values("chemont_id", "chemont_name")
        .annotate(cnt=Count("natural_product__bgc", distinct=True))
    )

    if not rows:
        return []

    direct_counts: dict[str, int] = {}
    name_map: dict[str, str] = {}
    for r in rows:
        direct_counts[r["chemont_id"]] = r["cnt"]
        name_map[r["chemont_id"]] = r["chemont_name"]

    annotated_ids = set(direct_counts.keys())

    # Try loading the ontology for hierarchy information.
    ont = None
    try:
        from common_core.chemont.ontology import get_ontology
        ont = get_ontology()
    except (FileNotFoundError, ImportError):
        pass

    # Build parent→children mapping.
    # Strategy: use the ontology if available, otherwise infer hierarchy from
    # co-occurrence patterns in the data.  Since the ETL stores full lineage
    # paths, if two annotated IDs share a parent-child relationship in the
    # ontology, both will be present in the DB.
    children_map: dict[str, list[str]] = {}
    root_ids: list[str] = []

    if ont is not None:
        # Ontology available: use real parent_ids.
        # Include ancestors of annotated terms so the tree is connected.
        relevant_ids = set(annotated_ids)
        for cid in list(annotated_ids):
            for ancestor in ont.get_ancestors(cid):
                relevant_ids.add(ancestor.id)
                if ancestor.id not in name_map:
                    name_map[ancestor.id] = ancestor.name

        for tid in relevant_ids:
            term = ont.get_term(tid)
            if term is None:
                if tid in annotated_ids:
                    root_ids.append(tid)
                continue
            has_relevant_parent = False
            for pid in term.parent_ids:
                if pid in relevant_ids:
                    children_map.setdefault(pid, []).append(tid)
                    has_relevant_parent = True
            if not has_relevant_parent:
                root_ids.append(tid)
    else:
        # No ontology: infer hierarchy from the annotated data itself.
        # NPs are annotated with full lineage paths, so for each NP the
        # annotated ChemOnt IDs form a chain.  We find parent-child pairs
        # by looking at which IDs always co-occur and have a subset
        # relationship on the NPs that reference them.
        #
        # Heuristic: for each pair (A, B) where A's NP set is a superset
        # of B's NP set AND A has more NPs, A is an ancestor of B.
        # We pick the *closest* ancestor (smallest superset) as the parent.
        id_to_nps: dict[str, set[int]] = {}
        for row in NaturalProductChemOntClass.objects.values_list(
            "chemont_id", "natural_product_id"
        ):
            id_to_nps.setdefault(row[0], set()).add(row[1])

        all_ids = list(annotated_ids)
        # For each term, find its parent = the term with the smallest
        # strict superset of NPs.
        parent_of: dict[str, str | None] = {}
        for cid in all_ids:
            my_nps = id_to_nps.get(cid, set())
            best_parent = None
            best_size = float("inf")
            for other in all_ids:
                if other == cid:
                    continue
                other_nps = id_to_nps.get(other, set())
                if my_nps < other_nps and len(other_nps) < best_size:
                    best_parent = other
                    best_size = len(other_nps)
            parent_of[cid] = best_parent

        for cid in all_ids:
            pid = parent_of[cid]
            if pid is not None:
                children_map.setdefault(pid, []).append(cid)
            else:
                root_ids.append(cid)

    # Propagate counts upward.
    def _count(tid: str) -> int:
        c = direct_counts.get(tid, 0)
        for child_id in children_map.get(tid, []):
            c += _count(child_id)
        return c

    def _build_tree(tid: str) -> ChemOntClassNode:
        return ChemOntClassNode(
            chemont_id=tid,
            name=name_map.get(tid, tid),
            count=_count(tid),
            children=sorted(
                [_build_tree(c) for c in children_map.get(tid, [])],
                key=lambda n: n.name,
            ),
        )

    return sorted(
        [_build_tree(r) for r in root_ids],
        key=lambda n: n.name,
    )


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


@discovery_router.get("/stats/assemblies/", response=AssemblyStatsResponse)
def assembly_stats(
    request,
    search: Optional[str] = None,
    taxonomy_path: Optional[str] = None,
    type_strain_only: bool = False,
    bgc_class: Optional[str] = None,
    biome_lineage: Optional[str] = None,
    bgc_accession: Optional[str] = None,
    assembly_accession: Optional[str] = None,
    assembly_ids: Optional[str] = None,
):
    qs = DashboardAssembly.objects.all()
    qs = _apply_assembly_filters(
        qs,
        assembly_ids=assembly_ids,
        type_strain_only=type_strain_only,
        taxonomy_path=taxonomy_path,
        search=search,
        bgc_class=bgc_class,
        biome_lineage=biome_lineage,
        bgc_accession=bgc_accession,
        assembly_accession=assembly_accession,
    )
    return compute_assembly_stats(qs)


@discovery_router.get("/stats/bgcs/", response=BgcStatsResponse)
def bgc_stats(
    request,
    assembly_ids: Optional[str] = None,
    bgc_ids: Optional[str] = None,
    tools: Optional[str] = None,
    include_all_versions: bool = False,
):
    qs = DashboardBgc.objects.all()
    if bgc_ids:
        ids = [int(x) for x in bgc_ids.split(",") if x.strip().isdigit()]
        qs = qs.filter(id__in=ids) if ids else qs.none()
    else:
        qs = _apply_bgc_filters(
            qs, assembly_ids=assembly_ids, tools=tools, include_all_versions=include_all_versions,
        )
    return compute_bgc_stats(qs)


@discovery_router.get("/stats/assemblies/export/")
def export_assembly_stats(
    request,
    format: str = "json",
    search: Optional[str] = None,
    taxonomy_path: Optional[str] = None,
    type_strain_only: bool = False,
    bgc_class: Optional[str] = None,
    biome_lineage: Optional[str] = None,
    bgc_accession: Optional[str] = None,
    assembly_accession: Optional[str] = None,
    assembly_ids: Optional[str] = None,
):
    qs = DashboardAssembly.objects.all()
    qs = _apply_assembly_filters(
        qs,
        assembly_ids=assembly_ids,
        type_strain_only=type_strain_only,
        taxonomy_path=taxonomy_path,
        search=search,
        bgc_class=bgc_class,
        biome_lineage=biome_lineage,
        bgc_accession=bgc_accession,
        assembly_accession=assembly_accession,
    )
    stats = compute_assembly_stats(qs)

    if format == "tsv":
        return _stats_to_tsv_response(stats, "assembly_stats.tsv")

    response = HttpResponse(
        json.dumps(stats, default=str),
        content_type="application/json",
    )
    response["Content-Disposition"] = 'attachment; filename="assembly_stats.json"'
    return response


@discovery_router.get("/stats/bgcs/export/")
def bgc_stats_export(
    request,
    format: str = "json",
    assembly_ids: Optional[str] = None,
    bgc_ids: Optional[str] = None,
    tools: Optional[str] = None,
    include_all_versions: bool = False,
):
    qs = DashboardBgc.objects.all()
    if bgc_ids:
        ids = [int(x) for x in bgc_ids.split(",") if x.strip().isdigit()]
        qs = qs.filter(id__in=ids) if ids else qs.none()
    else:
        qs = _apply_bgc_filters(
            qs, assembly_ids=assembly_ids, tools=tools, include_all_versions=include_all_versions,
        )
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


@discovery_router.post("/shortlist/assembly/export/")
def export_assembly_shortlist(request, body: ShortlistExportRequest):
    if not body.ids:
        raise HttpError(400, "No assembly IDs provided")
    if len(body.ids) > 20:
        raise HttpError(400, "Maximum 20 assemblies per export")

    assemblies = DashboardAssembly.objects.filter(id__in=body.ids)

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "accession", "organism_name",
        "biome_path",
        "is_type_strain", "type_strain_catalog_url",
        "assembly_size_mb",
        "bgc_count", "l1_class_count",
        "bgc_diversity_score", "bgc_novelty_score", "bgc_density", "taxonomic_novelty",
    ])

    for g in assemblies:
        writer.writerow([
            g.assembly_accession,
            g.organism_name,
            g.biome_path,
            g.is_type_strain, g.type_strain_catalog_url,
            g.assembly_size_mb or "",
            g.bgc_count, g.l1_class_count,
            g.bgc_diversity_score, g.bgc_novelty_score, g.bgc_density, g.taxonomic_novelty,
        ])

    response = HttpResponse(buf.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="assembly_shortlist.csv"'
    return response


@discovery_router.post("/shortlist/bgc/export/")
def export_bgc_shortlist(request, body: ShortlistExportRequest):
    """Export BGC shortlist as a multi-record GenBank file."""
    if not body.ids:
        raise HttpError(400, "No BGC IDs provided")
    if len(body.ids) > 20:
        raise HttpError(400, "Maximum 20 BGCs per export")

    from discovery.services.gbk import build_multi_bgc_gbk

    gbk_content = build_multi_bgc_gbk(body.ids)

    response = HttpResponse(gbk_content, content_type="application/octet-stream")
    response["Content-Disposition"] = 'attachment; filename="bgc_shortlist.gbk"'
    return response


# ── Assessment endpoints ─────────────────────────────────────────────────────


@discovery_router.post(
    "/assess/assembly/{assembly_id}/",
    response={202: AssessmentAccepted},
    tags=["Assessment"],
)
def assess_assembly(request, assembly_id: int):
    if not DashboardAssembly.objects.filter(pk=assembly_id).exists():
        raise HttpError(404, "Assembly not found")

    from discovery.tasks import assess_assembly as assess_assembly_task

    result = assess_assembly_task.delay(assembly_id)
    return 202, AssessmentAccepted(task_id=result.id, asset_type="assembly")


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
    "/assess/assembly/{assembly_id}/similar-assemblies/",
    response=list[int],
    tags=["Assessment"],
)
def similar_assemblies(request, assembly_id: int):
    if not DashboardAssembly.objects.filter(pk=assembly_id).exists():
        raise HttpError(404, "Assembly not found")

    from discovery.services.assessment import find_similar_assemblies

    return find_similar_assemblies(assembly_id, k=10)


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


@discovery_router.post(
    "/assess/upload/",
    response={202: AssessmentAccepted},
    tags=["Assessment"],
)
def upload_for_assessment(request):
    """Upload a .tar.gz / .tgz of TSV files for ephemeral asset evaluation.

    Expects a multipart form with:
    - ``type``: ``"bgc"`` or ``"assembly"``
    - ``file``: the .tar.gz or .tgz archive
    """
    from uuid import uuid4

    from django.core.cache import cache

    from discovery.services.upload_parser import (
        UploadValidationError,
        parse_assembly_upload,
        parse_bgc_upload,
    )

    upload_type = request.POST.get("type", "").strip()
    if upload_type not in ("bgc", "assembly"):
        raise HttpError(400, "type must be 'bgc' or 'assembly'")

    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        raise HttpError(400, "No file provided")
    name = (uploaded_file.name or "").lower()
    if not (name.endswith(".tar.gz") or name.endswith(".tgz")):
        raise HttpError(400, "File must be a .tar.gz or .tgz archive")
    if uploaded_file.size > 20 * 1024 * 1024:
        raise HttpError(400, "File too large (max 20 MB)")

    tar_bytes = uploaded_file.read()

    try:
        if upload_type == "bgc":
            parsed = parse_bgc_upload(tar_bytes)
        else:
            parsed = parse_assembly_upload(tar_bytes)
    except UploadValidationError as e:
        raise HttpError(400, str(e))

    upload_key = f"upload:{uuid4().hex}"
    cache.set(upload_key, parsed, 14_400)  # 4h TTL

    if upload_type == "bgc":
        from discovery.tasks import assess_uploaded_bgc

        result = assess_uploaded_bgc.delay(upload_key)
    else:
        from discovery.tasks import assess_uploaded_assembly

        result = assess_uploaded_assembly.delay(upload_key)

    return 202, AssessmentAccepted(task_id=result.id, asset_type=upload_type)


# ── Platform overview ─────────────────────────────────────────────────────────


@discovery_router.get("/stats/", response=DiscoveryStatsResponse)
def discovery_stats(request):
    """Latest Discovery Platform overview counts for the Run Query card."""
    latest = DiscoveryStats.objects.order_by("-created_at").first()
    if latest is None:
        return DiscoveryStatsResponse()
    return DiscoveryStatsResponse(**latest.stats, updated_at=latest.updated_at)
