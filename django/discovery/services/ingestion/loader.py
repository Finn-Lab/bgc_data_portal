"""Discovery data loader — orchestrates bulk ingestion from TSV files.

The pipeline loads data in dependency order, using PostgreSQL ``COPY FROM``
where possible and ``bulk_create`` for tables requiring per-row logic (BGCs
need region assignment).

Expected directory layout::

    data_dir/
      detectors.tsv
      assemblies.tsv
      contigs.tsv
      bgcs.tsv
      cds.tsv              (optional)
      domains.tsv           (optional)
      embeddings_bgc.tsv    (optional)
      natural_products.tsv  (optional)
      mibig_references.tsv  (optional)
      gcf.tsv               (optional)
"""

from __future__ import annotations

import base64
import csv
import logging
import struct
from pathlib import Path

from django.db import connection, transaction
from django.db.models import Avg, Count, F, Q

from discovery.models import (
    AssemblySource,
    BgcDomain,
    BgcEmbedding,
    DashboardAssembly,
    DashboardBgc,
    DashboardBgcClass,
    DashboardCds,
    DashboardContig,
    DashboardDetector,
    DashboardDomain,
    DashboardGCF,
    DashboardMibigReference,
    DashboardNaturalProduct,
    DashboardRegion,
    PrecomputedStats,
    RegionAccessionAlias,
)

from .region_assignment import RegionAssigner
from .tsv_copy import copy_tsv_to_table, truncate_tables

logger = logging.getLogger(__name__)

BATCH_SIZE = 10_000

# Tables in truncation order (respects FK CASCADE but explicit is safer)
ALL_DISCOVERY_TABLES = [
    "discovery_region_accession_alias",
    "discovery_bgc_embedding",
    "discovery_bgc_domain",
    "discovery_cds_sequence",
    "discovery_cds",
    "discovery_natural_product",
    "discovery_mibig_reference",
    "discovery_gcf",
    "discovery_precomputed_stats",
    "discovery_bgc",
    "discovery_region",
    "discovery_contig_sequence",
    "discovery_contig",
    "discovery_assembly",
    "discovery_detector",
    "discovery_assembly_source",
    "discovery_bgc_class",
    "discovery_domain",
]


def _version_sort_key(version_str: str) -> int:
    """Convert a semver-ish string to a sortable integer.

    Encodes up to 4 numeric parts (major.minor.patch.build) into a single
    32-bit-ish integer: ``major * 10^9 + minor * 10^6 + patch * 10^3 + build``.
    Non-numeric parts are ignored.
    """
    parts = []
    for segment in version_str.split("."):
        digits = "".join(c for c in segment if c.isdigit())
        parts.append(int(digits) if digits else 0)
    parts = (parts + [0, 0, 0, 0])[:4]
    return parts[0] * 10**9 + parts[1] * 10**6 + parts[2] * 10**3 + parts[3]


def _generate_tool_name_code(tool: str, existing_codes: set[str]) -> str:
    """Generate a 3-letter uppercase code from a tool name, avoiding collisions."""
    if not tool or not tool.strip():
        base = "UNK"
    else:
        base = tool.strip().upper()[:3]
    if len(base) < 3:
        base = base.ljust(3, "X")

    if base not in existing_codes:
        existing_codes.add(base)
        return base

    for i in range(2, 100):
        candidate = f"{base[:2]}{i}"
        if candidate not in existing_codes:
            existing_codes.add(candidate)
            return candidate

    raise ValueError(f"Cannot generate unique tool_name_code for {tool!r}")


# ── Pipeline steps ─────────────────────────────────────────────��──────────────


