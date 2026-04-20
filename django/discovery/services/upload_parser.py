"""Parse uploaded .tar.gz / .tgz bundles for ephemeral asset evaluation.

Extracts TSV files from a .tar.gz / .tgz archive, validates structure and
content, and returns in-memory dataclasses — no ORM objects, no DB
writes.  The parsed data is intended to be cached in Redis and fed
to the uploaded-assessment service.
"""

from __future__ import annotations

import base64
import csv
import io
import logging
import struct
import tarfile
from dataclasses import dataclass, field, asdict

from django.conf import settings

from discovery.models import EMBEDDING_DIM

log = logging.getLogger(__name__)

MAX_TAR_SIZE = 20 * 1024 * 1024  # 20 MB


class UploadValidationError(Exception):
    """Raised when the uploaded archive fails validation."""


# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass
class UploadedDomain:
    domain_acc: str
    domain_name: str = ""
    domain_description: str = ""
    ref_db: str = ""
    start_position: int = 0
    end_position: int = 0
    score: float | None = None


@dataclass
class UploadedBgc:
    index: int
    contig_sha256: str
    detector_name: str
    start_position: int
    end_position: int
    classification_path: str = ""
    gene_cluster_family: str = ""
    size_kb: float = 0.0
    is_partial: bool = False
    is_validated: bool = False
    domains: list[dict] = field(default_factory=list)
    embedding: list[float] = field(default_factory=list)


@dataclass
class UploadedContig:
    sequence_sha256: str
    accession: str = ""
    length: int = 0
    taxonomy_path: str = ""


@dataclass
class UploadedAssembly:
    accession: str
    organism_name: str = ""
    assembly_size_mb: float | None = None
    biome_path: str = ""
    is_type_strain: bool = False
    bgcs: list[UploadedBgc] = field(default_factory=list)
    contigs: list[UploadedContig] = field(default_factory=list)


# ── Public API ────────────────────────────────────────────────────────────────


def parse_bgc_upload(tar_bytes: bytes) -> dict:
    """Parse a single-BGC .tar.gz / .tgz upload and return a serialisable dict.

    Required files: bgcs.tsv (1 row), domains.tsv, embeddings_bgc.tsv
    Optional files: contigs.tsv, detectors.tsv, cds.tsv, natural_products.tsv
    """
    members = _extract_tar(tar_bytes)

    _require_files(members, ["bgcs.tsv", "domains.tsv", "embeddings_bgc.tsv"])

    bgc_rows = _read_tsv(members["bgcs.tsv"])
    if len(bgc_rows) != 1:
        raise UploadValidationError(
            f"bgcs.tsv must contain exactly 1 row for single-BGC upload, got {len(bgc_rows)}"
        )

    domain_rows = _read_tsv(members["domains.tsv"])
    embedding_rows = _read_tsv(members["embeddings_bgc.tsv"])

    bgc = _parse_bgc_row(bgc_rows[0], index=0)

    # Attach domains
    bgc_key = _bgc_key(bgc)
    bgc.domains = [
        asdict(d)
        for d in _parse_domain_rows(domain_rows, {bgc_key: 0})
        if True  # all domains belong to the single BGC
    ]

    # Attach embedding
    _attach_embeddings([bgc], embedding_rows)

    return asdict(bgc)


def parse_assembly_upload(tar_bytes: bytes) -> dict:
    """Parse an assembly-bundle .tar.gz / .tgz upload and return a serialisable dict.

    Required files: assemblies.tsv (1 row), contigs.tsv, bgcs.tsv (N rows),
                    domains.tsv, embeddings_bgc.tsv
    Optional files: detectors.tsv, cds.tsv, natural_products.tsv
    """
    members = _extract_tar(tar_bytes)

    _require_files(
        members,
        ["assemblies.tsv", "contigs.tsv", "bgcs.tsv", "domains.tsv", "embeddings_bgc.tsv"],
    )

    # Parse assembly
    assembly_rows = _read_tsv(members["assemblies.tsv"])
    if len(assembly_rows) != 1:
        raise UploadValidationError(
            f"assemblies.tsv must contain exactly 1 row, got {len(assembly_rows)}"
        )
    assembly = _parse_assembly_row(assembly_rows[0])

    # Parse contigs
    contig_rows = _read_tsv(members["contigs.tsv"])
    if not contig_rows:
        raise UploadValidationError("contigs.tsv must contain at least 1 row")
    assembly.contigs = [_parse_contig_row(r) for r in contig_rows]
    contig_sha256s = {c.sequence_sha256 for c in assembly.contigs}

    # Parse BGCs
    bgc_rows = _read_tsv(members["bgcs.tsv"])
    if not bgc_rows:
        raise UploadValidationError("bgcs.tsv must contain at least 1 row")

    bgcs: list[UploadedBgc] = []
    bgc_key_map: dict[tuple, int] = {}
    for i, row in enumerate(bgc_rows):
        bgc = _parse_bgc_row(row, index=i)
        if bgc.contig_sha256 not in contig_sha256s:
            raise UploadValidationError(
                f"BGC row {i} references contig_sha256={bgc.contig_sha256!r} "
                f"not found in contigs.tsv"
            )
        bgc_key_map[_bgc_key(bgc)] = i
        bgcs.append(bgc)

    # Parse and attach domains
    domain_rows = _read_tsv(members["domains.tsv"])
    parsed_domains = _parse_domain_rows(domain_rows, bgc_key_map)
    # Group domains by BGC index
    domain_groups: dict[int, list[dict]] = {}
    for row, dom in zip(domain_rows, parsed_domains):
        key = _domain_bgc_key(row)
        bgc_idx = bgc_key_map.get(key)
        if bgc_idx is not None:
            domain_groups.setdefault(bgc_idx, []).append(asdict(dom))
    for bgc in bgcs:
        bgc.domains = domain_groups.get(bgc.index, [])

    # Attach embeddings
    embedding_rows = _read_tsv(members["embeddings_bgc.tsv"])
    _attach_embeddings(bgcs, embedding_rows)

    assembly.bgcs = bgcs

    result = asdict(assembly)
    # Convert contigs from dataclass list to plain dicts
    result["contigs"] = [asdict(c) for c in assembly.contigs]
    return result


