"""Discovery data loader — orchestrates bulk ingestion from TSV files.

The pipeline loads data in dependency order, using PostgreSQL ``COPY FROM``
where possible and ``bulk_create`` for tables requiring per-row logic (BGCs
need region assignment).

Expected directory layout::

    data_dir/
      detectors.tsv
      assemblies.tsv
      contigs.tsv
      contig_sequences.tsv  (optional)
      bgcs.tsv
      cds.tsv               (optional)
      cds_sequences.tsv     (optional)
      domains.tsv           (optional)
      embeddings_bgc.tsv    (optional)
      embeddings_protein.tsv (optional)
      natural_products.tsv       (optional)
      np_chemont_classes.tsv     (optional)
"""

from __future__ import annotations

import base64
import csv
import logging
import struct
import sys
from pathlib import Path

from django.db.models import Avg, Count, Max
from django.db.models.expressions import RawSQL

from discovery.models import (
    AssemblySource,
    BgcDomain,
    BgcEmbedding,
    CdsSequence,
    ContigSequence,
    DashboardAssembly,
    DashboardBgc,
    DashboardBgcClass,
    DashboardCds,
    DashboardContig,
    DashboardDetector,
    DashboardDomain,
    DashboardNaturalProduct,
    DashboardRegion,
    NaturalProductChemOntClass,
    ProteinEmbedding,
    RegionAccessionAlias,
)

from .region_assignment import RegionAssigner
from .tsv_copy import copy_tsv_to_table, truncate_tables

logger = logging.getLogger(__name__)

BATCH_SIZE = 10_000

# Tables in truncation order (respects FK CASCADE but explicit is safer)
ALL_DISCOVERY_TABLES = [
    "discovery_region_accession_alias",
    "discovery_protein_embedding",
    "discovery_bgc_embedding",
    "discovery_bgc_domain",
    "discovery_cds_sequence",
    "discovery_cds",
    "discovery_np_chemont_class",
    "discovery_natural_product",
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
    # Encode as major*1_000_000 + minor*1_000 + patch.
    # Fits in PositiveIntegerField (max 2_147_483_647) for versions up to 2147.x.x.
    parts = (parts + [0, 0, 0])[:3]
    return parts[0] * 1_000_000 + parts[1] * 1_000 + parts[2]


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

    DashboardDetector.objects.bulk_create(
        rows_to_create,
        batch_size=BATCH_SIZE,
        update_conflicts=True,
        unique_fields=["tool", "version"],
        update_fields=["name", "tool_name_code", "version_sort_key"],
    )
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
                    biome_path=row.get("biome_path", ""),
                    is_type_strain=row.get("is_type_strain", "").lower() in ("true", "1"),
                    type_strain_catalog_url=row.get("type_strain_catalog_url", ""),
                    assembly_size_mb=float(row["assembly_size_mb"]) if row.get("assembly_size_mb") else None,
                    url=row.get("url", ""),
                )
            )

    DashboardAssembly.objects.bulk_create(
        rows,
        batch_size=BATCH_SIZE,
        update_conflicts=True,
        unique_fields=["assembly_accession"],
        update_fields=[
            "organism_name", "source", "assembly_type", "biome_path",
            "is_type_strain", "type_strain_catalog_url", "assembly_size_mb", "url",
        ],
    )
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

    Returns ``{sequence_sha256: contig_id}``.
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
                logger.warning(
                    "Unknown assembly %s for contig %s, skipping",
                    assembly_acc, row.get("accession", row["sequence_sha256"]),
                )
                continue
            src_id = row.get("source_contig_id")
            rows.append(
                DashboardContig(
                    assembly_id=assembly_id,
                    sequence_sha256=row["sequence_sha256"],
                    accession=row.get("accession", ""),
                    length=int(row.get("length", 0)),
                    taxonomy_path=row.get("taxonomy_path", ""),
                    source_contig_id=int(src_id) if src_id else None,
                )
            )

    DashboardContig.objects.bulk_create(
        rows,
        batch_size=BATCH_SIZE,
        update_conflicts=True,
        unique_fields=["sequence_sha256"],
        update_fields=["assembly", "accession", "length", "taxonomy_path", "source_contig_id"],
    )
    lookup = dict(DashboardContig.objects.values_list("sequence_sha256", "id"))
    logger.info("Loaded %d contigs", len(lookup))
    return lookup


