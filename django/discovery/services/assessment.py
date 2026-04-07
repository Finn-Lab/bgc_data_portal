"""Asset evaluation service — core computation for assembly and BGC assessment.

Uses the self-contained discovery models (DashboardAssembly, DashboardBgc,
BgcEmbedding, BgcDomain, DashboardGCF) instead of cross-schema joins.
Precomputed percentile columns on DashboardAssembly eliminate full-table scans.
"""

from __future__ import annotations

import numpy as np
from django.db.models import Avg, Count, F, Q
from pgvector.django import CosineDistance

from discovery.models import (
    BgcDomain,
    BgcEmbedding,
    DashboardBgc,
    DashboardGCF,
    DashboardAssembly,
    PrecomputedStats,
)


# Score dimensions for assembly percentile analysis
ASSEMBLY_SCORE_DIMENSIONS = [
    ("bgc_diversity_score", "Diversity"),
    ("bgc_novelty_score", "Novelty"),
    ("bgc_density", "Density"),
]

# If distance to nearest GCF representative exceeds this, BGC is a novel singleton.
GCF_NOVELTY_DISTANCE_THRESHOLD = 0.7


def compute_assembly_assessment(assembly_id: int) -> dict:
    """Produce a full assembly assessment report.

    Parameters
    ----------
    assembly_id : int
        Primary key of the DashboardAssembly to assess.
    """
    assembly = DashboardAssembly.objects.get(pk=assembly_id)
    total_all = DashboardAssembly.objects.count()
    total_ts = DashboardAssembly.objects.filter(is_type_strain=True).count()

    # ── Percentile ranks (precomputed columns) ──────────────────────────
    pctl_map = {
        "bgc_diversity_score": assembly.pctl_diversity,
        "bgc_novelty_score": assembly.pctl_novelty,
        "bgc_density": assembly.pctl_density,
    }
    percentile_ranks = []
    for dim, label in ASSEMBLY_SCORE_DIMENSIONS:
        value = getattr(assembly, dim)
        pctl_all = pctl_map[dim]
        # Type-strain percentile: SQL count
        count_ts = DashboardAssembly.objects.filter(
            is_type_strain=True, **{f"{dim}__lte": value}
        ).count()
        percentile_ranks.append(
            {
                "dimension": dim,
                "label": label,
                "value": round(value, 4),
                "percentile_all": round(pctl_all, 1),
                "percentile_type_strain": round(count_ts / max(total_ts, 1) * 100, 1),
            }
        )

    # ── DB rank by novelty score ────
    higher_count = DashboardAssembly.objects.filter(
        bgc_novelty_score__gt=assembly.bgc_novelty_score
    ).count()
    db_rank = higher_count + 1

    # ── BGC novelty breakdown ────────────────────────────────────────────
    bgcs = DashboardBgc.objects.filter(assembly=assembly)
    bgc_novelty_breakdown = [
        {
            "bgc_id": bgc.id,
            "accession": bgc.bgc_accession,
            "classification_path": bgc.classification_path,
            "novelty_vs_validated": round(bgc.nearest_validated_distance or 0.0, 4),
            "novelty_vs_db": round(bgc.novelty_score, 4),
            "domain_novelty": round(bgc.domain_novelty, 4),
            "is_partial": bgc.is_partial,
        }
        for bgc in bgcs
    ]
    bgc_novelty_breakdown.sort(key=lambda x: x["novelty_vs_db"], reverse=True)

    # ── Redundancy matrix ────────────────────────────────────────────────
    redundancy_matrix = []
    for bgc in bgcs:
        if not bgc.gene_cluster_family:
            redundancy_matrix.append(
                {
                    "bgc_id": bgc.id,
                    "accession": bgc.bgc_accession,
                    "classification_path": bgc.classification_path,
                    "gcf_family_id": None,
                    "gcf_member_count": 0,
                    "gcf_has_validated": False,
                    "gcf_has_type_strain": False,
                    "status": "novel_gcf",
                }
            )
            continue

        gcf = DashboardGCF.objects.filter(family_id=bgc.gene_cluster_family).first()
        if gcf is None:
            redundancy_matrix.append(
                {
                    "bgc_id": bgc.id,
                    "accession": bgc.bgc_accession,
                    "classification_path": bgc.classification_path,
                    "gcf_family_id": bgc.gene_cluster_family,
                    "gcf_member_count": 0,
                    "gcf_has_validated": False,
                    "gcf_has_type_strain": False,
                    "status": "novel_gcf",
                }
            )
            continue

        has_validated = gcf.validated_count > 0
        has_type_strain = DashboardBgc.objects.filter(
            gene_cluster_family=gcf.family_id, assembly__is_type_strain=True
        ).exclude(id=bgc.id).exists()

        status = "known_gcf_type_strain" if has_type_strain else "known_gcf_no_type_strain"

        redundancy_matrix.append(
            {
                "bgc_id": bgc.id,
                "accession": bgc.bgc_accession,
                "classification_path": bgc.classification_path,
                "gcf_family_id": gcf.family_id,
                "gcf_member_count": gcf.member_count,
                "gcf_has_validated": has_validated,
                "gcf_has_type_strain": has_type_strain,
                "status": status,
            }
        )

    # ── Chemical space ───────────────────────────────────────────────────
    # Use precomputed stats for sparse threshold when available
    try:
        bgc_stats = PrecomputedStats.objects.get(key="bgc_global")
        sparse_threshold = bgc_stats.data.get("sparse_threshold", 0.5)
    except PrecomputedStats.DoesNotExist:
        all_validated_dists = list(
            DashboardBgc.objects.filter(
                nearest_validated_distance__isnull=False
            ).values_list("nearest_validated_distance", flat=True)[:10_000]
        )
        sparse_threshold = float(np.percentile(all_validated_dists, 75)) if all_validated_dists else 0.5

    chemical_space_points = [
        {
            "bgc_id": bgc.id,
            "accession": bgc.bgc_accession,
            "umap_x": bgc.umap_x,
            "umap_y": bgc.umap_y,
            "classification_path": bgc.classification_path,
            "nearest_validated_distance": round(bgc.nearest_validated_distance or 0.0, 4),
            "is_sparse": (bgc.nearest_validated_distance or 0.0) > sparse_threshold,
        }
        for bgc in bgcs
    ]

    validated_ref_points = list(
        DashboardBgc.objects.filter(is_validated=True).values(
            "bgc_accession", "classification_path", "umap_x", "umap_y"
        )
    )

    sparse_count = sum(1 for p in chemical_space_points if p["is_sparse"])
    sparse_fraction = sparse_count / max(len(chemical_space_points), 1)
    mean_validated_dist = (
        np.mean([p["nearest_validated_distance"] for p in chemical_space_points])
        if chemical_space_points
        else 0.0
    )

    # ── Radar reference data (precomputed or on-the-fly) ────────────────
    try:
        assembly_stats = PrecomputedStats.objects.get(key="assembly_global")
        radar_references = assembly_stats.data.get("radar_references", [])
    except PrecomputedStats.DoesNotExist:
        radar_references = []
        for dim, label in ASSEMBLY_SCORE_DIMENSIONS:
            agg = DashboardAssembly.objects.aggregate(db_mean=Avg(dim))
            vals = list(
                DashboardAssembly.objects.values_list(dim, flat=True)[:10_000]
            )
            db_p90 = float(np.percentile(vals, 90)) if vals else 0.0
            radar_references.append(
                {
                    "dimension": dim,
                    "label": label,
                    "db_mean": round(agg["db_mean"] or 0.0, 4),
                    "db_p90": round(db_p90, 4),
                }
            )

    return {
        "assembly_id": assembly.id,
        "accession": assembly.assembly_accession,
        "organism_name": assembly.organism_name,
        "is_type_strain": assembly.is_type_strain,
        "percentile_ranks": percentile_ranks,
        "db_rank": db_rank,
        "db_total": total_all,
        "bgc_novelty_breakdown": bgc_novelty_breakdown,
        "redundancy_matrix": redundancy_matrix,
        "chemical_space_points": chemical_space_points,
        "validated_reference_points": validated_ref_points,
        "mean_nearest_validated_distance": round(float(mean_validated_dist), 4),
        "sparse_fraction": round(sparse_fraction, 4),
        "radar_references": radar_references,
    }


