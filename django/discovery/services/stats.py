"""Aggregation statistics for the discovery dashboard stats panels."""

import random
from collections import defaultdict

from django.db.models import Avg, Count, Q

from discovery.models import BgcScore, GenomeScore, NaturalProduct
from mgnify_bgcs.models import Domain, ProteinDomain


MAX_BOXPLOT_VALUES = 10_000


def _sample_values(values: list[float], limit: int = MAX_BOXPLOT_VALUES) -> list[float]:
    """Randomly sample values if they exceed the limit."""
    if len(values) <= limit:
        return values
    return random.sample(values, limit)


# ── Genome stats ─────────────────────────────────────────────────────────────


def compute_genome_stats(assembly_qs) -> dict:
    """Compute aggregate statistics for a filtered Assembly queryset.

    Returns a dict ready to be serialised into GenomeStatsResponse.
    """
    # Taxonomy sunburst — flat list of {id, label, parent, count}
    taxonomy_sunburst = _build_taxonomy_sunburst(assembly_qs)

    # Score distributions for boxplots
    score_rows = list(
        assembly_qs.filter(genome_score__isnull=False).values_list(
            "genome_score__bgc_diversity_score",
            "genome_score__bgc_novelty_score",
            "genome_score__bgc_density",
        )
    )
    diversity_vals = _sample_values([r[0] for r in score_rows if r[0] is not None])
    novelty_vals = _sample_values([r[1] for r in score_rows if r[1] is not None])
    density_vals = _sample_values([r[2] for r in score_rows if r[2] is not None])

    score_distributions = [
        {"label": "Diversity", "values": diversity_vals},
        {"label": "Novelty", "values": novelty_vals},
        {"label": "Density", "values": density_vals},
    ]

    # Type strain counts
    strain_agg = assembly_qs.aggregate(
        type_strain=Count("id", filter=Q(is_type_strain=True)),
        non_type_strain=Count("id", filter=Q(is_type_strain=False)),
    )

    # Average BGC count and L1 class count per genome
    avg_agg = GenomeScore.objects.filter(
        assembly__in=assembly_qs
    ).aggregate(
        mean_bgc=Avg("bgc_count"),
        mean_l1=Avg("l1_class_count"),
    )

    return {
        "taxonomy_sunburst": taxonomy_sunburst,
        "score_distributions": score_distributions,
        "type_strain_count": strain_agg["type_strain"],
        "non_type_strain_count": strain_agg["non_type_strain"],
        "mean_bgc_per_genome": round(avg_agg["mean_bgc"] or 0.0, 2),
        "mean_l1_class_per_genome": round(avg_agg["mean_l1"] or 0.0, 2),
        "total_genomes": assembly_qs.count(),
    }


def _build_taxonomy_sunburst(assembly_qs) -> list[dict]:
    """Build a flat list for Plotly sunburst from taxonomy columns.

    Returns [{id, label, parent, count}, ...] where parent="" for root nodes.
    """
    ranks = [
        "taxonomy_kingdom",
        "taxonomy_phylum",
        "taxonomy_class",
        "taxonomy_order",
        "taxonomy_family",
        "taxonomy_genus",
    ]
    rank_labels = {
        "taxonomy_kingdom": "Kingdom",
        "taxonomy_phylum": "Phylum",
        "taxonomy_class": "Class",
        "taxonomy_order": "Order",
        "taxonomy_family": "Family",
        "taxonomy_genus": "Genus",
    }

    rows = assembly_qs.values(*ranks).annotate(count=Count("id"))

    # Build a tree then flatten
    nodes: dict[str, dict] = {}  # id -> {label, parent, count}

    for row in rows:
        count = row["count"]
        parent_id = ""
        for rank in ranks:
            value = row[rank]
            if not value:
                break
            node_id = f"{rank}:{value}"
            if node_id not in nodes:
                nodes[node_id] = {
                    "id": node_id,
                    "label": value,
                    "parent": parent_id,
                    "count": 0,
                }
            nodes[node_id]["count"] += count
            parent_id = node_id

    return list(nodes.values())


# ── BGC stats ────────────────────────────────────────────────────────────────