def load_contig_sequences(data_dir: Path, contig_lookup: dict[str, int]) -> int:
    """Load contig_sequences.tsv → ContigSequence.

    Each row contains a base64-encoded zlib-compressed nucleotide sequence.
    The loader base64-decodes and stores the raw zlib bytes directly.

    Returns row count.
    """
    path = data_dir / "contig_sequences.tsv"
    if not path.exists():
        logger.info("contig_sequences.tsv not found, skipping")
        return 0

    batch: list[ContigSequence] = []
    total = 0

    with open(path, newline="") as f:
        csv.field_size_limit(sys.maxsize)
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            contig_sha = row["contig_sha256"]
            contig_id = contig_lookup.get(contig_sha)
            if contig_id is None:
                logger.warning("Unknown contig %s for sequence, skipping", contig_sha)
                continue

            raw_zlib = base64.b64decode(row["sequence_base64"])
            batch.append(ContigSequence(contig_id=contig_id, data=raw_zlib))

            if len(batch) >= BATCH_SIZE:
                ContigSequence.objects.bulk_create(
                batch, update_conflicts=True, unique_fields=["contig"], update_fields=["data"],
            )
                total += len(batch)
                batch.clear()

    if batch:
        ContigSequence.objects.bulk_create(
            batch, update_conflicts=True, unique_fields=["contig"], update_fields=["data"],
        )
        total += len(batch)

    logger.info("Loaded %d contig sequences", total)
    return total


def _build_bgc_lookup() -> dict[tuple[str, int, int, str], int]:
    """Build composite-key lookup from existing BGCs in the database.

    Returns ``{(contig_sha256, start, end, detector_name): bgc_id}``.
    """
    lookup: dict[tuple[str, int, int, str], int] = {}
    qs = DashboardBgc.objects.select_related("contig", "detector").only(
        "id", "contig__sequence_sha256", "start_position", "end_position", "detector__name",
    )
    for bgc in qs.iterator():
        key = (bgc.contig.sequence_sha256, bgc.start_position, bgc.end_position, bgc.detector.name)
        lookup[key] = bgc.id
    return lookup