def compute_bgc_assessment(bgc_id: int) -> dict:
    """Produce a full BGC assessment report.

    Parameters
    ----------
    bgc_id : int
        Primary key of the DashboardBgc to assess.
    """
    bgc = DashboardBgc.objects.select_related("assembly").get(pk=bgc_id)

    classification_path = bgc.classification_path

    # ── GCF placement ────────────────────────────────────────────────────
    gcf_context = None
    distance_to_rep = None
    is_novel_singleton = False

    if bgc.gene_cluster_family:
        gcf = DashboardGCF.objects.filter(family_id=bgc.gene_cluster_family).first()
        if gcf:
            gcf_context = _build_gcf_context(gcf, bgc)
            # Compute distance to representative via embedding if available
            if gcf.representative_bgc_id:
                try:
                    bgc_emb = BgcEmbedding.objects.get(bgc=bgc)
                    rep_emb = BgcEmbedding.objects.filter(bgc_id=gcf.representative_bgc_id).first()
                    if rep_emb:
                        dist_qs = (
                            BgcEmbedding.objects.filter(bgc_id=gcf.representative_bgc_id)
                            .annotate(distance=CosineDistance("vector", bgc_emb.vector))
                            .values_list("distance", flat=True)
                            .first()
                        )
                        distance_to_rep = float(dist_qs) if dist_qs is not None else None
                except BgcEmbedding.DoesNotExist:
                    pass
        else:
            is_novel_singleton = True
    else:
        # Try nearest-neighbor GCF placement via embedding
        try:
            bgc_emb = BgcEmbedding.objects.get(bgc=bgc)
            gcf, dist = _find_nearest_gcf(bgc_emb)
            if gcf and dist <= GCF_NOVELTY_DISTANCE_THRESHOLD:
                gcf_context = _build_gcf_context(gcf, bgc)
                distance_to_rep = dist
            else:
                is_novel_singleton = True
        except BgcEmbedding.DoesNotExist:
            is_novel_singleton = True

    # ── Domain differential ──────────────────────────────────────────────
    submitted_domains = _get_bgc_domains(bgc)
    submitted_domain_accs = {d["domain_acc"] for d in submitted_domains}
    domain_differential = []

    if gcf_context:
        gcf_domain_freq = {
            d["domain_acc"]: d for d in gcf_context["domain_frequency"]
        }
        for acc in submitted_domain_accs:
            freq_item = gcf_domain_freq.get(acc)
            freq = freq_item["frequency"] if freq_item else 0.0
            name = freq_item["domain_name"] if freq_item else _get_domain_name(acc)
            if freq >= 0.8:
                category = "core"
            elif freq < 0.5:
                category = "variable"
            else:
                category = "core"
            domain_differential.append(
                {
                    "domain_acc": acc,
                    "domain_name": name,
                    "in_submitted": True,
                    "gcf_frequency": round(freq, 4),
                    "category": category,
                }
            )
        for acc, freq_item in gcf_domain_freq.items():
            if acc not in submitted_domain_accs and freq_item["frequency"] > 0.5:
                domain_differential.append(
                    {
                        "domain_acc": acc,
                        "domain_name": freq_item["domain_name"],
                        "in_submitted": False,
                        "gcf_frequency": round(freq_item["frequency"], 4),
                        "category": "absent",
                    }
                )

    # ── Novelty decomposition ────────────────────────────────────────────
    novelty = _compute_novelty_decomposition(bgc, submitted_domain_accs)

    # ── Chemical space ───────────────────────────────────────────────────
    submitted_point = {
        "bgc_id": bgc.id,
        "accession": bgc.bgc_accession,
        "umap_x": bgc.umap_x,
        "umap_y": bgc.umap_y,
        "classification_path": classification_path,
        "nearest_validated_distance": round(bgc.nearest_validated_distance or 0.0, 4),
        "is_sparse": False,
    }

    nearest_neighbors = _find_nearest_neighbors(bgc, k=20)
    validated_ref_points = list(
        DashboardBgc.objects.filter(is_validated=True).values(
            "bgc_accession", "classification_path", "umap_x", "umap_y"
        )
    )

    # ── Nearest validated BGC for domain comparison ──────────────────────
    nearest_validated_accession = bgc.nearest_validated_accession or None
    nearest_validated_bgc_id = None
    if nearest_validated_accession:
        ref_bgc = DashboardBgc.objects.filter(
            bgc_accession=nearest_validated_accession
        ).values_list("id", flat=True).first()
        if ref_bgc:
            nearest_validated_bgc_id = ref_bgc

    return {
        "bgc_id": bgc.id,
        "accession": bgc.bgc_accession,
        "classification_path": classification_path,
        "gcf_context": gcf_context,
        "distance_to_gcf_representative": round(distance_to_rep, 4) if distance_to_rep is not None else None,
        "is_novel_singleton": is_novel_singleton,
        "domain_differential": domain_differential,
        "novelty": novelty,
        "submitted_point": submitted_point,
        "nearest_neighbors": nearest_neighbors,
        "validated_reference_points": validated_ref_points,
        "submitted_domains": submitted_domains,
        "nearest_validated_accession": nearest_validated_accession,
        "nearest_validated_bgc_id": nearest_validated_bgc_id,
    }


