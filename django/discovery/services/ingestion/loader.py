"""Discovery data loader — bulk ingest TSV files into the iBGC-first schema.

Pipeline phases (in dependency order):

  1. Detectors            → DashboardDetector
  2. Assemblies           → DashboardAssembly
  3. Contigs              → DashboardContig
  3.5 Contig sequences    → ContigSequence
  4. Source predictions   → SourceBgcPrediction + ConsensusBgc (via CbgcAssigner)
  5. CDS                  → ContigCds (deduped on contig + range + strand)
  5.5 CDS sequences       → CdsSequence
  6. Domains              → ContigDomain (FK to ContigCds + denormalised contig FK)
  7. CDS ChemOnt          → CdsChemOnt
  9–10. Assembly + catalog score recomputation

Natural products are NOT loaded here — they're per-iBGC and the iBGC table
is built downstream by ``build_integrated_bgcs``. The operator runs
``python manage.py load_natural_products --data-dir <dir>`` after the iBGC
build.

Expected directory layout::

    data_dir/
      detectors.tsv
      assemblies.tsv
      contigs.tsv
      contig_sequences.tsv      (optional)
      bgcs.tsv                  (source predictions)
      cds.tsv                   (optional)
      cds_sequences.tsv         (optional)
      domains.tsv               (optional)
      cds_chemont.tsv           (optional)
      natural_products.tsv      (read by load_natural_products step, not here)
"""

from __future__ import annotations

import base64
import csv
import logging
import sys
from pathlib import Path

from django.db.models import Avg, Count, Max
from django.db.models.expressions import RawSQL
from psycopg2.extras import NumericRange

from discovery.models import (
    AssemblySource,
    CdsChemOnt,
    CdsSequence,
    ContigCds,
    ContigDomain,
    ContigSequence,
    DashboardAssembly,
    DashboardBgcClass,
    DashboardContig,
    DashboardDetector,
    DashboardDomain,
    IntegratedBgc,
    SourceBgcPrediction,
)
from discovery.services.go_slim import go_slim_for_terms

from .cbgc_assigner import CbgcAssigner
from .tsv_copy import copy_tsv_to_table, truncate_tables

logger = logging.getLogger(__name__)

BATCH_SIZE = 10_000
SEQUENCE_INSERT_BATCH_SIZE = 500  # smaller SQL batches for large binary payloads

# Truncation order (FK CASCADE would handle it, but explicit is safer).
ALL_DISCOVERY_TABLES = [
    "discovery_accession_alias",
    "discovery_ibgc_natural_product",
    "discovery_ibgc_clustering_snapshot",
    "discovery_gcf",
    "discovery_cds_chemont",
    "discovery_domain_hit",
    "discovery_cds_sequence",
    "discovery_cds",
    "discovery_source_bgc",
    "discovery_ibgc",
    "discovery_cbgc",
    "discovery_accession_registry",
    "discovery_precomputed_stats",
    "discovery_contig_sequence",
    "discovery_contig",
    "discovery_assembly",
    "discovery_detector",
    "discovery_assembly_source",
    "discovery_bgc_class",
    "discovery_domain",
    "discovery_clustering_run",
]


def _range(start: int, end_inclusive: int) -> NumericRange:
    """Half-open ``[start, end+1)`` int4range value for Postgres."""
    return NumericRange(lower=int(start), upper=int(end_inclusive) + 1, bounds="[)")


def _version_sort_key(version_str: str) -> int:
    """Convert a semver-ish string to a sortable integer."""
    parts = []
    for segment in version_str.split("."):
        digits = "".join(c for c in segment if c.isdigit())
        parts.append(int(digits) if digits else 0)
    parts = (parts + [0, 0, 0])[:3]
    return parts[0] * 1_000_000 + parts[1] * 1_000 + parts[2]


def _generate_tool_name_code(tool: str, existing_codes: set[str]) -> str:
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


# ── Pipeline steps ───────────────────────────────────────────────────────────


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
    """Load assemblies.tsv → DashboardAssembly. Returns ``{accession: id}``."""
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
    lookup = dict(DashboardAssembly.objects.values_list("assembly_accession", "id"))
    logger.info("Loaded %d assemblies", len(lookup))
    return lookup


