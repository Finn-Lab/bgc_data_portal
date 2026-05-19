"""Score recomputation service for the discovery platform.

Computes all derived scores and materialized tables from raw loaded data:
  - Assembly aggregates (bgc_count, l1_class_count, novelty, diversity, density)
  - Assembly percentile ranks
  - GCF table rebuild from gene_cluster_family ltree
  - Catalog table rebuild (BgcClass, Domain)
  - UMAP coordinate recomputation (no-op stub; layout is written inline by
    the clustering pipeline)

BGC-level novelty (``DashboardBgc.novelty_score``) and ``domain_novelty``
were previously computed here from ESM-300M embeddings; both are retired in
the v2 redesign in favour of NRB-level scoring written by
``discovery.services.clustering.nrb_scoring`` over the composite-Dice
matrix. The DashboardBgc columns remain in the schema but are no longer
recomputed — drill-down views read scores from the parent NonRedundantBGC.
"""

from __future__ import annotations

import logging

from django.db import connection
from django.db.models import Avg, Count, Min
from django.db.models.expressions import RawSQL

from discovery.models import (
    BgcDomain,
    DashboardAssembly,
    DashboardBgc,
    DashboardBgcClass,
    DashboardCdsChemOnt,
    DashboardDomain,
    DashboardGCF,
    DashboardNaturalProduct,
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
    """Recompute denormalized scores on DashboardAssembly."""
    logger.info("Computing assembly aggregates ...")

    # Count total known L1 classes for diversity score
    total_l1_classes = (
        DashboardBgc.objects.exclude(classification_path="")
        .annotate(class_l1=RawSQL("SPLIT_PART(classification_path, '.', 1)", []))
        .values("class_l1")
        .distinct()
        .count()
    )
    total_l1_classes = max(total_l1_classes, 1)  # avoid division by zero

    assemblies = DashboardAssembly.objects.annotate(
        _bgc_count=Count("bgcs"),
        _l1_class_count=Count(
            RawSQL("SPLIT_PART(discovery_bgc.classification_path, '.', 1)", []),
            distinct=True,
        ),
        _avg_novelty=Avg("bgcs__novelty_score"),
    )

    batch = []
    for asm in assemblies.iterator():
        asm.bgc_count = asm._bgc_count
        asm.l1_class_count = asm._l1_class_count
        asm.bgc_novelty_score = asm._avg_novelty or 0.0
        # Density = bgc_count / assembly_size_mb (0.0 if size unknown)
        if asm.assembly_size_mb and asm.assembly_size_mb > 0:
            asm.bgc_density = asm.bgc_count / asm.assembly_size_mb
        else:
            asm.bgc_density = 0.0
        # Diversity = l1_class_count / total_known_classes
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
        cursor.execute("""
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
        """)

    logger.info("Percentile ranks computed")


# ── GCF rebuild ──────────────────────────────────────────────────────────────


def _rebuild_gcf_table() -> None:
    """Refresh DashboardGCF aggregates from the latest ClusteringRun.

    DashboardGCF rows are owned by ``run_bgc_clustering_task`` (one row per
    node in the hierarchy). This function only refreshes the per-node
    aggregates (``member_count``, ``validated_count``, ``mean_novelty``)
    against the *current* ``DashboardBgc.gene_cluster_family`` values — it
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
    """Recompute BGC class and domain catalog counts."""
    logger.info("Rebuilding catalog tables ...")

    # BGC classes from first segment of classification_path
    class_counts = (
        DashboardBgc.objects.exclude(classification_path="")
        .annotate(class_l1=RawSQL("SPLIT_PART(classification_path, '.', 1)", []))
        .values("class_l1")
        .annotate(cnt=Count("id"))
    )
    DashboardBgcClass.objects.all().delete()
    DashboardBgcClass.objects.bulk_create(
        [DashboardBgcClass(name=r["class_l1"], bgc_count=r["cnt"]) for r in class_counts],
        batch_size=BATCH_SIZE,
    )

    # Domain counts — group by acc only; the same acc can carry different name
    # strings across annotations, so we pick one name with Min to avoid
    # violating the unique constraint on discovery_domain.acc.
    domain_counts = (
        BgcDomain.objects.values("domain_acc", "ref_db")
        .annotate(cnt=Count("bgc_id", distinct=True), domain_name=Min("domain_name"))
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

    UMAP coordinates are now written directly by ``run_bgc_clustering_task``
    on the BGC graph (see ``services/clustering/layout.py``). There is no
    standalone UMAP model to retrain — the layout step happens inline as
    part of community detection.
    """
    logger.debug(
        "_recompute_umap: no-op; umap_x/y are written by run_bgc_clustering_task"
    )


def _compute_chemont_ic() -> None:
    """Precompute Information Content values for all ChemOnt terms.

    Stores the result in PrecomputedStats(key="chemont_ic") so the
    chemical similarity search task can use it without recomputing.

    Counts are taken over distinct BGCs (the unit on which CHAMOIS predicts
    a class), so IC reflects how broadly each ChemOnt term is observed across
    the BGC corpus.
    """
    from common_core.chemont.ontology import get_ontology
    from common_core.chemont.similarity import compute_ic_values

    total_bgcs = (
        DashboardCdsChemOnt.objects.values("cds__bgc").distinct().count()
    )
    if total_bgcs == 0:
        logger.info("No CDS ChemOnt annotations — skipping IC computation")
        return

    rows = (
        DashboardCdsChemOnt.objects
        .values("chemont_id")
        .annotate(cnt=Count("cds__bgc", distinct=True))
    )
    term_counts = {r["chemont_id"]: r["cnt"] for r in rows}

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

    ic_values = compute_ic_values(term_counts, total_bgcs, ont)

    PrecomputedStats.objects.update_or_create(
        key="chemont_ic",
        defaults={"data": ic_values},
    )
    logger.info(
        "ChemOnt IC computed for %d terms (%d BGCs)", len(ic_values), total_bgcs
    )
