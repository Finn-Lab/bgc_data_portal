"""Tests for build_ibgc_domain_matrix.

Verifies:
  * Domain matrix is derived from iBGCs (not source DashboardBgcs directly).
  * sources= filter is case-insensitive at the boundary and excludes
    non-selected ref_db rows.
  * The matrix dedupes (domain_acc, cds.start_position) across source BGCs of
    a merged iBGC so the same domain at the same position counts once.
"""

from __future__ import annotations

import pytest

from discovery.models import BgcDomain, DashboardBgc, IntegratedBGC
from discovery.services.clustering.membership import build_ibgc_domain_matrix
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


def _ibgc(contig, *, source_bgcs, start, end, tools):
    ibgc = IntegratedBGC.objects.create(
        contig=contig,
        start_position=start,
        end_position=end,
        source_tools=sorted(tools),
    )
    DashboardBgc.objects.filter(id__in=[b.id for b in source_bgcs]).update(
        integrated_bgc=ibgc, classification_source="merged",
    )
    return ibgc


def _domain(bgc, *, acc, ref_db, name="dummy", start=1, end=100, ipr=""):
    return BgcDomain.objects.create(
        bgc=bgc, domain_acc=acc, domain_name=name,
        ref_db=ref_db, start_position=start, end_position=end,
        interpro_entry_acc=ipr,
    )


def test_sources_filter_is_case_insensitive_and_excludes_tigrfam():
    contig = DashboardContigFactory()
    bgc = _bgc(contig, start=1, end=10_000)
    _ibgc(contig, source_bgcs=[bgc], start=1, end=10_000, tools=["GECCO"])

    _domain(bgc, acc="PF00001", ref_db="PFAM")
    _domain(bgc, acc="NF12345", ref_db="NCBIFAM")
    _domain(bgc, acc="TIGR00100", ref_db="TIGRFAM")

    M, row_ids, domain_accs = build_ibgc_domain_matrix(sources=("PFAM", "NCBIFAM","TIGRFAM"))

    assert M.shape == (1, 2)
    assert set(domain_accs.tolist()) == {"PF00001", "NF12345"}


def test_dedup_across_source_bgcs_of_merged_ibgc():
    contig = DashboardContigFactory()
    bgc_a = _bgc(contig, start=1, end=5_000)
    bgc_b = _bgc(contig, start=4_000, end=10_000)
    ibgc = _ibgc(
        contig, source_bgcs=[bgc_a, bgc_b],
        start=1, end=10_000, tools=["GECCO", "SanntiS"],
    )

    # Same accession on both source BGCs — must collapse to one column with one entry.
    _domain(bgc_a, acc="PF00001", ref_db="PFAM")
    _domain(bgc_b, acc="PF00001", ref_db="PFAM")
    _domain(bgc_b, acc="PF00002", ref_db="PFAM")

    M, row_ids, domain_accs = build_ibgc_domain_matrix(sources=("PFAM",))

    assert list(row_ids) == [ibgc.id]
    # Two distinct domains: PF00001 and PF00002.
    assert sorted(domain_accs.tolist()) == ["PF00001", "PF00002"]
    # nnz == 2 (one per (ibgc, domain)).
    assert M.nnz == 2


def test_sources_filter_matches_mixed_case_stored_ref_db():
    """The bulk loader stores ref_db verbatim from the ETL (mixed-case).

    The query must match upper-case API values against whatever casing the
    DB holds — Pfam / pfam / PFAM / PfAm all count as PFAM.
    """
    contig = DashboardContigFactory()
    bgc = _bgc(contig, start=1, end=10_000)
    _ibgc(contig, source_bgcs=[bgc], start=1, end=10_000, tools=["GECCO"])

    _domain(bgc, acc="PF00001", ref_db="Pfam")
    _domain(bgc, acc="NF12345", ref_db="NCBIfam")
    _domain(bgc, acc="TIGR00100", ref_db="TIGRfam")

    M, _, accs = build_ibgc_domain_matrix(sources=("PFAM", "NCBIFAM", "TIGRFAM"))

    assert M.shape == (1, 3)
    assert set(accs.tolist()) == {"PF00001", "NF12345", "TIGR00100"}


def test_only_ibgc_rows_appear_partials_skipped():
    contig = DashboardContigFactory()
    bgc_merged = _bgc(contig, start=1, end=5_000)
    bgc_partial = _bgc(contig, start=20_000, end=25_000, is_partial=True)
    _ibgc(contig, source_bgcs=[bgc_merged], start=1, end=5_000, tools=["GECCO"])

    _domain(bgc_merged, acc="PF00001", ref_db="PFAM")
    _domain(bgc_partial, acc="PF00099", ref_db="PFAM")

    M, row_ids, domain_accs = build_ibgc_domain_matrix(sources=("PFAM",))
    assert M.shape[0] == 1
    assert "PF00099" not in domain_accs.tolist()


def test_ipr_label_replaces_signature_acc_when_set():
    """``M_domains`` columns are IPR-projected: a signature with a non-blank
    ``interpro_entry_acc`` contributes under the IPR label, not the raw acc.
    """
    contig = DashboardContigFactory()
    bgc = _bgc(contig, start=1, end=10_000)
    _ibgc(contig, source_bgcs=[bgc], start=1, end=10_000, tools=["GECCO"])

    _domain(bgc, acc="PF00001", ref_db="PFAM", ipr="IPR000001")
    _domain(bgc, acc="NF12345", ref_db="NCBIFAM", ipr="")  # no mapping → fallback

    M, _, accs = build_ibgc_domain_matrix(sources=("PFAM", "NCBIFAM"))

    cols = set(accs.tolist())
    assert "IPR000001" in cols
    assert "PF00001" not in cols
    assert "NF12345" in cols  # blank IPR → raw acc kept


def test_distinct_signatures_collapse_to_same_ipr_column():
    """Two Pfam signatures that share an IPR entry occupy one column."""
    contig = DashboardContigFactory()
    bgc = _bgc(contig, start=1, end=10_000)
    _ibgc(contig, source_bgcs=[bgc], start=1, end=10_000, tools=["GECCO"])

    _domain(bgc, acc="PF00010", ref_db="PFAM", ipr="IPR000010", start=1, end=80)
    _domain(bgc, acc="PF00011", ref_db="PFAM", ipr="IPR000010", start=200, end=280)

    M, _, accs = build_ibgc_domain_matrix(sources=("PFAM",))

    assert list(accs.tolist()) == ["IPR000010"]
    # M counts one binary entry per (row, label), regardless of how many
    # signatures fed it.
    assert M.nnz == 1