def load_contigs(
    data_dir: Path,
    assembly_lookup: dict[str, int],
) -> dict[str, int]:
    """Load contigs.tsv → DashboardContig. Returns ``{sequence_sha256: contig_id}``."""
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
            rows.append(
                DashboardContig(
                    assembly_id=assembly_id,
                    sequence_sha256=row["sequence_sha256"],
                    accession=row.get("accession", ""),
                    length=int(row.get("length", 0)),
                    taxonomy_path=row.get("taxonomy_path", ""),
                )
            )

    DashboardContig.objects.bulk_create(
        rows,
        batch_size=BATCH_SIZE,
        update_conflicts=True,
        unique_fields=["sequence_sha256"],
        update_fields=["assembly", "accession", "length", "taxonomy_path"],
    )
    lookup = dict(DashboardContig.objects.values_list("sequence_sha256", "id"))
    logger.info("Loaded %d contigs", len(lookup))
    return lookup


def load_contig_sequences(data_dir: Path, contig_lookup: dict[str, int]) -> int:
    """Load contig_sequences.tsv → ContigSequence."""
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
                    batch,
                    update_conflicts=True, unique_fields=["contig"], update_fields=["data"],
                    batch_size=SEQUENCE_INSERT_BATCH_SIZE,
                )
                total += len(batch)
                batch.clear()

    if batch:
        ContigSequence.objects.bulk_create(
            batch,
            update_conflicts=True, unique_fields=["contig"], update_fields=["data"],
            batch_size=SEQUENCE_INSERT_BATCH_SIZE,
        )
        total += len(batch)

    logger.info("Loaded %d contig sequences", total)
    return total


# ── Source predictions + cBGC assignment ─────────────────────────────────────


def _build_source_bgc_lookup() -> dict[tuple[str, int, int, str], int]:
    """Return ``{(contig_sha256, start, end, detector_name): source_bgc_id}``."""
    lookup: dict[tuple[str, int, int, str], int] = {}
    qs = SourceBgcPrediction.objects.select_related("contig", "detector").only(
        "id", "contig__sequence_sha256", "bgc_range", "detector__name",
    )
    for sbgc in qs.iterator():
        rng = sbgc.bgc_range
        if rng is None:
            continue
        start = int(rng.lower)
        end_inclusive = int(rng.upper) - 1
        key = (
            sbgc.contig.sequence_sha256,
            start,
            end_inclusive,
            sbgc.detector.name if sbgc.detector_id else "",
        )
        lookup[key] = sbgc.id
    return lookup


def load_source_bgcs(
    data_dir: Path,
    contig_lookup: dict[str, int],
    detector_lookup: dict[str, tuple[int, str]],
    assembly_lookup: dict[str, int],
) -> dict[tuple[str, int, int, str], int]:
    """Load bgcs.tsv → SourceBgcPrediction + ConsensusBgc (via CbgcAssigner).

    Returns ``{(contig_sha256, start, end, detector_name): source_bgc_id}``.
    """
    path = data_dir / "bgcs.tsv"
    if not path.exists():
        logger.warning("bgcs.tsv not found, skipping")
        return {}

    contig_to_assembly: dict[int, int] = dict(
        DashboardContig.objects.values_list("id", "assembly_id")
    )
    contig_accession_by_id: dict[int, str] = dict(
        DashboardContig.objects.values_list("id", "accession")
    )

    assigner = CbgcAssigner()
    batch: list[SourceBgcPrediction] = []
    total = 0

    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            contig_sha = row["contig_sha256"]
            contig_id = contig_lookup.get(contig_sha)
            if contig_id is None:
                logger.warning("Unknown contig %s, skipping source prediction", contig_sha)
                continue

            detector_name = row["detector_name"]
            det_info = detector_lookup.get(detector_name)
            if det_info is None:
                logger.warning("Unknown detector %s, skipping source prediction", detector_name)
                continue
            detector_id, tool_code = det_info

            start = int(row["start_position"])
            end = int(row["end_position"])

            cbgc_id, bgc_number, prediction_accession = assigner.assign(
                contig_id=contig_id,
                contig_accession=contig_accession_by_id.get(contig_id, "") or contig_sha,
                start=start,
                end=end,
                detector_id=detector_id,
                tool_code=tool_code,
            )

            assembly_id = contig_to_assembly.get(contig_id)

            batch.append(
                SourceBgcPrediction(
                    assembly_id=assembly_id,
                    contig_id=contig_id,
                    prediction_accession=prediction_accession,
                    bgc_range=_range(start, end),
                    is_partial=row.get("is_partial", "").lower() in ("true", "1"),
                    is_validated=row.get("is_validated", "").lower() in ("true", "1"),
                    detector_id=detector_id,
                    cbgc_id=cbgc_id,
                    bgc_number=bgc_number,
                )
            )

            if len(batch) >= BATCH_SIZE:
                SourceBgcPrediction.objects.bulk_create(batch, ignore_conflicts=True)
                total += len(batch)
                batch.clear()

    if batch:
        SourceBgcPrediction.objects.bulk_create(batch, ignore_conflicts=True)
        total += len(batch)

    lookup = _build_source_bgc_lookup()
    logger.info(
        "Loaded %d source predictions across %d cBGCs",
        total,
        len({sbgc.cbgc_id for sbgc in SourceBgcPrediction.objects.only("cbgc_id").iterator()}),
    )
    return lookup


