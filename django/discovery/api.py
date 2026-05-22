"""Discovery Platform API — Django Ninja Router.

Mounted on the main NinjaAPI at /api/discovery/.

Fully self-contained: all endpoints query discovery models only.
No imports from mgnify_bgcs.

Status (v2 refactor): model renames + URL base flip done; the two new
endpoints ``GET /ibgcs/{id}/region/`` and ``GET /accessions/resolve/{acc}/``
are added below. Several filter paths that used the legacy FK chains
``ContigDomain → SourceBgcPrediction`` (reverse ``bgc_domains``),
``SourceBgcPrediction.region``, and per-prediction ``cds_list`` need a
range-overlap rewrite — they are flagged with ``# TODO(v2-range-overlap)``
inline. Search and per-prediction download paths are the affected
handlers; iBGC-keyed handlers are functional under the new schema.
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
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)
from django.http import HttpResponse
from ninja import Router
from ninja.errors import HttpError

from discovery.models import (
    AssemblySource,
    ContigDomain,
    ClusteringRun,
    SourceBgcPrediction,
    SourceBgcPredictionClass,
    ContigCds,
    CdsChemOnt,
    DashboardDetector,
    DashboardDomain,
    DashboardGCF,
    DashboardAssembly,
    IbgcNaturalProduct,
    DiscoveryStats,
    IntegratedBgc,
    PrecomputedStats,
)
from discovery.services.architecture import (
    bgc_architecture,
    collapse_to_interpro_rows,
    ibgc_architecture,
)
from discovery.services.stats import compute_bgc_stats, compute_assembly_stats
from discovery.api_schemas import (
    AssetStatusResponse,
    AssetUploadAccepted,
    SequenceQueryAccepted,
    SequenceQueryStatusResponse,
    BgcClassCount,
    BgcClassOption,
    BgcDetail,
    BgcRegionOut,
    BgcRosterItem,
    IbgcRegionOut,
    AccessionResolveOut,
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
    IbgcCountResponse,
    IbgcDetail,
    IbgcIdsResponse,
    IbgcMemberBgc,
    IbgcRosterItem,
    IbgcScatterPoint,
    IbgcUmapPoint,
    GcfOption,
    PaginatedDomainResponse,
    PaginatedGcfResponse,
    PaginatedIbgcRosterResponse,
    PaginatedSourceResponse,
    PaginatedDetectorResponse,
    ReportPayload,
    ReportSnapshotRequest,
    ReportSnapshotResponse,
    IbgcArchitectureQueryRequest,
    IbgcArchitectureResponse,
    SimilarIbgcRequest,
    SourceOption,
    DetectorOption,
    PaginatedAssemblyAggregationResponse,
    PaginatedAssemblyResponse,
    PaginatedQueryResultResponse,
    PaginationMeta,
    InterproAnnotationOut,
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


def _build_chemont_tree_from_cds(cds_chemont_rows) -> list[ChemOntAnnotationNode]:
    """Aggregate per-CDS ChemOnt rows into a hierarchical tree.

    *cds_chemont_rows* is an iterable of ``CdsChemOnt``-like objects
    (each carrying a single deepest ChemOnt class per CDS). Identical classes
    across CDSs are unified — ``probability`` is the max across rows and
    ``n_cds`` is the count.

    The ontology (if loaded) is used to fill in intermediate ancestors that
    connect annotated leaves; those ancestors are emitted with
    ``probability=None`` and ``n_cds`` equal to the sum of annotated descendants
    in this aggregation.
    """
    # Aggregate per chemont_id
    agg: dict[str, list] = {}  # cid -> [name, max_prob, n_cds]
    for r in cds_chemont_rows:
        cur = agg.get(r.chemont_id)
        if cur is None:
            agg[r.chemont_id] = [r.chemont_name, r.probability, 1]
        else:
            cur[1] = max(cur[1], r.probability)
            cur[2] += 1

    if not agg:
        return []

    annotated_ids = set(agg.keys())
    name_map: dict[str, str] = {cid: v[0] for cid, v in agg.items()}
    prob_map: dict[str, float] = {cid: v[1] for cid, v in agg.items()}
    n_cds_map: dict[str, int] = {cid: v[2] for cid, v in agg.items()}

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
        # Ontology available: walk to real ancestors and keep those that have
        # an annotated descendant.
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
        # No ontology — leaves only, no hierarchy.
        for cid in annotated_ids:
            roots.append(cid)
        depth_map = {cid: 0 for cid in annotated_ids}

    def _to_node(tid: str) -> ChemOntAnnotationNode:
        kid_ids = sorted(children_of.get(tid, []), key=lambda c: name_map.get(c, c))
        kid_nodes = [_to_node(c) for c in kid_ids]
        # n_cds: annotated terms keep their own count; intermediate ancestors
        # accumulate from descendants.
        if tid in n_cds_map:
            n_cds = n_cds_map[tid]
        else:
            n_cds = sum(k.n_cds for k in kid_nodes)
        return ChemOntAnnotationNode(
            chemont_id=tid,
            name=name_map.get(tid, tid),
            depth=depth_map.get(tid, 0),
            probability=prob_map.get(tid),  # None for intermediate ancestors
            n_cds=n_cds,
            children=kid_nodes,
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
    source_names: Optional[str] = None,
    detector_tools: Optional[str] = None,
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
    if source_names:
        names = [n.strip() for n in source_names.split(",") if n.strip()]
        if names:
            qs = qs.filter(source__name__in=names)
    if detector_tools:
        tools = [t.strip() for t in detector_tools.split(",") if t.strip()]
        if tools:
            qs = qs.filter(bgcs__detector__tool__in=tools).distinct()
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
            Q(contigs__ibgcs__gene_cluster_family__istartswith=bgc_class + ".")
            | Q(contigs__ibgcs__gene_cluster_family__iexact=bgc_class)
        ).distinct()
    if biome_lineage:
        qs = qs.filter(biome_path__icontains=biome_lineage)
    if bgc_accession:
        bgc_accession = bgc_accession.strip()
        upper = bgc_accession.upper()
        if "." in upper and upper.startswith("MGYB"):
            # Structured accession: exact match
            qs = qs.filter(source_bgcs__prediction_accession__iexact=bgc_accession).distinct()
        elif upper.startswith("MGYB") and "." not in upper:
            # cBGC accession (e.g. MGYB-ABC123). Resolve via the registry
            # (including any alias) and filter by the live cBGC id.
            from discovery.services.accession_registry import resolve as _acc_resolve

            resolved = _acc_resolve(upper)
            if resolved is not None and resolved.current_id is not None:
                qs = qs.filter(contigs__ibgcs__cbgc_id=resolved.current_id).distinct()
            else:
                qs = qs.filter(source_bgcs__prediction_accession__icontains=bgc_accession).distinct()
        else:
            qs = qs.filter(source_bgcs__prediction_accession__icontains=bgc_accession).distinct()
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
    """Apply common BGC filters to a SourceBgcPrediction queryset.

    Parameters
    ----------
    assembly_ids:
        Comma-separated DashboardAssembly pks. Restricts to BGCs belonging
        to those assemblies.
    bgc_ids:
        Comma-separated SourceBgcPrediction pks. Restricts to that exact set. Used
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
    source_names: Optional[str] = None,
    detector_tools: Optional[str] = None,
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
        source_names=source_names,
        detector_tools=detector_tools,
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
    bgcs = SourceBgcPrediction.objects.filter(assembly_id=assembly_id).order_by("-novelty_score")

    return [
        BgcRosterItem(
            id=bgc.id,
            accession=bgc.prediction_accession,
            classification_path=( bgc.integrated_bgc.gene_cluster_family if bgc.integrated_bgc_id else "" ),
            size_kb=bgc.size_kb,
            novelty_score=bgc.novelty_score,
            domain_novelty=bgc.domain_novelty,
            is_partial=bgc.is_partial,
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
    qs = SourceBgcPrediction.objects.select_related("assembly")
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
            accession=bgc.prediction_accession,
            classification_path=( bgc.integrated_bgc.gene_cluster_family if bgc.integrated_bgc_id else "" ),
            size_kb=bgc.size_kb,
            novelty_score=bgc.novelty_score,
            domain_novelty=bgc.domain_novelty,
            is_partial=bgc.is_partial,
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
        SourceBgcPrediction.objects.filter(id__in=ids)
        .values_list("assembly_id", flat=True)
        .distinct()
    )


@discovery_router.get("/assembly-scatter/", response=list[AssemblyScatterPoint])
def assembly_scatter(
    request,
    x_axis: str = "bgc_diversity_score",
    y_axis: str = "bgc_novelty_score",
    source_names: Optional[str] = None,
    detector_tools: Optional[str] = None,
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
    if source_names:
        names = [n.strip() for n in source_names.split(",") if n.strip()]
        if names:
            qs = qs.filter(source__name__in=names)
    if detector_tools:
        tools = [t.strip() for t in detector_tools.split(",") if t.strip()]
        if tools:
            qs = qs.filter(bgcs__detector__tool__in=tools).distinct()
    if taxonomy_path:
        from discovery.ltree import filter_contigs_by_taxonomy
        matching_contigs = filter_contigs_by_taxonomy(taxonomy_path)
        qs = qs.filter(contigs__in=matching_contigs).distinct()
    if bgc_class:
        qs = qs.filter(
            Q(contigs__ibgcs__gene_cluster_family__istartswith=bgc_class + ".")
            | Q(contigs__ibgcs__gene_cluster_family__iexact=bgc_class)
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
        bgc = SourceBgcPrediction.objects.select_related(
            "assembly", "assembly__source", "detector", "region",
        ).get(id=bgc_id)
    except SourceBgcPrediction.DoesNotExist:
        raise HttpError(404, "BGC not found")

    # Positional domain architecture pooled per BGC (PFAM + NCBIFAM hits,
    # ordered by CDS start then domain start). Shared with the iBGC-level
    # rollup so the surfaced sequence matches what the clustering pipeline
    # scored.
    domain_arch = [
        DomainArchitectureItem(
            domain_acc=r["domain_acc"],
            domain_name=r["domain_name"],
            ref_db=r["ref_db"],
            start=0,
            end=0,
            score=None,
            url=r["url"] or "",
        )
        for r in bgc_architecture(bgc.id)
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
            url=assembly.url or "",
        )

    # Curated natural products (CHAMOIS no longer feeds this table).
    np_items = []
    for np_obj in IbgcNaturalProduct.objects.filter(bgc=bgc):
        np_items.append(
            NaturalProductSummary(
                id=np_obj.id,
                name=np_obj.name,
                smiles=np_obj.smiles,
                smiles_svg="",
                structure_thumbnail=np_obj.structure_svg_base64,
                np_class_path=np_obj.np_class_path,
            )
        )

    # ChemOnt tree aggregated across all CDSs of this BGC.
    chemont_rows = CdsChemOnt.objects.filter(cds__bgc=bgc).only(
        "chemont_id", "chemont_name", "probability"
    )
    chemont_tree = _build_chemont_tree_from_cds(chemont_rows)

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
        accession=bgc.prediction_accession,
        classification_path=( bgc.integrated_bgc.gene_cluster_family if bgc.integrated_bgc_id else "" ),
        size_kb=bgc.size_kb,
        novelty_score=bgc.novelty_score,
        domain_novelty=bgc.domain_novelty,
        is_partial=bgc.is_partial,
        is_validated=bgc.is_validated,
        domain_architecture=domain_arch,
        parent_assembly=parent,
        natural_products=np_items,
        chemont_tree=chemont_tree,
        detector=detector_out,
        region_accession=region_acc,
    )


def _build_bgc_region_data(bgc: SourceBgcPrediction) -> BgcRegionOut:
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
        ContigCds.objects.filter(
            bgc=bgc,
            start_position__lte=window_end,
            end_position__gte=window_start,
        )
        .prefetch_related("domains", "seq", "chemont")
        .order_by("start_position")
    )

    cds_list = []
    domain_list = []

    for cds in cds_qs:
        pfam_rows = []
        # Sorted by start_position so the Protein Information card and the
        # CDS hover tooltip both render domains in N→C order.
        sorted_domains = sorted(cds.domains.all(), key=lambda d: d.start_position)
        for bd in sorted_domains:
            pfam_rows.append(
                PfamAnnotationOut(
                    accession=bd.domain_acc,
                    description=bd.domain_description or bd.domain_name or "",
                    go_slim=list(bd.go_slim or []),
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
                    go_slim=list(bd.go_slim or []),
                    parent_cds_id=cds.protein_id_str,
                    url=bd.url,
                )
            )

        # Non-redundant InterPro annotations for the Protein Information
        # card (deduped by interpro_entry_acc, fallback to signature acc).
        interpro_rows = [
            InterproAnnotationOut(**row)
            for row in collapse_to_interpro_rows(sorted_domains)
        ]

        rep = cds.cluster_representative

        # At most one chemont row per CDS (UniqueConstraint on (cds, chemont_id)
        # plus the converter emits a single deepest class per CDS).
        chemont_row = next(iter(cds.chemont.all()), None)

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
                interpro=interpro_rows,
                chemont_id=chemont_row.chemont_id if chemont_row else None,
                chemont_name=chemont_row.chemont_name if chemont_row else None,
                chemont_probability=chemont_row.probability if chemont_row else None,
                chemont_weight=chemont_row.weight if chemont_row else None,
            )
        )

    # Overlapping BGC clusters in the same contig region
    overlapping_bgcs = SourceBgcPrediction.objects.filter(
        contig=bgc.contig,
        start_position__lte=window_end,
        end_position__gte=window_start,
    ).select_related("detector")
    cluster_list = [
        RegionClusterOut(
            accession=ob.prediction_accession,
            start=max(0, ob.start_position - window_start),
            end=max(0, ob.end_position - window_start),
            source=ob.detector.name if ob.detector else "",
            bgc_classes=[( ob.integrated_bgc.gene_cluster_family if ob.integrated_bgc_id else "" ).split(".")[0]] if ( ob.integrated_bgc.gene_cluster_family if ob.integrated_bgc_id else "" ) else [],
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

    Served entirely from discovery models (ContigCds, ContigDomain).
    Negative ``bgc_id`` resolves to an asset iBGC's region payload via the
    ``X-Asset-Token`` header — keeps the path schema stable while still
    routing through the ephemeral cache.
    """
    if bgc_id < 0:
        token = request.headers.get("X-Asset-Token") or request.GET.get("asset_token")
        if not token:
            raise HttpError(404, "Asset token required for asset BGC")
        from discovery.services.asset_upload import cache as asset_cache

        payload = asset_cache.read_region(token, bgc_id)
        if payload is None:
            raise HttpError(404, "Asset BGC not found or expired")
        return BgcRegionOut(**payload)

    try:
        bgc = SourceBgcPrediction.objects.get(id=bgc_id)
    except SourceBgcPrediction.DoesNotExist:
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
            SourceBgcPrediction.objects.select_related("assembly", "contig", "contig__seq")
            .prefetch_related("cds_list", "cds_list__seq")
            .get(id=bgc_id)
        )
    except SourceBgcPrediction.DoesNotExist:
        raise HttpError(404, "BGC not found")

    accession = bgc.prediction_accession

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

    qs = SourceBgcPrediction.objects.all()

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
            bgc_class=( bgc.integrated_bgc.gene_cluster_family if bgc.integrated_bgc_id else "" ).split(".")[0] if ( bgc.integrated_bgc.gene_cluster_family if bgc.integrated_bgc_id else "" ) else "",
            is_validated=bgc.is_validated,
            compound_name=None,
            novelty_score=bgc.novelty_score,
            domain_novelty=bgc.domain_novelty,
        )
        for bgc in qs
    ]

    return points


# ── iBGC (Integrated BGC) endpoints ────────────────────────────────────────


_IBGC_AXES = {
    "size_kb",  # length / 1000
    "n_cds",
    "novelty_score",
    "domain_novelty",
    "similarity_score",  # populated only from a similarity query context
}

# Soft cap applied uniformly across the dashboard's "show me all matching
# iBGCs" surfaces: /ibgcs/umap/ (map points), /ibgcs/scatter/ (Variables map
# points), and the client-side top-K clip on scored query results. The
# roster paginates and is *not* capped here. ``/ibgcs/count/`` surfaces this
# value so the UI can warn before firing the heavier requests.
DASHBOARD_RESULT_CAP = 5_000


def _ibgc_label(ibgc_id: int) -> str:
    return f"iBGC-{ibgc_id}"


def _pick_representative_ibgc_id(ibgc_id: int) -> Optional[int]:
    """Lowest-id source SourceBgcPrediction for an iBGC (deterministic)."""
    return (
        SourceBgcPrediction.objects
        .filter(integrated_bgc_id=ibgc_id)
        .order_by("id")
        .values_list("id", flat=True)
        .first()
    )


def _ibgc_is_partial(ibgc: IntegratedBgc) -> bool:
    """An iBGC is "partial" when it didn't go through the primary clustering
    pass — either no clustering run touched it, or it was projected from a
    KNN average of its primary neighbours (``umap_projected=True``)."""
    return bool(ibgc.umap_projected) or ibgc.classification_run_id is None


# ── Asset-iBGC injection helpers ───────────────────────────────────────────
#
# Uploaded assets are stored in Redis under ``asset:{token}:*`` and never hit
# the DB. Negative ids mark them everywhere — the dispatcher in this module
# routes ``ibgc_id < 0`` to the cache instead of the ORM. Asset iBGCs bypass
# every filter ("always shown in results") per the locked product decision.


def _get_asset_roster_rows(asset_token: Optional[str]) -> list[dict]:
    if not asset_token:
        return []
    from discovery.services.asset_upload import cache as asset_cache

    return list(asset_cache.read_ibgc_list(asset_token) or [])


def _asset_only_mode(
    asset_token: Optional[str], parsed_ids: Optional[list[int]]
) -> bool:
    """Return True when the iBGC endpoints should skip the DB queryset.

    An uploaded asset narrows the dashboard to its own iBGCs by default;
    DB rows only re-enter the response when the caller supplies an explicit
    ``ibgc_ids`` allow-list (i.e. a Run Query result from one of the
    sequence/domain/chemical/similar-iBGC search endpoints). Pure chip /
    slider filters alone are not enough.
    """
    return bool(asset_token) and not parsed_ids


def _asset_row_to_roster_item(row: dict) -> IbgcRosterItem:
    return IbgcRosterItem(
        id=int(row["id"]),
        label=row.get("label", ""),
        classification_path=row.get("classification_path", "") or "",
        size_kb=float(row.get("size_kb", 0.0) or 0.0),
        n_source_bgcs=int(row.get("n_source_bgcs", 0) or 0),
        source_tools=list(row.get("source_tools") or []),
        novelty_score=row.get("novelty_score"),
        domain_novelty=row.get("domain_novelty"),
        is_partial=bool(row.get("is_partial", False)),
        is_validated=bool(row.get("is_validated", False)),
        is_type_strain=bool(row.get("is_type_strain", False)),
        umap_projected=bool(row.get("umap_projected", False)),
        parent_assembly_id=row.get("parent_assembly_id"),
        parent_assembly_accession=row.get("parent_assembly_accession"),
        organism_name=row.get("organism_name"),
        contig_accession=row.get("contig_accession"),
        similarity_score=row.get("similarity_score"),
        best_hit_protein_id=row.get("best_hit_protein_id"),
        best_pident=row.get("best_pident"),
        best_qcoverage=row.get("best_qcoverage"),
        is_asset=True,
    )


def _asset_row_to_umap_point(row: dict) -> Optional[IbgcUmapPoint]:
    if row.get("umap_x") is None or row.get("umap_y") is None:
        return None
    return IbgcUmapPoint(
        id=int(row["id"]),
        label=row.get("label", ""),
        umap_x=float(row["umap_x"]),
        umap_y=float(row["umap_y"]),
        classification_path=row.get("classification_path", "") or "",
        novelty_score=row.get("novelty_score"),
        is_partial=bool(row.get("is_partial", False)),
        is_validated=bool(row.get("is_validated", False)),
        is_type_strain=bool(row.get("is_type_strain", False)),
        umap_projected=bool(row.get("umap_projected", False)),
        is_asset=True,
    )


def _asset_row_to_scatter_point(
    row: dict, x_axis: str, y_axis: str
) -> Optional[IbgcScatterPoint]:
    # Asset rows expose the same numeric columns the DB rows do (novelty_score,
    # domain_novelty, size_kb). For non-existent axes we drop the point so the
    # surface stays consistent with the DB-row behaviour.
    axis_value: dict[str, Optional[float]] = {
        "novelty_score": row.get("novelty_score"),
        "domain_novelty": row.get("domain_novelty"),
        "size_kb": row.get("size_kb"),
    }
    x_val = axis_value.get(x_axis)
    y_val = axis_value.get(y_axis)
    if x_val is None or y_val is None:
        return None
    return IbgcScatterPoint(
        id=int(row["id"]),
        x=float(x_val),
        y=float(y_val),
        classification_path=row.get("classification_path", "") or "",
        novelty_score=row.get("novelty_score"),
        domain_novelty=row.get("domain_novelty"),
        is_partial=bool(row.get("is_partial", False)),
        is_validated=bool(row.get("is_validated", False)),
        is_type_strain=bool(row.get("is_type_strain", False)),
        umap_projected=bool(row.get("umap_projected", False)),
        is_asset=True,
    )


def _ibgc_to_roster_item(
    ibgc: IntegratedBgc,
    *,
    parent_assembly: Optional[DashboardAssembly] = None,
    n_source_bgcs: int = 0,
    is_validated: bool = False,
    is_type_strain: bool = False,
    contig_accession: Optional[str] = None,
    similarity_score: Optional[float] = None,
    best_hit_protein_id: Optional[str] = None,
    best_pident: Optional[float] = None,
    best_qcoverage: Optional[float] = None,
) -> IbgcRosterItem:
    return IbgcRosterItem(
        id=ibgc.id,
        label=_ibgc_label(ibgc.id),
        classification_path=ibgc.gene_cluster_family or "",
        size_kb=round((ibgc.end_position - ibgc.start_position) / 1000.0, 3),
        n_source_bgcs=n_source_bgcs,
        source_tools=list(ibgc.source_tools or []),
        novelty_score=ibgc.novelty_score,
        domain_novelty=ibgc.domain_novelty,
        is_partial=_ibgc_is_partial(ibgc),
        is_validated=is_validated,
        is_type_strain=is_type_strain,
        umap_projected=ibgc.umap_projected,
        parent_assembly_id=parent_assembly.id if parent_assembly else None,
        parent_assembly_accession=(
            parent_assembly.assembly_accession if parent_assembly else None
        ),
        organism_name=parent_assembly.organism_name if parent_assembly else None,
        contig_accession=contig_accession,
        similarity_score=similarity_score,
        best_hit_protein_id=best_hit_protein_id,
        best_pident=best_pident,
        best_qcoverage=best_qcoverage,
    )


# Keep each `IN (...)` clause well under sqlparse's 10k-token cap (which
# Django's DEBUG-mode SQL logger trips on). At ~3 tokens per id (digits,
# comma, space) 500 ids is comfortably below the ceiling.
_MEMBER_FACTS_CHUNK = 500


def _ibgc_member_facts(ibgc_ids: list[int]) -> dict[int, dict]:
    """Return per-iBGC aggregates: ``n_source_bgcs``, ``is_validated``,
    ``is_type_strain``, ``parent_assembly``, ``contig_accession``.

    ``is_type_strain`` is ORed across every member BGC's parent assembly so
    an iBGC is flagged whenever *any* of its source BGCs sits on a
    type-strain assembly. Mirrors the ``is_validated`` accumulator.

    The SourceBgcPrediction lookup is chunked so the generated SQL stays under the
    DEBUG-mode SQL formatter's token limit on large id lists (umap / scatter
    can request several thousand iBGCs in one call).
    """
    facts: dict[int, dict] = {
        nid: {
            "n_source_bgcs": 0,
            "is_validated": False,
            "is_type_strain": False,
            "parent_assembly": None,
            "contig_accession": None,
        }
        for nid in ibgc_ids
    }
    for i in range(0, len(ibgc_ids), _MEMBER_FACTS_CHUNK):
        chunk = ibgc_ids[i: i + _MEMBER_FACTS_CHUNK]
        rows = (
            SourceBgcPrediction.objects
            .filter(integrated_bgc_id__in=chunk)
            .select_related("assembly", "contig")
            .values(
                "integrated_bgc_id", "is_validated",
                "assembly_id", "assembly__assembly_accession",
                "assembly__organism_name",
                "assembly__is_type_strain",
                "contig__accession",
            )
        )
        for r in rows:
            nid = r["integrated_bgc_id"]
            f = facts.get(nid)
            if not f:
                continue
            f["n_source_bgcs"] += 1
            f["is_validated"] = f["is_validated"] or bool(r["is_validated"])
            f["is_type_strain"] = (
                f["is_type_strain"] or bool(r["assembly__is_type_strain"])
            )
            if f["parent_assembly"] is None and r["assembly_id"]:
                f["parent_assembly"] = type("AsmStub", (), {
                    "id": r["assembly_id"],
                    "assembly_accession": r["assembly__assembly_accession"],
                    "organism_name": r["assembly__organism_name"],
                })()
            if not f["contig_accession"]:
                f["contig_accession"] = r["contig__accession"]
    return facts


def _apply_ibgc_filters(
    qs,
    *,
    include_partials: bool = True,
    validated_only: bool = False,
    min_length_kb: Optional[float] = None,
    max_length_kb: Optional[float] = None,
    min_novelty: Optional[float] = None,
    max_novelty: Optional[float] = None,
    min_domain_novelty: Optional[float] = None,
    max_domain_novelty: Optional[float] = None,
    detector_tools: Optional[str] = None,  # CSV; "any of" on iBGC.source_tools JSON
    source_tools: Optional[str] = None,    # Deprecated alias for detector_tools
    source_names: Optional[str] = None,    # CSV of AssemblySource.name
    assembly_type: Optional[str] = None,   # AssemblyType label (metagenome/genome/region)
    leaf_path_prefix: Optional[str] = None,
    bgc_class: Optional[str] = None,
    chemont_ids: Optional[str] = None,     # CSV of ChemOnt class ids
    bgc_accession: Optional[str] = None,
    assembly_accession: Optional[str] = None,
    assembly_ids: Optional[str] = None,    # CSV of DashboardAssembly ids
    organism: Optional[str] = None,
    biome_lineage: Optional[str] = None,
    taxonomy_path: Optional[str] = None,
    ibgc_ids: Optional[list[int]] = None,
):
    """Apply iBGC-level filters to a ``IntegratedBgc`` queryset.

    Used by ``/ibgcs/roster/``, ``/ibgcs/umap/``, ``/ibgcs/scatter/`` and the
    iBGC-collapsed query endpoints (``/query/ibgc-domain/``,
    ``/query/ibgc-sequence/status/``) so the same filter surface is
    available regardless of how the initial iBGC id set was produced.

    ``detector_tools`` filters on the iBGC's ``source_tools`` JSON column
    (which stores the contributing detection tools, e.g. ``antiSMASH``,
    ``MIBiG``, ``GECCO``, ``SanntiS``). ``source_tools`` is kept as a
    deprecated alias so old callers continue to work.

    Joins through ``source_bgcs → assembly`` are used for
    ``source_names``, ``assembly_type``, ``assembly_ids`` and
    ``bgc_accession``; through ``source_bgcs → cds_list → chemont`` for
    ``chemont_ids``. All such filters apply ``.distinct()``.
    """
    if ibgc_ids is not None:
        qs = qs.filter(id__in=ibgc_ids)
    if not include_partials:
        # Primary iBGCs only: row was clustered directly (not projected) and
        # has a classification run.
        qs = qs.filter(classification_run_id__isnull=False, umap_projected=False)
    if validated_only:
        qs = qs.filter(source_predictions__is_validated=True).distinct()
    if min_length_kb is not None:
        qs = qs.filter(end_position__gte=F("start_position") + int(min_length_kb * 1000))
    if max_length_kb is not None:
        qs = qs.filter(end_position__lte=F("start_position") + int(max_length_kb * 1000))
    if min_novelty is not None:
        qs = qs.filter(novelty_score__gte=min_novelty)
    if max_novelty is not None:
        qs = qs.filter(novelty_score__lte=max_novelty)
    if min_domain_novelty is not None:
        qs = qs.filter(domain_novelty__gte=min_domain_novelty)
    if max_domain_novelty is not None:
        qs = qs.filter(domain_novelty__lte=max_domain_novelty)
    # ── Detector tools (iBGC.source_tools JSON, "any of") ───────────────────
    detector_csv = detector_tools or source_tools
    if detector_csv:
        tools = [t.strip() for t in detector_csv.split(",") if t.strip()]
        if tools:
            # JSONField "any of" — Postgres ?| operator: at least one tool
            # in `tools` is present in the iBGC's source_tools array.
            tool_q = Q()
            for t in tools:
                tool_q |= Q(source_tools__contains=[t])
            qs = qs.filter(tool_q)
    if source_names:
        names = [n.strip() for n in source_names.split(",") if n.strip()]
        if names:
            qs = qs.filter(
                source_predictions__assembly__source__name__in=names
            ).distinct()
    if assembly_type:
        from discovery.models import AssemblyType
        type_map = {v.label: v.value for v in AssemblyType}
        key = assembly_type.strip().lower()
        if key in type_map:
            qs = qs.filter(
                source_predictions__assembly__assembly_type=type_map[key]
            ).distinct()
    if leaf_path_prefix:
        # leaf_path_prefix targets the cluster-family ltree on the iBGC
        # itself (e.g. "cluster.0042"); see ``ClusteringRun`` outputs.
        qs = qs.filter(
            Q(gene_cluster_family__istartswith=leaf_path_prefix + ".")
            | Q(gene_cluster_family__iexact=leaf_path_prefix)
        )
    if bgc_class:
        # ``bgc_class`` is the chemical class (e.g. "Polyketide") served
        # by /filters/bgc-classes/ and stored on each source BGC's
        # ``classification_path`` ltree — NOT on the iBGC's
        # ``gene_cluster_family`` (which is the cluster path). Join
        # through ``source_bgcs`` so the filter actually matches.
        qs = qs.filter(
            Q(gene_cluster_family__istartswith=bgc_class + ".")
            | Q(gene_cluster_family__iexact=bgc_class)
        ).distinct()
    if chemont_ids:
        ids = [c.strip() for c in chemont_ids.split(",") if c.strip()]
        if ids:
            qs = qs.filter(
                source_predictions__integrated_bgc__contig__cds_list__chemont__chemont_id__in=ids  # TODO(v2-range-overlap): scope by bgc_range && cds_range
            ).distinct()
    if bgc_accession:
        # Reuse the assembly-side MGYB-aware semantics: structured accession
        # → exact match; bare MGYBxxx region accession → match by region id
        # or alias; everything else → substring.
        acc = bgc_accession.strip()
        upper = acc.upper()
        if "." in upper and upper.startswith("MGYB"):
            qs = qs.filter(source_predictions__prediction_accession__iexact=acc).distinct()
        elif upper.startswith("MGYB") and "." not in upper:
            # cBGC accession (e.g. MGYB-ABC123). Resolve via the registry,
            # then filter iBGCs by their cBGC parent.
            from discovery.services.accession_registry import resolve as _acc_resolve

            resolved = _acc_resolve(upper)
            if resolved is not None and resolved.current_id is not None:
                qs = qs.filter(cbgc_id=resolved.current_id).distinct()
            else:
                qs = qs.filter(
                    source_predictions__prediction_accession__icontains=acc
                ).distinct()
        else:
            qs = qs.filter(
                source_predictions__prediction_accession__icontains=acc
            ).distinct()
    if assembly_accession:
        qs = qs.filter(
            source_predictions__assembly__assembly_accession__icontains=assembly_accession.strip()
        ).distinct()
    if assembly_ids:
        ids = [int(x) for x in assembly_ids.split(",") if x.strip().isdigit()]
        if ids:
            qs = qs.filter(source_predictions__assembly_id__in=ids).distinct()
        else:
            qs = qs.none()
    if organism:
        qs = qs.filter(
            source_predictions__assembly__organism_name__icontains=organism.strip()
        ).distinct()
    if biome_lineage:
        qs = qs.filter(
            source_predictions__assembly__biome_path__icontains=biome_lineage.strip()
        ).distinct()
    if taxonomy_path:
        from discovery.ltree import filter_contigs_by_taxonomy
        qs = qs.filter(
            contig__in=filter_contigs_by_taxonomy(taxonomy_path)
        ).distinct()
    return qs


@discovery_router.get("/ibgcs/count/", response=IbgcCountResponse)
def ibgc_count(
    request,
    include_partials: bool = True,
    validated_only: bool = False,
    min_length_kb: Optional[float] = None,
    max_length_kb: Optional[float] = None,
    min_novelty: Optional[float] = None,
    max_novelty: Optional[float] = None,
    min_domain_novelty: Optional[float] = None,
    max_domain_novelty: Optional[float] = None,
    detector_tools: Optional[str] = None,
    source_tools: Optional[str] = None,  # deprecated alias for detector_tools
    source_names: Optional[str] = None,
    assembly_type: Optional[str] = None,
    leaf_path_prefix: Optional[str] = None,
    bgc_class: Optional[str] = None,
    chemont_ids: Optional[str] = None,
    bgc_accession: Optional[str] = None,
    assembly_accession: Optional[str] = None,
    assembly_ids: Optional[str] = None,
    organism: Optional[str] = None,
    biome_lineage: Optional[str] = None,
    taxonomy_path: Optional[str] = None,
    ibgc_ids: Optional[str] = None,
    asset_token: Optional[str] = None,
):
    """Cheap COUNT over the iBGC filter surface.

    The v2 dashboard hits this before firing /ibgcs/roster/, /ibgcs/umap/ and
    /ibgcs/scatter/ so it can (a) gate the empty-state CTA when no scope is
    set and (b) warn the user when the result will be sampled by the maps
    (count > ``DASHBOARD_RESULT_CAP``).
    """
    parsed_ids: Optional[list[int]] = None
    if ibgc_ids:
        parsed_ids = [
            int(x) for x in ibgc_ids.split(",") if x.strip().isdigit()
        ] or None

    asset_rows = _get_asset_roster_rows(asset_token)
    if _asset_only_mode(asset_token, parsed_ids):
        total = len(asset_rows)
    else:
        qs = _apply_ibgc_filters(
            IntegratedBgc.objects.all(),
            ibgc_ids=parsed_ids,
            include_partials=include_partials,
            validated_only=validated_only,
            min_length_kb=min_length_kb,
            max_length_kb=max_length_kb,
            min_novelty=min_novelty,
            max_novelty=max_novelty,
            min_domain_novelty=min_domain_novelty,
            max_domain_novelty=max_domain_novelty,
            detector_tools=detector_tools,
            source_tools=source_tools,
            source_names=source_names,
            assembly_type=assembly_type,
            leaf_path_prefix=leaf_path_prefix,
            bgc_class=bgc_class,
            chemont_ids=chemont_ids,
            bgc_accession=bgc_accession,
            assembly_accession=assembly_accession,
            assembly_ids=assembly_ids,
            organism=organism,
            biome_lineage=biome_lineage,
            taxonomy_path=taxonomy_path,
        )
        total = qs.count() + len(asset_rows)
    return IbgcCountResponse(
        exact_count=total,
        cap=DASHBOARD_RESULT_CAP,
        will_sample=total > DASHBOARD_RESULT_CAP,
    )


@discovery_router.get("/ibgcs/roster/", response=PaginatedIbgcRosterResponse)
def ibgc_roster(
    request,
    sort_by: str = "novelty_score",
    order: str = "desc",
    page: int = 1,
    page_size: int = 25,
    include_partials: bool = True,
    validated_only: bool = False,
    min_length_kb: Optional[float] = None,
    max_length_kb: Optional[float] = None,
    min_novelty: Optional[float] = None,
    max_novelty: Optional[float] = None,
    min_domain_novelty: Optional[float] = None,
    max_domain_novelty: Optional[float] = None,
    detector_tools: Optional[str] = None,
    source_tools: Optional[str] = None,  # deprecated alias for detector_tools
    source_names: Optional[str] = None,
    assembly_type: Optional[str] = None,
    leaf_path_prefix: Optional[str] = None,
    bgc_class: Optional[str] = None,
    chemont_ids: Optional[str] = None,
    bgc_accession: Optional[str] = None,
    assembly_accession: Optional[str] = None,
    assembly_ids: Optional[str] = None,
    organism: Optional[str] = None,
    biome_lineage: Optional[str] = None,
    taxonomy_path: Optional[str] = None,
    ibgc_ids: Optional[str] = None,
    asset_token: Optional[str] = None,
):
    """Paginated, filterable iBGC roster (v2 Discovery primary unit).

    ``ibgc_ids`` is an optional comma-separated id allow-list so the dashboard
    can refilter to a Run Query result set without re-issuing the query.
    ``asset_token`` pre-pends ephemeral asset iBGCs (negative ids) ahead of
    the DB rows on page 1; they bypass filters and always render.
    """
    parsed_ids: Optional[list[int]] = None
    if ibgc_ids:
        parsed_ids = [
            int(x) for x in ibgc_ids.split(",") if x.strip().isdigit()
        ] or None

    asset_only = _asset_only_mode(asset_token, parsed_ids)
    if asset_only:
        qs = IntegratedBgc.objects.none()
    else:
        qs = _apply_ibgc_filters(
            IntegratedBgc.objects.all(),
            ibgc_ids=parsed_ids,
            include_partials=include_partials,
            validated_only=validated_only,
            min_length_kb=min_length_kb,
            max_length_kb=max_length_kb,
            min_novelty=min_novelty,
            max_novelty=max_novelty,
            min_domain_novelty=min_domain_novelty,
            max_domain_novelty=max_domain_novelty,
            detector_tools=detector_tools,
            source_tools=source_tools,
            source_names=source_names,
            assembly_type=assembly_type,
            leaf_path_prefix=leaf_path_prefix,
            bgc_class=bgc_class,
            chemont_ids=chemont_ids,
            bgc_accession=bgc_accession,
            assembly_accession=assembly_accession,
            assembly_ids=assembly_ids,
            organism=organism,
            biome_lineage=biome_lineage,
            taxonomy_path=taxonomy_path,
        )

    # Special-case: ``sort_by=similarity`` honours the caller-supplied order
    # of ``ibgc_ids`` (the dashboard passes them in similarity-descending order
    # after Find Similar iBGCs). Postgres ``array_position`` returns the 1-based
    # index of each row's id in the input array, so ORDER BY that index gives
    # us the exact rank we want. ``order=asc`` reverses the list to flip the
    # sense. Falls back to novelty_score when ibgc_ids is missing.
    if sort_by == "similarity" and parsed_ids:
        from django.db.models import IntegerField
        from django.db.models.expressions import RawSQL
        ordered_ids = list(parsed_ids) if order != "asc" else list(reversed(parsed_ids))
        # The roster queryset may join discovery_bgc / discovery_assembly when
        # a chip filter is active, so qualify the id column to avoid an
        # ``ambiguous column "id"`` error from Postgres.
        ibgc_id_col = f"{IntegratedBgc._meta.db_table}.id"
        qs = qs.annotate(
            _sim_pos=RawSQL(
                f"array_position(%s::int[], {ibgc_id_col})",
                [ordered_ids],
                output_field=IntegerField(),
            )
        ).order_by("_sim_pos")
    else:
        sort_map = {
            "novelty_score": "novelty_score",
            "domain_novelty": "domain_novelty",
            "classification_path": "gene_cluster_family",
            "id": "id",
        }
        if sort_by == "size_kb":
            qs = qs.annotate(_size=F("end_position") - F("start_position"))
            order_field = "_size"
        else:
            order_field = sort_map.get(sort_by, "novelty_score")
        descending = order == "desc"
        # NULLS LAST keeps unscored partials out of the head of the page.
        qs = qs.order_by(
            F(order_field).desc(nulls_last=True) if descending
            else F(order_field).asc(nulls_last=True)
        )

    asset_rows = _get_asset_roster_rows(asset_token)
    asset_items = [_asset_row_to_roster_item(r) for r in asset_rows]
    db_total = qs.count()
    total_count = db_total + len(asset_items)
    pg, ps, tp, offset = _paginate(page, page_size, total_count)

    # Asset rows always sit at the very top — they bypass filters and the
    # roster's sort, so they only land in the slice covering global offset 0.
    asset_slice: list[IbgcRosterItem] = []
    db_offset = offset
    db_limit = ps
    if offset < len(asset_items):
        asset_slice = asset_items[offset : offset + ps]
        db_limit = max(0, ps - len(asset_slice))
        db_offset = 0
    else:
        db_offset = offset - len(asset_items)

    page_qs = (
        list(qs[db_offset : db_offset + db_limit]) if db_limit > 0 else []
    )

    facts = _ibgc_member_facts([ibgc.id for ibgc in page_qs])
    db_items = [
        _ibgc_to_roster_item(
            ibgc,
            parent_assembly=facts[ibgc.id]["parent_assembly"],
            n_source_bgcs=facts[ibgc.id]["n_source_bgcs"],
            is_validated=facts[ibgc.id]["is_validated"],
            is_type_strain=facts[ibgc.id]["is_type_strain"],
            contig_accession=facts[ibgc.id]["contig_accession"],
        )
        for ibgc in page_qs
    ]
    return PaginatedIbgcRosterResponse(
        items=asset_slice + db_items,
        pagination=PaginationMeta(
            page=pg, page_size=ps, total_count=total_count, total_pages=tp,
        ),
    )


# Cap on /ibgcs/ids/ so "Add all to shortlist" can fill the 1000-iBGC
# shortlist in a single fetch without ever loading unbounded result sets.
IBGC_IDS_MAX = 1_000


@discovery_router.get("/ibgcs/ids/", response=IbgcIdsResponse)
def ibgc_ids(
    request,
    sort_by: str = "novelty_score",
    order: str = "desc",
    include_partials: bool = True,
    validated_only: bool = False,
    min_length_kb: Optional[float] = None,
    max_length_kb: Optional[float] = None,
    min_novelty: Optional[float] = None,
    max_novelty: Optional[float] = None,
    min_domain_novelty: Optional[float] = None,
    max_domain_novelty: Optional[float] = None,
    detector_tools: Optional[str] = None,
    source_tools: Optional[str] = None,  # deprecated alias
    source_names: Optional[str] = None,
    assembly_type: Optional[str] = None,
    leaf_path_prefix: Optional[str] = None,
    bgc_class: Optional[str] = None,
    chemont_ids: Optional[str] = None,
    bgc_accession: Optional[str] = None,
    assembly_accession: Optional[str] = None,
    assembly_ids: Optional[str] = None,
    organism: Optional[str] = None,
    biome_lineage: Optional[str] = None,
    taxonomy_path: Optional[str] = None,
    ibgc_ids: Optional[str] = None,
    asset_token: Optional[str] = None,
):
    """Bulk iBGC ids matching the same filter surface as ``/ibgcs/roster/``.

    Cheaper than the roster (no row hydration, no asset enrichment beyond
    raw ids); capped at ``IBGC_IDS_MAX`` so callers can size buffers up
    front. Honors ``sort_by`` / ``order`` so the returned ordering matches
    what the roster would show. ``truncated=True`` when the filter would
    have matched more rows than the cap.
    """
    parsed_ids: Optional[list[int]] = None
    if ibgc_ids:
        parsed_ids = [
            int(x) for x in ibgc_ids.split(",") if x.strip().isdigit()
        ] or None

    asset_only = _asset_only_mode(asset_token, parsed_ids)
    if asset_only:
        qs = IntegratedBgc.objects.none()
    else:
        qs = _apply_ibgc_filters(
            IntegratedBgc.objects.all(),
            ibgc_ids=parsed_ids,
            include_partials=include_partials,
            validated_only=validated_only,
            min_length_kb=min_length_kb,
            max_length_kb=max_length_kb,
            min_novelty=min_novelty,
            max_novelty=max_novelty,
            min_domain_novelty=min_domain_novelty,
            max_domain_novelty=max_domain_novelty,
            detector_tools=detector_tools,
            source_tools=source_tools,
            source_names=source_names,
            assembly_type=assembly_type,
            leaf_path_prefix=leaf_path_prefix,
            bgc_class=bgc_class,
            chemont_ids=chemont_ids,
            bgc_accession=bgc_accession,
            assembly_accession=assembly_accession,
            assembly_ids=assembly_ids,
            organism=organism,
            biome_lineage=biome_lineage,
            taxonomy_path=taxonomy_path,
        )

    if sort_by == "similarity" and parsed_ids:
        from django.db.models import IntegerField
        from django.db.models.expressions import RawSQL
        ordered_ids = list(parsed_ids) if order != "asc" else list(reversed(parsed_ids))
        ibgc_id_col = f"{IntegratedBgc._meta.db_table}.id"
        qs = qs.annotate(
            _sim_pos=RawSQL(
                f"array_position(%s::int[], {ibgc_id_col})",
                [ordered_ids],
                output_field=IntegerField(),
            )
        ).order_by("_sim_pos")
    else:
        sort_map = {
            "novelty_score": "novelty_score",
            "domain_novelty": "domain_novelty",
            "classification_path": "gene_cluster_family",
            "id": "id",
        }
        if sort_by == "size_kb":
            qs = qs.annotate(_size=F("end_position") - F("start_position"))
            order_field = "_size"
        else:
            order_field = sort_map.get(sort_by, "novelty_score")
        descending = order == "desc"
        qs = qs.order_by(
            F(order_field).desc(nulls_last=True) if descending
            else F(order_field).asc(nulls_last=True)
        )

    # Asset iBGCs always sit at the head of the roster, so they should also
    # lead the id list — same convention so "Add all" mirrors what the user
    # sees on page 1.
    asset_rows = _get_asset_roster_rows(asset_token)
    asset_id_seq = [int(r["id"]) for r in asset_rows]

    db_total = qs.count()
    total_count = db_total + len(asset_id_seq)
    remaining = max(0, IBGC_IDS_MAX - len(asset_id_seq))
    db_id_seq = list(qs.values_list("id", flat=True)[:remaining])
    ids = asset_id_seq + db_id_seq

    return IbgcIdsResponse(
        ids=ids,
        total_count=total_count,
        truncated=len(ids) < total_count,
    )


@discovery_router.get("/ibgcs/umap/", response=list[IbgcUmapPoint])
def ibgc_umap(
    request,
    include_partials: bool = True,
    max_points: int = DASHBOARD_RESULT_CAP,
    validated_only: bool = False,
    detector_tools: Optional[str] = None,
    source_tools: Optional[str] = None,  # deprecated alias for detector_tools
    source_names: Optional[str] = None,
    assembly_type: Optional[str] = None,
    bgc_class: Optional[str] = None,
    chemont_ids: Optional[str] = None,
    bgc_accession: Optional[str] = None,
    assembly_accession: Optional[str] = None,
    assembly_ids: Optional[str] = None,
    organism: Optional[str] = None,
    biome_lineage: Optional[str] = None,
    taxonomy_path: Optional[str] = None,
    ibgc_ids: Optional[str] = None,
    asset_token: Optional[str] = None,
):
    """All iBGC UMAP coordinates. ``umap_projected`` marks partial-derived coords.

    Accepts the same filter surface as ``/ibgcs/roster/`` so the v2 dashboard
    can keep the UMAP map in lockstep with the roster after a Run Query.
    """
    parsed_ids: Optional[list[int]] = None
    if ibgc_ids:
        parsed_ids = [
            int(x) for x in ibgc_ids.split(",") if x.strip().isdigit()
        ] or None

    if _asset_only_mode(asset_token, parsed_ids):
        db_points: list[IbgcUmapPoint] = []
    else:
        qs = (
            IntegratedBgc.objects
            .exclude(umap_x__isnull=True)
            .exclude(umap_y__isnull=True)
        )
        qs = _apply_ibgc_filters(
            qs,
            ibgc_ids=parsed_ids,
            include_partials=include_partials,
            validated_only=validated_only,
            detector_tools=detector_tools,
            source_tools=source_tools,
            source_names=source_names,
            assembly_type=assembly_type,
            bgc_class=bgc_class,
            chemont_ids=chemont_ids,
            bgc_accession=bgc_accession,
            assembly_accession=assembly_accession,
            assembly_ids=assembly_ids,
            organism=organism,
            biome_lineage=biome_lineage,
            taxonomy_path=taxonomy_path,
        )

        # Deterministic SQL-side stride: at multi-million-row scale we can't
        # afford to materialise the full queryset and downsample in Python.
        # ``id % stride = 0`` runs in the DB, returns the cap directly, and is
        # reproducible across calls (so the UMAP doesn't flicker between
        # refreshes).
        total = qs.count()
        if total > max_points:
            stride = total // max_points + 1
            qs = qs.annotate(_bucket=F("id") % stride).filter(_bucket=0)
        all_ibgcs = list(qs.order_by("id"))

        facts = _ibgc_member_facts([n.id for n in all_ibgcs])
        db_points = [
            IbgcUmapPoint(
                id=ibgc.id,
                label=_ibgc_label(ibgc.id),
                umap_x=ibgc.umap_x,
                umap_y=ibgc.umap_y,
                classification_path=ibgc.gene_cluster_family or "",
                novelty_score=ibgc.novelty_score,
                is_partial=_ibgc_is_partial(ibgc),
                is_validated=facts[ibgc.id]["is_validated"],
                is_type_strain=facts[ibgc.id]["is_type_strain"],
                umap_projected=ibgc.umap_projected,
            )
            for ibgc in all_ibgcs
        ]
    asset_points: list[IbgcUmapPoint] = []
    for row in _get_asset_roster_rows(asset_token):
        pt = _asset_row_to_umap_point(row)
        if pt is not None:
            asset_points.append(pt)
    return asset_points + db_points


@discovery_router.get("/ibgcs/scatter/", response=list[IbgcScatterPoint])
def ibgc_scatter(
    request,
    x_axis: str = "novelty_score",
    y_axis: str = "domain_novelty",
    include_partials: bool = True,
    max_points: int = 5_000,
    validated_only: bool = False,
    detector_tools: Optional[str] = None,
    source_tools: Optional[str] = None,  # deprecated alias for detector_tools
    source_names: Optional[str] = None,
    assembly_type: Optional[str] = None,
    bgc_class: Optional[str] = None,
    chemont_ids: Optional[str] = None,
    bgc_accession: Optional[str] = None,
    assembly_accession: Optional[str] = None,
    assembly_ids: Optional[str] = None,
    organism: Optional[str] = None,
    biome_lineage: Optional[str] = None,
    taxonomy_path: Optional[str] = None,
    ibgc_ids: Optional[str] = None,
    asset_token: Optional[str] = None,
):
    if x_axis not in _IBGC_AXES or y_axis not in _IBGC_AXES:
        raise HttpError(
            400, f"axes must be one of: {', '.join(sorted(_IBGC_AXES))}"
        )

    parsed_ids: Optional[list[int]] = None
    if ibgc_ids:
        parsed_ids = [
            int(x) for x in ibgc_ids.split(",") if x.strip().isdigit()
        ] or None

    # similarity_score is not a stored column — only meaningful when supplied
    # by a similar-iBGC or domain query. For the bare scatter endpoint, treat
    # it as null and the UI will offer it only post-query.
    if x_axis == "similarity_score" or y_axis == "similarity_score":
        raise HttpError(
            400,
            "similarity_score axis requires a similarity-query context; "
            "use the query response payload instead of /ibgcs/scatter/",
        )

    points: list[IbgcScatterPoint] = []
    if not _asset_only_mode(asset_token, parsed_ids):
        qs = _apply_ibgc_filters(
            IntegratedBgc.objects.all(),
            ibgc_ids=parsed_ids,
            include_partials=include_partials,
            validated_only=validated_only,
            detector_tools=detector_tools,
            source_tools=source_tools,
            source_names=source_names,
            assembly_type=assembly_type,
            bgc_class=bgc_class,
            chemont_ids=chemont_ids,
            bgc_accession=bgc_accession,
            assembly_accession=assembly_accession,
            assembly_ids=assembly_ids,
            organism=organism,
            biome_lineage=biome_lineage,
            taxonomy_path=taxonomy_path,
        )

        n_cds_subq = (
            SourceBgcPrediction.objects
            .filter(integrated_bgc_id=OuterRef("id"))
            .values("integrated_bgc_id")
            .annotate(c=Count("cds_list"))
            .values("c")
        )
        qs = qs.annotate(
            size_kb=(F("end_position") - F("start_position")) / 1000.0,
            n_cds=Subquery(n_cds_subq[:1]),
        )

        # Deterministic SQL-side stride (same approach as /ibgcs/umap/) — keeps
        # the response reproducible across calls and avoids ``ORDER BY ?``,
        # which is a full table sort at multi-million-row scale.
        total = qs.count()
        if total > max_points:
            stride = total // max_points + 1
            qs = qs.annotate(_bucket=F("id") % stride).filter(_bucket=0)

        ibgc_list = list(qs)
        facts = _ibgc_member_facts([n.id for n in ibgc_list])
        for ibgc in ibgc_list:
            x_val = getattr(ibgc, x_axis, None)
            y_val = getattr(ibgc, y_axis, None)
            if x_val is None or y_val is None:
                continue
            points.append(
                IbgcScatterPoint(
                    id=ibgc.id,
                    x=float(x_val),
                    y=float(y_val),
                    classification_path=ibgc.gene_cluster_family or "",
                    novelty_score=ibgc.novelty_score,
                    domain_novelty=ibgc.domain_novelty,
                    is_partial=not facts[ibgc.id]["is_validated"]
                               and ibgc.classification_run_id is None,
                    is_validated=facts[ibgc.id]["is_validated"],
                    is_type_strain=facts[ibgc.id]["is_type_strain"],
                    umap_projected=ibgc.umap_projected,
                )
            )
    asset_points: list[IbgcScatterPoint] = []
    for row in _get_asset_roster_rows(asset_token):
        pt = _asset_row_to_scatter_point(row, x_axis, y_axis)
        if pt is not None:
            asset_points.append(pt)
    return asset_points + points


# NOTE: this catch-all path-param route MUST come after every other
# `/ibgcs/<literal>/` route above (roster, umap, scatter, …) — Django Ninja
# matches in declaration order, so an earlier `{ibgc_id}` would swallow
# "umap" / "scatter" and 422 on int parsing.
def _asset_token_header(request) -> Optional[str]:
    """Frontend passes the active asset token via ``X-Asset-Token`` so the
    negative-id dispatcher can resolve asset iBGCs out of Redis without
    polluting the URL with a query param."""
    return request.headers.get("X-Asset-Token") or request.GET.get("asset_token")


@discovery_router.get("/ibgcs/{ibgc_id}/", response=IbgcDetail)
def ibgc_detail(request, ibgc_id: int):
    if ibgc_id < 0:
        token = _asset_token_header(request)
        if not token:
            raise HttpError(404, "Asset token required for asset iBGC")
        from discovery.services.asset_upload import cache as asset_cache

        payload = asset_cache.read_ibgc_detail(token, ibgc_id)
        if payload is None:
            raise HttpError(404, "Asset iBGC not found or expired")
        return IbgcDetail(**payload)

    try:
        ibgc = IntegratedBgc.objects.select_related("contig").get(id=ibgc_id)
    except IntegratedBgc.DoesNotExist:
        raise HttpError(404, "iBGC not found")

    member_qs = (
        SourceBgcPrediction.objects
        .filter(integrated_bgc_id=ibgc_id)
        .select_related("assembly", "assembly__source", "detector")
        .order_by("id")
    )
    members = list(member_qs)
    is_validated = any(m.is_validated for m in members)
    is_type_strain = any(
        m.assembly is not None and m.assembly.is_type_strain
        for m in members
    )

    parent = None
    if members:
        asm = members[0].assembly
        if asm:
            parent = ParentAssemblySummary(
                assembly_id=asm.id,
                accession=asm.assembly_accession,
                organism_name=asm.organism_name,
                source_name=asm.source.name if asm.source else None,
                is_type_strain=asm.is_type_strain,
                url=asm.url or "",
            )

    representative_id = _pick_representative_ibgc_id(ibgc_id)

    # Pooled positional domain architecture across all member BGCs of the
    # iBGC. Mirrors the ordering rule the adjacency builder uses so the
    # surfaced sequence is exactly what the clustering pipeline scored.
    domain_arch = [
        DomainArchitectureItem(
            domain_acc=r["domain_acc"],
            domain_name=r["domain_name"],
            ref_db=r["ref_db"],
            start=0,
            end=0,
            score=None,
            url=r["url"] or "",
        )
        for r in ibgc_architecture([m.id for m in members])
    ]

    # Natural products: union over members (each curated NP attaches to one BGC).
    member_ids = [m.id for m in members]
    np_items: list[NaturalProductSummary] = []
    for np_obj in IbgcNaturalProduct.objects.filter(bgc_id__in=member_ids):
        np_items.append(
            NaturalProductSummary(
                id=np_obj.id,
                name=np_obj.name,
                smiles=np_obj.smiles,
                smiles_svg="",
                structure_thumbnail=np_obj.structure_svg_base64,
                np_class_path=np_obj.np_class_path,
            )
        )

    # ChemOnt tree aggregated across all CDSs of all member BGCs of the iBGC.
    chemont_rows = CdsChemOnt.objects.filter(
        cds__bgc_id__in=member_ids
    ).only("chemont_id", "chemont_name", "probability")
    chemont_tree = _build_chemont_tree_from_cds(chemont_rows)

    member_items = [
        IbgcMemberBgc(
            id=m.id,
            accession=m.prediction_accession,
            detector_name=m.detector.tool if m.detector else None,
            is_partial=m.is_partial,
            is_validated=m.is_validated,
            size_kb=m.size_kb,
        )
        for m in members
    ]

    return IbgcDetail(
        id=ibgc.id,
        label=_ibgc_label(ibgc.id),
        classification_path=ibgc.gene_cluster_family or "",
        size_kb=round((ibgc.end_position - ibgc.start_position) / 1000.0, 3),
        start_position=ibgc.start_position,
        end_position=ibgc.end_position,
        contig_accession=ibgc.contig.accession if ibgc.contig else None,
        source_tools=list(ibgc.source_tools or []),
        novelty_score=ibgc.novelty_score,
        domain_novelty=ibgc.domain_novelty,
        is_partial=_ibgc_is_partial(ibgc),
        is_validated=is_validated,
        is_type_strain=is_type_strain,
        umap_projected=ibgc.umap_projected,
        umap_x=ibgc.umap_x,
        umap_y=ibgc.umap_y,
        parent_assembly=parent,
        representative_ibgc_id=representative_id,
        member_bgcs=member_items,
        domain_architecture=domain_arch,
        natural_products=np_items,
        chemont_tree=chemont_tree,
    )


@discovery_router.get(
    "/ibgcs/{ibgc_id}/architecture/", response=IbgcArchitectureResponse,
)
def ibgc_architecture_endpoint(request, ibgc_id: int):
    """Pooled positional domain accessions for an iBGC (clipboard payload).

    Lightweight wrapper around the same ordering rule that ``ibgc_detail``
    uses for ``domain_architecture``.
    """
    if ibgc_id < 0:
        token = _asset_token_header(request)
        if not token:
            raise HttpError(404, "Asset token required for asset iBGC")
        from discovery.services.asset_upload import cache as asset_cache

        ordered_accs = asset_cache.read_architecture(token, ibgc_id)
        if ordered_accs is None:
            raise HttpError(404, "Asset iBGC not found or expired")
        return IbgcArchitectureResponse(
            id=ibgc_id,
            label=f"iBGC-A{abs(ibgc_id)}",
            ordered_accs=ordered_accs,
        )

    try:
        ibgc = IntegratedBgc.objects.get(id=ibgc_id)
    except IntegratedBgc.DoesNotExist:
        raise HttpError(404, "iBGC not found")

    member_ids = list(
        SourceBgcPrediction.objects
        .filter(integrated_bgc_id=ibgc_id)
        .values_list("id", flat=True)
    )
    ordered_accs = [r["domain_acc"] for r in ibgc_architecture(member_ids)]
    return IbgcArchitectureResponse(
        id=ibgc.id,
        label=_ibgc_label(ibgc.id),
        ordered_accs=ordered_accs,
    )


@discovery_router.post(
    "/query/similar-ibgc/", response=PaginatedIbgcRosterResponse,
)
def similar_ibgc_query(
    request,
    body: SimilarIbgcRequest,
    page: int = 1,
    page_size: int = 25,
):
    """Top-K iBGCs by composite-Dice similarity to ``body.ibgc_id``.

    Composite-Dice is computed on demand against the per-iBGC signature
    matrices of the active ClusteringRun. The full N×N similarity matrix
    is no longer materialised; the result is cached in Redis for 24h keyed
    on the run's sha256 so a new clustering run invalidates the cache by
    orphaning the previous keys.
    """
    from discovery.services.clustering.similarity_on_demand import (
        cache_key_find_similar,
        cache_similarity_query,
        get_active_scoring_cache,
        score_against_all,
        top_k,
    )

    try:
        scoring = get_active_scoring_cache()
    except FileNotFoundError as exc:
        raise HttpError(503, str(exc))

    row_ix = scoring.row_index_for(body.ibgc_id)
    if row_ix is None:
        raise HttpError(
            400,
            "Seed iBGC is not a primary in the latest ClusteringRun — "
            "similar-iBGC requires a primary seed in v1.",
        )

    k = max(1, min(int(body.k), 500))

    def _compute():
        import numpy as np

        q_dom = scoring.M_domains.getrow(row_ix)
        q_pair = scoring.M_pairs.getrow(row_ix)
        scores = score_against_all(q_dom, q_pair, scoring)
        scores[row_ix] = -np.inf  # exclude self
        rows, vals = top_k(scores, k)
        ids = [int(scoring.ibgc_ids[r]) for r in rows]
        return {"ids": ids, "scores": vals}

    cache_key = cache_key_find_similar(sha256=scoring.sha256, ibgc_id=body.ibgc_id, k=k)
    cached = cache_similarity_query(cache_key=cache_key, compute=_compute)
    top_ids: list[int] = list(cached["ids"])
    top_sims: list[float] = [float(v) for v in cached["scores"]]
    sim_lookup = dict(zip(top_ids, top_sims))

    if not top_ids:
        return PaginatedIbgcRosterResponse(
            items=[],
            pagination=PaginationMeta(page=1, page_size=page_size, total_count=0, total_pages=0),
        )

    total_count = len(top_ids)
    pg, ps, tp, offset = _paginate(page, page_size, total_count)
    page_ids = top_ids[offset: offset + ps]

    ibgcs = {n.id: n for n in IntegratedBgc.objects.filter(id__in=page_ids)}
    facts = _ibgc_member_facts(page_ids)
    items = [
        _ibgc_to_roster_item(
            ibgcs[nid],
            parent_assembly=facts[nid]["parent_assembly"],
            n_source_bgcs=facts[nid]["n_source_bgcs"],
            is_validated=facts[nid]["is_validated"],
            is_type_strain=facts[nid]["is_type_strain"],
            contig_accession=facts[nid]["contig_accession"],
            similarity_score=round(sim_lookup[nid], 4),
        )
        for nid in page_ids
        if nid in ibgcs
    ]
    return PaginatedIbgcRosterResponse(
        items=items,
        pagination=PaginationMeta(
            page=pg, page_size=ps, total_count=total_count, total_pages=tp,
        ),
    )


@discovery_router.post(
    "/query/ibgc-architecture/", response=PaginatedIbgcRosterResponse,
)
def ibgc_architecture_query(
    request,
    body: IbgcArchitectureQueryRequest,
    page: int = 1,
    page_size: int = 25,
):
    """Top-K iBGCs by composite-Dice to a user-supplied domain architecture.

    Scores ``weight·Dice(domain set) + (1-weight)·Dice(adjacency pairs)``
    against the cached primary-iBGC matrices for the latest ClusteringRun.
    Accessions outside the run's domain vocabulary are silently dropped.
    """
    from discovery.services.clustering.architecture_search import (
        architecture_search,
        normalize_architecture_input,
    )
    from discovery.services.clustering.similarity_on_demand import (
        cache_key_architecture,
        cache_similarity_query,
        get_active_scoring_cache,
    )

    accs = normalize_architecture_input(body.architecture)
    if not accs:
        raise HttpError(400, "architecture must contain at least one accession")

    try:
        scoring = get_active_scoring_cache()
    except FileNotFoundError as exc:
        raise HttpError(503, str(exc))

    k = max(1, min(int(body.k), 500))

    def _compute():
        result = architecture_search(
            accs, weight=body.weight, k=k, cache=scoring,
        )
        return {"ids": result["ibgc_ids"], "scores": result["scores"]}

    cache_key = cache_key_architecture(
        sha256=scoring.sha256, accs_ordered=accs, weight=float(body.weight), k=k,
    )
    cached = cache_similarity_query(cache_key=cache_key, compute=_compute)
    top_ids: list[int] = list(cached["ids"])
    top_scores: list[float] = [float(s) for s in cached["scores"]]
    if not top_ids:
        raise HttpError(
            400,
            "No supplied accession matched the scoring cache vocabulary — "
            "check the input or rerun clustering against a broader source set.",
        )

    sim_lookup = dict(zip(top_ids, top_scores))
    total_count = len(top_ids)
    pg, ps, tp, offset = _paginate(page, page_size, total_count)
    page_ids = top_ids[offset: offset + ps]

    ibgcs = {n.id: n for n in IntegratedBgc.objects.filter(id__in=page_ids)}
    facts = _ibgc_member_facts(page_ids)
    items = [
        _ibgc_to_roster_item(
            ibgcs[nid],
            parent_assembly=facts[nid]["parent_assembly"],
            n_source_bgcs=facts[nid]["n_source_bgcs"],
            is_validated=facts[nid]["is_validated"],
            is_type_strain=facts[nid]["is_type_strain"],
            contig_accession=facts[nid]["contig_accession"],
            similarity_score=round(sim_lookup[nid], 4),
        )
        for nid in page_ids
        if nid in ibgcs
    ]
    return PaginatedIbgcRosterResponse(
        items=items,
        pagination=PaginationMeta(
            page=pg, page_size=ps, total_count=total_count, total_pages=tp,
        ),
    )


# ── Shortlist Report endpoints ───────────────────────────────────────────────


@discovery_router.post("/report/snapshot/", response=ReportSnapshotResponse)
def report_snapshot(request, body: ReportSnapshotRequest):
    """Materialise a shortlist Report payload and cache it in Redis by token.

    The token is ``sha256(sorted comma-joined ids)[:32]`` so the same shortlist
    always resolves to the same token (cheap re-render across browsers/sessions).
    """
    from django.core.cache import cache
    import hashlib

    from discovery.services.report import (
        MAX_SHORTLIST,
        REPORT_TTL_SECONDS,
        build_report_payload,
    )

    ids = sorted({int(i) for i in body.ibgc_ids})
    if not ids:
        raise HttpError(400, "ibgc_ids must be non-empty")
    if len(ids) > MAX_SHORTLIST:
        raise HttpError(400, f"shortlist limit is {MAX_SHORTLIST} iBGCs")

    # Split positive (DB) from negative (asset) ids and hydrate the asset
    # rows from Redis if a token was supplied.
    asset_ids = [i for i in ids if i < 0]
    extra_rows: list[dict] = []
    extra_domain_rows: list[dict] = []
    if asset_ids:
        if not body.asset_token:
            raise HttpError(
                400,
                "asset_token is required when asset iBGC ids (negative) are shortlisted",
            )
        from discovery.services.asset_upload import cache as asset_cache

        cached_roster = {
            int(r["id"]): r for r in (asset_cache.read_ibgc_list(body.asset_token) or [])
        }
        for nid in asset_ids:
            row = cached_roster.get(nid)
            if row is None:
                raise HttpError(
                    404,
                    f"Asset iBGC {nid} not found in asset token {body.asset_token!r}",
                )
            extra_rows.append(row)

        # Domain hits feed the report's domain composition + GO slim matrix
        # panels for the asset rows. Scope to the shortlisted asset ids so
        # an upload with many iBGCs doesn't drag the rest into the rollup.
        shortlisted = set(asset_ids)
        extra_domain_rows = [
            r
            for r in (asset_cache.read_domain_hits(body.asset_token) or [])
            if int(r.get("ibgc_id", 0)) in shortlisted
        ]

    # The token covers both ids and asset rows so cached snapshots don't
    # collide across different asset uploads with the same negative ids.
    token_seed = ",".join(str(i) for i in ids)
    if body.asset_token:
        token_seed += f"|asset={body.asset_token}"
    token = hashlib.sha256(token_seed.encode("utf-8")).hexdigest()[:32]
    cache_key = f"report:{token}"

    cached = cache.get(cache_key)
    if cached:
        return ReportSnapshotResponse(
            token=token,
            expires_at=cached.get("expires_at", ""),
            n_ibgcs=cached.get("n_ibgcs", len(ids)),
        )

    payload = build_report_payload(
        ids,
        extra_ibgc_rows=extra_rows,
        extra_domain_rows=extra_domain_rows,
    )
    cache.set(cache_key, payload, REPORT_TTL_SECONDS)
    return ReportSnapshotResponse(
        token=token,
        expires_at=payload["expires_at"],
        n_ibgcs=payload["n_ibgcs"],
    )


@discovery_router.get("/report/{token}/", response=ReportPayload)
def report_get(request, token: str):
    """Return the cached Report payload for ``token``; 404 if expired."""
    from django.core.cache import cache

    cached = cache.get(f"report:{token}")
    if not cached:
        raise HttpError(
            404,
            "Report not found or expired — POST /report/snapshot/ to regenerate.",
        )
    return ReportPayload(token=token, **cached)


def _get_cached_report(token: str) -> dict:
    from django.core.cache import cache

    cached = cache.get(f"report:{token}")
    if not cached:
        raise HttpError(
            404,
            "Report not found or expired — POST /report/snapshot/ to regenerate.",
        )
    return cached


@discovery_router.get("/report/{token}/export.assemblies.tsv")
def report_export_assemblies_tsv(request, token: str):
    """Download the report's assembly roster as a TSV.

    Reads from the cached snapshot — no extra DB queries within the 24h TTL.
    """
    from discovery.services.export import build_report_assembly_tsv

    cached = _get_cached_report(token)
    tsv = build_report_assembly_tsv(cached.get("assembly_rows", []))
    response = HttpResponse(tsv, content_type="text/tab-separated-values")
    response["Content-Disposition"] = (
        f'attachment; filename="report_{token}_assemblies.tsv"'
    )
    return response


@discovery_router.get("/report/{token}/export.json")
def report_export_json(request, token: str):
    """Download the report as an analyst-friendly tidy JSON.

    Reshapes the cached chart-oriented payload into a two-layer
    ``{metadata, ...tables}`` structure. Pure reshape (no DB).
    """
    from discovery.services.report import build_report_analyst_export

    cached = _get_cached_report(token)
    body = build_report_analyst_export(token, cached)
    response = HttpResponse(
        json.dumps(body, default=str),
        content_type="application/json",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="report_{token}.json"'
    )
    return response


@discovery_router.get("/report/{token}/export.gbk.zip")
def report_export_gbk_zip(request, token: str):
    """Download a zip of GBK files (one per source BGC) for the shortlist.

    Each record carries BGC / iBGC / Region features in addition to CDSs.
    Files are grouped as ``iBGC-{id}/{bgc_accession}.gbk``.
    """
    from discovery.services.gbk import build_shortlist_gbk_zip

    cached = _get_cached_report(token)
    ibgc_ids = [row["id"] for row in cached.get("ibgc_rows", [])]
    zip_bytes = build_shortlist_gbk_zip(ibgc_ids)
    response = HttpResponse(zip_bytes, content_type="application/zip")
    response["Content-Disposition"] = (
        f'attachment; filename="report_{token}_gbk.zip"'
    )
    return response


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
    source_names: Optional[str] = None,
    detector_tools: Optional[str] = None,
    bgc_class: Optional[str] = None,
    biome_lineage: Optional[str] = None,
    assembly_accession: Optional[str] = None,
    bgc_accession: Optional[str] = None,
):
    required = [d.acc for d in body.domains if d.required]
    excluded = [d.acc for d in body.domains if not d.required]

    qs = SourceBgcPrediction.objects.select_related("assembly")

    # Sidebar filters
    if source_names:
        names = [n.strip() for n in source_names.split(",") if n.strip()]
        if names:
            qs = qs.filter(assembly__source__name__in=names)
    if detector_tools:
        tools = [t.strip() for t in detector_tools.split(",") if t.strip()]
        if tools:
            qs = qs.filter(detector__tool__in=tools)
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

    # Domain filtering via ContigDomain (single join instead of 5)
    if body.logic == "and" and required:
        for acc in required:
            qs = qs.filter(contig__cds_list__domains__domain_acc=acc)
        qs = qs.distinct()
    elif required:
        qs = qs.filter(contig__cds_list__domains__domain_acc__in=required).distinct()

    if excluded:
        qs = qs.exclude(contig__cds_list__domains__domain_acc__in=excluded)

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
            accession=bgc.prediction_accession,
            classification_path=( bgc.integrated_bgc.gene_cluster_family if bgc.integrated_bgc_id else "" ),
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


# ── iBGC-collapsed query endpoints ────────────────────────────────────────────


def _ibgc_roster_page_response(
    qs,
    *,
    sort_by: str,
    order: str,
    page: int,
    page_size: int,
    similarity_lookup: Optional[dict[int, float]] = None,
    best_hit_protein_lookup: Optional[dict[int, str]] = None,
    best_pident_lookup: Optional[dict[int, float]] = None,
    best_qcoverage_lookup: Optional[dict[int, float]] = None,
) -> PaginatedIbgcRosterResponse:
    """Sort, paginate, and serialise a filtered ``IntegratedBgc`` queryset.

    Shared between ``/ibgcs/roster/``, ``/query/ibgc-domain/``, and
    ``/query/ibgc-sequence/status/`` so result shape stays identical.
    ``similarity_lookup`` is an optional ``{ibgc_id: score}`` map that gets
    stamped onto each ``IbgcRosterItem.similarity_score`` (used by the
    query endpoints; ``/ibgcs/roster/`` leaves it null).
    ``best_hit_protein_lookup`` is filled only by the sequence-search
    endpoint and carries the protein_id of the winning CDS per iBGC.
    """
    sort_map = {
        "novelty_score": "novelty_score",
        "domain_novelty": "domain_novelty",
        "classification_path": "gene_cluster_family",
        "id": "id",
    }
    if sort_by == "size_kb":
        qs = qs.annotate(_size=F("end_position") - F("start_position"))
        order_field = "_size"
    elif sort_by == "similarity_score" and similarity_lookup is not None:
        # Materialise + sort in Python — similarity isn't a DB column.
        rows = list(qs)
        rows.sort(
            key=lambda n: similarity_lookup.get(n.id, 0.0),
            reverse=(order == "desc"),
        )
        total_count = len(rows)
        pg, ps, tp, offset = _paginate(page, page_size, total_count)
        page_rows = rows[offset: offset + ps]
        facts = _ibgc_member_facts([n.id for n in page_rows])
        items = [
            _ibgc_to_roster_item(
                n,
                parent_assembly=facts[n.id]["parent_assembly"],
                n_source_bgcs=facts[n.id]["n_source_bgcs"],
                is_validated=facts[n.id]["is_validated"],
                is_type_strain=facts[n.id]["is_type_strain"],
                contig_accession=facts[n.id]["contig_accession"],
                similarity_score=similarity_lookup.get(n.id),
                best_hit_protein_id=(
                    best_hit_protein_lookup.get(n.id)
                    if best_hit_protein_lookup else None
                ),
                best_pident=(
                    best_pident_lookup.get(n.id)
                    if best_pident_lookup else None
                ),
                best_qcoverage=(
                    best_qcoverage_lookup.get(n.id)
                    if best_qcoverage_lookup else None
                ),
            )
            for n in page_rows
        ]
        return PaginatedIbgcRosterResponse(
            items=items,
            pagination=PaginationMeta(
                page=pg, page_size=ps, total_count=total_count, total_pages=tp,
            ),
        )
    else:
        order_field = sort_map.get(sort_by, "novelty_score")

    descending = order == "desc"
    qs = qs.order_by(
        F(order_field).desc(nulls_last=True) if descending
        else F(order_field).asc(nulls_last=True)
    )
    total_count = qs.count()
    pg, ps, tp, offset = _paginate(page, page_size, total_count)
    page_qs = list(qs[offset: offset + ps])
    facts = _ibgc_member_facts([n.id for n in page_qs])
    items = [
        _ibgc_to_roster_item(
            n,
            parent_assembly=facts[n.id]["parent_assembly"],
            n_source_bgcs=facts[n.id]["n_source_bgcs"],
            is_validated=facts[n.id]["is_validated"],
            is_type_strain=facts[n.id]["is_type_strain"],
            contig_accession=facts[n.id]["contig_accession"],
            similarity_score=(
                similarity_lookup.get(n.id) if similarity_lookup else None
            ),
            best_hit_protein_id=(
                best_hit_protein_lookup.get(n.id)
                if best_hit_protein_lookup else None
            ),
            best_pident=(
                best_pident_lookup.get(n.id)
                if best_pident_lookup else None
            ),
            best_qcoverage=(
                best_qcoverage_lookup.get(n.id)
                if best_qcoverage_lookup else None
            ),
        )
        for n in page_qs
    ]
    return PaginatedIbgcRosterResponse(
        items=items,
        pagination=PaginationMeta(
            page=pg, page_size=ps, total_count=total_count, total_pages=tp,
        ),
    )


@discovery_router.post(
    "/query/ibgc-domain/", response=PaginatedIbgcRosterResponse, tags=["Query"],
)
def ibgc_domain_query(
    request,
    body: DomainQueryRequest,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "novelty_score",
    order: str = "desc",
    include_partials: bool = True,
    validated_only: bool = False,
    min_length_kb: Optional[float] = None,
    max_length_kb: Optional[float] = None,
    min_novelty: Optional[float] = None,
    max_novelty: Optional[float] = None,
    min_domain_novelty: Optional[float] = None,
    max_domain_novelty: Optional[float] = None,
    detector_tools: Optional[str] = None,
    source_tools: Optional[str] = None,  # deprecated alias for detector_tools
    source_names: Optional[str] = None,
    assembly_type: Optional[str] = None,
    leaf_path_prefix: Optional[str] = None,
    bgc_class: Optional[str] = None,
    chemont_ids: Optional[str] = None,
    bgc_accession: Optional[str] = None,
    assembly_accession: Optional[str] = None,
    assembly_ids: Optional[str] = None,
    organism: Optional[str] = None,
    biome_lineage: Optional[str] = None,
    taxonomy_path: Optional[str] = None,
):
    """iBGC-collapsed domain query.

    Resolves the domain conditions against ``ContigDomain`` rows, collapses to
    distinct ``IntegratedBgc`` ids (any source BGC of the iBGC carrying a
    required domain counts the iBGC in; excluded domains drop the iBGC if any
    source BGC carries them). All iBGC-level filters from ``/ibgcs/roster/``
    apply in the same shape.
    """
    required = [d.acc for d in body.domains if d.required]
    excluded = [d.acc for d in body.domains if not d.required]

    # Resolve the matching iBGC id set via ContigDomain → SourceBgcPrediction → iBGC.
    bgc_qs = SourceBgcPrediction.objects.filter(integrated_bgc__isnull=False)
    if body.logic == "and" and required:
        for acc in required:
            bgc_qs = bgc_qs.filter(contig__cds_list__domains__domain_acc=acc)
    elif required:
        bgc_qs = bgc_qs.filter(contig__cds_list__domains__domain_acc__in=required)
    ibgc_ids = list(
        bgc_qs.values_list("integrated_bgc_id", flat=True).distinct()
    )
    if excluded and ibgc_ids:
        excluded_ibgc_ids = set(
            SourceBgcPrediction.objects
            .filter(integrated_bgc_id__in=ibgc_ids, contig__cds_list__domains__domain_acc__in=excluded)
            .values_list("integrated_bgc_id", flat=True)
            .distinct()
        )
        ibgc_ids = [i for i in ibgc_ids if i not in excluded_ibgc_ids]

    if not ibgc_ids:
        return PaginatedIbgcRosterResponse(
            items=[],
            pagination=PaginationMeta(
                page=1, page_size=page_size, total_count=0, total_pages=0,
            ),
        )

    qs = _apply_ibgc_filters(
        IntegratedBgc.objects.all(),
        ibgc_ids=ibgc_ids,
        include_partials=include_partials,
        validated_only=validated_only,
        min_length_kb=min_length_kb,
        max_length_kb=max_length_kb,
        min_novelty=min_novelty,
        max_novelty=max_novelty,
        min_domain_novelty=min_domain_novelty,
        max_domain_novelty=max_domain_novelty,
        detector_tools=detector_tools,
        source_tools=source_tools,
        source_names=source_names,
        assembly_type=assembly_type,
        leaf_path_prefix=leaf_path_prefix,
        bgc_class=bgc_class,
        chemont_ids=chemont_ids,
        bgc_accession=bgc_accession,
        assembly_accession=assembly_accession,
        assembly_ids=assembly_ids,
        organism=organism,
        biome_lineage=biome_lineage,
        taxonomy_path=taxonomy_path,
    )
    # Domain match is binary → similarity_score = 1.0 for every iBGC.
    similarity_lookup = {nid: 1.0 for nid in ibgc_ids}
    return _ibgc_roster_page_response(
        qs,
        sort_by=sort_by,
        order=order,
        page=page,
        page_size=page_size,
        similarity_lookup=similarity_lookup,
    )


@discovery_router.get(
    "/query/ibgc-sequence/status/{task_id}/",
    response=PaginatedIbgcRosterResponse,
    tags=["Query"],
)
def ibgc_sequence_query_status(
    request,
    task_id: str,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "similarity_score",
    order: str = "desc",
    include_partials: bool = True,
    validated_only: bool = False,
    min_length_kb: Optional[float] = None,
    max_length_kb: Optional[float] = None,
    min_novelty: Optional[float] = None,
    max_novelty: Optional[float] = None,
    min_domain_novelty: Optional[float] = None,
    max_domain_novelty: Optional[float] = None,
    detector_tools: Optional[str] = None,
    source_tools: Optional[str] = None,  # deprecated alias for detector_tools
    source_names: Optional[str] = None,
    assembly_type: Optional[str] = None,
    leaf_path_prefix: Optional[str] = None,
    bgc_class: Optional[str] = None,
    chemont_ids: Optional[str] = None,
    bgc_accession: Optional[str] = None,
    assembly_accession: Optional[str] = None,
    assembly_ids: Optional[str] = None,
    organism: Optional[str] = None,
    biome_lineage: Optional[str] = None,
    taxonomy_path: Optional[str] = None,
):
    """Poll a ``sequence_similarity_search`` Celery task and return results
    collapsed to iBGC level.

    The task itself is the same one ``POST /query/sequence/`` dispatches —
    only the result shape differs. Each iBGC keeps the best-bitscore hit
    among its source BGCs as ``similarity_score``. Tasks still PENDING raise
    503 so the client can poll on a fixed interval; FAILURE raises 500.
    """
    from celery.result import AsyncResult

    res = AsyncResult(task_id)
    if res.failed():
        # Surface the underlying message — the most actionable case is
        # IndexNotBuiltError, which means the operator needs to run
        # ``make build-protein-index`` before sequence search can return
        # anything. Without this, the dashboard just showed an empty
        # roster and the cause was invisible.
        raw = res.result
        detail = (
            f"{type(raw).__name__}: {raw}"
            if isinstance(raw, BaseException)
            else "Sequence search failed"
        )
        raise HttpError(500, detail)
    if not res.ready():
        raise HttpError(503, "Sequence search still running")

    raw_result = res.result or {}
    bgc_metrics: dict[int, dict[str, float | str]] = {
        int(k): v for k, v in raw_result.items()
    }
    if not bgc_metrics:
        return PaginatedIbgcRosterResponse(
            items=[],
            pagination=PaginationMeta(
                page=1, page_size=page_size, total_count=0, total_pages=0,
            ),
        )

    # Collapse BGC hits → iBGC id with best bitscore. Also carry the
    # ``protein_id`` of the winning CDS plus its aggregate alignment stats
    # (pident, qcov) so the Variables Map can plot those metrics.
    bgc_to_ibgc = dict(
        SourceBgcPrediction.objects.filter(id__in=bgc_metrics.keys())
        .values_list("id", "integrated_bgc_id")
    )
    ibgc_best: dict[int, float] = {}
    ibgc_best_protein: dict[int, str] = {}
    ibgc_best_pident: dict[int, float] = {}
    ibgc_best_qcov: dict[int, float] = {}
    for bgc_id, ibgc_id in bgc_to_ibgc.items():
        if ibgc_id is None:
            continue
        m = bgc_metrics[bgc_id]
        bs = float(m.get("bitscore", 0.0))
        if bs > ibgc_best.get(ibgc_id, float("-inf")):
            ibgc_best[ibgc_id] = bs
            pid = m.get("protein_id")
            if pid:
                ibgc_best_protein[ibgc_id] = str(pid)
            pident = m.get("pident")
            if pident is not None:
                ibgc_best_pident[ibgc_id] = float(pident)
            qcov = m.get("qcoverage")
            if qcov is not None:
                ibgc_best_qcov[ibgc_id] = float(qcov)

    if not ibgc_best:
        return PaginatedIbgcRosterResponse(
            items=[],
            pagination=PaginationMeta(
                page=1, page_size=page_size, total_count=0, total_pages=0,
            ),
        )

    qs = _apply_ibgc_filters(
        IntegratedBgc.objects.all(),
        ibgc_ids=list(ibgc_best.keys()),
        include_partials=include_partials,
        validated_only=validated_only,
        min_length_kb=min_length_kb,
        max_length_kb=max_length_kb,
        min_novelty=min_novelty,
        max_novelty=max_novelty,
        min_domain_novelty=min_domain_novelty,
        max_domain_novelty=max_domain_novelty,
        detector_tools=detector_tools,
        source_tools=source_tools,
        source_names=source_names,
        assembly_type=assembly_type,
        leaf_path_prefix=leaf_path_prefix,
        bgc_class=bgc_class,
        chemont_ids=chemont_ids,
        bgc_accession=bgc_accession,
        assembly_accession=assembly_accession,
        assembly_ids=assembly_ids,
        organism=organism,
        biome_lineage=biome_lineage,
        taxonomy_path=taxonomy_path,
    )
    return _ibgc_roster_page_response(
        qs,
        sort_by=sort_by,
        order=order,
        page=page,
        page_size=page_size,
        similarity_lookup=ibgc_best,
        best_hit_protein_lookup=ibgc_best_protein,
        best_pident_lookup=ibgc_best_pident,
        best_qcoverage_lookup=ibgc_best_qcov,
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
    source_names: Optional[str] = None,
    detector_tools: Optional[str] = None,
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

    qs = SourceBgcPrediction.objects.filter(id__in=bgc_similarities.keys()).select_related("assembly")

    # Sidebar filters
    if source_names:
        names = [n.strip() for n in source_names.split(",") if n.strip()]
        if names:
            qs = qs.filter(assembly__source__name__in=names)
    if detector_tools:
        tools = [t.strip() for t in detector_tools.split(",") if t.strip()]
        if tools:
            qs = qs.filter(detector__tool__in=tools)
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
                cds_list__chemont__chemont_id__in=cid_list
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
            accession=bgc.prediction_accession,
            classification_path=( bgc.integrated_bgc.gene_cluster_family if bgc.integrated_bgc_id else "" ),
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


@discovery_router.post(
    "/query/sequence/",
    response={202: SequenceQueryAccepted},
    tags=["Query"],
)
def sequence_query(request, body: SequenceQueryRequest):
    lines = body.sequence.strip().splitlines()
    cleaned = "".join(l.strip() for l in lines if not l.startswith(">"))
    if not cleaned:
        raise HttpError(400, "Protein sequence is required")
    if len(cleaned) > 5000:
        raise HttpError(400, "Sequence exceeds maximum length of 5,000 amino acids")
    if not (0.0 <= body.min_bitscore <= 10_000.0):
        raise HttpError(400, "min_bitscore must be between 0 and 10000")
    if not (0.0 <= body.min_pident <= 100.0):
        raise HttpError(400, "min_pident must be between 0 and 100")
    if not (0.0 <= body.min_qcov <= 100.0):
        raise HttpError(400, "min_qcov must be between 0 and 100")

    from discovery.tasks import sequence_similarity_search

    try:
        result = sequence_similarity_search.delay(
            cleaned,
            body.min_bitscore,
            body.min_pident,
            body.min_qcov,
        )
    except Exception as e:
        logger.error("Failed to dispatch sequence search task: %s", e)
        raise HttpError(503, "Search service temporarily unavailable")

    return 202, SequenceQueryAccepted(task_id=result.id)


@discovery_router.get(
    "/query/sequence/status/{task_id}/",
    response=SequenceQueryStatusResponse,
    tags=["Query"],
)
def sequence_query_status(
    request,
    task_id: str,
    page: int = 1,
    page_size: int = 25,
    sort_by: str = "similarity_score",
    order: str = "desc",
    search: Optional[str] = None,
    taxonomy_path: Optional[str] = None,
    source_names: Optional[str] = None,
    detector_tools: Optional[str] = None,
    bgc_class: Optional[str] = None,
    biome_lineage: Optional[str] = None,
    assembly_accession: Optional[str] = None,
    bgc_accession: Optional[str] = None,
):
    from celery.result import AsyncResult

    res = AsyncResult(task_id)

    if res.failed():
        return SequenceQueryStatusResponse(status="FAILURE")
    if not res.ready():
        return SequenceQueryStatusResponse(status="PENDING")

    raw_result = res.result or {}
    # Task returns {bgc_id: {"bitscore": .., "pident": .., "qcoverage": ..}}.
    bgc_metrics: dict[int, dict[str, float]] = {int(k): v for k, v in raw_result.items()}

    if not bgc_metrics:
        return SequenceQueryStatusResponse(
            status="SUCCESS",
            items=[],
            pagination=PaginationMeta(page=1, page_size=page_size, total_count=0, total_pages=0),
        )

    qs = SourceBgcPrediction.objects.filter(id__in=bgc_metrics.keys()).select_related("assembly", "assembly__source")

    if source_names:
        names = [n.strip() for n in source_names.split(",") if n.strip()]
        if names:
            qs = qs.filter(assembly__source__name__in=names)
    if detector_tools:
        tools = [t.strip() for t in detector_tools.split(",") if t.strip()]
        if tools:
            qs = qs.filter(detector__tool__in=tools)
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
        m = bgc_metrics.get(bgc.id) or {}
        bitscore = round(float(m.get("bitscore", 0.0)), 2)
        pident = round(float(m.get("pident", 0.0)), 2)
        qcov = round(float(m.get("qcoverage", 0.0)), 2)
        results.append((bgc, bitscore, pident, qcov))

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
            accession=bgc.prediction_accession,
            classification_path=( bgc.integrated_bgc.gene_cluster_family if bgc.integrated_bgc_id else "" ),
            size_kb=bgc.size_kb,
            novelty_score=bgc.novelty_score,
            domain_novelty=bgc.domain_novelty,
            is_partial=bgc.is_partial,
            similarity_score=bitscore,
            best_bitscore=bitscore,
            best_pident=pident,
            best_qcoverage=qcov,
            assembly_id=bgc.assembly_id,
            assembly_accession=bgc.assembly.assembly_accession if bgc.assembly else None,
            organism_name=bgc.assembly.organism_name if bgc.assembly else None,
            is_type_strain=bgc.assembly.is_type_strain if bgc.assembly else False,
            source_name=bgc.assembly.source.name if bgc.assembly and bgc.assembly.source else None,
        )
        for bgc, bitscore, pident, qcov in page_results
    ]

    return SequenceQueryStatusResponse(
        status="SUCCESS",
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
        SourceBgcPrediction.objects.filter(id__in=ids)
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
        for row in SourceBgcPredictionClass.objects.filter(bgc_count__gt=0).order_by("-bgc_count")
    ]


@discovery_router.get("/filters/np-classes/", response=list[NpClassLevel])
def np_classes(request):
    paths = (
        IbgcNaturalProduct.objects
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

    Uses the ChemOnt OBO ontology when available; otherwise the tree is flat
    (since each CDS only carries its deepest class, hierarchy can only be
    reconstructed via the ontology).
    """
    # Direct annotation counts: BGCs that have at least one CDS classified to
    # each chemont_id.
    rows = list(
        CdsChemOnt.objects
        .values("chemont_id", "chemont_name")
        .annotate(cnt=Count("cds__bgc", distinct=True))
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
        # No ontology: each CDS carries only its deepest class, so we can't
        # reconstruct hierarchy. Return a flat list of leaves.
        for cid in annotated_ids:
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


@discovery_router.get("/filters/gcfs/", response=PaginatedGcfResponse)
def gcf_list(
    request,
    search: Optional[str] = None,
    level: Optional[int] = None,
    page: int = 1,
    page_size: int = 50,
):
    # Scope to the latest ClusteringRun — IntegratedBgc.gene_cluster_family is
    # rewritten on every successful run, so this is the only set whose paths
    # match the live iBGC rows that ``leaf_path_prefix`` filters against.
    run = ClusteringRun.objects.order_by("-created_at").first()
    if run is None:
        return PaginatedGcfResponse(
            items=[],
            pagination=PaginationMeta(page=1, page_size=page_size, total_count=0, total_pages=0),
        )

    qs = DashboardGCF.objects.filter(clustering_run=run, member_count__gt=0)
    if search:
        qs = qs.filter(family_path__icontains=search)
    if level is not None:
        qs = qs.filter(level=level)

    total_count = qs.count()
    pg, ps, tp, offset = _paginate(page, page_size, total_count)

    items = [
        GcfOption(
            family_path=g.family_path,
            level=g.level,
            member_count=g.member_count,
            validated_count=g.validated_count,
            mean_novelty=g.mean_novelty,
        )
        for g in qs.order_by("-member_count", "level", "family_path")[offset: offset + ps]
    ]

    return PaginatedGcfResponse(
        items=items,
        pagination=PaginationMeta(page=pg, page_size=ps, total_count=total_count, total_pages=tp),
    )


@discovery_router.get("/filters/sources/", response=PaginatedSourceResponse)
def source_list(
    request,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
):
    qs = AssemblySource.objects.filter(assemblies__isnull=False).annotate(
        assembly_count=Count("assemblies", distinct=True)
    )
    if search:
        qs = qs.filter(name__icontains=search)
    total_count = qs.count()
    pg, ps, tp, offset = _paginate(page, page_size, total_count)
    items = [
        SourceOption(name=s.name, count=s.assembly_count)
        for s in qs.order_by("-assembly_count")[offset: offset + ps]
    ]
    return PaginatedSourceResponse(
        items=items,
        pagination=PaginationMeta(page=pg, page_size=ps, total_count=total_count, total_pages=tp),
    )


@discovery_router.get("/filters/detectors/", response=PaginatedDetectorResponse)
def detector_list(
    request,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
):
    qs = (
        DashboardDetector.objects
        .values("tool")
        .annotate(count=Count("bgcs"))
        .filter(count__gt=0)
    )
    if search:
        qs = qs.filter(tool__icontains=search)
    total_count = qs.count()
    pg, ps, tp, offset = _paginate(page, page_size, total_count)
    items = [
        DetectorOption(tool=d["tool"], count=d["count"])
        for d in qs.order_by("-count")[offset: offset + ps]
    ]
    return PaginatedDetectorResponse(
        items=items,
        pagination=PaginationMeta(page=pg, page_size=ps, total_count=total_count, total_pages=tp),
    )


# ── Stats endpoints ──────────────────────────────────────────────────────────


@discovery_router.get("/stats/assemblies/", response=AssemblyStatsResponse)
def assembly_stats(
    request,
    search: Optional[str] = None,
    taxonomy_path: Optional[str] = None,
    source_names: Optional[str] = None,
    detector_tools: Optional[str] = None,
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
        source_names=source_names,
        detector_tools=detector_tools,
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
    qs = SourceBgcPrediction.objects.all()
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
    source_names: Optional[str] = None,
    detector_tools: Optional[str] = None,
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
        source_names=source_names,
        detector_tools=detector_tools,
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
    qs = SourceBgcPrediction.objects.all()
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


# Assessment endpoints removed in v2 — the Evaluate Asset feature is
# superseded by the Shortlist Report flow (see /report/snapshot/).


# ── Platform overview ─────────────────────────────────────────────────────────


@discovery_router.get("/stats/", response=DiscoveryStatsResponse)
def discovery_stats(request):
    """Latest Discovery Platform overview counts for the Run Query card."""
    latest = DiscoveryStats.objects.order_by("-created_at").first()
    if latest is None:
        return DiscoveryStatsResponse()
    known = {
        k: v
        for k, v in latest.stats.items()
        if k in DiscoveryStatsResponse.model_fields
    }
    return DiscoveryStatsResponse(**known, updated_at=latest.updated_at)


# ── Ephemeral asset upload ───────────────────────────────────────────────────


# Compressed (.tar.gz) upload cap. The decompressed cap lives in
# ``asset_upload/schemas.py:MAX_TARBALL_BYTES``; this one bounds the bytes we
# accept on the wire so a hostile client can't OOM us before validation.
_ASSET_MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB


@discovery_router.post(
    "/assets/upload/",
    response={202: AssetUploadAccepted},
)
def asset_upload(request):
    """Upload an ephemeral tarball of BGC TSVs (``Ga…_assembly_upload.tar.gz``).

    Returns ``202`` with ``{token, task_id}``; the projection runs in a
    Celery worker and the result is cached in Redis under ``asset:{token}:*``
    for 6 hours. Poll ``GET /assets/{token}/status/`` for progress.

    The request body is ``multipart/form-data`` with a single ``file`` field.
    """
    import hashlib

    from discovery.services.asset_upload import cache as asset_cache
    from discovery.tasks import process_asset_upload_task

    upload = request.FILES.get("file")
    if upload is None:
        raise HttpError(400, "Missing 'file' field in multipart upload")

    if upload.size and upload.size > _ASSET_MAX_UPLOAD_BYTES:
        raise HttpError(413, "Upload exceeds 5 MB cap")

    raw = upload.read(_ASSET_MAX_UPLOAD_BYTES + 1)
    if len(raw) > _ASSET_MAX_UPLOAD_BYTES:
        raise HttpError(413, "Upload exceeds 5 MB cap")

    if not raw.startswith(b"\x1f\x8b"):
        raise HttpError(400, "Upload must be a gzip-compressed tarball")

    token = hashlib.sha256(raw).hexdigest()[:24]

    # Park the bytes in Redis so the Celery worker (separate pod, separate
    # /tmp) can read them by token. Avoids any shared-filesystem coupling.
    asset_cache.stash_upload(token, raw)

    # Mark pending up front so concurrent status polls don't return UNKNOWN
    # in the gap between dispatch and the worker writing RUNNING.
    asset_cache.mark_pending(token, task_id="")
    async_result = process_asset_upload_task.delay(token)
    # If the cache still says PENDING, fold the actual task_id in. The worker
    # may have already written RUNNING / SUCCESS by now — leave that alone.
    status_payload = asset_cache.read_status(token)
    if status_payload and status_payload.get("state") == "PENDING":
        asset_cache.mark_pending(token, task_id=async_result.id)

    return 202, AssetUploadAccepted(token=token, task_id=async_result.id)


@discovery_router.get(
    "/assets/{token}/status/", response=AssetStatusResponse,
)
def asset_status(request, token: str):
    """Return the current state of the asset projection.

    ``state`` is one of ``PENDING``, ``RUNNING``, ``SUCCESS``, ``FAILED``,
    ``UNKNOWN`` (when the token has expired or never existed).
    """
    from discovery.services.asset_upload import cache as asset_cache

    payload = asset_cache.read_status(token)
    if payload is None:
        return AssetStatusResponse(state="UNKNOWN")
    return AssetStatusResponse(**payload)


@discovery_router.delete("/assets/{token}/", response={204: None})
def asset_evict(request, token: str):
    """Drop every Redis key tied to this asset token (user X-click on chip)."""
    from discovery.services.asset_upload import cache as asset_cache

    asset_cache.evict_asset(token)
    return 204, None


# ── iBGC region (merged CDS view) ──────────────────────────────────────────────


@discovery_router.get("/ibgcs/{ibgc_id}/region/", response=IbgcRegionOut)
def ibgc_region(request, ibgc_id: int):
    """Merged region payload for an iBGC.

    Pools every ``ContigCds`` whose ``cds_range`` overlaps the iBGC's
    ``bgc_range`` on the same contig. Each CDS carries ``claimed_by_tools``
    — the sorted unique tool codes whose ``SourceBgcPrediction`` range
    covers it within this iBGC. Coordinates are relative to the iBGC
    interval (``window_start=0``).
    """
    from django.db import connection
    from discovery.models import IntegratedBgc

    try:
        ibgc = IntegratedBgc.objects.select_related("contig", "cbgc").get(id=ibgc_id)
    except IntegratedBgc.DoesNotExist:
        raise HttpError(404, f"iBGC {ibgc_id} not found")

    bgc_range = ibgc.bgc_range
    window_start = bgc_range.lower
    window_end = bgc_range.upper
    region_length = window_end - window_start

    predictions = list(
        SourceBgcPrediction.objects.filter(integrated_bgc_id=ibgc.id)
        .select_related("detector")
    )

    # CDS overlapping the iBGC range, on the same contig.
    cds_rows = list(
        ContigCds.objects.filter(
            contig_id=ibgc.contig_id,
            cds_range__overlap=bgc_range,
        ).select_related("seq").order_by("cds_range")
    )
    cds_ids = [c.id for c in cds_rows]

    # Domains per CDS (with InterPro projection done client-side via collapse).
    domains_by_cds: dict[int, list] = {}
    if cds_ids:
        for d in ContigDomain.objects.filter(cds_id__in=cds_ids).order_by(
            "cds_id", "start_position",
        ):
            domains_by_cds.setdefault(d.cds_id, []).append(d)

    # Per-CDS ChemOnt (deepest class per CDS, when present).
    chemont_by_cds: dict[int, CdsChemOnt] = {}
    if cds_ids:
        for ch in CdsChemOnt.objects.filter(cds_id__in=cds_ids):
            chemont_by_cds.setdefault(ch.cds_id, ch)

    cds_list_out: list[RegionCdsOut] = []
    domain_list_out: list[RegionDomainOut] = []
    for cds in cds_rows:
        cds_doms = domains_by_cds.get(cds.id, [])
        interpro = collapse_to_interpro_rows(cds_doms)

        pfam = []
        for d in cds_doms:
            pfam.append(PfamAnnotationOut(
                accession=d.domain_acc or "",
                description=d.domain_description or d.domain_name or "",
                go_slim=list(d.go_slim or []),
                envelope_start=d.start_position or 0,
                envelope_end=d.end_position or 0,
                e_value=str(d.score) if d.score is not None else None,
                url=d.url or "",
            ))
            if (cds.strand or 1) >= 0:
                dom_nt_start = cds.start_position + (d.start_position or 0) * 3
                dom_nt_end = cds.start_position + (d.end_position or 0) * 3
            else:
                dom_nt_start = cds.end_position - (d.end_position or 0) * 3
                dom_nt_end = cds.end_position - (d.start_position or 0) * 3
            domain_list_out.append(RegionDomainOut(
                accession=d.domain_acc or "",
                description=d.domain_description or d.domain_name or "",
                start=max(0, dom_nt_start - window_start),
                end=max(0, dom_nt_end - window_start),
                strand=cds.strand,
                score=d.score,
                go_slim=list(d.go_slim or []),
                parent_cds_id=cds.protein_id_str,
                url=d.url or "",
            ))

        # claimed_by_tools: predictions whose bgc_range overlaps this CDS.
        claimed: set[str] = set()
        for pred in predictions:
            if pred.bgc_range is None:
                continue
            if pred.bgc_range.lower < cds.cds_range.upper and \
               cds.cds_range.lower < pred.bgc_range.upper:
                tool = pred.detector.tool if pred.detector_id else ""
                if tool:
                    claimed.add(tool)

        seq_obj = getattr(cds, "seq", None)
        sequence = seq_obj.get_sequence() if seq_obj else ""

        chemont_hit = chemont_by_cds.get(cds.id)
        cds_list_out.append(RegionCdsOut(
            protein_id=cds.protein_id_str,
            start=cds.start_position - window_start,
            end=cds.end_position - window_start,
            strand=cds.strand,
            protein_length=cds.protein_length,
            gene_caller=cds.gene_caller or "",
            cluster_representative=cds.cluster_representative or None,
            cluster_representative_url=None,
            sequence=sequence,
            pfam=pfam,
            interpro=[InterproAnnotationOut(**r) for r in interpro],
            chemont_id=chemont_hit.chemont_id if chemont_hit else None,
            chemont_name=chemont_hit.chemont_name if chemont_hit else None,
            chemont_probability=chemont_hit.probability if chemont_hit else None,
            chemont_weight=chemont_hit.weight if chemont_hit else None,
            claimed_by_tools=sorted(claimed),
        ))

    cluster_list_out = []
    for pred in predictions:
        if pred.bgc_range is None:
            continue
        cluster_list_out.append(RegionClusterOut(
            accession=pred.prediction_accession,
            start=max(0, pred.bgc_range.lower - window_start),
            end=max(0, pred.bgc_range.upper - 1 - window_start),
            source=pred.detector.tool if pred.detector_id else "",
            bgc_classes=[],
        ))

    return IbgcRegionOut(
        ibgc_id=ibgc.id,
        ibgc_accession=ibgc.accession,
        cbgc_accession=ibgc.cbgc.accession if ibgc.cbgc_id else "",
        region_length=region_length,
        window_start=0,
        window_end=region_length,
        contig_accession=ibgc.contig.accession if ibgc.contig_id else None,
        cds_list=cds_list_out,
        domain_list=domain_list_out,
        cluster_list=cluster_list_out,
    )


# ── Accession resolve ─────────────────────────────────────────────────────────


@discovery_router.get("/accessions/resolve/{accession}/", response=AccessionResolveOut)
def accession_resolve(request, accession: str):
    """Resolve an ``MGYB-XXXXXX`` (cBGC) or ``MGYB-XXXXXX-YY`` (iBGC) accession.

    Walks ``AccessionAlias`` so tombstoned accessions still find their live
    successor. Returns ``tombstoned=True`` with a NULL ``current_id`` when
    the accession has been retired without a replacement.
    """
    from discovery.models import AccessionEntityType
    from discovery.services.accession_registry import resolve as registry_resolve

    canonical = accession.strip().upper()
    resolved = registry_resolve(canonical)
    if resolved is None:
        raise HttpError(404, f"Unknown accession {accession!r}")

    kind = "ibgc" if resolved.kind == AccessionEntityType.IBGC else "cbgc"
    if resolved.current_id is None:
        current_url: Optional[str] = None
    elif kind == "ibgc":
        current_url = f"/api/discovery/ibgcs/{resolved.current_id}/"
    else:
        current_url = f"/api/discovery/cbgcs/{resolved.current_id}/"

    return AccessionResolveOut(
        accession=resolved.accession,
        kind=kind,
        current_id=resolved.current_id,
        current_url=current_url,
        tombstoned=resolved.tombstoned,
        alias_of=resolved.alias_of,
    )