def load_bgcs(
    data_dir: Path,
    contig_lookup: dict[str, int],
    detector_lookup: dict[str, tuple[int, str]],
    assembly_lookup: dict[str, int],
) -> dict[tuple[str, int, int, str], int]:
    """Load bgcs.tsv → DashboardBgc + DashboardRegion (via region assignment).

    Returns ``{(contig_sha256, start, end, detector_name): dashboard_bgc_id}``.
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
            contig_sha = row["contig_sha256"]
            contig_id = contig_lookup.get(contig_sha)
            if contig_id is None:
                logger.warning("Unknown contig %s, skipping BGC", contig_sha)
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

            # Support both old (nearest_mibig_*) and new (nearest_validated_*) column names
            nearest_val_acc = row.get(
                "nearest_validated_accession",
                row.get("nearest_mibig_accession", ""),
            )
            raw_dist = row.get(
                "nearest_validated_distance",
                row.get("nearest_mibig_distance", ""),
            )

            batch.append(
                DashboardBgc(
                    assembly_id=assembly_id,
                    contig_id=contig_id,
                    bgc_accession=accession,
                    start_position=start,
                    end_position=end,
                    classification_path=row.get("classification_path", ""),
                    novelty_score=float(row.get("novelty_score", 0)),
                    domain_novelty=float(row.get("domain_novelty", 0)),
                    size_kb=float(row.get("size_kb", 0)),
                    nearest_validated_accession=nearest_val_acc,
                    nearest_validated_distance=float(raw_dist) if raw_dist else None,
                    is_partial=row.get("is_partial", "").lower() in ("true", "1"),
                    is_validated=row.get("is_validated", "").lower() in ("true", "1"),
                    umap_x=float(row.get("umap_x", 0)),
                    umap_y=float(row.get("umap_y", 0)),
                    gene_cluster_family=row.get("gene_cluster_family", ""),
                    detector_id=detector_id,
                    region_id=region_id,
                    bgc_number=bgc_number,
                )
            )

            if len(batch) >= BATCH_SIZE:
                DashboardBgc.objects.bulk_create(
                    batch,
                    update_conflicts=True,
                    unique_fields=["contig", "start_position", "end_position", "detector"],
                    update_fields=[
                        "assembly", "classification_path", "novelty_score", "domain_novelty",
                        "size_kb", "nearest_validated_accession", "nearest_validated_distance",
                        "is_partial", "is_validated", "umap_x", "umap_y", "gene_cluster_family",
                    ],
                )
                total += len(batch)
                batch.clear()

    if batch:
        DashboardBgc.objects.bulk_create(
            batch,
            update_conflicts=True,
            unique_fields=["contig", "start_position", "end_position", "detector"],
            update_fields=[
                "assembly", "classification_path", "novelty_score", "domain_novelty",
                "size_kb", "nearest_validated_accession", "nearest_validated_distance",
                "is_partial", "is_validated", "umap_x", "umap_y", "gene_cluster_family",
            ],
        )
        total += len(batch)

    lookup = _build_bgc_lookup()
    logger.info("Loaded %d BGCs across %d regions", total, DashboardRegion.objects.count())
    return lookup


def _resolve_bgc_key(row: dict, bgc_lookup: dict[tuple[str, int, int, str], int]) -> int | None:
    """Resolve a BGC composite key from a TSV row to a database ID."""
    key = (
        row["contig_sha256"],
        int(row["bgc_start"]),
        int(row["bgc_end"]),
        row["detector_name"],
    )
    return bgc_lookup.get(key)


def load_cds(
    data_dir: Path,
    bgc_lookup: dict[tuple[str, int, int, str], int],
) -> dict[tuple[int, str], int]:
    """Load cds.tsv → DashboardCds.

    Returns ``{(bgc_db_id, protein_id_str): cds_id}``.
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
            bgc_id = _resolve_bgc_key(row, bgc_lookup)
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
                    protein_sha256=row.get("protein_sha256", ""),
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

    # Build lookup for domain loading: (bgc_db_id, protein_id_str) → cds_id
    cds_lookup: dict[tuple[int, str], int] = {}
    for cds in DashboardCds.objects.only("id", "protein_id_str", "bgc_id"):
        cds_lookup[(cds.bgc_id, cds.protein_id_str)] = cds.id
    return cds_lookup


def load_cds_sequences(
    data_dir: Path,
    bgc_lookup: dict[tuple[str, int, int, str], int],
    cds_lookup: dict[tuple[int, str], int],
) -> int:
    """Load cds_sequences.tsv → CdsSequence.

    Each row contains a base64-encoded zlib-compressed amino acid sequence.
    The loader base64-decodes and stores the raw zlib bytes directly.

    Returns row count.
    """
    path = data_dir / "cds_sequences.tsv"
    if not path.exists():
        logger.info("cds_sequences.tsv not found, skipping")
        return 0

    batch: list[CdsSequence] = []
    total = 0

    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            bgc_id = _resolve_bgc_key(row, bgc_lookup)
            if bgc_id is None:
                continue
            protein_id = row["protein_id_str"]
            cds_id = cds_lookup.get((bgc_id, protein_id))
            if cds_id is None:
                continue

            raw_zlib = base64.b64decode(row["sequence_base64"])
            batch.append(CdsSequence(cds_id=cds_id, data=raw_zlib))

            if len(batch) >= BATCH_SIZE:
                deduped = list({obj.cds_id: obj for obj in batch}.values())
                CdsSequence.objects.bulk_create(
                    deduped, update_conflicts=True, unique_fields=["cds"], update_fields=["data"],
                )
                total += len(deduped)
                batch.clear()

    if batch:
        deduped = list({obj.cds_id: obj for obj in batch}.values())
        CdsSequence.objects.bulk_create(
            deduped, update_conflicts=True, unique_fields=["cds"], update_fields=["data"],
        )
        total += len(deduped)

    logger.info("Loaded %d CDS sequences", total)
    return total


