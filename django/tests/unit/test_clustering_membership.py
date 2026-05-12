"""Tests for build_nrb_domain_matrix.

Verifies:
  * Domain matrix is derived from NRBs (not source DashboardBgcs directly).
  * sources= filter is case-insensitive at the boundary and excludes
    non-selected ref_db rows.
  * The matrix dedupes (domain_acc, cds.start_position) across source BGCs of
    a merged NRB so the same domain at the same position counts once.
"""

from __future__ import annotations

import pytest

from discovery.models import BgcDomain, DashboardBgc, NonRedundantBGC
from discovery.services.clustering.membership import build_nrb_domain_matrix
from tests.factories.discovery_models import DashboardContigFactory


pytestmark = pytest.mark.django_db


def _bgc(contig, *, start, end, is_partial=False):
    return DashboardBgc.objects.create(
        assembly=contig.assembly,
        contig=contig,
        bgc_accession=f"MGYB{DashboardBgc.objects.count() + 1:08d}",
        start_position=start,
        end_position=end,
        is_partial=is_partial,
    )


def _nrb(contig, *, source_bgcs, start, end, tools):
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


def _domain(bgc, *, acc, ref_db, name="dummy", start=1, end=100):
    return BgcDomain.objects.create(
        bgc=bgc, domain_acc=acc, domain_name=name,
        ref_db=ref_db, start_position=start, end_position=end,
    )


def test_sources_filter_is_case_insensitive_and_excludes_tigrfam():
    contig = DashboardContigFactory()
    bgc = _bgc(contig, start=1, end=10_000)
    _nrb(contig, source_bgcs=[bgc], start=1, end=10_000, tools=["GECCO"])

    _domain(bgc, acc="PF00001", ref_db="PFAM")
    _domain(bgc, acc="NF12345", ref_db="NCBIFAM")
    _domain(bgc, acc="TIGR00100", ref_db="TIGRFAM")

    M, row_ids, domain_accs = build_nrb_domain_matrix(sources=("pfam", "ncbifam"))

    assert M.shape == (1, 2)
    assert set(domain_accs.tolist()) == {"PF00001", "NF12345"}


def test_dedup_across_source_bgcs_of_merged_nrb():
    contig = DashboardContigFactory()
    bgc_a = _bgc(contig, start=1, end=5_000)
    bgc_b = _bgc(contig, start=4_000, end=10_000)
    nrb = _nrb(
        contig, source_bgcs=[bgc_a, bgc_b],
        start=1, end=10_000, tools=["GECCO", "SanntiS"],
    )

    # Same accession on both source BGCs — must collapse to one column with one entry.
    _domain(bgc_a, acc="PF00001", ref_db="PFAM")
    _domain(bgc_b, acc="PF00001", ref_db="PFAM")
    _domain(bgc_b, acc="PF00002", ref_db="PFAM")

    M, row_ids, domain_accs = build_nrb_domain_matrix(sources=("PFAM",))

    assert list(row_ids) == [nrb.id]
    # Two distinct domains: PF00001 and PF00002.
    assert sorted(domain_accs.tolist()) == ["PF00001", "PF00002"]
    # nnz == 2 (one per (nrb, domain)).
    assert M.nnz == 2


def test_sources_filter_matches_mixed_case_stored_ref_db():
    """The bulk loader stores ref_db verbatim from the ETL (mixed-case).

    The query must match upper-case API values against whatever casing the
    DB holds — Pfam / pfam / PFAM / PfAm all count as PFAM.
    """
    contig = DashboardContigFactory()
    bgc = _bgc(contig, start=1, end=10_000)
    _nrb(contig, source_bgcs=[bgc], start=1, end=10_000, tools=["GECCO"])

    _domain(bgc, acc="PF00001", ref_db="Pfam")
    _domain(bgc, acc="NF12345", ref_db="NCBIfam")
    _domain(bgc, acc="TIGR00100", ref_db="TIGRfam")

    M, _, accs = build_nrb_domain_matrix(sources=("PFAM", "NCBIFAM", "TIGRFAM"))

    assert M.shape == (1, 3)
    assert set(accs.tolist()) == {"PF00001", "NF12345", "TIGR00100"}


def test_only_nrb_rows_appear_partials_skipped():
    contig = DashboardContigFactory()
    bgc_merged = _bgc(contig, start=1, end=5_000)
    bgc_partial = _bgc(contig, start=20_000, end=25_000, is_partial=True)
    _nrb(contig, source_bgcs=[bgc_merged], start=1, end=5_000, tools=["GECCO"])

    _domain(bgc_merged, acc="PF00001", ref_db="PFAM")
    _domain(bgc_partial, acc="PF00099", ref_db="PFAM")

    M, row_ids, domain_accs = build_nrb_domain_matrix(sources=("PFAM",))
    assert M.shape[0] == 1
    assert "PF00099" not in domain_accs.tolist()
