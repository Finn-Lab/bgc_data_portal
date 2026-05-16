"""Safety + schema validation tests for the asset-upload tarball gate."""

from __future__ import annotations

import gzip
import io
import tarfile

import pytest

from discovery.services.asset_upload.validate import (
    AssetValidationError,
    inspect_tarball,
)


def _build_tarball(members: dict[str, bytes]) -> bytes:
    """Pack a dict of basename → bytes into a gzipped tarball."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _minimal_required() -> dict[str, bytes]:
    return {
        "assemblies.tsv": b"assembly_accession\nA1\n",
        "contigs.tsv": b"assembly_accession\tsequence_sha256\nA1\tdeadbeef\n",
        "detectors.tsv": b"name\ttool\tversion\nantiSMASH:1\tantiSMASH\t1.0\n",
        "bgcs.tsv": (
            b"contig_sha256\tdetector_name\tstart_position\tend_position\n"
            b"deadbeef\tantiSMASH:1\t0\t100\n"
        ),
    }


def test_accepts_minimal_valid_tarball():
    raw = _build_tarball(_minimal_required())
    out = inspect_tarball(raw)
    assert set(out.members.keys()) >= {
        "assemblies.tsv",
        "contigs.tsv",
        "detectors.tsv",
        "bgcs.tsv",
    }
    assert out.decompressed_bytes == sum(len(v) for v in _minimal_required().values())


def test_rejects_non_gzip_input():
    with pytest.raises(AssetValidationError, match="gzip"):
        inspect_tarball(b"not a gzip stream")


def test_rejects_empty_upload():
    with pytest.raises(AssetValidationError, match="Empty"):
        inspect_tarball(b"")


def test_rejects_missing_required_file():
    members = _minimal_required()
    members.pop("bgcs.tsv")
    raw = _build_tarball(members)
    with pytest.raises(AssetValidationError, match="missing required"):
        inspect_tarball(raw)


def test_unknown_files_are_silently_skipped():
    """Unexpected basenames (e.g. ``embeddings_bgc.tsv`` from upstream
    pipelines that bundle ESM exports) are ignored — the safety gates above
    still reject anything dangerous, and the parser only reads allow-listed
    files. Validation should succeed and the extra member must not appear
    in the parsed result."""
    members = _minimal_required()
    members["embeddings_bgc.tsv"] = b"some\textra\tcolumns\n1\t2\t3\n"
    raw = _build_tarball(members)
    validated = inspect_tarball(raw)
    assert "embeddings_bgc.tsv" not in validated.members
    assert "bgcs.tsv" in validated.members


def test_rejects_nested_path():
    members = _minimal_required()
    # Repack manually so we can put bgcs.tsv into a subdirectory.
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in members.items():
            target = name if name != "bgcs.tsv" else "data/bgcs.tsv"
            info = tarfile.TarInfo(name=target)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    with pytest.raises(AssetValidationError, match="tarball root"):
        inspect_tarball(buf.getvalue())


def test_rejects_symlink_member():
    members = _minimal_required()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        sym = tarfile.TarInfo(name="evil.tsv")
        sym.type = tarfile.SYMTYPE
        sym.linkname = "/etc/passwd"
        tf.addfile(sym)
    with pytest.raises(AssetValidationError, match="regular files"):
        inspect_tarball(buf.getvalue())


def test_rejects_traversal_path():
    members = _minimal_required()
    members.pop("bgcs.tsv")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        evil = b"x\n"
        info = tarfile.TarInfo(name="../bgcs.tsv")
        info.size = len(evil)
        tf.addfile(info, io.BytesIO(evil))
    with pytest.raises(AssetValidationError, match="unsafe member path"):
        inspect_tarball(buf.getvalue())


def test_rejects_bad_header_in_required_tsv():
    members = _minimal_required()
    # Drop the required "start_position" column.
    members["bgcs.tsv"] = (
        b"contig_sha256\tdetector_name\tend_position\n"
        b"deadbeef\tantiSMASH:1\t100\n"
    )
    raw = _build_tarball(members)
    with pytest.raises(AssetValidationError, match="missing required column"):
        inspect_tarball(raw)


def test_rejects_oversize_member():
    from discovery.services.asset_upload.schemas import MAX_FILE_BYTES

    members = _minimal_required()
    members["contig_sequences.tsv"] = (
        b"contig_sha256\tsequence_base64\n" + b"x" * (MAX_FILE_BYTES + 10)
    )
    raw = _build_tarball(members)
    with pytest.raises(AssetValidationError, match="per-file cap"):
        inspect_tarball(raw)


def test_truncated_gzip_is_rejected():
    raw = _build_tarball(_minimal_required())
    truncated = raw[: len(raw) // 2]
    with pytest.raises(AssetValidationError):
        inspect_tarball(truncated)


def test_round_trips_gzip_minimal():
    """Sanity: the helper gzip-decodes the same bytes the test packed."""
    raw = _build_tarball(_minimal_required())
    decoded = gzip.decompress(raw)
    assert b"assemblies.tsv" in decoded or b"bgcs.tsv" in decoded
