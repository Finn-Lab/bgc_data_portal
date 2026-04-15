"""Score recomputation service for the discovery platform.

Computes all derived scores and materialized tables from raw loaded data:
  - BGC novelty_score (nearest validated BGC embedding distance)
  - BGC domain_novelty (fraction of unique domains)
  - Assembly aggregates (bgc_count, l1_class_count, novelty, diversity, density)
  - Assembly percentile ranks
  - GCF table rebuild from gene_cluster_family ltree
  - Catalog table rebuild (BgcClass, Domain)
  - UMAP coordinate recomputation (if model available)
"""

from __future__ import annotations

import logging
from collections import defaultdict

from django.db import connection
from django.db.models import Avg, Count, Min
from django.db.models.expressions import RawSQL

from discovery.models import (
    BgcDomain,
    BgcEmbedding,
    DashboardAssembly,
    DashboardBgc,
    DashboardBgcClass,
    DashboardDomain,
    DashboardGCF,
    DashboardNaturalProduct,
    NaturalProductChemOntClass,
    PrecomputedStats,
)

logger = logging.getLogger(__name__)

BATCH_SIZE = 10_000


def recompute_all_scores() -> None:
    """Master function — orchestrates all score recomputation."""
    logger.info("Starting full score recomputation ...")
    _compute_bgc_novelty_scores()
    _compute_bgc_domain_novelty()
    _compute_assembly_aggregates()
    _compute_percentile_ranks()
    _rebuild_gcf_table()
    _rebuild_catalog_tables()
    _compute_chemont_ic()
    _recompute_umap()
    logger.info("Score recomputation complete.")


# ── BGC-level scores ─────────────────────────────────────────────────────────


