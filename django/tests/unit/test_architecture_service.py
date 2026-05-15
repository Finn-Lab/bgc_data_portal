"""Tests for the pooled positional architecture helper.

Mirrors the ordering rule used by ``build_nrb_adjacency_pair_matrix`` so
both surfaces stay in lockstep.
"""

from __future__ import annotations

import pytest

from discovery.models import (
    BgcDomain,
    DashboardBgc,
    DashboardCds,
    NonRedundantBGC,
)
from discovery.services.architecture import (
    bgc_architecture,
    nrb_architecture,
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


def _nrb(contig, *, source_bgcs):
    nrb = NonRedundantBGC.objects.create(
        contig=contig,
        start_position=1,
        end_position=10_000,
        source_tools=["GECCO"],
    )
    DashboardBgc.objects.filter(id__in=[b.id for b in source_bgcs]).update(
        non_redundant_bgc=nrb, classification_source="merged",
    )
    return nrb


def _cds(bgc, start, end):
    return DashboardCds.objects.create(
        bgc=bgc, protein_id_str=f"P{DashboardCds.objects.count() + 1}",
        start_position=start, end_position=end, strand=1,
        protein_length=(end - start) // 3, protein_sha256="",
    )


def _domain(bgc, *, cds, acc, ref_db="PFAM", aa_start=10):
    return BgcDomain.objects.create(
        bgc=bgc, cds=cds, domain_acc=acc, domain_name=acc,
        ref_db=ref_db, start_position=aa_start, end_position=aa_start + 50,
    )


def test_bgc_architecture_is_positional_not_alphabetical():
    contig = DashboardContigFactory()
    bgc = _bgc(contig)
    # Alphabetical order would be A, B, C; we plant them in C → A → B order.
    cds1 = _cds(bgc, 100, 400)
    cds2 = _cds(bgc, 500, 800)
    cds3 = _cds(bgc, 900, 1200)
    _domain(bgc, cds=cds1, acc="C")
    _domain(bgc, cds=cds2, acc="A")
    _domain(bgc, cds=cds3, acc="B")

    rows = bgc_architecture(bgc.id)
    assert [r["domain_acc"] for r in rows] == ["C", "A", "B"]


def test_nrb_architecture_pools_across_member_bgcs():
    contig = DashboardContigFactory()
    bgc_a = _bgc(contig, start=1, end=5_000)
    bgc_b = _bgc(contig, start=5_001, end=10_000)
    nrb = _nrb(contig, source_bgcs=[bgc_a, bgc_b])

    cds_a = _cds(bgc_a, 100, 400)
    cds_b1 = _cds(bgc_b, 6_000, 6_400)
    cds_b2 = _cds(bgc_b, 7_000, 7_400)
    _domain(bgc_a, cds=cds_a, acc="A")
    _domain(bgc_b, cds=cds_b1, acc="B")
    _domain(bgc_b, cds=cds_b2, acc="C")

    member_ids = list(
        DashboardBgc.objects.filter(non_redundant_bgc=nrb).values_list(
            "id", flat=True,
        )
    )
    rows = nrb_architecture(member_ids)
    assert [r["domain_acc"] for r in rows] == ["A", "B", "C"]


def test_architecture_drops_non_default_sources():
    contig = DashboardContigFactory()
    bgc = _bgc(contig)
    cds = _cds(bgc, 100, 400)
    _domain(bgc, cds=cds, acc="PF00109", ref_db="PFAM")
    _domain(bgc, cds=cds, acc="IPR123", ref_db="INTERPRO")

    rows = bgc_architecture(bgc.id)
    assert [r["domain_acc"] for r in rows] == ["PF00109"]


def test_architecture_skips_domains_without_cds():
    contig = DashboardContigFactory()
    bgc = _bgc(contig)
    cds = _cds(bgc, 100, 400)
    _domain(bgc, cds=cds, acc="PF00001")
    BgcDomain.objects.create(
        bgc=bgc, cds=None, domain_acc="PF99999", domain_name="orphan",
        ref_db="PFAM", start_position=0, end_position=0,
    )

    rows = bgc_architecture(bgc.id)
    assert [r["domain_acc"] for r in rows] == ["PF00001"]