def find_similar_assemblies(assembly_id: int, k: int = 10) -> list[int]:
    """Find the K most similar assemblies by mean BGC embedding distance.

    Returns a list of DashboardAssembly IDs.
    """
    assembly = DashboardAssembly.objects.get(pk=assembly_id)

    # Get BGC embeddings for this assembly from the dedicated table
    embeddings = list(
        BgcEmbedding.objects.filter(
            bgc__assembly=assembly
        ).values_list("vector", flat=True)
    )
    if not embeddings:
        return []

    mean_embedding = np.mean(embeddings, axis=0).tolist()

    # ANN search on the lean embedding table
    nearest_bgcs = (
        BgcEmbedding.objects.exclude(bgc__assembly=assembly)
        .annotate(distance=CosineDistance("vector", mean_embedding))
        .order_by("distance")
        .select_related("bgc")[:k * 5]
    )

    seen_assemblies = set()
    result = []
    for emb in nearest_bgcs:
        aid = emb.bgc.assembly_id
        if aid not in seen_assemblies:
            seen_assemblies.add(aid)
            result.append(aid)
            if len(result) >= k:
                break

    return result


# ── Private helpers ──────────────────────────────────────────────────────────


def _build_gcf_context(gcf: DashboardGCF, exclude_bgc: DashboardBgc) -> dict:
    """Build the GCF context panel data."""
    members = DashboardBgc.objects.filter(
        gene_cluster_family=gcf.family_id
    ).select_related("assembly")

    member_points = []
    novelty_values = []
    taxonomy_counts: dict[str, int] = {}

    for mbgc in members:
        assembly = mbgc.assembly
        is_ts = assembly.is_type_strain if assembly else False
        tax_label = assembly.organism_name if assembly else "Unknown"

        member_points.append(
            {
                "bgc_id": mbgc.id,
                "umap_x": mbgc.umap_x,
                "umap_y": mbgc.umap_y,
                "is_type_strain": is_ts,
                "accession": mbgc.bgc_accession,
            }
        )
        novelty_values.append(mbgc.novelty_score)

        tf = tax_label or "Unknown"
        taxonomy_counts[tf] = taxonomy_counts.get(tf, 0) + 1

    # Domain frequency via BgcDomain (single join)
    member_bgc_ids = [m.id for m in members]
    domain_frequency = _compute_gcf_domain_frequency(member_bgc_ids)

    taxonomy_distribution = [
        {"taxonomy_label": k, "count": v}
        for k, v in sorted(taxonomy_counts.items(), key=lambda x: -x[1])
    ]

    return {
        "gcf_id": gcf.id,
        "family_id": gcf.family_id,
        "member_count": gcf.member_count,
        "validated_count": gcf.validated_count,
        "mean_novelty": round(np.mean(novelty_values) if novelty_values else 0.0, 4),
        "known_chemistry_annotation": gcf.known_chemistry_annotation or None,
        "validated_accession": gcf.validated_accession or None,
        "domain_frequency": domain_frequency,
        "taxonomy_distribution": taxonomy_distribution,
        "member_points": member_points,
    }