def _compute_bgc_novelty_scores() -> None:
    """Compute novelty_score for each BGC as cosine distance to nearest validated BGC.

    Uses the HNSW index on BgcEmbedding for efficient approximate nearest-neighbor.
    """
    logger.info("Computing BGC novelty scores ...")

    validated_bgc_ids = set(
        DashboardBgc.objects.filter(is_validated=True).values_list("id", flat=True)
    )

    if not validated_bgc_ids:
        logger.warning("No validated BGCs found — setting all novelty_score to 1.0")
        DashboardBgc.objects.all().update(
            novelty_score=1.0,
            nearest_validated_accession="",
            nearest_validated_distance=None,
        )
        return

    # Build accession lookup for validated BGCs
    validated_accessions = dict(
        DashboardBgc.objects.filter(is_validated=True).values_list("id", "bgc_accession")
    )

    # Process all BGCs with embeddings in batches using raw SQL for efficiency.
    # The HNSW index on BgcEmbedding supports <=> (cosine distance) operator.
    batch_updates = []
    processed = 0

    # Use a cursor-based approach: for each BGC embedding, find nearest validated
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT e.bgc_id, e.vector
            FROM discovery_bgc_embedding e
            ORDER BY e.bgc_id
        """)

        for bgc_id, vector in cursor.fetchall():
            # Find nearest validated BGC embedding via cosine distance
            nearest = (
                BgcEmbedding.objects.filter(bgc_id__in=validated_bgc_ids)
                .exclude(bgc_id=bgc_id)
                .extra(
                    select={"distance": "vector <=> %s::halfvec"},
                    select_params=[str(vector)],
                )
                .order_by("distance")
                .values_list("bgc_id", "distance")
                .first()
            )

            if nearest:
                ref_id, distance = nearest
                batch_updates.append({
                    "id": bgc_id,
                    "novelty_score": min(float(distance), 1.0),
                    "nearest_validated_accession": validated_accessions.get(ref_id, ""),
                    "nearest_validated_distance": float(distance),
                })
            else:
                batch_updates.append({
                    "id": bgc_id,
                    "novelty_score": 1.0,
                    "nearest_validated_accession": "",
                    "nearest_validated_distance": None,
                })

            if len(batch_updates) >= BATCH_SIZE:
                _bulk_update_bgc_scores(batch_updates)
                processed += len(batch_updates)
                logger.info("  novelty: %d BGCs processed", processed)
                batch_updates.clear()

    if batch_updates:
        _bulk_update_bgc_scores(batch_updates)
        processed += len(batch_updates)

    logger.info("Novelty scores computed for %d BGCs", processed)


def _bulk_update_bgc_scores(updates: list[dict]) -> None:
    """Batch-update novelty fields on DashboardBgc."""
    if not updates:
        return
    objs = DashboardBgc.objects.in_bulk([u["id"] for u in updates])
    to_update = []
    for u in updates:
        bgc = objs.get(u["id"])
        if bgc is None:
            continue
        bgc.novelty_score = u["novelty_score"]
        bgc.nearest_validated_accession = u["nearest_validated_accession"]
        bgc.nearest_validated_distance = u["nearest_validated_distance"]
        to_update.append(bgc)
    DashboardBgc.objects.bulk_update(
        to_update,
        ["novelty_score", "nearest_validated_accession", "nearest_validated_distance"],
        batch_size=BATCH_SIZE,
    )


def _compute_bgc_domain_novelty() -> None:
    """Compute domain_novelty for each BGC.

    domain_novelty = fraction of this BGC's domains not found in any other BGC.
    """
    logger.info("Computing BGC domain novelty ...")

    # Build domain_acc -> set of bgc_ids
    domain_to_bgcs: dict[str, set[int]] = defaultdict(set)
    for domain_acc, bgc_id in BgcDomain.objects.values_list("domain_acc", "bgc_id"):
        domain_to_bgcs[domain_acc].add(bgc_id)

    # Build bgc_id -> set of domain_accs
    bgc_to_domains: dict[int, set[str]] = defaultdict(set)
    for domain_acc, bgc_id in BgcDomain.objects.values_list("domain_acc", "bgc_id"):
        bgc_to_domains[bgc_id].add(domain_acc)

    batch = []
    processed = 0

    for bgc_id, domains in bgc_to_domains.items():
        if not domains:
            continue
        unique_count = sum(
            1 for d in domains if len(domain_to_bgcs[d]) == 1
        )
        domain_novelty = unique_count / len(domains)
        batch.append((bgc_id, domain_novelty))

        if len(batch) >= BATCH_SIZE:
            _bulk_update_domain_novelty(batch)
            processed += len(batch)
            batch.clear()

    if batch:
        _bulk_update_domain_novelty(batch)
        processed += len(batch)

    logger.info("Domain novelty computed for %d BGCs", processed)


def _bulk_update_domain_novelty(updates: list[tuple[int, float]]) -> None:
    """Batch-update domain_novelty on DashboardBgc."""
    ids = [u[0] for u in updates]
    objs = DashboardBgc.objects.in_bulk(ids)
    to_update = []
    for bgc_id, novelty in updates:
        bgc = objs.get(bgc_id)
        if bgc is None:
            continue
        bgc.domain_novelty = novelty
        to_update.append(bgc)
    DashboardBgc.objects.bulk_update(to_update, ["domain_novelty"], batch_size=BATCH_SIZE)


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
    """Rebuild DashboardGCF from DashboardBgc.gene_cluster_family ltree grouping."""
    logger.info("Rebuilding GCF table ...")

    DashboardGCF.objects.all().delete()

    # Group BGCs by gene_cluster_family (exclude empty)
    family_groups = (
        DashboardBgc.objects.exclude(gene_cluster_family="")
        .values("gene_cluster_family")
        .annotate(
            member_count=Count("id"),
            mean_novelty=Avg("novelty_score"),
            validated_count=Count("id", filter=DashboardBgc.objects.filter(is_validated=True).query.where),
        )
    )

    # For validated_count and representative, we need separate queries
    family_stats = (
        DashboardBgc.objects.exclude(gene_cluster_family="")
        .values("gene_cluster_family")
        .annotate(
            member_count=Count("id"),
            mean_novelty=Avg("novelty_score"),
        )
    )

    gcf_batch = []
    for group in family_stats:
        family_id = group["gene_cluster_family"]

        # Find representative (lowest novelty_score)
        representative = (
            DashboardBgc.objects.filter(gene_cluster_family=family_id)
            .order_by("novelty_score")
            .values_list("id", flat=True)
            .first()
        )

        # Count validated members
        val_count = DashboardBgc.objects.filter(
            gene_cluster_family=family_id, is_validated=True
        ).count()

        # Get first validated accession if any
        val_acc = ""
        if val_count > 0:
            val_acc = (
                DashboardBgc.objects.filter(
                    gene_cluster_family=family_id, is_validated=True
                )
                .values_list("bgc_accession", flat=True)
                .first()
            ) or ""

        gcf_batch.append(
            DashboardGCF(
                family_id=family_id,
                representative_bgc_id=representative,
                member_count=group["member_count"],
                mean_novelty=group["mean_novelty"] or 0.0,
                validated_count=val_count,
                validated_accession=val_acc,
            )
        )

        if len(gcf_batch) >= BATCH_SIZE:
            DashboardGCF.objects.bulk_create(gcf_batch, batch_size=BATCH_SIZE)
            gcf_batch.clear()

    if gcf_batch:
        DashboardGCF.objects.bulk_create(gcf_batch, batch_size=BATCH_SIZE)

    logger.info("GCF table rebuilt: %d families", DashboardGCF.objects.count())


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
    """Recompute UMAP coordinates from embeddings using the latest saved model.

    Looks for a UMAPTransform model blob in the mgnify_bgcs app. If none is found,
    logs a warning and skips.
    """
    try:
        from mgnify_bgcs.models import UMAPTransform
    except ImportError:
        logger.warning("mgnify_bgcs app not available — skipping UMAP recomputation")
        return

    latest_model = UMAPTransform.objects.order_by("-created_at").first()
    if latest_model is None:
        logger.warning("No UMAP model found — skipping UMAP recomputation. "
                        "Run 'train_umap_model' to create one.")
        return

    import pickle

    import numpy as np

    try:
        umap_model = pickle.loads(latest_model.model_blob)
    except Exception:
        logger.exception("Failed to load UMAP model — skipping recomputation")
        return

    logger.info("Recomputing UMAP coordinates using model from %s ...", latest_model.created_at)

    # Collect all embeddings
    bgc_ids = []
    vectors = []
    for bgc_id, vector in BgcEmbedding.objects.values_list("bgc_id", "vector"):
        bgc_ids.append(bgc_id)
        vectors.append(vector)

    if not vectors:
        logger.info("No embeddings found — skipping UMAP")
        return

    embeddings = np.array(vectors, dtype=np.float32)
    coords = umap_model.transform(embeddings)

    batch = []
    objs = {bgc.id: bgc for bgc in DashboardBgc.objects.in_bulk(bgc_ids).values()}
    for i, bgc_id in enumerate(bgc_ids):
        bgc = objs.get(bgc_id)
        if bgc is None:
            continue
        bgc.umap_x = float(coords[i, 0])
        bgc.umap_y = float(coords[i, 1])
        batch.append(bgc)

        if len(batch) >= BATCH_SIZE:
            DashboardBgc.objects.bulk_update(batch, ["umap_x", "umap_y"], batch_size=BATCH_SIZE)
            batch.clear()

    if batch:
        DashboardBgc.objects.bulk_update(batch, ["umap_x", "umap_y"], batch_size=BATCH_SIZE)

    logger.info("UMAP coordinates recomputed for %d BGCs", len(bgc_ids))


def _compute_chemont_ic() -> None:
    """Precompute Information Content values for all ChemOnt terms.

    Stores the result in PrecomputedStats(key="chemont_ic") so the
    chemical similarity search task can use it without recomputing.
    """
    from common_core.chemont.ontology import get_ontology
    from common_core.chemont.similarity import compute_ic_values

    total_nps = DashboardNaturalProduct.objects.count()
    if total_nps == 0:
        logger.info("No natural products — skipping ChemOnt IC computation")
        return

    # Direct annotation counts: how many distinct NPs have each ChemOnt term.
    rows = (
        NaturalProductChemOntClass.objects
        .values("chemont_id")
        .annotate(cnt=Count("natural_product", distinct=True))
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

    ic_values = compute_ic_values(term_counts, total_nps, ont)

    PrecomputedStats.objects.update_or_create(
        key="chemont_ic",
        defaults={"data": ic_values},
    )
    logger.info(
        "ChemOnt IC computed for %d terms (%d NPs)", len(ic_values), total_nps
    )
