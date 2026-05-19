"""Aggregation statistics for the Discovery Platform stats panels.

Uses DashboardAssembly/DashboardBgc and the denormalized BgcDomain table
instead of cross-schema joins.  For unfiltered views, reads from
PrecomputedStats to avoid full-table scans.
"""

import random
from collections import defaultdict

from django.db.models import Avg, Count, Q

from discovery.models import (
    AssemblyType,
    BgcDomain,
    DashboardBgc,
    DashboardAssembly,
    DashboardCdsChemOnt,
    DashboardNaturalProduct,
    DashboardRegion,
    PrecomputedStats,
)


MAX_BOXPLOT_VALUES = 10_000


def _sample_values(values: list[float], limit: int = MAX_BOXPLOT_VALUES) -> list[float]:
    """Randomly sample values if they exceed the limit."""
    if len(values) <= limit:
        return values
    return random.sample(values, limit)


# ── Assembly stats ───────────────────────────────────────────────────────────


def compute_assembly_stats(assembly_qs) -> dict:
    """Compute aggregate statistics for a filtered DashboardAssembly queryset.

    Returns a dict ready to be serialised into AssemblyStatsResponse.
    """
    taxonomy_sunburst = _build_taxonomy_sunburst(assembly_qs)

    # Score distributions for boxplots
    score_rows = list(
        assembly_qs.values_list(
            "bgc_diversity_score",
            "bgc_novelty_score",
            "bgc_density",
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

    # Average BGC count and L1 class count per assembly
    avg_agg = assembly_qs.aggregate(
        mean_bgc=Avg("bgc_count"),
        mean_l1=Avg("l1_class_count"),
    )

    # Biome and source distributions (one count per assembly).
    biome_distribution = [
        {"name": row["biome_path"] or "(unknown)", "count": row["c"]}
        for row in (
            assembly_qs.values("biome_path")
            .annotate(c=Count("id"))
            .order_by("-c", "biome_path")
        )
    ]
    source_distribution = [
        {"name": row["source__name"] or "(unknown)", "count": row["c"]}
        for row in (
            assembly_qs.values("source__name")
            .annotate(c=Count("id"))
            .order_by("-c", "source__name")
        )
    ]

    return {
        "taxonomy_sunburst": taxonomy_sunburst,
        "score_distributions": score_distributions,
        "type_strain_count": strain_agg["type_strain"],
        "non_type_strain_count": strain_agg["non_type_strain"],
        "mean_bgc_per_assembly": round(avg_agg["mean_bgc"] or 0.0, 2),
        "mean_l1_class_per_assembly": round(avg_agg["mean_l1"] or 0.0, 2),
        "total_assemblies": assembly_qs.count(),
        "biome_distribution": biome_distribution,
        "source_distribution": source_distribution,
    }


TAXONOMY_RANK_NAMES = [
    "kingdom", "phylum", "class", "order", "family", "genus", "species",
]


def build_taxonomy_sunburst_from_paths(paths) -> list[dict]:
    """Build flat sunburst nodes from an iterable of ltree taxonomy paths.

    Each non-empty path contributes one count to every ancestor node it
    traverses. Returns ``[{id, label, parent, count}, ...]`` with
    ``parent=""`` for root nodes.
    """
    nodes: dict[str, dict] = {}
    for path in paths:
        if not path:
            continue
        parts = path.split(".")
        parent_id = ""
        for depth, label in enumerate(parts):
            rank = (
                TAXONOMY_RANK_NAMES[depth]
                if depth < len(TAXONOMY_RANK_NAMES)
                else f"rank_{depth}"
            )
            node_id = f"{rank}:{label}"
            if node_id not in nodes:
                nodes[node_id] = {
                    "id": node_id,
                    "label": label,
                    "parent": parent_id,
                    "count": 0,
                }
            nodes[node_id]["count"] += 1
            parent_id = node_id
    return list(nodes.values())


def _build_taxonomy_sunburst(assembly_qs) -> list[dict]:
    """Build a flat list for Plotly sunburst from contig taxonomy_path (ltree).

    Returns [{id, label, parent, count}, ...] where parent="" for root nodes.
    """
    from discovery.models import DashboardContig

    contig_paths = (
        DashboardContig.objects.filter(assembly__in=assembly_qs)
        .exclude(taxonomy_path="")
        .values_list("taxonomy_path", flat=True)
    )
    return build_taxonomy_sunburst_from_paths(contig_paths)


# ── BGC stats ────────────────────────────────────────────────────────────────


def compute_bgc_stats(bgc_qs) -> dict:
    """Compute aggregate statistics for a filtered DashboardBgc queryset.

    Returns a dict ready to be serialised into BgcStatsResponse.
    """
    total_bgcs = bgc_qs.count()

    # Core domains (present in >80% of BGCs) — single join to BgcDomain
    core_domains = _compute_core_domains(bgc_qs, total_bgcs)

    # Score distributions for boxplots
    score_rows = list(
        bgc_qs.values_list("novelty_score", "domain_novelty")
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

    # NP chemical class sunburst (legacy)
    np_class_sunburst = _build_np_class_sunburst(bgc_qs)

    # ChemOnt class sunburst
    chemont_sunburst = _build_chemont_sunburst(bgc_qs)

    # BGC class distribution (from first segment of classification_path)
    from django.db.models.expressions import RawSQL

    bgc_class_dist = list(
        bgc_qs.exclude(classification_path="")
        .annotate(class_l1=RawSQL("SPLIT_PART(classification_path, '.', 1)", []))
        .values("class_l1")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    bgc_class_distribution = [
        {"name": row["class_l1"], "count": row["count"]}
        for row in bgc_class_dist
    ]

    return {
        "core_domains": core_domains,
        "score_distributions": score_distributions,
        "complete_count": completeness_agg["complete"],
        "partial_count": completeness_agg["partial"],
        "np_class_sunburst": np_class_sunburst,
        "chemont_sunburst": chemont_sunburst,
        "bgc_class_distribution": bgc_class_distribution,
        "total_bgcs": total_bgcs,
    }


def _compute_core_domains(bgc_qs, total_bgcs: int) -> list[dict]:
    """Find domains present in >80% of the filtered BGCs.

    Uses the denormalized BgcDomain table — a single join instead of the
    previous 5-table chain (Domain→ProteinDomain→Protein→CDS→Contig→BGC).
    """
    if total_bgcs == 0:
        return []

    threshold = max(1, int(total_bgcs * 0.8))

    domain_counts = (
        BgcDomain.objects.filter(bgc__in=bgc_qs)
        .values("domain_acc", "domain_name")
        .annotate(bgc_count=Count("bgc", distinct=True))
        .filter(bgc_count__gte=threshold)
        .order_by("-bgc_count")
    )

    return [
        {
            "acc": row["domain_acc"],
            "name": row["domain_name"],
            "bgc_count": row["bgc_count"],
            "fraction": round(row["bgc_count"] / total_bgcs, 4),
        }
        for row in domain_counts
    ]


def _build_np_class_sunburst(bgc_qs) -> list[dict]:
    """Build a flat sunburst list for NP chemical class hierarchy."""
    paths = (
        DashboardNaturalProduct.objects.filter(bgc__in=bgc_qs)
        .exclude(np_class_path="")
        .values_list("np_class_path", flat=True)
    )

    nodes: dict[str, dict] = {}

    for path in paths:
        parts = path.split(".")
        l1 = parts[0] if len(parts) > 0 else ""
        l2 = parts[1] if len(parts) > 1 else ""
        l3 = parts[2] if len(parts) > 2 else ""

        if not l1:
            continue

        l1_id = f"l1:{l1}"
        if l1_id not in nodes:
            nodes[l1_id] = {"id": l1_id, "label": l1, "parent": "", "count": 0}
        nodes[l1_id]["count"] += 1

        if l2:
            l2_id = f"l2:{l1}/{l2}"
            if l2_id not in nodes:
                nodes[l2_id] = {"id": l2_id, "label": l2, "parent": l1_id, "count": 0}
            nodes[l2_id]["count"] += 1

            if l3:
                l3_id = f"l3:{l1}/{l2}/{l3}"
                if l3_id not in nodes:
                    nodes[l3_id] = {"id": l3_id, "label": l3, "parent": l2_id, "count": 0}
                nodes[l3_id]["count"] += 1

    return list(nodes.values())


def _build_chemont_sunburst(bgc_qs) -> list[dict]:
    """Build a flat sunburst list for ChemOnt chemical class hierarchy."""
    rows = (
        DashboardCdsChemOnt.objects.filter(cds__bgc__in=bgc_qs)
        .values("chemont_id", "chemont_name")
        .annotate(cnt=Count("cds__bgc", distinct=True))
    )

    if not rows:
        return []

    try:
        from common_core.chemont.ontology import get_ontology

        ont = get_ontology()
    except (FileNotFoundError, ImportError):
        return [
            {"id": r["chemont_id"], "label": r["chemont_name"], "parent": "", "count": r["cnt"]}
            for r in rows
        ]

    direct_counts: dict[str, int] = {}
    name_map: dict[str, str] = {}
    for r in rows:
        direct_counts[r["chemont_id"]] = r["cnt"]
        name_map[r["chemont_id"]] = r["chemont_name"]

    relevant_ids: set[str] = set(direct_counts.keys())
    for cid in list(direct_counts.keys()):
        for ancestor in ont.get_ancestors(cid):
            relevant_ids.add(ancestor.id)
            if ancestor.id not in name_map:
                name_map[ancestor.id] = ancestor.name

    nodes: dict[str, dict] = {}
    for tid in relevant_ids:
        term = ont.get_term(tid)
        parent = ""
        if term and term.parent_ids:
            for pid in term.parent_ids:
                if pid in relevant_ids:
                    parent = pid
                    break
        nodes[tid] = {
            "id": tid,
            "label": name_map.get(tid, tid),
            "parent": parent,
            "count": direct_counts.get(tid, 0),
        }

    return list(nodes.values())


# ── Platform overview ─────────────────────────────────────────────────────────


def generate_discovery_stats() -> dict:
    """High-level Discovery Platform counts shown in the Run Query card."""
    return {
        "genomes": DashboardAssembly.objects.filter(
            assembly_type=AssemblyType.GENOME
        ).count(),
        "metagenomes": DashboardAssembly.objects.filter(
            assembly_type=AssemblyType.METAGENOME
        ).count(),
        "validated_bgcs": DashboardBgc.objects.filter(is_validated=True).count(),
        "regions": DashboardRegion.objects.count(),
        "total_bgc_predictions": DashboardBgc.objects.count(),
    }