def load_detectors(data_dir: Path) -> dict[str, tuple[int, str]]:
    """Load detectors.tsv → DashboardDetector.

    Returns ``{name: (detector_id, tool_name_code)}``.
    """
    path = data_dir / "detectors.tsv"
    if not path.exists():
        logger.warning("detectors.tsv not found, skipping")
        return {}

    existing_codes: set[str] = set()
    rows_to_create: list[DashboardDetector] = []

    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            tool = row["tool"]
            version = row["version"]
            code = _generate_tool_name_code(tool, existing_codes)
            rows_to_create.append(
                DashboardDetector(
                    name=row["name"],
                    tool=tool,
                    version=version,
                    tool_name_code=code,
                    version_sort_key=_version_sort_key(version),
                )
            )

    DashboardDetector.objects.bulk_create(rows_to_create, batch_size=BATCH_SIZE)
    lookup = {
        d.name: (d.id, d.tool_name_code)
        for d in DashboardDetector.objects.all()
    }
    logger.info("Loaded %d detectors", len(lookup))
    return lookup


def load_assemblies(data_dir: Path) -> dict[str, int]:
    """Load assemblies.tsv → DashboardAssembly.

    Returns ``{assembly_accession: assembly_id}``.
    """
    path = data_dir / "assemblies.tsv"
    if not path.exists():
        logger.warning("assemblies.tsv not found, skipping")
        return {}

    source_cache: dict[str, AssemblySource] = {}

    def _get_source(name: str) -> AssemblySource | None:
        if not name:
            return None
        if name not in source_cache:
            obj, _ = AssemblySource.objects.get_or_create(name=name)
            source_cache[name] = obj
        return source_cache[name]

    rows: list[DashboardAssembly] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            source = _get_source(row.get("source", ""))
            rows.append(
                DashboardAssembly(
                    assembly_accession=row["assembly_accession"],
                    organism_name=row.get("organism_name", ""),
                    source=source,
                    assembly_type=int(row.get("assembly_type", 2)),
                    dominant_taxonomy_path=row.get("dominant_taxonomy_path", ""),
                    dominant_taxonomy_label=row.get("dominant_taxonomy_label", ""),
                    biome_path=row.get("biome_path", ""),
                    is_type_strain=row.get("is_type_strain", "").lower() in ("true", "1"),
                    type_strain_catalog_url=row.get("type_strain_catalog_url", ""),
                    assembly_size_mb=float(row["assembly_size_mb"]) if row.get("assembly_size_mb") else None,
                    assembly_quality=float(row["assembly_quality"]) if row.get("assembly_quality") else None,
                    isolation_source=row.get("isolation_source", ""),
                    url=row.get("url", ""),
                    source_assembly_id=int(row["source_assembly_id"]),
                )
            )

    DashboardAssembly.objects.bulk_create(rows, batch_size=BATCH_SIZE)
    lookup = dict(
        DashboardAssembly.objects.values_list("assembly_accession", "id")
    )
    logger.info("Loaded %d assemblies", len(lookup))
    return lookup


def load_contigs(
    data_dir: Path,
    assembly_lookup: dict[str, int],
) -> dict[str, int]:
    """Load contigs.tsv → DashboardContig.

    Returns ``{contig_accession: contig_id}``.
    """
    path = data_dir / "contigs.tsv"
    if not path.exists():
        logger.warning("contigs.tsv not found, skipping")
        return {}

    rows: list[DashboardContig] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            assembly_acc = row["assembly_accession"]
            assembly_id = assembly_lookup.get(assembly_acc)
            if assembly_id is None:
                logger.warning("Unknown assembly %s for contig %s, skipping", assembly_acc, row["accession"])
                continue
            rows.append(
                DashboardContig(
                    assembly_id=assembly_id,
                    accession=row["accession"],
                    length=int(row.get("length", 0)),
                    taxonomy_path=row.get("taxonomy_path", ""),
                    source_contig_id=int(row["source_contig_id"]),
                )
            )

    DashboardContig.objects.bulk_create(rows, batch_size=BATCH_SIZE)
    lookup = dict(DashboardContig.objects.values_list("accession", "id"))
    logger.info("Loaded %d contigs", len(lookup))
    return lookup


