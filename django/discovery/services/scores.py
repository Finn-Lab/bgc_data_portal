"""Score recomputation service for the discovery platform.

Computes all derived scores and materialised tables from raw loaded data:
  - Assembly aggregates (iBGC count, l1_class_count, novelty, diversity, density)
  - Assembly percentile ranks
  - GCF table aggregate refresh from the latest ClusteringRun
  - Catalog table rebuild (DashboardBgcClass, DashboardDomain)
  - ChemOnt Information Content precomputation
  - UMAP coordinate recomputation (no-op stub; layout is written inline by
    the clustering pipeline)

iBGC-level novelty and ``domain_novelty`` are written by
``discovery.services.clustering.ibgc_scoring`` over the composite-Dice
matrix — not here.
"""

from __future__ import annotations

import logging

from django.db import connection
from django.db.models import Count, Min
from django.db.models.expressions import RawSQL

from discovery.models import (
    CdsChemOnt,
    ContigDomain,
    DashboardAssembly,
    DashboardBgcClass,
    DashboardDomain,
    DashboardGCF,
    IntegratedBgc,
    PrecomputedStats,
)

logger = logging.getLogger(__name__)

BATCH_SIZE = 10_000


def recompute_all_scores() -> None:
    """Master function — orchestrates all score recomputation."""
    logger.info("Starting full score recomputation ...")
    _compute_assembly_aggregates()
    _compute_percentile_ranks()
    _rebuild_gcf_table()
    _rebuild_catalog_tables()
    _compute_chemont_ic()
    _recompute_umap()
    logger.info("Score recomputation complete.")


# ── Assembly-level scores ────────────────────────────────────────────────────


def _compute_assembly_aggregates() -> None:
    """Recompute denormalised iBGC-derived scores on DashboardAssembly.

    ``bgc_count`` reflects iBGC count via the contig chain
    (``assembly.contigs.ibgcs``). ``l1_class_count`` counts distinct first
    segments of ``IntegratedBgc.gene_cluster_family`` per assembly.
    """
    logger.info("Computing assembly aggregates ...")

    total_l1_classes = (
        IntegratedBgc.objects.exclude(gene_cluster_family="")
        .annotate(class_l1=RawSQL("SPLIT_PART(gene_cluster_family, '.', 1)", []))
        .values("class_l1")
        .distinct()
        .count()
    )
    total_l1_classes = max(total_l1_classes, 1)

    # iBGC count + l1 distinct count + mean novelty per assembly, via
    # contigs → ibgcs traversal.
    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT a.id,
                   COUNT(DISTINCT i.id) AS ibgc_count,
                   COUNT(DISTINCT SPLIT_PART(i.gene_cluster_family, '.', 1))
                     FILTER (WHERE i.gene_cluster_family <> '') AS l1_count,
                   AVG(i.novelty_score) AS avg_novelty
            FROM discovery_assembly a
            LEFT JOIN discovery_contig c ON c.assembly_id = a.id
            LEFT JOIN discovery_ibgc i ON i.contig_id = c.id
            GROUP BY a.id
            """
        )
        agg_by_id = {row[0]: (row[1], row[2], row[3]) for row in cur.fetchall()}

    batch = []
    for asm in DashboardAssembly.objects.iterator():
        bgc_count, l1_count, avg_novelty = agg_by_id.get(asm.id, (0, 0, None))
        asm.bgc_count = int(bgc_count or 0)
        asm.l1_class_count = int(l1_count or 0)
        asm.bgc_novelty_score = float(avg_novelty or 0.0)
        if asm.assembly_size_mb and asm.assembly_size_mb > 0:
            asm.bgc_density = asm.bgc_count / asm.assembly_size_mb
        else:
            asm.bgc_density = 0.0
        asm.bgc_diversity_score = asm.l1_class_count / total_l1_classes
        batch.append(asm)
        if len(batch) >= BATCH_SIZE:
            DashboardAssembly.objects.bulk_update(
                batch,
                ["bgc_count", "l1_class_count", "bgc_novelty_score", "bgc_density", "bgc_diversity_score"],
                batch_size=BATCH_SIZE,
            )
            batch.clear()

    if batch:
        DashboardAssembly.objects.bulk_update(
            batch,
            ["bgc_count", "l1_class_count", "bgc_novelty_score", "bgc_density", "bgc_diversity_score"],
            batch_size=BATCH_SIZE,
        )

    logger.info("Assembly aggregates computed")


def _compute_percentile_ranks() -> None:
    """Compute percentile ranks for assembly scores using SQL window functions."""
    logger.info("Computing percentile ranks ...")

    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE discovery_assembly AS a
            SET
                pctl_novelty  = sub.pctl_novelty,
                pctl_diversity = sub.pctl_diversity,
                pctl_density  = sub.pctl_density
            FROM (
                SELECT
                    id,
                    ROUND((100.0 * PERCENT_RANK() OVER (ORDER BY bgc_novelty_score))::numeric, 2) AS pctl_novelty,
                    ROUND((100.0 * PERCENT_RANK() OVER (ORDER BY bgc_diversity_score))::numeric, 2) AS pctl_diversity,
                    ROUND((100.0 * PERCENT_RANK() OVER (ORDER BY bgc_density))::numeric, 2) AS pctl_density
                FROM discovery_assembly
            ) AS sub
            WHERE a.id = sub.id
            """
        )

    logger.info("Percentile ranks computed")


# ── GCF rebuild ──────────────────────────────────────────────────────────────


