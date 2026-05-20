"""Build / update the on-disk phmmer protein DB.

Layout (all under ``settings.PROTEIN_SEARCH_INDEX_DIR``)::

    proteins.faa        FASTA, one record per unique protein_sha256
    VERSION             monotonic integer, bumped after each successful write

Workers stat ``VERSION`` and reload their in-memory block when it changes.
The FASTA is read sequentially into a ``DigitalSequenceBlock`` at load time;
no random-access index is required.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional

from django.conf import settings
from django.db import connection

from pyhmmer.easel import TextSequence

log = logging.getLogger(__name__)

FASTA_NAME = "proteins.faa"
VERSION_NAME = "VERSION"

# How many proteins to stream from Postgres per chunk while building/appending.
_DB_FETCH_CHUNK = 50_000

# How many FASTA records to write per flush.
_WRITE_FLUSH_EVERY = 10_000


@dataclass(frozen=True)
class IndexPaths:
    """Resolved paths for the on-disk index artifacts."""

    base_dir: Path
    fasta: Path
    version: Path


def index_paths(base_dir: Optional[str | os.PathLike] = None) -> IndexPaths:
    """Resolve and return the canonical paths for the on-disk index."""
    base = Path(base_dir) if base_dir is not None else Path(settings.PROTEIN_SEARCH_INDEX_DIR)
    return IndexPaths(
        base_dir=base,
        fasta=base / FASTA_NAME,
        version=base / VERSION_NAME,
    )


@dataclass
class IndexStats:
    """Summary returned by build/update operations (logged & enqueued in Celery results)."""

    total_in_db: int
    already_indexed: int
    newly_added: int
    elapsed_seconds: float
    version: int


# ── Reading existing sha256 set ─────────────────────────────────────────────────


def _read_indexed_sha256s(fasta_path: Path) -> set[str]:
    """Return the set of sha256 IDs already written to the FASTA.

    Empty set when the file does not exist yet. Streamed read — does not load
    the sequences, only the ``>`` header lines.
    """
    if not fasta_path.exists():
        return set()
    out: set[str] = set()
    with fasta_path.open("r") as fh:
        for line in fh:
            if line.startswith(">"):
                # Header is ">sha256" (no description after).
                out.add(line[1:].split(None, 1)[0].strip())
    return out


# ── Streaming unique proteins from the DB ───────────────────────────────────────


def iter_unique_proteins(exclude: Optional[set[str]] = None) -> Iterator[tuple[str, str]]:
    """Yield ``(sha256, aa_seq)`` for every unique protein in ContigCds.

    Joins ``discovery_cds`` with ``discovery_cds_sequence`` (zlib-compressed AA)
    and de-duplicates by ``protein_sha256``. Optional ``exclude`` filters out
    sha256s already in the index.

    Streamed via a server-side cursor — safe for tens of millions of rows.
    """
    import zlib

    exclude_set = exclude or set()
    sql = """
        SELECT DISTINCT ON (cds.protein_sha256)
               cds.protein_sha256, seq.data
        FROM discovery_cds AS cds
        JOIN discovery_cds_sequence AS seq ON seq.cds_id = cds.id
        WHERE cds.protein_sha256 IS NOT NULL
          AND cds.protein_sha256 <> ''
        ORDER BY cds.protein_sha256, cds.id
    """

    with connection.cursor() as cursor:
        cursor.execute(sql)
        while True:
            rows = cursor.fetchmany(_DB_FETCH_CHUNK)
            if not rows:
                return
            for sha256, blob in rows:
                if sha256 in exclude_set:
                    continue
                if not blob:
                    continue
                try:
                    aa = zlib.decompress(bytes(blob)).decode("utf-8")
                except (zlib.error, UnicodeDecodeError):
                    log.warning("Skipping unreadable sequence for sha256=%s", sha256)
                    continue
                aa = aa.strip()
                if not aa:
                    continue
                yield sha256, aa


# ── FASTA write helpers ─────────────────────────────────────────────────────────


def _append_records(fasta_path: Path, records: Iterable[tuple[str, str]]) -> int:
    """Append ``(sha256, seq)`` records to ``fasta_path``. Returns count written."""
    n = 0
    fasta_path.parent.mkdir(parents=True, exist_ok=True)
    with fasta_path.open("a") as fh:
        buf: list[str] = []
        for sha256, seq in records:
            buf.append(f">{sha256}\n{seq}\n")
            n += 1
            if len(buf) >= _WRITE_FLUSH_EVERY:
                fh.write("".join(buf))
                buf.clear()
        if buf:
            fh.write("".join(buf))
    return n


# ── Version stamp ───────────────────────────────────────────────────────────────


def read_version(paths: IndexPaths) -> int:
    """Return current version stamp (0 if missing/unreadable)."""
    try:
        return int(paths.version.read_text().strip())
    except (FileNotFoundError, ValueError):
        return 0


def bump_version(paths: IndexPaths) -> int:
    """Write a new version stamp = current+1 and return it."""
    next_v = read_version(paths) + 1
    paths.base_dir.mkdir(parents=True, exist_ok=True)
    tmp = paths.version.with_suffix(paths.version.suffix + ".tmp")
    tmp.write_text(f"{next_v}\n")
    os.replace(tmp, paths.version)
    return next_v


# ── Public build / update operations ────────────────────────────────────────────


def rebuild_index(base_dir: Optional[str | os.PathLike] = None) -> IndexStats:
    """Full rebuild: write a fresh FASTA from the DB, regenerate SSI, bump version.

    Writes to a tempfile in the index dir and atomically swaps to avoid leaving
    a half-written FASTA in place if the process dies mid-build.
    """
    paths = index_paths(base_dir)
    paths.base_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    fd, tmp_path_str = tempfile.mkstemp(prefix="proteins.", suffix=".faa.tmp", dir=str(paths.base_dir))
    os.close(fd)
    tmp_path = Path(tmp_path_str)

    written = 0
    try:
        written = _append_records(tmp_path, iter_unique_proteins(exclude=None))
        # Atomically swap the FASTA into place.
        os.replace(tmp_path, paths.fasta)
        log.info("Wrote %d proteins to %s", written, paths.fasta)
        version = bump_version(paths)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    elapsed = time.perf_counter() - t0
    stats = IndexStats(
        total_in_db=written,
        already_indexed=0,
        newly_added=written,
        elapsed_seconds=elapsed,
        version=version,
    )
    log.info(
        "protein_search rebuild done: wrote=%d elapsed=%.1fs version=%d",
        written, elapsed, version,
    )
    return stats


def update_index(base_dir: Optional[str | os.PathLike] = None) -> IndexStats:
    """Append-only update: stream new proteins (not in FASTA), append, rebuild SSI.

    If the FASTA doesn't exist yet, this delegates to :func:`rebuild_index`.
    """
    paths = index_paths(base_dir)
    if not paths.fasta.exists():
        return rebuild_index(base_dir)

    t0 = time.perf_counter()
    existing = _read_indexed_sha256s(paths.fasta)
    log.info("protein_search update: %d sha256s already indexed", len(existing))

    # Stage appends to a sibling tmp file, then concatenate atomically. Avoids
    # leaving the main FASTA half-extended on crash.
    fd, tmp_path_str = tempfile.mkstemp(prefix="proteins.append.", suffix=".faa", dir=str(paths.base_dir))
    os.close(fd)
    tmp_path = Path(tmp_path_str)

    newly_added = 0
    try:
        newly_added = _append_records(tmp_path, iter_unique_proteins(exclude=existing))
        if newly_added == 0:
            tmp_path.unlink()
            elapsed = time.perf_counter() - t0
            log.info("protein_search update: nothing to add (elapsed %.2fs)", elapsed)
            return IndexStats(
                total_in_db=len(existing),
                already_indexed=len(existing),
                newly_added=0,
                elapsed_seconds=elapsed,
                version=read_version(paths),
            )

        # Concatenate tmp onto the existing FASTA.
        with paths.fasta.open("ab") as dst, tmp_path.open("rb") as src:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
        tmp_path.unlink()

        log.info("protein_search update: appended %d proteins", newly_added)
        version = bump_version(paths)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    elapsed = time.perf_counter() - t0
    stats = IndexStats(
        total_in_db=len(existing) + newly_added,
        already_indexed=len(existing),
        newly_added=newly_added,
        elapsed_seconds=elapsed,
        version=version,
    )
    log.info(
        "protein_search update done: added=%d total=%d elapsed=%.1fs version=%d",
        newly_added, stats.total_in_db, elapsed, version,
    )
    return stats


def write_records(
    fasta_path: Path | str,
    records: Iterable[tuple[str, str]],
) -> int:
    """Write ``(sha256, seq)`` records to a FASTA (creates parent dirs).

    Public helper used by tests. Truncates an existing file.
    """
    fasta_path = Path(fasta_path)
    if fasta_path.exists():
        fasta_path.unlink()
    return _append_records(fasta_path, records)


# Make TextSequence importable from this module for tests / callers building
# ad-hoc blocks without importing pyhmmer themselves.
__all__ = [
    "IndexPaths",
    "IndexStats",
    "index_paths",
    "iter_unique_proteins",
    "read_version",
    "bump_version",
    "rebuild_index",
    "update_index",
    "write_records",
    "TextSequence",
]