def load_bgcs(
    data_dir: Path,
    contig_lookup: dict[str, int],
    detector_lookup: dict[str, tuple[int, str]],
    assembly_lookup: dict[str, int],
) -> dict[int, int]:
    """Load bgcs.tsv → DashboardBgc + DashboardRegion (via region assignment).

    Returns ``{source_bgc_id: dashboard_bgc_id}``.
    """
    path = data_dir / "bgcs.tsv"
    if not path.exists():
        logger.warning("bgcs.tsv not found, skipping")
        return {}

    # Build contig→assembly lookup for setting assembly FK
    contig_to_assembly: dict[int, int] = dict(
        DashboardContig.objects.values_list("id", "assembly_id")
    )

    assigner = RegionAssigner()
    batch: list[DashboardBgc] = []
    total = 0

    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            contig_acc = row["contig_accession"]
            contig_id = contig_lookup.get(contig_acc)
            if contig_id is None:
                logger.warning("Unknown contig %s, skipping BGC", contig_acc)
                continue

            detector_name = row["detector_name"]
            det_info = detector_lookup.get(detector_name)
            if det_info is None:
                logger.warning("Unknown detector %s, skipping BGC", detector_name)
                continue
            detector_id, tool_code = det_info

            start = int(row["start_position"])
            end = int(row["end_position"])

            region_id, bgc_number, accession = assigner.assign(
                contig_id=contig_id,
                start=start,
                end=end,
                detector_id=detector_id,
                tool_code=tool_code,
            )

            assembly_id = contig_to_assembly.get(contig_id)

            batch.append(
                DashboardBgc(
                    assembly_id=assembly_id,
                    contig_id=contig_id,
                    bgc_accession=accession,
                    contig_accession=contig_acc,
                    start_position=start,
                    end_position=end,
                    classification_path=row.get("classification_path", ""),
                    classification_l1=row.get("classification_l1", ""),
                    classification_l2=row.get("classification_l2", ""),
                    classification_l3=row.get("classification_l3", ""),
                    novelty_score=float(row.get("novelty_score", 0)),
                    domain_novelty=float(row.get("domain_novelty", 0)),
                    size_kb=float(row.get("size_kb", 0)),
                    nearest_mibig_accession=row.get("nearest_mibig_accession", ""),
                    nearest_mibig_distance=float(row["nearest_mibig_distance"]) if row.get("nearest_mibig_distance") else None,
                    is_partial=row.get("is_partial", "").lower() in ("true", "1"),
                    is_validated=row.get("is_validated", "").lower() in ("true", "1"),
                    is_mibig=row.get("is_mibig", "").lower() in ("true", "1"),
                    umap_x=float(row.get("umap_x", 0)),
                    umap_y=float(row.get("umap_y", 0)),
                    detector_id=detector_id,
                    detector_names=detector_name,
                    region_id=region_id,
                    bgc_number=bgc_number,
                    source_bgc_id=int(row["source_bgc_id"]),
                    source_contig_id=contig_id,
                )
            )

            if len(batch) >= BATCH_SIZE:
                DashboardBgc.objects.bulk_create(batch, ignore_conflicts=True)
                total += len(batch)
                batch.clear()

    if batch:
        DashboardBgc.objects.bulk_create(batch, ignore_conflicts=True)
        total += len(batch)

    lookup = dict(DashboardBgc.objects.values_list("source_bgc_id", "id"))
    logger.info("Loaded %d BGCs across %d regions", total, DashboardRegion.objects.count())
    return lookup