def load_domains(
    data_dir: Path,
    bgc_lookup: dict[tuple[str, int, int, str], int],
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
            bgc_id = _resolve_bgc_key(row, bgc_lookup)
            if bgc_id is None:
                continue

            protein_id = row.get("protein_id_str", "")
            cds_id = cds_lookup.get((bgc_id, protein_id))

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
                    url=row.get("url", ""),
                )
            )

            if len(batch) >= BATCH_SIZE:
                BgcDomain.objects.bulk_create(
                    batch,
                    update_conflicts=True,
                    unique_fields=["bgc", "domain_acc", "cds", "start_position", "end_position"],
                    update_fields=["domain_name", "domain_description", "ref_db", "score", "url"],
                )
                total += len(batch)
                batch.clear()

    if batch:
        BgcDomain.objects.bulk_create(
            batch,
            update_conflicts=True,
            unique_fields=["bgc", "domain_acc", "cds", "start_position", "end_position"],
            update_fields=["domain_name", "domain_description", "ref_db", "score", "url"],
        )
        total += len(batch)

    logger.info("Loaded %d domain rows", total)
    return total


def load_embeddings(
    data_dir: Path,
    bgc_lookup: dict[tuple[str, int, int, str], int],
) -> int:
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
            bgc_id = _resolve_bgc_key(row, bgc_lookup)
            if bgc_id is None:
                continue

            raw = base64.b64decode(row["vector_base64"])
            vector = list(struct.unpack(f"<{len(raw)//4}f", raw))

            batch.append(BgcEmbedding(bgc_id=bgc_id, vector=vector))

            if len(batch) >= BATCH_SIZE:
                BgcEmbedding.objects.bulk_create(
                    batch, update_conflicts=True, unique_fields=["bgc"], update_fields=["vector"],
                )
                total += len(batch)
                batch.clear()

    if batch:
        BgcEmbedding.objects.bulk_create(
            batch, update_conflicts=True, unique_fields=["bgc"], update_fields=["vector"],
        )
        total += len(batch)

    logger.info("Loaded %d BGC embeddings", total)
    return total


def load_protein_embeddings(data_dir: Path) -> int:
    """Load embeddings_protein.tsv → ProteinEmbedding. Returns row count."""
    path = data_dir / "embeddings_protein.tsv"
    if not path.exists():
        logger.info("embeddings_protein.tsv not found, skipping")
        return 0

    batch: list[ProteinEmbedding] = []
    total = 0

    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            raw = base64.b64decode(row["vector_base64"])
            vector = list(struct.unpack(f"<{len(raw)//4}f", raw))

            batch.append(
                ProteinEmbedding(
                    protein_sha256=row["protein_sha256"],
                    vector=vector,
                    source_protein_id=None,
                )
            )

            if len(batch) >= BATCH_SIZE:
                ProteinEmbedding.objects.bulk_create(
                    batch,
                    update_conflicts=True,
                    unique_fields=["protein_sha256"],
                    update_fields=["vector"],
                )
                total += len(batch)
                batch.clear()

    if batch:
        ProteinEmbedding.objects.bulk_create(
            batch,
            update_conflicts=True,
            unique_fields=["protein_sha256"],
            update_fields=["vector"],
        )
        total += len(batch)

    logger.info("Loaded %d protein embeddings", total)
    return total


def load_natural_products(
    data_dir: Path,
    bgc_lookup: dict[tuple[str, int, int, str], int],
) -> int:
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
            bgc_id = _resolve_bgc_key(row, bgc_lookup)
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
                    structure_svg_base64=row.get("structure_svg_base64", ""),
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


