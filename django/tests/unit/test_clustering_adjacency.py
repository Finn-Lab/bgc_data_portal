"""Tests for build_nrb_adjacency_pair_matrix.

Verifies:
  * Sliding-window-2 pair extraction over a genome-ordered domain sequence.
  * Domains with cds=NULL are dropped from the adjacency calculation.
  * Ordering uses (cds.start_position, BgcDomain.start_position).
  * The ref_db filter is applied BEFORE sequencing, so non-selected sources
    don't interrupt the adjacency string.
"""

from __future__ import annotations

import pytest

from discovery.models import (
    BgcDomain,
    DashboardBgc,
    DashboardCds,
    NonRedundantBGC,
)
from discovery.services.clustering.adjacency import (
    build_nrb_adjacency_pair_matrix,
)
from tests.factories.discovery_models import DashboardContigFactory


pytestmark = pytest.mark.django_db


def _bgc(contig, start=1, end=10_000):
    return DashboardBgc.objects.create(
        assembly=contig.assembly,
        contig=contig,
        bgc_accession=f"MGYB{DashboardBgc.objects.count() + 1:08d}",
        start_position=start,
        end_position=end,
    )


def _nrb(contig, *, source_bgcs, start=1, end=10_000, tools=("GECCO",)):
    nrb = NonRedundantBGC.objects.create(
        contig=contig,
        start_position=start,
        end_position=end,
        source_tools=sorted(tools),
    )
    DashboardBgc.objects.filter(id__in=[b.id for b in source_bgcs]).update(
        non_redundant_bgc=nrb, classification_source="merged",
    )
    return nrb


def _cds(bgc, start, end, sha=""):
    return DashboardCds.objects.create(
        bgc=bgc, protein_id_str=f"P{DashboardCds.objects.count() + 1}",
        start_position=start, end_position=end, strand=1,
        protein_length=(end - start) // 3, protein_sha256=sha,
    )


def _domain(bgc, *, cds, acc, ref_db="PFAM", aa_start=10, aa_end=80, name=""):
    return BgcDomain.objects.create(
        bgc=bgc, cds=cds, domain_acc=acc, domain_name=name or acc,
        ref_db=ref_db, start_position=aa_start, end_position=aa_end,
    )


def test_three_domain_sequence_yields_two_pairs():
    contig = DashboardContigFactory()
    bgc = _bgc(contig)
    nrb = _nrb(contig, source_bgcs=[bgc])
    cds1 = _cds(bgc, 100, 400)
    cds2 = _cds(bgc, 500, 800)
    cds3 = _cds(bgc, 900, 1200)
    _domain(bgc, cds=cds1, acc="A")
    _domain(bgc, cds=cds2, acc="B")
    _domain(bgc, cds=cds3, acc="C")

    M, row_ids, pair_vocab = build_nrb_adjacency_pair_matrix(sources=("PFAM",))
    assert list(row_ids) == [nrb.id]
    pairs = {tuple(p) for p in pair_vocab.tolist()}
    assert pairs == {("A", "B"), ("B", "C")}


def test_single_domain_produces_empty_row():
    contig = DashboardContigFactory()
    bgc = _bgc(contig)
    nrb = _nrb(contig, source_bgcs=[bgc])
    cds1 = _cds(bgc, 100, 400)
    _domain(bgc, cds=cds1, acc="A")

    M, row_ids, pair_vocab = build_nrb_adjacency_pair_matrix(sources=("PFAM",))
    # Row exists but has zero pairs.
    assert list(row_ids) == [nrb.id]
    assert M.shape[1] == 0
    assert M.nnz == 0


def test_adjacent_identical_domains_kept_as_self_pair():
    contig = DashboardContigFactory()
    bgc = _bgc(contig)
    nrb = _nrb(contig, source_bgcs=[bgc])
    cds1 = _cds(bgc, 100, 400)
    cds2 = _cds(bgc, 500, 800)
    cds3 = _cds(bgc, 900, 1200)
    _domain(bgc, cds=cds1, acc="A")
    _domain(bgc, cds=cds2, acc="A")
    _domain(bgc, cds=cds3, acc="B")

    M, row_ids, pair_vocab = build_nrb_adjacency_pair_matrix(sources=("PFAM",))
    pairs = {tuple(p) for p in pair_vocab.tolist()}
    assert ("A", "A") in pairs
    assert ("A", "B") in pairs


def test_null_cds_domains_dropped_from_adjacency():
    contig = DashboardContigFactory()
    bgc = _bgc(contig)
    nrb = _nrb(contig, source_bgcs=[bgc])
    cds1 = _cds(bgc, 100, 400)
    cds2 = _cds(bgc, 900, 1200)
    _domain(bgc, cds=cds1, acc="A")
    # cds=NULL row — must be dropped before sequencing.
    BgcDomain.objects.create(
        bgc=bgc, cds=None, domain_acc="X", domain_name="X",
        ref_db="PFAM", start_position=10, end_position=80,
    )
    _domain(bgc, cds=cds2, acc="B")

    M, row_ids, pair_vocab = build_nrb_adjacency_pair_matrix(sources=("PFAM",))
    pairs = {tuple(p) for p in pair_vocab.tolist()}
    # X is invisible to adjacency; sequence is [A, B] → {(A,B)} only.
    assert pairs == {("A", "B")}


def test_adjacency_matches_mixed_case_stored_ref_db():
    """Mirrors the membership-side test: bulk loader stores mixed-case ref_db."""
    contig = DashboardContigFactory()
    bgc = _bgc(contig)
    nrb = _nrb(contig, source_bgcs=[bgc])
    cds1 = _cds(bgc, 100, 400)
    cds2 = _cds(bgc, 500, 800)
    _domain(bgc, cds=cds1, acc="A", ref_db="Pfam")
    _domain(bgc, cds=cds2, acc="B", ref_db="NCBIfam")

    M, row_ids, pair_vocab = build_nrb_adjacency_pair_matrix(
        sources=("PFAM", "NCBIFAM","TIGRFAM"),
    )
    assert list(row_ids) == [nrb.id]
    assert {tuple(p) for p in pair_vocab.tolist()} == {("A", "B")}


def test_ref_db_filter_applies_before_sequencing():
    contig = DashboardContigFactory()
    bgc = _bgc(contig)
    nrb = _nrb(contig, source_bgcs=[bgc])
    cds1 = _cds(bgc, 100, 400)
    cds2 = _cds(bgc, 500, 800)
    cds3 = _cds(bgc, 900, 1200)
    _domain(bgc, cds=cds1, acc="A", ref_db="PFAM")
    # TIGRFAM domain in the middle — must be dropped before windowing so
    # the sequence becomes [A, B], not [A, T, B].
    _domain(bgc, cds=cds2, acc="T", ref_db="TIGRFAM")
    _domain(bgc, cds=cds3, acc="B", ref_db="NCBIFAM")

    M, row_ids, pair_vocab = build_nrb_adjacency_pair_matrix(
        sources=("PFAM", "NCBIFAM","TIGRFAM"),
    )
    pairs = {tuple(p) for p in pair_vocab.tolist()}
    assert pairs == {("A", "B")}
