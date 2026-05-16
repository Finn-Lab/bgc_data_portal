"""Safety + schema validation for uploaded asset tarballs.

Two-stage validation. ``inspect_tarball`` runs cheaply over the upload's
bytes before parsing: gzip magic, member count + size caps, no symlinks /
device files / absolute or traversal paths, only allow-listed basenames,
required files present. ``check_tsv_headers`` then verifies the required
column subset for each TSV without reading row bodies.

Returning a structured ``ValidatedTarball`` keeps the upload endpoint
small — it inspects, then hands the validated payload to ``parse.py``.
"""

from __future__ import annotations

import gzip
import io
import logging
import tarfile
from dataclasses import dataclass

from .schemas import (
    ALLOWED_FILES,
    MAX_FILE_BYTES,
    MAX_TARBALL_BYTES,
    MAX_TARBALL_ENTRIES,
    REQUIRED_COLUMNS,
    REQUIRED_FILES,
)

log = logging.getLogger(__name__)

GZIP_MAGIC = b"\x1f\x8b"


class AssetValidationError(ValueError):
    """Raised when an upload fails any validation gate."""


@dataclass
class ValidatedTarball:
    """Outcome of ``inspect_tarball``: bytes per file, ready for parsing.

    Keys are basenames (e.g. ``"bgcs.tsv"``). Values are the raw bytes of
    each member, decompressed from the tarball. Total memory footprint is
    bounded by ``MAX_TARBALL_BYTES``.
    """

    members: dict[str, bytes]
    decompressed_bytes: int


def inspect_tarball(raw: bytes) -> ValidatedTarball:
    """Validate a ``tar.gz`` byte blob and return the extracted member bytes.

    Raises ``AssetValidationError`` on any safety or schema failure.
    """
    if len(raw) == 0:
        raise AssetValidationError("Empty upload")

    if not raw.startswith(GZIP_MAGIC):
        raise AssetValidationError(
            "Not a valid gzip stream — expected .tar.gz / .tgz upload"
        )

    try:
        gz = gzip.GzipFile(fileobj=io.BytesIO(raw))
        tf = tarfile.open(fileobj=gz, mode="r:")
    except (OSError, EOFError, tarfile.TarError) as exc:
        raise AssetValidationError(f"Could not open tarball: {exc}") from exc

    members: dict[str, bytes] = {}
    total = 0
    entries = 0

    try:
        try:
            iterator = iter(tf)
        except (OSError, EOFError, tarfile.TarError) as exc:
            raise AssetValidationError(f"Corrupt tarball: {exc}") from exc

        while True:
            try:
                member = next(iterator)
            except StopIteration:
                break
            except (OSError, EOFError, tarfile.TarError) as exc:
                raise AssetValidationError(f"Corrupt tarball: {exc}") from exc
            entries += 1
            if entries > MAX_TARBALL_ENTRIES:
                raise AssetValidationError(
                    f"Tarball has more than {MAX_TARBALL_ENTRIES} entries"
                )

            if not member.isfile():
                raise AssetValidationError(
                    f"Unsupported member type for {member.name!r} — only regular files are allowed"
                )

            name = member.name
            if name.startswith(("/", "./")) or ".." in name.split("/") or "\\" in name:
                raise AssetValidationError(
                    f"Refusing unsafe member path: {name!r}"
                )
            # Allow ``./bgcs.tsv`` etc. but only after stripping any leading dot-slash.
            basename = name.lstrip("./")
            if "/" in basename:
                raise AssetValidationError(
                    f"Members must sit at the tarball root; got nested path {name!r}"
                )

            if basename not in ALLOWED_FILES:
                # Bundles produced by upstream pipelines (e.g. ESM embedding
                # exports) sometimes carry extra TSVs we don't consume here.
                # Skip them — safety gates above (path-traversal, symlink,
                # nested-path, entry/size caps) have already rejected
                # anything dangerous, and the parser only reads allow-listed
                # basenames so the extra bytes never get interpreted.
                log.debug("inspect_tarball: skipping unexpected member %r", basename)
                continue

            if member.size > MAX_FILE_BYTES:
                raise AssetValidationError(
                    f"{basename}: {member.size} bytes exceeds per-file cap of {MAX_FILE_BYTES}"
                )

            total += member.size
            if total > MAX_TARBALL_BYTES:
                raise AssetValidationError(
                    f"Decompressed size exceeds {MAX_TARBALL_BYTES} bytes"
                )

            try:
                fp = tf.extractfile(member)
                if fp is None:
                    raise AssetValidationError(f"Could not read {basename!r}")
                data = fp.read()
            except (OSError, EOFError, tarfile.TarError) as exc:
                raise AssetValidationError(
                    f"Corrupt tarball while reading {basename!r}: {exc}"
                ) from exc
            if len(data) != member.size:
                raise AssetValidationError(
                    f"{basename}: declared size {member.size} but read {len(data)} bytes"
                )
            members[basename] = data
    finally:
        tf.close()
        gz.close()

    missing = [f for f in REQUIRED_FILES if f not in members]
    if missing:
        raise AssetValidationError(
            f"Upload missing required files: {', '.join(missing)}"
        )

    check_tsv_headers(members)

    return ValidatedTarball(members=members, decompressed_bytes=total)


def check_tsv_headers(members: dict[str, bytes]) -> None:
    """Verify each TSV's header contains the required column subset.

    Extra columns are allowed (TSVs evolve), but every required column must
    be present. Empty / header-only files are accepted — row caps and shape
    checks live in the parser.
    """
    for basename, required in REQUIRED_COLUMNS.items():
        raw = members.get(basename)
        if raw is None:
            continue
        first_line = raw.split(b"\n", 1)[0].decode("utf-8", errors="replace")
        header = [c.strip() for c in first_line.split("\t")]
        missing = [c for c in required if c not in header]
        if missing:
            raise AssetValidationError(
                f"{basename}: missing required column(s) {', '.join(missing)}"
            )