# ── CDS / domains / chemont ──────────────────────────────────────────────────


def load_cds(
    data_dir: Path,
    contig_lookup: dict[str, int],
) -> dict[tuple[int, str], int]:
    """Load cds.tsv → ContigCds. CDS are contig-anchored and deduped on
    ``(contig, cds_range, strand)`` — the same gene called by two BGC tools
    is stored once.

    Returns ``{(contig_id, protein_id_str): cds_id}``.
    """
    path = data_dir / "cds.tsv"
    if not path.exists():
        logger.info("cds.tsv not found, skipping")
        return {}

    batch: list[ContigCds] = []
    total = 0
    seen: set[tuple[int, int, int, int]] = set()  # (contig_id, lower, upper, strand)

    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            contig_sha = row["contig_sha256"]
            contig_id = contig_lookup.get(contig_sha)
            if contig_id is None:
                continue

            start = int(row["start_position"])
            end = int(row["end_position"])
            strand = int(row["strand"])
            cds_range = _range(start, end)

            dedup_key = (contig_id, cds_range.lower, cds_range.upper, strand)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            batch.append(
                ContigCds(
                    contig_id=contig_id,
                    cds_range=cds_range,
                    strand=strand,
                    protein_id_str=row["protein_id_str"],
                    protein_length=int(row.get("protein_length", 0)),
                    gene_caller=row.get("gene_caller", ""),
                    cluster_representative=row.get("cluster_representative", ""),
                    protein_sha256=row.get("protein_sha256", ""),
                )
            )

            if len(batch) >= BATCH_SIZE:
                ContigCds.objects.bulk_create(batch, ignore_conflicts=True)
                total += len(batch)
                batch.clear()

    if batch:
        ContigCds.objects.bulk_create(batch, ignore_conflicts=True)
        total += len(batch)

    logger.info("Loaded %d CDS rows", total)

    # Lookup keyed by (contig_id, protein_id_str) — the natural per-gene key.
    cds_lookup: dict[tuple[int, str], int] = {}
    for cds_id, contig_id, protein_id in ContigCds.objects.values_list(
        "id", "contig_id", "protein_id_str",
    ):
        cds_lookup[(contig_id, protein_id)] = cds_id
    return cds_lookup


def load_cds_sequences(
    data_dir: Path,
    contig_lookup: dict[str, int],
    cds_lookup: dict[tuple[int, str], int],
) -> int:
    """Load cds_sequences.tsv → CdsSequence."""
    path = data_dir / "cds_sequences.tsv"
    if not path.exists():
        logger.info("cds_sequences.tsv not found, skipping")
        return 0

    batch: list[CdsSequence] = []
    total = 0

    with open(path, newline="") as f:
        csv.field_size_limit(sys.maxsize)
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            contig_sha = row.get("contig_sha256", "")
            contig_id = contig_lookup.get(contig_sha)
            if contig_id is None:
                continue
            cds_id = cds_lookup.get((contig_id, row["protein_id_str"]))
            if cds_id is None:
                continue

            raw_zlib = base64.b64decode(row["sequence_base64"])
            batch.append(CdsSequence(cds_id=cds_id, data=raw_zlib))

            if len(batch) >= BATCH_SIZE:
                deduped = list({obj.cds_id: obj for obj in batch}.values())
                CdsSequence.objects.bulk_create(
                    deduped,
                    update_conflicts=True, unique_fields=["cds"], update_fields=["data"],
                    batch_size=SEQUENCE_INSERT_BATCH_SIZE,
                )
                total += len(deduped)
                batch.clear()

    if batch:
        deduped = list({obj.cds_id: obj for obj in batch}.values())
        CdsSequence.objects.bulk_create(
            deduped,
            update_conflicts=True, unique_fields=["cds"], update_fields=["data"],
            batch_size=SEQUENCE_INSERT_BATCH_SIZE,
        )
        total += len(deduped)

    logger.info("Loaded %d CDS sequences", total)
    return total