def compute_bgc_stats(bgc_qs) -> dict:
    """Compute aggregate statistics for a filtered Bgc queryset.

    Returns a dict ready to be serialised into BgcStatsResponse.
    """
    total_bgcs = bgc_qs.count()

    # Core domains (present in >80% of BGCs)
    core_domains = _compute_core_domains(bgc_qs, total_bgcs)

    # Score distributions for boxplots
    score_rows = list(
        BgcScore.objects.filter(bgc__in=bgc_qs).values_list(
            "novelty_score", "domain_novelty"
        )
    )
    novelty_vals = _sample_values([r[0] for r in score_rows if r[0] is not None])
    domain_novelty_vals = _sample_values([r[1] for r in score_rows if r[1] is not None])

    score_distributions = [
        {"label": "Novelty", "values": novelty_vals},
        {"label": "Domain Novelty", "values": domain_novelty_vals},
    ]

    # Completeness counts
    completeness_agg = bgc_qs.aggregate(
        complete=Count("id", filter=Q(is_partial=False)),
        partial=Count("id", filter=Q(is_partial=True)),
    )

    # NP chemical class sunburst
    np_class_sunburst = _build_np_class_sunburst(bgc_qs)

    # BGC class distribution
    bgc_class_dist = list(
        BgcScore.objects.filter(bgc__in=bgc_qs)
        .exclude(classification_l1="")
        .values("classification_l1")
        .annotate(count=Count("bgc_id"))
        .order_by("-count")
    )
    bgc_class_distribution = [
        {"name": row["classification_l1"], "count": row["count"]}
        for row in bgc_class_dist
    ]

    return {
        "core_domains": core_domains,
        "score_distributions": score_distributions,
        "complete_count": completeness_agg["complete"],
        "partial_count": completeness_agg["partial"],
        "np_class_sunburst": np_class_sunburst,
        "bgc_class_distribution": bgc_class_distribution,
        "total_bgcs": total_bgcs,
    }


def _compute_core_domains(bgc_qs, total_bgcs: int) -> list[dict]:
    """Find domains present in >80% of the filtered BGCs."""
    if total_bgcs == 0:
        return []

    threshold = int(total_bgcs * 0.8)
    if threshold < 1:
        threshold = 1

    # Count how many distinct BGCs each domain appears in.
    # Path: ProteinDomain → Protein → Cds → Contig → Bgc
    domain_counts = (
        Domain.objects.filter(
            proteindomain__protein__cds__contig__bgcs__in=bgc_qs
        )
        .annotate(
            bgc_count=Count(
                "proteindomain__protein__cds__contig__bgcs",
                distinct=True,
                filter=Q(proteindomain__protein__cds__contig__bgcs__in=bgc_qs),
            )
        )
        .filter(bgc_count__gte=threshold)
        .values("acc", "name", "bgc_count")
        .order_by("-bgc_count")
    )

    return [
        {
            "acc": row["acc"],
            "name": row["name"],
            "bgc_count": row["bgc_count"],
            "fraction": round(row["bgc_count"] / total_bgcs, 4),
        }
        for row in domain_counts
    ]


def _build_np_class_sunburst(bgc_qs) -> list[dict]:
    """Build a flat sunburst list for NP chemical class hierarchy."""
    nps = NaturalProduct.objects.filter(bgc__in=bgc_qs).values(
        "chemical_class_l1", "chemical_class_l2", "chemical_class_l3"
    ).annotate(count=Count("id"))

    nodes: dict[str, dict] = {}

    for row in nps:
        count = row["count"]
        l1 = row["chemical_class_l1"]
        l2 = row["chemical_class_l2"]
        l3 = row["chemical_class_l3"]

        if not l1:
            continue

        l1_id = f"l1:{l1}"
        if l1_id not in nodes:
            nodes[l1_id] = {"id": l1_id, "label": l1, "parent": "", "count": 0}
        nodes[l1_id]["count"] += count

        if l2:
            l2_id = f"l2:{l1}/{l2}"
            if l2_id not in nodes:
                nodes[l2_id] = {"id": l2_id, "label": l2, "parent": l1_id, "count": 0}
            nodes[l2_id]["count"] += count

            if l3:
                l3_id = f"l3:{l1}/{l2}/{l3}"
                if l3_id not in nodes:
                    nodes[l3_id] = {"id": l3_id, "label": l3, "parent": l2_id, "count": 0}
                nodes[l3_id]["count"] += count

    return list(nodes.values())
