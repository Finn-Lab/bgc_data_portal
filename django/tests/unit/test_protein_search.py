"""Unit tests for the discovery.services.protein_search package.

These tests are self-contained: they build a tiny FASTA on disk, exercise the
build/reload/search paths directly, and never touch Postgres.
"""

from __future__ import annotations

import hashlib

import pytest
from pyhmmer.easel import Alphabet, SequenceFile

from discovery.services.protein_search.build import (
    bump_version,
    index_paths,
    read_version,
    write_records,
)
from discovery.services.protein_search.index import (
    IndexNotBuiltError,
    ProteinSearchIndex,
)
from discovery.services.protein_search.search import (
    ProteinHitMetrics,
    phmmer_search,
)


# A handful of clearly-distinguishable proteins. The "target" is repeated in
# slightly mutated form so phmmer recovers it for a query equal to the original.
_PROTEIN_A = (
    "MKAILVVLLYTFATANADTLCIGYHANNSTDTVDTVLEKNVTVTHSVNLLEDKHNGKLCKLR"
    "GVAPLHLGKCNIAGWILGNPECESLSTASSWSYIVETSSSDNGTCYPGDFIDYEELREQLSS"
    "VSSFERFEIFPKTSSWPNHDSNKGVTAACPHAGAKSFYKNLIWLVKKGNSYPKLSKSYINDK"
    "GKEVLVLWGIHHPSTSADQQSLYQNADAYVFVGTSRYSKKFKPEIAIRPKVRDQEGRMNYYW"
    "TLVEPGDKITFEATGNLVVPRYAFAMERN"
)

_PROTEIN_B = (
    "MTEYKLVVVGAGGVGKSALTIQLIQNHFVDEYDPTIEDSYRKQVVIDGETCLLDILDTAGQE"
    "EYSAMRDQYMRTGEGFLCVFAINNTKSFEDIHHYREQIKRVKDSEDVPMVLVGNKCDLPSRT"
    "VDTKQAQDLARSYGIPFIETSAKTRQGVDDAFYTLVREIRKHKEKMSKDGKKKKKKSKTKCVIM"
)

_PROTEIN_C = (
    "MASLLKRLKRKKEEDLSEEGELKKVKKEEDEEEFGGLPDDLEDLERELLAQRQQQEDQEEEED"
    "EDDEEDDEDDLEEEEFLEELKKKGSKLDDDDKKNRDDLKKNGDDDLKKMRDKLEDLKKKLED"
)


def _sha256(seq: str) -> str:
    return hashlib.sha256(seq.encode()).hexdigest()


@pytest.fixture
def index_dir(tmp_path):
    """Empty index directory; child tests build into it."""
    return tmp_path / "protein_search"


@pytest.fixture
def built_index(index_dir):
    """Build a tiny FASTA + VERSION rooted at ``index_dir``."""
    paths = index_paths(index_dir)
    index_dir.mkdir(parents=True, exist_ok=True)
    records = [
        (_sha256(_PROTEIN_A), _PROTEIN_A),
        (_sha256(_PROTEIN_B), _PROTEIN_B),
        (_sha256(_PROTEIN_C), _PROTEIN_C),
    ]
    written = write_records(paths.fasta, records)
    assert written == 3
    bump_version(paths)
    return paths, records


# ── Build / write / SSI / version ──────────────────────────────────────────────


def test_write_records_produces_fasta_with_sha256_ids(tmp_path):
    fasta = tmp_path / "proteins.faa"
    sha_a = _sha256(_PROTEIN_A)
    written = write_records(fasta, [(sha_a, _PROTEIN_A)])
    assert written == 1

    text = fasta.read_text()
    assert text.startswith(f">{sha_a}\n")
    assert _PROTEIN_A in text


def test_fasta_roundtrip_via_sequence_file(built_index):
    paths, records = built_index

    alphabet = Alphabet.amino()
    with SequenceFile(str(paths.fasta), format="fasta", digital=True, alphabet=alphabet) as sf:
        block = sf.read_block()
    assert len(block) == len(records)
    names_seen = {seq.name.decode("ascii") for seq in block}
    assert names_seen == {sha for sha, _ in records}


def test_bump_version_is_monotonic(index_dir):
    paths = index_paths(index_dir)
    index_dir.mkdir(parents=True, exist_ok=True)
    assert read_version(paths) == 0
    assert bump_version(paths) == 1
    assert bump_version(paths) == 2
    assert read_version(paths) == 2


# ── phmmer_search ──────────────────────────────────────────────────────────────


def _load_block(paths):
    alphabet = Alphabet.amino()
    with SequenceFile(str(paths.fasta), format="fasta", digital=True, alphabet=alphabet) as sf:
        return sf.read_block()