def load_domains(
    data_dir: Path,
    contig_lookup: dict[str, int],
    cds_lookup: dict[tuple[int, str], int],
) -> int:
    """Load domains.tsv → ContigDomain (FK to ContigCds + denormalised contig FK).

    All ref_db values ingested unchanged — downstream callers apply their own
    PFAM/NCBIFAM filter. Domain rows are deduped per (cds, acc, start, end).
    """
    path = data_dir / "domains.tsv"
    if not path.exists():
        logger.info("domains.tsv not found, skipping")
        return 0

    batch: list[ContigDomain] = []
    total = 0
    seen: set[tuple[int, str, int, int]] = set()

    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            contig_sha = row.get("contig_sha256", "")
            contig_id = contig_lookup.get(contig_sha)
            if contig_id is None:
                continue
            protein_id = row.get("protein_id_str", "")
            cds_id = cds_lookup.get((contig_id, protein_id))
            if cds_id is None:
                continue

            domain_acc = row["domain_acc"]
            d_start = int(row.get("start_position", 0))
            d_end = int(row.get("end_position", 0))
            dedup_key = (cds_id, domain_acc, d_start, d_end)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            go_terms_raw = (row.get("go_terms") or "").strip()
            go_terms = [t for t in go_terms_raw.split("|") if t] if go_terms_raw else []

            batch.append(
                ContigDomain(
                    cds_id=cds_id,
                    contig_id=contig_id,
                    domain_acc=domain_acc,
                    domain_name=row.get("domain_name", ""),
                    domain_description=row.get("domain_description", ""),
                    ref_db=row.get("ref_db", ""),
                    start_position=d_start,
                    end_position=d_end,
                    score=float(row["score"]) if row.get("score") else None,
                    url=row.get("url", ""),
                    go_slim=go_slim_for_terms(go_terms),
                    interpro_entry_acc=row.get("interpro_entry_acc", ""),
                    interpro_entry_description=row.get("interpro_entry_description", ""),
                    go_terms=go_terms,
                )
            )

            if len(batch) >= BATCH_SIZE:
                ContigDomain.objects.bulk_create(batch, ignore_conflicts=True)
                total += len(batch)
                batch.clear()

    if batch:
        ContigDomain.objects.bulk_create(batch, ignore_conflicts=True)
        total += len(batch)

    logger.info("Loaded %d domain rows", total)
    return total


def load_cds_chemont(
    data_dir: Path,
    contig_lookup: dict[str, int],
    cds_lookup: dict[tuple[int, str], int],
) -> int:
    """Load cds_chemont.tsv → CdsChemOnt.

    Each row identifies a CDS via ``(contig_sha256, protein_id_str)`` and
    carries the deepest ChemOnt class chosen by CHAMOIS plus its
    iBGC-level probability and gene-specific weight.
    """
    path = data_dir / "cds_chemont.tsv"
    if not path.exists():
        logger.info("cds_chemont.tsv not found, skipping")
        return 0

    batch: list[CdsChemOnt] = []
    total = 0
    skipped = 0

    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            contig_sha = row.get("contig_sha256", "")
            contig_id = contig_lookup.get(contig_sha)
            if contig_id is None:
                skipped += 1
                continue
            protein_id = row.get("protein_id_str", "")
            cds_id = cds_lookup.get((contig_id, protein_id))
            if cds_id is None:
                skipped += 1
                continue

            try:
                probability = float(row.get("probability", "0.0"))
            except ValueError:
                probability = 0.0
            try:
                weight = float(row.get("weight", "0.0"))
            except ValueError:
                weight = 0.0

            batch.append(
                CdsChemOnt(
                    cds_id=cds_id,
                    chemont_id=row["chemont_id"],
                    chemont_name=row["chemont_name"],
                    probability=probability,
                    weight=weight,
                )
            )

            if len(batch) >= BATCH_SIZE:
                CdsChemOnt.objects.bulk_create(
                    batch,
                    update_conflicts=True,
                    unique_fields=["cds", "chemont_id"],
                    update_fields=["chemont_name", "probability", "weight"],
                )
                total += len(batch)
                batch.clear()

    if batch:
        CdsChemOnt.objects.bulk_create(
            batch,
            update_conflicts=True,
            unique_fields=["cds", "chemont_id"],
            update_fields=["chemont_name", "probability", "weight"],
        )
        total += len(batch)

    if skipped:
        logger.warning("Skipped %d CDS ChemOnt rows (unresolved CDS)", skipped)
    logger.info("Loaded %d CDS ChemOnt classifications", total)
    return total


