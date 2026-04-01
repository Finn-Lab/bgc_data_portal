"""Asset evaluation service — core computation for genome and BGC assessment.

Uses the self-contained discovery models (DashboardGenome, DashboardBgc,
BgcEmbedding, BgcDomain, DashboardGCF) instead of cross-schema joins.
Precomputed percentile columns on DashboardGenome eliminate full-table scans.
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
    DashboardGenome,
    DashboardMibigReference,
    PrecomputedStats,
)
from discovery.services.scoring import compute_composite_priority


# Score dimensions for genome percentile analysis
GENOME_SCORE_DIMENSIONS = [
    ("bgc_diversity_score", "Diversity"),
    ("bgc_novelty_score", "Novelty"),
    ("bgc_density", "Density"),
]

# If distance to nearest GCF representative exceeds this, BGC is a novel singleton.
GCF_NOVELTY_DISTANCE_THRESHOLD = 0.7


def compute_genome_assessment(genome_id: int, weights: dict) -> dict:
    """Produce a full genome assessment report.

    Parameters
    ----------
    genome_id : int
        Primary key of the DashboardGenome to assess.
    weights : dict
        User-selected weights for composite priority.
    """
    genome = DashboardGenome.objects.get(pk=genome_id)
    total_all = DashboardGenome.objects.count()
    total_ts = DashboardGenome.objects.filter(is_type_strain=True).count()

    # ── Percentile ranks (precomputed columns) ──────────────────────────
    pctl_map = {
        "bgc_diversity_score": genome.pctl_diversity,
        "bgc_novelty_score": genome.pctl_novelty,
        "bgc_density": genome.pctl_density,
    }
    percentile_ranks = []
    for dim, label in GENOME_SCORE_DIMENSIONS:
        value = getattr(genome, dim)
        pctl_all = pctl_map[dim]
        # Type-strain percentile: SQL count
        count_ts = DashboardGenome.objects.filter(
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

    # ── Composite score and DB rank (SQL aggregate, not Python loop) ────
    w_div = weights.get("w_diversity", 0.30)
    w_nov = weights.get("w_novelty", 0.45)
    w_den = weights.get("w_density", 0.25)

    composite = compute_composite_priority(
        scores={
            "diversity": genome.bgc_diversity_score,
            "novelty": genome.bgc_novelty_score,
            "density": genome.bgc_density,
        },
        weights={"diversity": w_div, "novelty": w_nov, "density": w_den},
    )

    # Count genomes with higher composite via SQL expression
    from django.db.models import ExpressionWrapper, FloatField, Value
    w_sum = w_div + w_nov + w_den
    if w_sum > 0:
        higher_count = DashboardGenome.objects.annotate(
            c=ExpressionWrapper(
                (Value(w_div) * F("bgc_diversity_score")
                 + Value(w_nov) * F("bgc_novelty_score")
                 + Value(w_den) * F("bgc_density")) / Value(w_sum),
                output_field=FloatField(),
            )
        ).filter(c__gt=composite).count()
    else:
        higher_count = 0

    db_rank = higher_count + 1

    # ── BGC novelty breakdown ────────────────────────────────────────────
    bgcs = DashboardBgc.objects.filter(genome=genome)
    bgc_novelty_breakdown = [
        {
            "bgc_id": bgc.id,
            "accession": bgc.bgc_accession,
            "classification_l1": bgc.classification_l1,
            "novelty_vs_mibig": round(bgc.nearest_mibig_distance or 0.0, 4),
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
        if bgc.gcf_id is None:
            redundancy_matrix.append(
                {
                    "bgc_id": bgc.id,
                    "accession": bgc.bgc_accession,
                    "classification_l1": bgc.classification_l1,
                    "gcf_family_id": None,
                    "gcf_member_count": 0,
                    "gcf_has_mibig": False,
                    "gcf_has_type_strain": False,
                    "status": "novel_gcf",
                }
            )
            continue

        try:
            gcf = DashboardGCF.objects.get(pk=bgc.gcf_id)
        except DashboardGCF.DoesNotExist:
            redundancy_matrix.append(
                {
                    "bgc_id": bgc.id,
                    "accession": bgc.bgc_accession,
                    "classification_l1": bgc.classification_l1,
                    "gcf_family_id": None,
                    "gcf_member_count": 0,
                    "gcf_has_mibig": False,
                    "gcf_has_type_strain": False,
                    "status": "novel_gcf",
                }
            )
            continue

        has_mibig = bool(gcf.mibig_accession)
        # Check if any co-member's genome is a type strain
        has_type_strain = DashboardBgc.objects.filter(
            gcf_id=gcf.id, genome__is_type_strain=True
        ).exclude(id=bgc.id).exists()

        status = "known_gcf_type_strain" if has_type_strain else "known_gcf_no_type_strain"

        redundancy_matrix.append(
            {
                "bgc_id": bgc.id,
                "accession": bgc.bgc_accession,
                "classification_l1": bgc.classification_l1,
                "gcf_family_id": gcf.family_id,
                "gcf_member_count": gcf.member_count,
                "gcf_has_mibig": has_mibig,
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
        all_mibig_dists = list(
            DashboardBgc.objects.filter(
                nearest_mibig_distance__isnull=False
            ).values_list("nearest_mibig_distance", flat=True)[:10_000]
        )
        sparse_threshold = float(np.percentile(all_mibig_dists, 75)) if all_mibig_dists else 0.5

    chemical_space_points = [
        {
            "bgc_id": bgc.id,
            "accession": bgc.bgc_accession,
            "umap_x": bgc.umap_x,
            "umap_y": bgc.umap_y,
            "classification_l1": bgc.classification_l1,
            "nearest_mibig_distance": round(bgc.nearest_mibig_distance or 0.0, 4),
            "is_sparse": (bgc.nearest_mibig_distance or 0.0) > sparse_threshold,
        }
        for bgc in bgcs
    ]

    mibig_points = list(
        DashboardMibigReference.objects.values(
            "accession", "compound_name", "bgc_class", "umap_x", "umap_y"
        )
    )

    sparse_count = sum(1 for p in chemical_space_points if p["is_sparse"])
    sparse_fraction = sparse_count / max(len(chemical_space_points), 1)
    mean_mibig_dist = (
        np.mean([p["nearest_mibig_distance"] for p in chemical_space_points])
        if chemical_space_points
        else 0.0
    )

    # ── Radar reference data (precomputed or on-the-fly) ────────────────
    try:
        genome_stats = PrecomputedStats.objects.get(key="genome_global")
        radar_references = genome_stats.data.get("radar_references", [])
    except PrecomputedStats.DoesNotExist:
        radar_references = []
        for dim, label in GENOME_SCORE_DIMENSIONS:
            agg = DashboardGenome.objects.aggregate(db_mean=Avg(dim))
            vals = list(
                DashboardGenome.objects.values_list(dim, flat=True)[:10_000]
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
        "assembly_id": genome.id,
        "accession": genome.assembly_accession,
        "organism_name": genome.organism_name,
        "is_type_strain": genome.is_type_strain,
        "percentile_ranks": percentile_ranks,
        "db_rank": db_rank,
        "db_total": total_all,
        "composite_score": round(composite, 4),
        "bgc_novelty_breakdown": bgc_novelty_breakdown,
        "redundancy_matrix": redundancy_matrix,
        "chemical_space_points": chemical_space_points,
        "mibig_reference_points": mibig_points,
        "mean_nearest_mibig_distance": round(float(mean_mibig_dist), 4),
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
    bgc = DashboardBgc.objects.select_related("genome").get(pk=bgc_id)

    classification_l1 = bgc.classification_l1
    classification_l2 = bgc.classification_l2

    # ── GCF placement ────────────────────────────────────────────────────
    gcf_context = None
    distance_to_rep = bgc.distance_to_gcf_representative
    is_novel_singleton = False

    if bgc.gcf_id is not None:
        try:
            gcf = DashboardGCF.objects.get(pk=bgc.gcf_id)
            gcf_context = _build_gcf_context(gcf, bgc)
        except DashboardGCF.DoesNotExist:
            is_novel_singleton = True
            distance_to_rep = None
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
                distance_to_rep = None
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
        "classification_l1": classification_l1,
        "nearest_mibig_distance": round(bgc.nearest_mibig_distance or 0.0, 4),
        "is_sparse": False,
    }

    nearest_neighbors = _find_nearest_neighbors(bgc, k=20)
    mibig_points = list(
        DashboardMibigReference.objects.values(
            "accession", "compound_name", "bgc_class", "umap_x", "umap_y"
        )
    )

    # ── Nearest MIBiG for domain comparison ──────────────────────────────
    nearest_mibig_accession = bgc.nearest_mibig_accession or None
    nearest_mibig_bgc_id = None
    if nearest_mibig_accession:
        mibig_ref = DashboardMibigReference.objects.filter(
            accession=nearest_mibig_accession
        ).first()
        if mibig_ref and mibig_ref.dashboard_bgc_id:
            nearest_mibig_bgc_id = mibig_ref.dashboard_bgc_id

    return {
        "bgc_id": bgc.id,
        "accession": bgc.bgc_accession,
        "classification_l1": classification_l1,
        "classification_l2": classification_l2,
        "gcf_context": gcf_context,
        "distance_to_gcf_representative": round(distance_to_rep, 4) if distance_to_rep is not None else None,
        "is_novel_singleton": is_novel_singleton,
        "domain_differential": domain_differential,
        "novelty": novelty,
        "submitted_point": submitted_point,
        "nearest_neighbors": nearest_neighbors,
        "mibig_reference_points": mibig_points,
        "submitted_domains": submitted_domains,
        "nearest_mibig_accession": nearest_mibig_accession,
        "nearest_mibig_bgc_id": nearest_mibig_bgc_id,
    }


def find_similar_genomes(genome_id: int, k: int = 10) -> list[int]:
    """Find the K most similar genomes by mean BGC embedding distance.

    Returns a list of DashboardGenome IDs.
    """
    genome = DashboardGenome.objects.get(pk=genome_id)

    # Get BGC embeddings for this genome from the dedicated table
    embeddings = list(
        BgcEmbedding.objects.filter(
            bgc__genome=genome
        ).values_list("vector", flat=True)
    )
    if not embeddings:
        return []

    mean_embedding = np.mean(embeddings, axis=0).tolist()

    # ANN search on the lean embedding table
    nearest_bgcs = (
        BgcEmbedding.objects.exclude(bgc__genome=genome)
        .annotate(distance=CosineDistance("vector", mean_embedding))
        .order_by("distance")
        .select_related("bgc")[:k * 5]
    )

    seen_genomes = set()
    result = []
    for emb in nearest_bgcs:
        gid = emb.bgc.genome_id
        if gid not in seen_genomes:
            seen_genomes.add(gid)
            result.append(gid)
            if len(result) >= k:
                break

    return result


# ── Private helpers ──────────────────────────────────────────────────────────


def _build_gcf_context(gcf: DashboardGCF, exclude_bgc: DashboardBgc) -> dict:
    """Build the GCF context panel data."""
    members = DashboardBgc.objects.filter(gcf_id=gcf.id).select_related("genome")

    member_points = []
    novelty_values = []
    taxonomy_counts: dict[str, int] = {}

    for mbgc in members:
        genome = mbgc.genome
        is_ts = genome.is_type_strain if genome else False
        tax_family = genome.taxonomy_family if genome else "Unknown"

        member_points.append(
            {
                "bgc_id": mbgc.id,
                "umap_x": mbgc.umap_x,
                "umap_y": mbgc.umap_y,
                "is_type_strain": is_ts,
                "distance_to_representative": round(
                    mbgc.distance_to_gcf_representative or 0.0, 4
                ),
                "accession": mbgc.bgc_accession,
            }
        )
        novelty_values.append(mbgc.novelty_score)

        tf = tax_family or "Unknown"
        taxonomy_counts[tf] = taxonomy_counts.get(tf, 0) + 1

    # Domain frequency via BgcDomain (single join)
    member_bgc_ids = [m.id for m in members]
    domain_frequency = _compute_gcf_domain_frequency(member_bgc_ids)

    taxonomy_distribution = [
        {"taxonomy_family": k, "count": v}
        for k, v in sorted(taxonomy_counts.items(), key=lambda x: -x[1])
    ]

    return {
        "gcf_id": gcf.id,
        "family_id": gcf.family_id,
        "member_count": gcf.member_count,
        "mibig_count": gcf.mibig_count,
        "mean_novelty": round(np.mean(novelty_values) if novelty_values else 0.0, 4),
        "known_chemistry_annotation": gcf.known_chemistry_annotation or None,
        "mibig_accession": gcf.mibig_accession or None,
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

    # Chemistry novelty
    chemistry_novelty = 0.0
    if bgc.nearest_mibig_distance is not None:
        chemistry_novelty = min(bgc.nearest_mibig_distance, 1.0)

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
    """Find K nearest DB BGCs and MIBiG references to a BGC."""
    neighbors: list[dict] = []

    try:
        bgc_emb = BgcEmbedding.objects.get(bgc=bgc)
    except BgcEmbedding.DoesNotExist:
        return neighbors

    # Nearest DB BGCs via embedding table
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
                "mibig_accession": None,
                "umap_x": nb.bgc.umap_x,
                "umap_y": nb.bgc.umap_y,
                "distance": round(float(nb.distance), 4),
                "label": nb.bgc.bgc_accession,
                "is_mibig": False,
            }
        )

    # Nearest MIBiG references
    nearest_mibig = (
        DashboardMibigReference.objects.filter(embedding__isnull=False)
        .annotate(distance=CosineDistance("embedding", bgc_emb.vector))
        .order_by("distance")[:5]
    )
    for mr in nearest_mibig:
        neighbors.append(
            {
                "bgc_id": None,
                "mibig_accession": mr.accession,
                "umap_x": mr.umap_x,
                "umap_y": mr.umap_y,
                "distance": round(float(mr.distance), 4),
                "label": f"{mr.accession} ({mr.compound_name})",
                "is_mibig": True,
            }
        )

    neighbors.sort(key=lambda x: x["distance"])
    return neighbors
