"""Aggregation statistics for the Discovery Platform stats panels.

iBGC is the unit of every stats panel — ``compute_bgc_stats`` takes an
``IntegratedBgc`` queryset. Domain / NP / ChemOnt aggregations reach
their targets through range-overlap joins on the contig (no more
through-BGC FK chain). For unfiltered views, reads from PrecomputedStats
to avoid full-table scans.

The legacy ``BgcStatsResponse`` field names (``total_bgcs``,
``core_domains``, ``bgc_class_distribution``) are kept for API parity —
the values now reflect iBGC-level counts.
"""

import random
from collections import defaultdict

from django.db import connection
from django.db.models import Avg, Count, Q

from discovery.models import (
    AssemblyType,
    CdsChemOnt,
    DashboardAssembly,
    IbgcNaturalProduct,
    IntegratedBgc,
    PrecomputedStats,
    SourceBgcPrediction,
)


MAX_BOXPLOT_VALUES = 10_000


def _sample_values(values: list[float], limit: int = MAX_BOXPLOT_VALUES) -> list[float]:
    """Randomly sample values if they exceed the limit."""
    if len(values) <= limit:
        return values
    return random.sample(values, limit)


# ── Assembly stats ───────────────────────────────────────────────────────────


def compute_assembly_stats(assembly_qs) -> dict:
    """Compute aggregate statistics for a filtered DashboardAssembly queryset."""
    taxonomy_sunburst = _build_taxonomy_sunburst(assembly_qs)

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

    strain_agg = assembly_qs.aggregate(
        type_strain=Count("id", filter=Q(is_type_strain=True)),
        non_type_strain=Count("id", filter=Q(is_type_strain=False)),
    )

    avg_agg = assembly_qs.aggregate(
        mean_bgc=Avg("bgc_count"),
        mean_l1=Avg("l1_class_count"),
    )

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
    """Build flat sunburst nodes from an iterable of ltree taxonomy paths."""
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
    from discovery.models import DashboardContig

    contig_paths = (
        DashboardContig.objects.filter(assembly__in=assembly_qs)
        .exclude(taxonomy_path="")
        .values_list("taxonomy_path", flat=True)
    )
    return build_taxonomy_sunburst_from_paths(contig_paths)


# ── iBGC stats ───────────────────────────────────────────────────────────────


def compute_bgc_stats(ibgc_qs) -> dict:
    """Compute aggregate statistics for a filtered ``IntegratedBgc`` queryset.

    Returns a dict ready to be serialised into ``BgcStatsResponse``. The
    response field names retain the legacy ``bgc_`` prefix for API parity;
    counts and pools reflect iBGCs.
    """
    total_ibgcs = ibgc_qs.count()

    core_domains = _compute_core_domains(ibgc_qs, total_ibgcs)

    score_rows = list(
        ibgc_qs.values_list("novelty_score", "domain_novelty")
    )
    novelty_vals = _sample_values([r[0] for r in score_rows if r[0] is not None])
    domain_novelty_vals = _sample_values([r[1] for r in score_rows if r[1] is not None])

    score_distributions = [
        {"label": "Novelty", "values": novelty_vals},
        {"label": "Domain Novelty", "values": domain_novelty_vals},
    ]

    # An iBGC is "complete" iff none of its source predictions are partial.
    # Compute via an EXISTS subquery on SourceBgcPrediction.
    ibgc_ids = list(ibgc_qs.values_list("id", flat=True))
    if ibgc_ids:
        partial_ids = set(
            SourceBgcPrediction.objects
            .filter(integrated_bgc_id__in=ibgc_ids, is_partial=True)
            .values_list("integrated_bgc_id", flat=True)
            .distinct()
        )
    else:
        partial_ids = set()
    partial_count = len(partial_ids)
    complete_count = total_ibgcs - partial_count

    np_class_sunburst = _build_np_class_sunburst(ibgc_qs)
    chemont_sunburst = _build_chemont_sunburst(ibgc_qs)

    from django.db.models.expressions import RawSQL

    bgc_class_dist = list(
        ibgc_qs.exclude(gene_cluster_family="")
        .annotate(class_l1=RawSQL("SPLIT_PART(gene_cluster_family, '.', 1)", []))
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
        "complete_count": complete_count,
        "partial_count": partial_count,
        "np_class_sunburst": np_class_sunburst,
        "chemont_sunburst": chemont_sunburst,
        "bgc_class_distribution": bgc_class_distribution,
        "total_bgcs": total_ibgcs,
    }


