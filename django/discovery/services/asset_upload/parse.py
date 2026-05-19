"""Parse validated asset tarball bytes into in-memory ``AssetData``.

Mirrors the column conventions of ``services/ingestion/loader.py`` so the
same TSV layout that the persistent loader accepts works here unchanged.
This module never writes to disk or to the ORM.
"""

from __future__ import annotations

import csv
import io
import logging
import sys

# ``contig_sequences.tsv`` carries base64-encoded contig sequences that
# routinely exceed Python's default 128 KB csv field cap. Lift the limit to
# the platform max — the upload byte cap and ``MAX_FILE_BYTES`` already
# bound the actual size we'll see.
csv.field_size_limit(sys.maxsize)

from .schemas import (
    MAX_BGC_ROWS,
    MAX_CDS_ROWS,
    MAX_DOMAIN_ROWS,
    AssetAssembly,
    AssetBgc,
    AssetCds,
    AssetContig,
    AssetData,
    AssetDetector,
    AssetDomain,
    AssetCdsChemOnt,
    AssetNaturalProduct,
)
from .validate import AssetValidationError, ValidatedTarball

log = logging.getLogger(__name__)


def _reader(buf: bytes):
    """Wrap raw bytes in a ``csv.DictReader`` over TSV format."""
    return csv.DictReader(io.StringIO(buf.decode("utf-8", errors="replace")), delimiter="\t")