def _compute_gcf_domain_frequency(member_bgc_ids: list[int]) -> list[dict]:
    """Compute domain frequency across GCF member BGCs via BgcDomain."""
    if not member_bgc_ids:
        return []

    n_members = len(member_bgc_ids)

    domain_counts = (
        BgcDomain.objects.filter(bgc_id__in=member_bgc_ids)
        .values("domain_acc", "domain_name", "domain_description")
        .annotate(bgc_count=Count("bgc", distinct=True))
        .filter(bgc_count__gte=1)
        .order_by("-bgc_count")
    )

    result = []
    for row in domain_counts:
        freq = row["bgc_count"] / n_members
        if freq >= 0.8:
            category = "core"
        elif freq >= 0.2:
            category = "variable"
        else:
            category = "rare"
        result.append(
            {
                "domain_acc": row["domain_acc"],
                "domain_name": row["domain_name"],
                "description": row["domain_description"] or "",
                "frequency": round(freq, 4),
                "category": category,
            }
        )

    return result


def _get_bgc_domains(bgc: DashboardBgc) -> list[dict]:
    """Get domain list for a BGC from the denormalized BgcDomain table."""
    return [
        {
            "domain_acc": bd.domain_acc,
            "domain_name": bd.domain_name,
            "ref_db": bd.ref_db,
            "start": 0,
            "end": 0,
            "score": None,
        }
        for bd in BgcDomain.objects.filter(bgc=bgc).order_by("domain_acc")
    ]


