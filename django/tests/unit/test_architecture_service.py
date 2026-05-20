"""Tests for the pooled positional architecture helper.

Mirrors the ordering rule used by ``build_ibgc_adjacency_pair_matrix`` so
both surfaces stay in lockstep.
"""

from __future__ import annotations

import pytest

from discovery.models import (
    BgcDomain,
    DashboardBgc,
    DashboardCds,
    IntegratedBGC,
)
from discovery.services.architecture import (
    bgc_architecture,
    ibgc_architecture,
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


def _ibgc(contig, *, source_bgcs):
    ibgc = IntegratedBGC.objects.create(
        contig=contig,
        start_position=1,
        end_position=10_000,
        source_tools=["GECCO"],
    )
    DashboardBgc.objects.filter(id__in=[b.id for b in source_bgcs]).update(
        integrated_bgc=ibgc, classification_source="merged",
    )
    return ibgc


def _cds(bgc, start, end):
    return DashboardCds.objects.create(
        bgc=bgc, protein_id_str=f"P{DashboardCds.objects.count() + 1}",
        start_position=start, end_position=end, strand=1,
        protein_length=(end - start) // 3, protein_sha256="",
    )


def _domain(bgc, *, cds, acc, ref_db="PFAM", aa_start=10, ipr="", ipr_desc=""):
    return BgcDomain.objects.create(
        bgc=bgc, cds=cds, domain_acc=acc, domain_name=acc,
        ref_db=ref_db, start_position=aa_start, end_position=aa_start + 50,
        interpro_entry_acc=ipr, interpro_entry_description=ipr_desc,
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


def test_ibgc_architecture_pools_across_member_bgcs():
    contig = DashboardContigFactory()
    bgc_a = _bgc(contig, start=1, end=5_000)
    bgc_b = _bgc(contig, start=5_001, end=10_000)
    ibgc = _ibgc(contig, source_bgcs=[bgc_a, bgc_b])

    cds_a = _cds(bgc_a, 100, 400)
    cds_b1 = _cds(bgc_b, 6_000, 6_400)
    cds_b2 = _cds(bgc_b, 7_000, 7_400)
    _domain(bgc_a, cds=cds_a, acc="A")
    _domain(bgc_b, cds=cds_b1, acc="B")
    _domain(bgc_b, cds=cds_b2, acc="C")

    member_ids = list(
        DashboardBgc.objects.filter(integrated_bgc=ibgc).values_list(
            "id", flat=True,
        )
    )
    rows = ibgc_architecture(member_ids)
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


def test_architecture_projects_to_ipr_when_available():
    """Each positional row emits the IPR acc/url/ref_db when
    ``interpro_entry_acc`` is set; signatures without an IPR mapping keep
    their raw values.
    """
    contig = DashboardContigFactory()
    bgc = _bgc(contig)
    cds1 = _cds(bgc, 100, 400)
    cds2 = _cds(bgc, 500, 800)
    _domain(bgc, cds=cds1, acc="PF00001", ipr="IPR000001", ipr_desc="ABC fold")
    _domain(bgc, cds=cds2, acc="NF12345", ref_db="NCBIFAM")  # no IPR

    rows = bgc_architecture(bgc.id)
    accs = [r["domain_acc"] for r in rows]
    assert accs == ["IPR000001", "NF12345"]
    by_acc = {r["domain_acc"]: r for r in rows}
    assert by_acc["IPR000001"]["ref_db"] == "InterPro"
    assert by_acc["IPR000001"]["url"].endswith("/IPR000001/")
    assert by_acc["NF12345"]["ref_db"] == "NCBIFAM"


def test_architecture_positional_preserves_contiguous_repeats():
    """The pooled positional surface does NOT collapse adjacent same-label
    hits — that rule is local to M_pairs. The UI needs every hit visible.
    """
    contig = DashboardContigFactory()
    bgc = _bgc(contig)
    cds1 = _cds(bgc, 100, 400)
    cds2 = _cds(bgc, 500, 800)
    cds3 = _cds(bgc, 900, 1200)
    _domain(bgc, cds=cds1, acc="PF00010", ipr="IPR000010")
    _domain(bgc, cds=cds2, acc="PF00011", ipr="IPR000010")  # same IPR
    _domain(bgc, cds=cds3, acc="PF00020", ipr="IPR000020")

    rows = bgc_architecture(bgc.id)
    accs = [r["domain_acc"] for r in rows]
    assert accs == ["IPR000010", "IPR000010", "IPR000020"]