def _to_bool(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in ("true", "1", "yes", "t")


def _to_int(value: str | None, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError) as exc:
        raise AssetValidationError(f"Expected integer, got {value!r}") from exc


def _to_float(value: str | None, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise AssetValidationError(f"Expected number, got {value!r}") from exc


def _to_optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise AssetValidationError(f"Expected number, got {value!r}") from exc


def parse_asset_tar(validated: ValidatedTarball) -> AssetData:
    """Materialise an ``AssetData`` from a previously-validated tarball."""
    members = validated.members
    data = AssetData()

    # ── detectors ────────────────────────────────────────────────────────
    for row in _reader(members["detectors.tsv"]):
        data.detectors.append(
            AssetDetector(
                name=row["name"],
                tool=row.get("tool", ""),
                version=row.get("version", ""),
            )
        )

    # ── assemblies ───────────────────────────────────────────────────────
    for row in _reader(members["assemblies.tsv"]):
        data.assemblies.append(
            AssetAssembly(
                assembly_accession=row["assembly_accession"],
                organism_name=row.get("organism_name", ""),
                source=row.get("source", ""),
                assembly_type=_to_int(row.get("assembly_type"), default=2),
                biome_path=row.get("biome_path", ""),
                is_type_strain=_to_bool(row.get("is_type_strain")),
                type_strain_catalog_url=row.get("type_strain_catalog_url", ""),
                assembly_size_mb=_to_optional_float(row.get("assembly_size_mb")),
                url=row.get("url", ""),
            )
        )
    if not data.assemblies:
        raise AssetValidationError("assemblies.tsv has no data rows")

    # ── contigs ──────────────────────────────────────────────────────────
    asm_accessions = {a.assembly_accession for a in data.assemblies}
    for row in _reader(members["contigs.tsv"]):
        assembly_acc = row["assembly_accession"]
        if assembly_acc not in asm_accessions:
            raise AssetValidationError(
                f"contigs.tsv references unknown assembly {assembly_acc!r}"
            )
        src_id = row.get("source_contig_id") or ""
        data.contigs.append(
            AssetContig(
                assembly_accession=assembly_acc,
                sequence_sha256=row["sequence_sha256"],
                accession=row.get("accession", ""),
                length=_to_int(row.get("length")),
                taxonomy_path=row.get("taxonomy_path", ""),
                source_contig_id=int(src_id) if src_id else None,
            )
        )
    if not data.contigs:
        raise AssetValidationError("contigs.tsv has no data rows")

    # ── contig_sequences (optional) ──────────────────────────────────────
    if "contig_sequences.tsv" in members:
        for row in _reader(members["contig_sequences.tsv"]):
            data.contig_sequences[row["contig_sha256"]] = row.get("sequence_base64", "")

    # ── bgcs ─────────────────────────────────────────────────────────────
    contig_shas = {c.sequence_sha256 for c in data.contigs}
    detector_names = {d.name for d in data.detectors}
    seen_bgc_keys: set[tuple[str, int, int, str]] = set()

    for row in _reader(members["bgcs.tsv"]):
        contig_sha = row["contig_sha256"]
        detector_name = row["detector_name"]
        if contig_sha not in contig_shas:
            raise AssetValidationError(
                f"bgcs.tsv references unknown contig sha {contig_sha!r}"
            )
        if detector_name not in detector_names:
            raise AssetValidationError(
                f"bgcs.tsv references unknown detector {detector_name!r}"
            )
        start = _to_int(row["start_position"])
        end = _to_int(row["end_position"])
        if start < 0 or end <= start:
            raise AssetValidationError(
                f"bgcs.tsv invalid interval start={start} end={end} on {contig_sha}"
            )
        key = (contig_sha, start, end, detector_name)
        if key in seen_bgc_keys:
            # Duplicate BGC row — silently drop, matches the persistent path's
            # update_conflicts behaviour.
            continue
        seen_bgc_keys.add(key)
        size_kb = _to_optional_float(row.get("size_kb"))
        if size_kb is None:
            size_kb = (end - start) / 1000.0
        data.bgcs.append(
            AssetBgc(
                contig_sha256=contig_sha,
                detector_name=detector_name,
                start_position=start,
                end_position=end,
                classification_path=row.get("classification_path", ""),
                size_kb=size_kb,
                is_partial=_to_bool(row.get("is_partial")),
                is_validated=_to_bool(row.get("is_validated")),
            )
        )
        if len(data.bgcs) > MAX_BGC_ROWS:
            raise AssetValidationError(
                f"bgcs.tsv has more than {MAX_BGC_ROWS} rows"
            )
    if not data.bgcs:
        raise AssetValidationError("bgcs.tsv has no data rows")

    bgc_keys = {b.key for b in data.bgcs}

    # ── cds (optional) ───────────────────────────────────────────────────
    if "cds.tsv" in members:
        for row in _reader(members["cds.tsv"]):
            key = (
                row["contig_sha256"],
                _to_int(row["bgc_start"]),
                _to_int(row["bgc_end"]),
                row["detector_name"],
            )
            if key not in bgc_keys:
                continue
            data.cds.append(
                AssetCds(
                    bgc_key=key,
                    protein_id_str=row["protein_id_str"],
                    start_position=_to_int(row["start_position"]),
                    end_position=_to_int(row["end_position"]),
                    strand=_to_int(row.get("strand"), default=1),
                    protein_length=_to_int(row.get("protein_length")),
                    gene_caller=row.get("gene_caller", ""),
                    cluster_representative=row.get("cluster_representative", ""),
                    protein_sha256=row.get("protein_sha256", ""),
                )
            )
            if len(data.cds) > MAX_CDS_ROWS:
                raise AssetValidationError(
                    f"cds.tsv has more than {MAX_CDS_ROWS} rows"
                )

    # ── cds_sequences (optional) — merged into matching AssetCds rows ───
    if "cds_sequences.tsv" in members and data.cds:
        cds_lookup: dict[tuple[tuple[str, int, int, str], str], AssetCds] = {
            (c.bgc_key, c.protein_id_str): c for c in data.cds
        }
        for row in _reader(members["cds_sequences.tsv"]):
            key = (
                row["contig_sha256"],
                _to_int(row["bgc_start"]),
                _to_int(row["bgc_end"]),
                row["detector_name"],
            )
            protein_id = row["protein_id_str"]
            cds = cds_lookup.get((key, protein_id))
            if cds is None:
                continue
            cds.sequence_zlib_b64 = row.get("sequence_base64", "")

    # ── domains (optional) ───────────────────────────────────────────────
    if "domains.tsv" in members:
        for row in _reader(members["domains.tsv"]):
            key = (
                row["contig_sha256"],
                _to_int(row["bgc_start"]),
                _to_int(row["bgc_end"]),
                row["detector_name"],
            )
            if key not in bgc_keys:
                continue
            data.domains.append(
                AssetDomain(
                    bgc_key=key,
                    cds_protein_id=row["protein_id_str"],
                    domain_acc=row.get("domain_acc", ""),
                    domain_name=row.get("domain_name", ""),
                    domain_description=row.get("domain_description", ""),
                    ref_db=row.get("ref_db", ""),
                    start_position=_to_int(row.get("start_position")),
                    end_position=_to_int(row.get("end_position")),
                    score=_to_optional_float(row.get("score")),
                    url=row.get("url", ""),
                )
            )
            if len(data.domains) > MAX_DOMAIN_ROWS:
                raise AssetValidationError(
                    f"domains.tsv has more than {MAX_DOMAIN_ROWS} rows"
                )

    # ── natural products (optional) ─────────────────────────────────────
    if "natural_products.tsv" in members:
        for row in _reader(members["natural_products.tsv"]):
            key = (
                row["contig_sha256"],
                _to_int(row["bgc_start"]),
                _to_int(row["bgc_end"]),
                row["detector_name"],
            )
            if key not in bgc_keys:
                continue
            data.natural_products.append(
                AssetNaturalProduct(
                    bgc_key=key,
                    name=row.get("name", ""),
                    smiles=row.get("smiles", ""),
                    np_class_path=row.get("np_class_path", ""),
                    structure_svg_base64=row.get("structure_svg_base64", ""),
                    morgan_fp_b64=row.get("morgan_fp_base64", ""),
                )
            )

    # ── Per-CDS ChemOnt classifications (optional) ──────────────────────
    if "cds_chemont.tsv" in members:
        for row in _reader(members["cds_chemont.tsv"]):
            key = (
                row["contig_sha256"],
                _to_int(row["bgc_start"]),
                _to_int(row["bgc_end"]),
                row["detector_name"],
            )
            if key not in bgc_keys:
                continue
            data.cds_chemont.append(
                AssetCdsChemOnt(
                    bgc_key=key,
                    protein_id_str=row.get("protein_id_str", ""),
                    chemont_id=row.get("chemont_id", ""),
                    chemont_name=row.get("chemont_name", ""),
                    probability=_to_float(row.get("probability"), default=0.0),
                    weight=_to_float(row.get("weight"), default=0.0),
                )
            )

    log.info(
        "parse_asset_tar: %d assemblies, %d contigs, %d bgcs, %d cds, %d domains, %d nps",
        len(data.assemblies),
        len(data.contigs),
        len(data.bgcs),
        len(data.cds),
        len(data.domains),
        len(data.natural_products),
    )
    return data