def _get_domain_name(acc: str) -> str:
    """Lookup a domain name by accession from BgcDomain."""
    bd = BgcDomain.objects.filter(domain_acc=acc).first()
    return bd.domain_name if bd else acc


def _find_nearest_gcf(bgc_emb: BgcEmbedding) -> tuple[DashboardGCF | None, float | None]:
    """Find the nearest GCF by cosine distance to its representative's embedding."""
    rep_bgc_ids = list(
        DashboardGCF.objects.filter(
            representative_bgc__isnull=False
        ).values_list("representative_bgc_id", flat=True)
    )
    if not rep_bgc_ids:
        return None, None

    nearest = (
        BgcEmbedding.objects.filter(bgc_id__in=rep_bgc_ids)
        .annotate(distance=CosineDistance("vector", bgc_emb.vector))
        .order_by("distance")
        .first()
    )

    if nearest is None:
        return None, None

    gcf = DashboardGCF.objects.filter(representative_bgc_id=nearest.bgc_id).first()
    return gcf, float(nearest.distance)


def _compute_novelty_decomposition(
    bgc: DashboardBgc, submitted_domain_accs: set[str]
) -> dict:
    """Compute three-axis novelty decomposition for a BGC."""
    # Sequence novelty via embedding table
    sequence_novelty = 0.0
    try:
        bgc_emb = BgcEmbedding.objects.get(bgc=bgc)
        nearest_db = (
            BgcEmbedding.objects.exclude(bgc=bgc)
            .annotate(distance=CosineDistance("vector", bgc_emb.vector))
            .order_by("distance")
            .values_list("distance", flat=True)
            .first()
        )
        if nearest_db is not None:
            sequence_novelty = min(float(nearest_db), 1.0)
    except BgcEmbedding.DoesNotExist:
        pass

    # Chemistry novelty (distance to nearest validated BGC)
    chemistry_novelty = 0.0
    if bgc.nearest_validated_distance is not None:
        chemistry_novelty = min(bgc.nearest_validated_distance, 1.0)

    # Architecture novelty: fraction of domains not found in any other DB BGC
    architecture_novelty = 0.0
    if submitted_domain_accs:
        known_domains = set(
            BgcDomain.objects.filter(domain_acc__in=submitted_domain_accs)
            .exclude(bgc=bgc)
            .values_list("domain_acc", flat=True)
            .distinct()
        )
        novel_count = len(submitted_domain_accs - known_domains)
        architecture_novelty = novel_count / len(submitted_domain_accs)

    return {
        "sequence_novelty": round(sequence_novelty, 4),
        "chemistry_novelty": round(chemistry_novelty, 4),
        "architecture_novelty": round(architecture_novelty, 4),
    }


def _find_nearest_neighbors(bgc: DashboardBgc, k: int = 20) -> list[dict]:
    """Find K nearest BGCs (including validated ones) by embedding distance."""
    neighbors: list[dict] = []

    try:
        bgc_emb = BgcEmbedding.objects.get(bgc=bgc)
    except BgcEmbedding.DoesNotExist:
        return neighbors

    nearest_bgcs = (
        BgcEmbedding.objects.exclude(bgc=bgc)
        .annotate(distance=CosineDistance("vector", bgc_emb.vector))
        .order_by("distance")
        .select_related("bgc")[:k]
    )
    for nb in nearest_bgcs:
        neighbors.append(
            {
                "bgc_id": nb.bgc.id,
                "validated_accession": nb.bgc.bgc_accession if nb.bgc.is_validated else None,
                "umap_x": nb.bgc.umap_x,
                "umap_y": nb.bgc.umap_y,
                "distance": round(float(nb.distance), 4),
                "label": nb.bgc.bgc_accession,
                "is_validated": nb.bgc.is_validated,
            }
        )

    neighbors.sort(key=lambda x: x["distance"])
    return neighbors