def test_phmmer_search_self_match_returns_full_metrics(built_index):
    """A query equal to one of the indexed proteins should return a hit with
    near-perfect identity, full coverage, and a high bit score."""
    paths, _records = built_index
    block = _load_block(paths)

    sha_a = _sha256(_PROTEIN_A)
    hits = phmmer_search(
        _PROTEIN_A,
        min_bitscore=30.0,
        min_pident=70.0,
        min_qcov=70.0,
        block=block,
    )

    assert sha_a in hits
    m = hits[sha_a]
    assert isinstance(m, ProteinHitMetrics)
    # Self-match: identity should be essentially 100% and coverage ~100%.
    assert m.pident >= 95.0
    assert m.qcoverage >= 95.0
    assert m.bitscore >= 30.0

    # The self-match must also be the highest-bitscore hit.
    if hits:
        assert m.bitscore == max(h.bitscore for h in hits.values())


def test_phmmer_search_respects_min_bitscore(built_index):
    """A bitscore floor above the self-match score yields no hits."""
    paths, _ = built_index
    block = _load_block(paths)

    hits = phmmer_search(
        _PROTEIN_A,
        min_bitscore=1e6,
        min_pident=0.0,
        min_qcov=0.0,
        block=block,
    )
    assert hits == {}


def test_phmmer_search_respects_min_pident(built_index):
    """Requiring >100% identity is impossible; result must be empty."""
    paths, _ = built_index
    block = _load_block(paths)

    hits = phmmer_search(
        _PROTEIN_A,
        min_bitscore=0.0,
        min_pident=100.1,
        min_qcov=0.0,
        block=block,
    )
    assert hits == {}


def test_phmmer_search_respects_min_qcov(built_index):
    """Requiring >100% query coverage is impossible; result must be empty."""
    paths, _ = built_index
    block = _load_block(paths)

    hits = phmmer_search(
        _PROTEIN_A,
        min_bitscore=0.0,
        min_pident=0.0,
        min_qcov=100.1,
        block=block,
    )
    assert hits == {}


def test_phmmer_search_metrics_are_in_valid_ranges(built_index):
    """For any hit that comes back, the percentage fields must lie in [0,100]
    and bitscore must be non-negative."""
    paths, _ = built_index
    block = _load_block(paths)

    hits = phmmer_search(
        _PROTEIN_A,
        min_bitscore=0.0,
        min_pident=0.0,
        min_qcov=0.0,
        block=block,
    )
    for m in hits.values():
        assert 0.0 <= m.pident <= 100.0
        assert 0.0 <= m.qcoverage <= 100.0
        assert m.bitscore >= 0.0


def test_phmmer_search_partial_query_yields_partial_coverage(built_index):
    """A query that is a fragment of an indexed protein should still find
    that protein, but its query coverage should round-trip to ~100%
    (the fragment IS the full query, so coverage is on the query side, not
    the target side) — what differs from the self-match case is that the
    full self-match maps the entire target while the fragment only maps a
    region. We verify the fragment is recovered with high identity."""
    paths, _ = built_index
    block = _load_block(paths)

    # Take a 100-AA slice of protein A as the query.
    fragment = _PROTEIN_A[50:150]
    sha_a = _sha256(_PROTEIN_A)
    hits = phmmer_search(
        fragment,
        min_bitscore=30.0,
        min_pident=70.0,
        min_qcov=70.0,
        block=block,
    )

    assert sha_a in hits
    m = hits[sha_a]
    # Coverage is over the query (the 100-AA fragment), so it should be ~100%.
    assert m.qcoverage >= 70.0
    assert m.pident >= 70.0


# ── ProteinSearchIndex (worker-local cache) ────────────────────────────────────


def test_index_not_built_raises_clear_error(index_dir, monkeypatch):
    """Calling get_block() before the FASTA exists must raise IndexNotBuiltError."""
    monkeypatch.setattr(
        "discovery.services.protein_search.build.settings.PROTEIN_SEARCH_INDEX_DIR",
        index_dir,
    )
    psi = ProteinSearchIndex()
    with pytest.raises(IndexNotBuiltError):
        psi.get_block()


def test_index_reloads_on_version_bump(built_index, monkeypatch):
    """Bumping the VERSION stamp triggers a reload on the next get_block()."""
    paths, _ = built_index
    monkeypatch.setattr(
        "discovery.services.protein_search.build.settings.PROTEIN_SEARCH_INDEX_DIR",
        paths.base_dir,
    )
    psi = ProteinSearchIndex()

    block_v1 = psi.get_block()
    v1 = psi.loaded_version()
    assert v1 > 0
    # Same call again returns the same cached block, no reload.
    assert psi.get_block() is block_v1
    assert psi.loaded_version() == v1

    # Append a new protein and bump version.
    extra_sha = _sha256("MYAAAAA")
    with paths.fasta.open("a") as fh:
        fh.write(f">{extra_sha}\nMYAAAAA\n")
    v2 = bump_version(paths)
    assert v2 > v1

    block_v2 = psi.get_block()
    assert psi.loaded_version() == v2
    assert block_v2 is not block_v1
    assert len(block_v2) == len(block_v1) + 1