def _compute_core_domains(ibgc_qs, total_ibgcs: int) -> list[dict]:
    """Find domains present in >80% of the filtered iBGCs.

    Joins ``discovery_domain_hit`` → ``discovery_cds`` → ``discovery_ibgc``
    via range overlap. A domain is counted once per iBGC even if it appears
    on multiple CDS within that iBGC.
    """
    if total_ibgcs == 0:
        return []

    ibgc_ids = list(ibgc_qs.values_list("id", flat=True))
    if not ibgc_ids:
        return []

    threshold = max(1, int(total_ibgcs * 0.8))

    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT d.domain_acc,
                   MAX(d.domain_name) AS domain_name,
                   COUNT(DISTINCT i.id) AS ibgc_count
            FROM discovery_domain_hit d
            JOIN discovery_cds c ON c.id = d.cds_id
            JOIN discovery_ibgc i
              ON i.contig_id = c.contig_id
             AND i.bgc_range && c.cds_range
            WHERE i.id = ANY(%s::bigint[])
            GROUP BY d.domain_acc
            HAVING COUNT(DISTINCT i.id) >= %s
            ORDER BY ibgc_count DESC, d.domain_acc ASC
            """,
            [ibgc_ids, threshold],
        )
        rows = cur.fetchall()

    return [
        {
            "acc": acc,
            "name": name or "",
            "bgc_count": ibgc_count,
            "fraction": round(ibgc_count / total_ibgcs, 4),
        }
        for acc, name, ibgc_count in rows
    ]


def _build_np_class_sunburst(ibgc_qs) -> list[dict]:
    """Flat sunburst list for NP chemical class hierarchy across iBGCs."""
    paths = (
        IbgcNaturalProduct.objects.filter(ibgc__in=ibgc_qs)
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


def _build_chemont_sunburst(ibgc_qs) -> list[dict]:
    """Flat sunburst list for ChemOnt chemical class hierarchy across iBGCs.

    Joins ``discovery_cds_chemont`` → ``discovery_cds`` → ``discovery_ibgc``
    via range overlap. Each (iBGC, chemont_id) pair contributes one count.
    """
    ibgc_ids = list(ibgc_qs.values_list("id", flat=True))
    if not ibgc_ids:
        return []

    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT ch.chemont_id,
                   MAX(ch.chemont_name) AS chemont_name,
                   COUNT(DISTINCT i.id) AS cnt
            FROM discovery_cds_chemont ch
            JOIN discovery_cds c ON c.id = ch.cds_id
            JOIN discovery_ibgc i
              ON i.contig_id = c.contig_id
             AND i.bgc_range && c.cds_range
            WHERE i.id = ANY(%s::bigint[])
            GROUP BY ch.chemont_id
            """,
            [ibgc_ids],
        )
        rows = cur.fetchall()

    if not rows:
        return []

    try:
        from common_core.chemont.ontology import get_ontology

        ont = get_ontology()
    except (FileNotFoundError, ImportError):
        return [
            {"id": cid, "label": cname, "parent": "", "count": cnt}
            for cid, cname, cnt in rows
        ]

    direct_counts: dict[str, int] = {cid: cnt for cid, _cname, cnt in rows}
    name_map: dict[str, str] = {cid: cname or "" for cid, cname, _cnt in rows}

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
    """High-level Discovery Platform counts shown in the Run Query card.

    ``validated_bgcs`` counts iBGCs whose source predictions include at
    least one validated row (ground-truth iBGCs).
    """
    validated_ibgc_ids = (
        SourceBgcPrediction.objects
        .filter(is_validated=True, integrated_bgc__isnull=False)
        .values_list("integrated_bgc_id", flat=True)
        .distinct()
    )
    return {
        "genomes": DashboardAssembly.objects.filter(
            assembly_type=AssemblyType.GENOME
        ).count(),
        "metagenomes": DashboardAssembly.objects.filter(
            assembly_type=AssemblyType.METAGENOME
        ).count(),
        "validated_bgcs": IntegratedBgc.objects.filter(id__in=validated_ibgc_ids).count(),
        "ibgcs": IntegratedBgc.objects.count(),
        "total_bgc_predictions": SourceBgcPrediction.objects.count(),
    }