# ── Private helpers ───────────────────────────────────────────────────────────


def _extract_tar(tar_bytes: bytes) -> dict[str, bytes]:
    """Extract a .tar.gz / .tgz into a dict of {filename: file_bytes}.

    Validates gzip magic bytes and enforces size limit.
    """
    if len(tar_bytes) > MAX_TAR_SIZE:
        raise UploadValidationError(
            f"Archive too large ({len(tar_bytes)} bytes, max {MAX_TAR_SIZE})"
        )
    if len(tar_bytes) < 2 or tar_bytes[:2] != b"\x1f\x8b":
        raise UploadValidationError("File is not a valid .tar.gz / .tgz archive")

    members: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                # Strip directory prefix — use only the basename
                name = member.name.rsplit("/", 1)[-1]
                if not name.endswith(".tsv"):
                    continue
                f = tf.extractfile(member)
                if f is not None:
                    members[name] = f.read()
    except tarfile.TarError as e:
        raise UploadValidationError(f"Invalid tar archive: {e}") from e

    return members


def _require_files(members: dict[str, bytes], required: list[str]) -> None:
    missing = [f for f in required if f not in members]
    if missing:
        raise UploadValidationError(f"Missing required files: {', '.join(missing)}")


def _read_tsv(data: bytes) -> list[dict[str, str]]:
    text = data.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    return list(reader)


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in ("true", "1")


def _parse_float(value: str, default: float = 0.0) -> float:
    if not value or not value.strip():
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _parse_int(value: str, default: int = 0) -> int:
    if not value or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _decode_embedding(vector_base64: str) -> list[float]:
    """Decode a base64-encoded float32 vector and validate dimension."""
    raw = base64.b64decode(vector_base64)
    n_floats = len(raw) // 4
    if n_floats != EMBEDDING_DIM:
        raise UploadValidationError(
            f"Embedding dimension must be {EMBEDDING_DIM}, got {n_floats}"
        )
    return list(struct.unpack(f"<{n_floats}f", raw))


def _bgc_key(bgc: UploadedBgc) -> tuple:
    # detector_name is lowercased here because the ETL emits it lowercased in
    # embeddings_bgc.tsv (bgc_embedding_aggregator.py) while bgcs.tsv keeps the
    # original case from the detector tool — we need both keys to line up.
    return (bgc.contig_sha256, bgc.start_position, bgc.end_position, bgc.detector_name.lower())


def _domain_bgc_key(row: dict[str, str]) -> tuple:
    return (
        row["contig_sha256"],
        int(row["bgc_start"]),
        int(row["bgc_end"]),
        row["detector_name"],
    )


def _embedding_bgc_key(row: dict[str, str]) -> tuple:
    return (
        row["contig_sha256"],
        int(row.get("bgc_start", row.get("start_position", "0"))),
        int(row.get("bgc_end", row.get("end_position", "0"))),
        row["detector_name"].lower(),
    )


def _parse_bgc_row(row: dict[str, str], index: int) -> UploadedBgc:
    for col in ("contig_sha256", "detector_name", "start_position", "end_position"):
        if col not in row or not row[col].strip():
            raise UploadValidationError(f"bgcs.tsv: missing required column '{col}'")
    return UploadedBgc(
        index=index,
        contig_sha256=row["contig_sha256"].strip(),
        detector_name=row["detector_name"].strip(),
        start_position=int(row["start_position"]),
        end_position=int(row["end_position"]),
        classification_path=row.get("classification_path", ""),
        gene_cluster_family=row.get("gene_cluster_family", ""),
        size_kb=_parse_float(row.get("size_kb", "")),
        is_partial=_parse_bool(row.get("is_partial", "")),
        is_validated=_parse_bool(row.get("is_validated", "")),
    )