def _rebuild_gcf_table() -> None:
    """Refresh DashboardGCF aggregates from the latest ClusteringRun.

    DashboardGCF rows are owned by ``run_bgc_clustering_task`` (one row per
    node in the hierarchy). This function only refreshes the per-node
    aggregates (``member_count``, ``validated_count``, ``mean_novelty``)
    against the current ``IntegratedBgc.gene_cluster_family`` values — it
    never creates or deletes rows. If no ClusteringRun has been performed
    yet, this is a no-op.
    """
    from discovery.services.clustering.reclassify import _refresh_gcf_aggregates

    from discovery.models import ClusteringRun

    latest = ClusteringRun.objects.order_by("-created_at").values_list("id", flat=True).first()
    if latest is None:
        logger.info("No ClusteringRun yet — skipping GCF aggregate refresh")
        return
    _refresh_gcf_aggregates(latest)
    logger.info(
        "GCF aggregates refreshed for ClusteringRun pk=%s (%d nodes)",
        latest, DashboardGCF.objects.filter(clustering_run_id=latest).count(),
    )


# ── Catalog rebuild ──────────────────────────────────────────────────────────


def _rebuild_catalog_tables() -> None:
    """Recompute iBGC class and domain catalog counts."""
    logger.info("Rebuilding catalog tables ...")

    # iBGC classes from first segment of gene_cluster_family.
    class_counts = (
        IntegratedBgc.objects.exclude(gene_cluster_family="")
        .annotate(class_l1=RawSQL("SPLIT_PART(gene_cluster_family, '.', 1)", []))
        .values("class_l1")
        .annotate(cnt=Count("id"))
    )
    DashboardBgcClass.objects.all().delete()
    DashboardBgcClass.objects.bulk_create(
        [DashboardBgcClass(name=r["class_l1"], bgc_count=r["cnt"]) for r in class_counts],
        batch_size=BATCH_SIZE,
    )

    # Domain counts — distinct iBGC reach via the denormalised contig FK on
    # ContigDomain. Same acc can carry different names across annotations;
    # pick one deterministically via Min.
    domain_counts = (
        ContigDomain.objects.values("domain_acc", "ref_db")
        .annotate(
            cnt=Count("contig__ibgcs", distinct=True),
            domain_name=Min("domain_name"),
        )
    )
    DashboardDomain.objects.all().delete()
    DashboardDomain.objects.bulk_create(
        [
            DashboardDomain(
                acc=r["domain_acc"],
                name=r["domain_name"] or "",
                ref_db=r["ref_db"] or "",
                bgc_count=r["cnt"],
            )
            for r in domain_counts
        ],
        batch_size=BATCH_SIZE,
    )

    logger.info("Catalog tables rebuilt")


# ── UMAP recomputation ───────────────────────────────────────────────────────


def _recompute_umap() -> None:
    """No-op stub kept for API compatibility.

    UMAP coordinates are written directly by ``run_bgc_clustering_task``
    on the iBGC graph (see ``services/clustering/layout.py``). There is no
    standalone UMAP model to retrain — the layout step happens inline as
    part of community detection.
    """
    logger.debug(
        "_recompute_umap: no-op; umap_x/y are written by run_bgc_clustering_task"
    )


def _compute_chemont_ic() -> None:
    """Precompute Information Content values for all ChemOnt terms.

    Stores the result in ``PrecomputedStats(key="chemont_ic")`` so the
    chemical similarity search task can use it without recomputing.

    Counts are taken over distinct iBGCs (the unit on which the dashboard
    aggregates) — a CDS is attributed to the iBGC whose ``bgc_range``
    overlaps its ``cds_range`` on the same contig. IC therefore reflects
    how broadly each ChemOnt term is observed across the iBGC corpus.
    """
    from common_core.chemont.ontology import get_ontology
    from common_core.chemont.similarity import compute_ic_values

    with connection.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(DISTINCT i.id)
            FROM discovery_cds_chemont ch
            JOIN discovery_cds c ON c.id = ch.cds_id
            JOIN discovery_ibgc i
              ON i.contig_id = c.contig_id
             AND i.bgc_range && c.cds_range
            """
        )
        total_ibgcs = int(cur.fetchone()[0] or 0)

        if total_ibgcs == 0:
            logger.info("No iBGC ChemOnt annotations — skipping IC computation")
            return

        cur.execute(
            """
            SELECT ch.chemont_id, COUNT(DISTINCT i.id) AS cnt
            FROM discovery_cds_chemont ch
            JOIN discovery_cds c ON c.id = ch.cds_id
            JOIN discovery_ibgc i
              ON i.contig_id = c.contig_id
             AND i.bgc_range && c.cds_range
            GROUP BY ch.chemont_id
            """
        )
        term_counts = {row[0]: int(row[1]) for row in cur.fetchall()}

    if not term_counts:
        logger.info("No ChemOnt annotations — skipping IC computation")
        return

    try:
        ont = get_ontology()
    except FileNotFoundError:
        logger.warning(
            "ChemOnt OBO file not found — skipping IC computation. "
            "Set CHEMONT_OBO_PATH to enable."
        )
        return

    ic_values = compute_ic_values(term_counts, total_ibgcs, ont)

    PrecomputedStats.objects.update_or_create(
        key="chemont_ic",
        defaults={"data": ic_values},
    )
    logger.info(
        "ChemOnt IC computed for %d terms (%d iBGCs)", len(ic_values), total_ibgcs
    )