def load_cds(data_dir: Path, bgc_lookup: dict[int, int]) -> dict[tuple[int, str], int]:
    """Load cds.tsv → DashboardCds.

    Returns ``{(source_bgc_id, protein_id_str): cds_id}``.
    """
    path = data_dir / "cds.tsv"
    if not path.exists():
        logger.info("cds.tsv not found, skipping")
        return {}

    batch: list[DashboardCds] = []
    total = 0

    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            src_bgc = int(row["source_bgc_id"])
            bgc_id = bgc_lookup.get(src_bgc)
            if bgc_id is None:
                continue

            batch.append(
                DashboardCds(
                    bgc_id=bgc_id,
                    protein_id_str=row["protein_id_str"],
                    start_position=int(row["start_position"]),
                    end_position=int(row["end_position"]),
                    strand=int(row["strand"]),
                    protein_length=int(row.get("protein_length", 0)),
                    gene_caller=row.get("gene_caller", ""),
                    cluster_representative=row.get("cluster_representative", ""),
                )
            )

            if len(batch) >= BATCH_SIZE:
                DashboardCds.objects.bulk_create(batch, ignore_conflicts=True)
                total += len(batch)
                batch.clear()

    if batch:
        DashboardCds.objects.bulk_create(batch, ignore_conflicts=True)
        total += len(batch)

    logger.info("Loaded %d CDS rows", total)

    # Build lookup for domain loading
    cds_lookup = {}
    for cds in DashboardCds.objects.select_related("bgc").only("id", "protein_id_str", "bgc__source_bgc_id"):
        cds_lookup[(cds.bgc.source_bgc_id, cds.protein_id_str)] = cds.id
    return cds_lookup


def load_domains(
    data_dir: Path,
    bgc_lookup: dict[int, int],
    cds_lookup: dict[tuple[int, str], int],
) -> int:
    """Load domains.tsv → BgcDomain. Returns row count."""
    path = data_dir / "domains.tsv"
    if not path.exists():
        logger.info("domains.tsv not found, skipping")
        return 0

    batch: list[BgcDomain] = []
    total = 0

    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            src_bgc = int(row["source_bgc_id"])
            bgc_id = bgc_lookup.get(src_bgc)
            if bgc_id is None:
                continue

            protein_id = row.get("protein_id_str", "")
            cds_id = cds_lookup.get((src_bgc, protein_id))

            batch.append(
                BgcDomain(
                    bgc_id=bgc_id,
                    cds_id=cds_id,
                    domain_acc=row["domain_acc"],
                    domain_name=row.get("domain_name", ""),
                    domain_description=row.get("domain_description", ""),
                    ref_db=row.get("ref_db", ""),
                    start_position=int(row.get("start_position", 0)),
                    end_position=int(row.get("end_position", 0)),
                    score=float(row["score"]) if row.get("score") else None,
                )
            )

            if len(batch) >= BATCH_SIZE:
                BgcDomain.objects.bulk_create(batch, ignore_conflicts=True)
                total += len(batch)
                batch.clear()

    if batch:
        BgcDomain.objects.bulk_create(batch, ignore_conflicts=True)
        total += len(batch)

    logger.info("Loaded %d domain rows", total)
    return total


def load_embeddings(data_dir: Path, bgc_lookup: dict[int, int]) -> int:
    """Load embeddings_bgc.tsv → BgcEmbedding. Returns row count."""
    path = data_dir / "embeddings_bgc.tsv"
    if not path.exists():
        logger.info("embeddings_bgc.tsv not found, skipping")
        return 0

    batch: list[BgcEmbedding] = []
    total = 0

    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            src_bgc = int(row["source_bgc_id"])
            bgc_id = bgc_lookup.get(src_bgc)
            if bgc_id is None:
                continue

            raw = base64.b64decode(row["vector_base64"])
            vector = list(struct.unpack(f"<{len(raw)//4}f", raw))

            batch.append(BgcEmbedding(bgc_id=bgc_id, vector=vector))

            if len(batch) >= BATCH_SIZE:
                BgcEmbedding.objects.bulk_create(batch, ignore_conflicts=True)
                total += len(batch)
                batch.clear()

    if batch:
        BgcEmbedding.objects.bulk_create(batch, ignore_conflicts=True)
        total += len(batch)

    logger.info("Loaded %d BGC embeddings", total)
    return total