def _parse_assembly_row(row: dict[str, str]) -> UploadedAssembly:
    if "assembly_accession" not in row or not row["assembly_accession"].strip():
        raise UploadValidationError("assemblies.tsv: missing required column 'assembly_accession'")
    size = row.get("assembly_size_mb", "")
    return UploadedAssembly(
        accession=row["assembly_accession"].strip(),
        organism_name=row.get("organism_name", ""),
        assembly_size_mb=float(size) if size and size.strip() else None,
        biome_path=row.get("biome_path", ""),
        is_type_strain=_parse_bool(row.get("is_type_strain", "")),
    )


def _parse_contig_row(row: dict[str, str]) -> UploadedContig:
    if "sequence_sha256" not in row or not row["sequence_sha256"].strip():
        raise UploadValidationError("contigs.tsv: missing required column 'sequence_sha256'")
    return UploadedContig(
        sequence_sha256=row["sequence_sha256"].strip(),
        accession=row.get("accession", ""),
        length=_parse_int(row.get("length", "")),
        taxonomy_path=row.get("taxonomy_path", ""),
    )


def _parse_domain_rows(
    rows: list[dict[str, str]], bgc_key_map: dict[tuple, int]
) -> list[UploadedDomain]:
    """Parse domain rows, validating each row and filtering by the ref_db allowlist.

    Rows are skipped (not fatal) when any of the following is true:
      - ``domain_acc`` is missing or empty
      - the BGC coordinates reference a BGC that is not in ``bgc_key_map``
      - ``ref_db`` is outside ``settings.ALLOWED_DOMAIN_REF_DBS`` (PFAM/TIGRFAM)
      - ``start_position`` / ``end_position`` are missing, unparsable, or form
        an empty range — they participate in the ``BgcDomain`` unique constraint
        ``(bgc, domain_acc, cds, start_position, end_position)`` so an empty
        value collapses unrelated rows together.

    Drop counts per reason are logged at INFO once the pass finishes.
    """
    allowed = {v.upper() for v in getattr(settings, "ALLOWED_DOMAIN_REF_DBS", ())}
    dropped: dict[str, int] = {}

    domains: list[UploadedDomain] = []
    for row in rows:
        domain_acc = (row.get("domain_acc") or "").strip()
        if not domain_acc:
            dropped["missing_domain_acc"] = dropped.get("missing_domain_acc", 0) + 1
            continue

        try:
            key = _domain_bgc_key(row)
        except (KeyError, ValueError):
            dropped["bad_bgc_key"] = dropped.get("bad_bgc_key", 0) + 1
            continue
        if key not in bgc_key_map:
            dropped["unknown_bgc"] = dropped.get("unknown_bgc", 0) + 1
            continue

        if allowed:
            ref_db_value = (row.get("ref_db") or "").strip().upper()
            if ref_db_value not in allowed:
                dropped["ref_db_not_allowed"] = dropped.get("ref_db_not_allowed", 0) + 1
                continue

        start_raw = (row.get("start_position") or "").strip()
        end_raw = (row.get("end_position") or "").strip()
        if not start_raw or not end_raw:
            dropped["missing_position"] = dropped.get("missing_position", 0) + 1
            continue
        start_pos = _parse_int(start_raw, default=-1)
        end_pos = _parse_int(end_raw, default=-1)
        if start_pos < 0 or end_pos < 0 or end_pos <= start_pos:
            dropped["bad_position"] = dropped.get("bad_position", 0) + 1
            continue

        score_str = row.get("score", "")
        domains.append(
            UploadedDomain(
                domain_acc=domain_acc,
                domain_name=row.get("domain_name", ""),
                domain_description=row.get("domain_description", ""),
                ref_db=row.get("ref_db", ""),
                start_position=start_pos,
                end_position=end_pos,
                score=float(score_str) if score_str and score_str.strip() else None,
            )
        )

    if dropped:
        log.info(
            "asset-upload domain filter: kept=%d dropped=%d by reason: %s",
            len(domains),
            sum(dropped.values()),
            dict(sorted(dropped.items())),
        )
    return domains


def _attach_embeddings(bgcs: list[UploadedBgc], embedding_rows: list[dict[str, str]]) -> None:
    """Match embedding rows to BGCs by composite key, validate all BGCs have embeddings."""
    bgc_key_to_idx = {_bgc_key(bgc): bgc.index for bgc in bgcs}

    matched = set()
    for row in embedding_rows:
        key = _embedding_bgc_key(row)
        idx = bgc_key_to_idx.get(key)
        if idx is None:
            continue
        if "vector_base64" not in row or not row["vector_base64"].strip():
            raise UploadValidationError(
                f"embeddings_bgc.tsv: missing vector_base64 for BGC {key}"
            )
        bgcs[idx].embedding = _decode_embedding(row["vector_base64"])
        matched.add(idx)

    missing = set(range(len(bgcs))) - matched
    if missing:
        missing_keys = [_bgc_key(bgcs[i]) for i in sorted(missing)]
        raise UploadValidationError(
            f"Missing embeddings for {len(missing)} BGC(s): {missing_keys}"
        )