# ── Post-load computations ───────────────────────────────────────────────────


def compute_assembly_scores() -> None:
    """Recompute denormalised counts on DashboardAssembly from loaded iBGCs.

    Runs after the iBGC table is built (i.e. after ``build_integrated_bgcs``).
    ``bgc_count`` reflects iBGC count per assembly; ``l1_class_count`` /
    ``bgc_novelty_score`` likewise iBGC-derived.
    """
    logger.info("Computing assembly iBGC counts/scores ...")

    # iBGCs per assembly via contig FK chain: ibgc.contig.assembly.
    assemblies = DashboardAssembly.objects.annotate(
        _ibgc_count=Count("contigs__ibgcs", distinct=True),
        _l1_class_count=Count(
            RawSQL("SPLIT_PART(discovery_ibgc.gene_cluster_family, '.', 1)", []),
            distinct=True,
        ),
        _avg_novelty=Avg("contigs__ibgcs__novelty_score"),
    )

    batch = []
    for asm in assemblies.iterator():
        asm.bgc_count = asm._ibgc_count
        asm.l1_class_count = asm._l1_class_count
        asm.bgc_novelty_score = asm._avg_novelty or 0.0
        batch.append(asm)
        if len(batch) >= BATCH_SIZE:
            DashboardAssembly.objects.bulk_update(
                batch, ["bgc_count", "l1_class_count", "bgc_novelty_score"], batch_size=BATCH_SIZE,
            )
            batch.clear()

    if batch:
        DashboardAssembly.objects.bulk_update(
            batch, ["bgc_count", "l1_class_count", "bgc_novelty_score"], batch_size=BATCH_SIZE,
        )

    logger.info("Assembly scores computed")


def compute_catalog_counts() -> None:
    """Recompute BGC class and domain catalog counts (iBGC-derived)."""
    logger.info("Computing catalog counts ...")

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

    # Domain counts — distinct iBGC reach per domain acc.
    # ContigDomain.contig is denormalised so the join chain is short.
    domain_counts = (
        ContigDomain.objects
        .values("domain_acc")
        .annotate(
            cnt=Count("contig__ibgcs", distinct=True),
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


# ── Main entry point ─────────────────────────────────────────────────────────


def run_pipeline(data_dir: str | Path, *, truncate: bool = False, skip_stats: bool = False) -> None:
    """Execute the full discovery data loading pipeline.

    Notes:
      * iBGCs and natural products are NOT created here — both are
        post-load steps that run via ``build_integrated_bgcs`` and
        ``load_natural_products`` respectively. ``compute_assembly_scores``
        and ``compute_catalog_counts`` therefore expect to be run again
        after those steps; the call inside this function gives ingest-time
        counts of zero iBGCs, which is fine if you chain the steps via the
        operator runbook.
    """
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Data directory not found: {data_dir}")

    if truncate:
        logger.info("Truncating all discovery tables ...")
        truncate_tables(ALL_DISCOVERY_TABLES)

    detector_lookup = load_detectors(data_dir)
    assembly_lookup = load_assemblies(data_dir)
    contig_lookup = load_contigs(data_dir, assembly_lookup)
    load_contig_sequences(data_dir, contig_lookup)

    # Source predictions + cBGC envelopes (with stable accessions).
    load_source_bgcs(data_dir, contig_lookup, detector_lookup, assembly_lookup)

    # CDS / domains / chemont — contig-anchored, deduped at insert.
    cds_lookup = load_cds(data_dir, contig_lookup)
    load_cds_sequences(data_dir, contig_lookup, cds_lookup)
    load_domains(data_dir, contig_lookup, cds_lookup)
    load_cds_chemont(data_dir, contig_lookup, cds_lookup)

    if not skip_stats:
        compute_assembly_scores()
        compute_catalog_counts()

    logger.info(
        "Loader complete. Next steps (operator):\n"
        "  python manage.py build_integrated_bgcs\n"
        "  python manage.py load_natural_products --data-dir %s",
        data_dir,
    )