def load_natural_products(data_dir: Path, bgc_lookup: dict[int, int]) -> int:
    """Load natural_products.tsv → DashboardNaturalProduct."""
    path = data_dir / "natural_products.tsv"
    if not path.exists():
        logger.info("natural_products.tsv not found, skipping")
        return 0

    batch: list[DashboardNaturalProduct] = []
    total = 0

    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            src_bgc = int(row["source_bgc_id"])
            bgc_id = bgc_lookup.get(src_bgc)
            if bgc_id is None:
                continue

            morgan_fp = None
            if row.get("morgan_fp_base64"):
                morgan_fp = base64.b64decode(row["morgan_fp_base64"])

            batch.append(
                DashboardNaturalProduct(
                    bgc_id=bgc_id,
                    name=row["name"],
                    smiles=row.get("smiles", ""),
                    np_class_path=row.get("np_class_path", ""),
                    chemical_class_l1=row.get("chemical_class_l1", ""),
                    chemical_class_l2=row.get("chemical_class_l2", ""),
                    chemical_class_l3=row.get("chemical_class_l3", ""),
                    structure_svg_base64=row.get("structure_svg_base64", ""),
                    producing_organism=row.get("producing_organism", ""),
                    morgan_fp=morgan_fp,
                )
            )

            if len(batch) >= BATCH_SIZE:
                DashboardNaturalProduct.objects.bulk_create(batch, ignore_conflicts=True)
                total += len(batch)
                batch.clear()

    if batch:
        DashboardNaturalProduct.objects.bulk_create(batch, ignore_conflicts=True)
        total += len(batch)

    logger.info("Loaded %d natural products", total)
    return total


def load_mibig_references(data_dir: Path, bgc_lookup: dict[int, int]) -> int:
    """Load mibig_references.tsv → DashboardMibigReference."""
    path = data_dir / "mibig_references.tsv"
    if not path.exists():
        logger.info("mibig_references.tsv not found, skipping")
        return 0

    batch: list[DashboardMibigReference] = []
    total = 0

    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            embedding = None
            if row.get("embedding_base64"):
                raw = base64.b64decode(row["embedding_base64"])
                embedding = list(struct.unpack(f"<{len(raw)//4}f", raw))

            src_bgc = int(row["source_bgc_id"]) if row.get("source_bgc_id") else None
            dashboard_bgc_id = bgc_lookup.get(src_bgc) if src_bgc else None

            batch.append(
                DashboardMibigReference(
                    accession=row["accession"],
                    compound_name=row.get("compound_name", ""),
                    bgc_class=row.get("bgc_class", ""),
                    umap_x=float(row.get("umap_x", 0)),
                    umap_y=float(row.get("umap_y", 0)),
                    embedding=embedding,
                    dashboard_bgc_id=dashboard_bgc_id,
                )
            )

            if len(batch) >= BATCH_SIZE:
                DashboardMibigReference.objects.bulk_create(batch, ignore_conflicts=True)
                total += len(batch)
                batch.clear()

    if batch:
        DashboardMibigReference.objects.bulk_create(batch, ignore_conflicts=True)
        total += len(batch)

    logger.info("Loaded %d MIBiG references", total)
    return total


def load_gcf(data_dir: Path, bgc_lookup: dict[int, int]) -> int:
    """Load gcf.tsv → DashboardGCF."""
    path = data_dir / "gcf.tsv"
    if not path.exists():
        logger.info("gcf.tsv not found, skipping")
        return 0

    batch: list[DashboardGCF] = []
    total = 0

    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rep_src = int(row["representative_source_bgc_id"]) if row.get("representative_source_bgc_id") else None
            rep_id = bgc_lookup.get(rep_src) if rep_src else None

            batch.append(
                DashboardGCF(
                    family_id=row["family_id"],
                    representative_bgc_id=rep_id,
                    member_count=int(row.get("member_count", 0)),
                    known_chemistry_annotation=row.get("known_chemistry_annotation", ""),
                    mibig_accession=row.get("mibig_accession", ""),
                    mean_novelty=float(row.get("mean_novelty", 0)),
                    mibig_count=int(row.get("mibig_count", 0)),
                )
            )

            if len(batch) >= BATCH_SIZE:
                DashboardGCF.objects.bulk_create(batch, ignore_conflicts=True)
                total += len(batch)
                batch.clear()

    if batch:
        DashboardGCF.objects.bulk_create(batch, ignore_conflicts=True)
        total += len(batch)

    logger.info("Loaded %d GCFs", total)
    return total