def load_np_chemont_classes(
    data_dir: Path,
    bgc_lookup: dict[tuple[str, int, int, str], int],
) -> int:
    """Load np_chemont_classes.tsv → NaturalProductChemOntClass.

    Each row maps a natural product (identified by BGC key + name) to a
    ChemOnt ontology term with a probability score.
    """
    path = data_dir / "np_chemont_classes.tsv"
    if not path.exists():
        logger.info("np_chemont_classes.tsv not found, skipping")
        return 0

    # Build NP lookup: (bgc_id, np_name) → np_id
    np_lookup: dict[tuple[int, str], int] = {}
    for np_obj in DashboardNaturalProduct.objects.values_list("id", "bgc_id", "name"):
        np_lookup[(np_obj[1], np_obj[2])] = np_obj[0]

    batch: list[NaturalProductChemOntClass] = []
    total = 0
    skipped = 0

    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            bgc_id = _resolve_bgc_key(row, bgc_lookup)
            if bgc_id is None:
                skipped += 1
                continue

            np_name = row.get("natural_product_name", "")
            np_id = np_lookup.get((bgc_id, np_name))
            if np_id is None:
                skipped += 1
                continue

            probability = float(row.get("probability", "1.0"))

            batch.append(
                NaturalProductChemOntClass(
                    natural_product_id=np_id,
                    chemont_id=row["chemont_id"],
                    chemont_name=row["chemont_name"],
                    probability=probability,
                )
            )

            if len(batch) >= BATCH_SIZE:
                NaturalProductChemOntClass.objects.bulk_create(
                    batch,
                    update_conflicts=True,
                    unique_fields=["natural_product", "chemont_id"],
                    update_fields=["chemont_name", "probability"],
                )
                total += len(batch)
                batch.clear()

    if batch:
        NaturalProductChemOntClass.objects.bulk_create(
            batch,
            update_conflicts=True,
            unique_fields=["natural_product", "chemont_id"],
            update_fields=["chemont_name", "probability"],
        )
        total += len(batch)

    if skipped:
        logger.warning("Skipped %d ChemOnt class rows (unresolved NP)", skipped)
    logger.info("Loaded %d NP ChemOnt classifications", total)
    return total


# ── Post-load computations ────────────────────────────────────────────────────


def compute_assembly_scores() -> None:
    """Recompute denormalized scores on DashboardAssembly from loaded BGC data."""
    logger.info("Computing assembly scores ...")

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

    # Domain counts — group by acc only so each acc maps to exactly one row,
    # avoiding UniqueViolation when the same acc appears with different names
    # across data batches (e.g. casing/punctuation drift between runs).
    domain_counts = (
        BgcDomain.objects
        .values("domain_acc")
        .annotate(
            cnt=Count("bgc_id", distinct=True),
            domain_name=Max("domain_name"),
            ref_db=Max("ref_db"),
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

    # 3.5. Contig sequences
    load_contig_sequences(data_dir, contig_lookup)

    # 4. BGCs + regions
    bgc_lookup = load_bgcs(data_dir, contig_lookup, detector_lookup, assembly_lookup)

    # 5. CDS
    cds_lookup = load_cds(data_dir, bgc_lookup)

    # 5.5. CDS sequences
    load_cds_sequences(data_dir, bgc_lookup, cds_lookup)

    # 6. Domains
    load_domains(data_dir, bgc_lookup, cds_lookup)

    # 7. BGC embeddings
    load_embeddings(data_dir, bgc_lookup)

    # 7.5. Protein embeddings
    load_protein_embeddings(data_dir)

    # 8. Natural products
    load_natural_products(data_dir, bgc_lookup)

    # 8.5. NP ChemOnt classifications
    load_np_chemont_classes(data_dir, bgc_lookup)

    # 9–10. Post-load computations
    if not skip_stats:
        compute_assembly_scores()
        compute_catalog_counts()

    logger.info("Pipeline complete.")
