"""Integration tests for the NRB count endpoint.

``/api/dashboard/nrbs/count/`` drives the empty-state guard + the
"Showing X of Y, sampled" banner in the v2 Discovery dashboard. These
tests pin (a) that the filter surface matches ``/nrbs/roster/`` and
(b) that ``will_sample`` flips on the right side of
``DASHBOARD_RESULT_CAP``.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from django.test import Client

from discovery.api import DASHBOARD_RESULT_CAP
from discovery.models import (
    AssemblySource,
    AssemblyType,
    DashboardAssembly,
    DashboardBgc,
    DashboardContig,
    DashboardDetector,
    NonRedundantBGC,
)


@pytest.fixture
def api_client():
    return Client()


def _make_contig(assembly, idx=0):
    sha = hashlib.sha256(f"{assembly.assembly_accession}_{idx}".encode()).hexdigest()
    return DashboardContig.objects.create(
        assembly=assembly,
        sequence_sha256=sha,
        accession=f"CONTIG_{assembly.assembly_accession}_{idx}",
        length=100_000,
    )


def _make_nrb(contig, *, source_tools):
    return NonRedundantBGC.objects.create(
        contig=contig,
        start_position=1_000,
        end_position=11_000,
        source_tools=source_tools,
        gene_cluster_family="cluster.0001",
        umap_x=1.0,
        umap_y=2.0,
        umap_projected=False,
        novelty_score=0.5,
        domain_novelty=0.3,
    )


@pytest.fixture
def nrb_dataset():
    """Three NRBs: 1 MIBiG, 2 antiSMASH (same source/assembly)."""
    src_mibig, _ = AssemblySource.objects.get_or_create(name="MIBiG")
    src_gtdb, _ = AssemblySource.objects.get_or_create(name="GTDB")

    a_mibig = DashboardAssembly.objects.create(
        assembly_accession="MIB_001",
        organism_name="MIBiG ref",
        source=src_mibig,
        assembly_type=AssemblyType.GENOME,
    )
    a_gtdb = DashboardAssembly.objects.create(
        assembly_accession="GTDB_001",
        organism_name="Streptomyces sp.",
        source=src_gtdb,
        assembly_type=AssemblyType.METAGENOME,
    )

    c_mibig = _make_contig(a_mibig, 0)
    c_gtdb = _make_contig(a_gtdb, 0)

    n1 = _make_nrb(c_mibig, source_tools=["MIBiG"])
    n2 = _make_nrb(c_gtdb, source_tools=["antiSMASH"])
    n3 = _make_nrb(c_gtdb, source_tools=["antiSMASH"])

    det_mibig = DashboardDetector.objects.create(
        name="MIBiG v3.1", tool="MIBiG", version="3.1.0",
        tool_name_code="MIB", version_sort_key=310,
    )
    det_anti = DashboardDetector.objects.create(
        name="antiSMASH v7.1", tool="antiSMASH", version="7.1.0",
        tool_name_code="ANT", version_sort_key=710,
    )
    DashboardBgc.objects.create(
        assembly=a_mibig, contig=c_mibig,
        bgc_accession="MGYB10000001.MIB.1.01",
        start_position=1_000, end_position=11_000,
        classification_path="Polyketide", detector=det_mibig,
        non_redundant_bgc=n1,
    )
    DashboardBgc.objects.create(
        assembly=a_gtdb, contig=c_gtdb,
        bgc_accession="MGYB10000002.ANT.1.01",
        start_position=1_000, end_position=11_000,
        classification_path="NRP", detector=det_anti,
        non_redundant_bgc=n2,
    )
    DashboardBgc.objects.create(
        assembly=a_gtdb, contig=c_gtdb,
        bgc_accession="MGYB10000003.ANT.1.01",
        start_position=2_000, end_position=12_000,
        classification_path="NRP", detector=det_anti,
        non_redundant_bgc=n3,
    )
    return {"mibig": n1, "anti1": n2, "anti2": n3}


def _count(api_client, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"/api/dashboard/nrbs/count/?{qs}" if qs else "/api/dashboard/nrbs/count/"
    resp = api_client.get(url)
    assert resp.status_code == 200, resp.content
    return json.loads(resp.content)


@pytest.mark.django_db
class TestNrbCount:
    def test_no_filter_returns_full_count(self, api_client, nrb_dataset):
        body = _count(api_client)
        assert body["exact_count"] == 3
        assert body["cap"] == DASHBOARD_RESULT_CAP
        assert body["will_sample"] is False

    def test_detector_tools_narrows(self, api_client, nrb_dataset):
        # Same filter surface as /nrbs/roster/ — must narrow identically.
        body = _count(api_client, detector_tools="MIBiG")
        assert body["exact_count"] == 1

    def test_source_names_narrows(self, api_client, nrb_dataset):
        body = _count(api_client, source_names="GTDB")
        assert body["exact_count"] == 2

    def test_nrb_ids_allow_list(self, api_client, nrb_dataset):
        ids = f"{nrb_dataset['mibig'].id},{nrb_dataset['anti1'].id}"
        body = _count(api_client, nrb_ids=ids)
        assert body["exact_count"] == 2

    def test_unknown_filter_value_returns_zero(self, api_client, nrb_dataset):
        body = _count(api_client, source_names="NoSuchSource")
        assert body["exact_count"] == 0
        assert body["will_sample"] is False

    def test_will_sample_threshold(self, api_client, monkeypatch, nrb_dataset):
        # ``will_sample`` is purely a function of count > cap; pin the
        # threshold to 1 so we don't need to materialise 5k rows in tests.
        monkeypatch.setattr(
            "discovery.api.DASHBOARD_RESULT_CAP", 1
        )
        body = _count(api_client)
        # The endpoint reads the module-level constant at request time, so
        # the patched value flows through.
        assert body["cap"] == 1
        assert body["exact_count"] == 3
        assert body["will_sample"] is True