# ── Post-load computations ────────────────────────────────────────────────────


def compute_assembly_scores() -> None:
    """Recompute denormalized scores on DashboardAssembly from loaded BGC data."""
    logger.info("Computing assembly scores ...")

    assemblies = DashboardAssembly.objects.annotate(
        _bgc_count=Count("bgcs"),
        _l1_class_count=Count("bgcs__classification_l1", distinct=True),
        _avg_novelty=Avg("bgcs__novelty_score"),
    )

    batch = []
    for asm in assemblies.iterator():
        asm.bgc_count = asm._bgc_count
        asm.l1_class_count = asm._l1_class_count
        asm.bgc_novelty_score = asm._avg_novelty or 0.0
        batch.append(asm)

        if len(batch) >= BATCH_SIZE:
            DashboardAssembly.objects.bulk_update(
                batch, ["bgc_count", "l1_class_count", "bgc_novelty_score"], batch_size=BATCH_SIZE
            )
            batch.clear()

    if batch:
        DashboardAssembly.objects.bulk_update(
            batch, ["bgc_count", "l1_class_count", "bgc_novelty_score"], batch_size=BATCH_SIZE
        )

    logger.info("Assembly scores computed")


def compute_catalog_counts() -> None:
    """Recompute BGC class and domain catalog counts."""
    logger.info("Computing catalog counts ...")

    # BGC classes from classification_l1
    class_counts = (
        DashboardBgc.objects.exclude(classification_l1="")
        .values("classification_l1")
        .annotate(cnt=Count("id"))
    )
    DashboardBgcClass.objects.all().delete()
    DashboardBgcClass.objects.bulk_create(
        [DashboardBgcClass(name=r["classification_l1"], bgc_count=r["cnt"]) for r in class_counts],
        batch_size=BATCH_SIZE,
    )

    # Domain counts
    domain_counts = (
        BgcDomain.objects.values("domain_acc", "domain_name", "ref_db")
        .annotate(cnt=Count("bgc_id", distinct=True))
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

    logger.info("Catalog counts computed")


# ── Main entry point ──────────────────────────────────────────────────────────


def run_pipeline(data_dir: str | Path, *, truncate: bool = False, skip_stats: bool = False) -> None:
    """Execute the full discovery data loading pipeline.

    Parameters
    ----------
    data_dir:
        Directory containing TSV files.
    truncate:
        If ``True``, TRUNCATE all discovery tables before loading.
    skip_stats:
        If ``True``, skip post-load score/stats computation.
    """
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Data directory not found: {data_dir}")

    if truncate:
        logger.info("Truncating all discovery tables ...")
        truncate_tables(ALL_DISCOVERY_TABLES)

    # 1. Detectors
    detector_lookup = load_detectors(data_dir)

    # 2. Assemblies
    assembly_lookup = load_assemblies(data_dir)

    # 3. Contigs
    contig_lookup = load_contigs(data_dir, assembly_lookup)

    # 4. BGCs + regions
    bgc_lookup = load_bgcs(data_dir, contig_lookup, detector_lookup, assembly_lookup)

    # 5. CDS
    cds_lookup = load_cds(data_dir, bgc_lookup)

    # 6. Domains
    load_domains(data_dir, bgc_lookup, cds_lookup)

    # 7. Embeddings
    load_embeddings(data_dir, bgc_lookup)

    # 8. Natural products
    load_natural_products(data_dir, bgc_lookup)

    # 9. MIBiG references
    load_mibig_references(data_dir, bgc_lookup)

    # 10. GCFs
    load_gcf(data_dir, bgc_lookup)

    # 11–12. Post-load computations
    if not skip_stats:
        compute_assembly_scores()
        compute_catalog_counts()

    logger.info("Pipeline complete.")
