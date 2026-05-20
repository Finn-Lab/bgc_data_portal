"""Integration tests for the iBGC filter surface.

Covers the regressions that surfaced in dev: the v2 Discovery dashboard
was sending the chip values silently for every dimension except a
handful, so picking e.g. ``Detector = MIBiG`` did not narrow the roster
at all. These tests pin the API contract — every chip listed in
``components/filters/FilterPanel.tsx`` must round-trip through
``/api/dashboard/ibgcs/roster/`` and produce the expected narrowing.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from django.test import Client

from discovery.models import (
    AssemblySource,
    AssemblyType,
    DashboardAssembly,
    DashboardBgc,
    DashboardBgcClass,
    DashboardCds,
    DashboardCdsChemOnt,
    DashboardContig,
    DashboardDetector,
    DashboardNaturalProduct,
    IntegratedBGC,
)


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def api_client():
    return Client()


def _make_contig(assembly, idx=0, taxonomy_path=""):
    sha = hashlib.sha256(f"{assembly.assembly_accession}_{idx}".encode()).hexdigest()
    return DashboardContig.objects.create(
        assembly=assembly,
        sequence_sha256=sha,
        accession=f"CONTIG_{assembly.assembly_accession}_{idx}",
        length=100_000,
        taxonomy_path=taxonomy_path,
    )


def _make_ibgc(contig, *, start, end, source_tools, gene_cluster_family=""):
    return IntegratedBGC.objects.create(
        contig=contig,
        start_position=start,
        end_position=end,
        source_tools=source_tools,
        gene_cluster_family=gene_cluster_family,
        umap_x=1.0,
        umap_y=2.0,
        umap_projected=False,
        novelty_score=0.5,
        domain_novelty=0.3,
    )


@pytest.fixture
def ibgc_dataset():
    """Three iBGCs across two assemblies with distinct detector/source/type."""
    src_mibig, _ = AssemblySource.objects.get_or_create(name="MIBiG")
    src_gtdb, _ = AssemblySource.objects.get_or_create(name="GTDB")

    a_mibig = DashboardAssembly.objects.create(
        assembly_accession="MIB_001",
        organism_name="MIBiG ref",
        source=src_mibig,
        assembly_type=AssemblyType.GENOME,
        biome_path="root.Reference",
    )
    a_gtdb = DashboardAssembly.objects.create(
        assembly_accession="GTDB_001",
        organism_name="Streptomyces sp.",
        source=src_gtdb,
        assembly_type=AssemblyType.METAGENOME,
        biome_path="root.Environmental.Terrestrial.Soil",
    )

    c_mibig = _make_contig(a_mibig, 0, "Bacteria.Actinomycetota")
    c_gtdb = _make_contig(a_gtdb, 0, "Bacteria.Pseudomonadota")

    # IBGC1 — MIBiG-only, from the MIBiG assembly.
    ibgc1 = _make_ibgc(
        c_mibig, start=1_000, end=20_000, source_tools=["MIBiG"],
        gene_cluster_family="Polyketide",
    )
    # IBGC2 — antiSMASH on the GTDB assembly.
    ibgc2 = _make_ibgc(
        c_gtdb, start=1_000, end=15_000, source_tools=["antiSMASH"],
        gene_cluster_family="NRP",
    )
    # IBGC3 — antiSMASH + SanntiS chain on the GTDB assembly.
    ibgc3 = _make_ibgc(
        c_gtdb, start=30_000, end=45_000,
        source_tools=["SanntiS", "antiSMASH"],
        gene_cluster_family="RiPP",
    )

    det_mibig = DashboardDetector.objects.create(
        name="MIBiG v3.1", tool="MIBiG", version="3.1.0",
        tool_name_code="MIB", version_sort_key=310,
    )
    det_anti = DashboardDetector.objects.create(
        name="antiSMASH v7.1", tool="antiSMASH", version="7.1.0",
        tool_name_code="ANT", version_sort_key=710,
    )

    # Source DashboardBgc rows — one per iBGC, wired to assembly + detector
    # so the helper's joins through ``source_bgcs`` resolve.
    DashboardBgc.objects.create(
        assembly=a_mibig, contig=c_mibig,
        bgc_accession="MGYB10000001.MIB.1.01",
        start_position=1_000, end_position=20_000,
        classification_path="Polyketide", detector=det_mibig,
        is_validated=True, integrated_bgc=ibgc1,
    )
    DashboardBgc.objects.create(
        assembly=a_gtdb, contig=c_gtdb,
        bgc_accession="MGYB10000002.ANT.1.01",
        start_position=1_000, end_position=15_000,
        classification_path="NRP", detector=det_anti,
        integrated_bgc=ibgc2,
    )
    DashboardBgc.objects.create(
        assembly=a_gtdb, contig=c_gtdb,
        bgc_accession="MGYB10000003.ANT.1.01",
        start_position=30_000, end_position=45_000,
        classification_path="RiPP", detector=det_anti,
        integrated_bgc=ibgc3,
    )

    DashboardBgcClass.objects.create(name="Polyketide", bgc_count=1)
    DashboardBgcClass.objects.create(name="NRP", bgc_count=1)
    DashboardBgcClass.objects.create(name="RiPP", bgc_count=1)

    return {
        "assemblies": {"mibig": a_mibig, "gtdb": a_gtdb},
        "sources": {"mibig": src_mibig, "gtdb": src_gtdb},
        "ibgcs": {"mibig": ibgc1, "antismash": ibgc2, "chain": ibgc3},
    }


def _roster_ids(api_client, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"/api/dashboard/ibgcs/roster/?{qs}" if qs else "/api/dashboard/ibgcs/roster/"
    resp = api_client.get(url)
    assert resp.status_code == 200, resp.content
    data = json.loads(resp.content)
    return {item["id"] for item in data["items"]}


# ── Tests ────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestIbgcRosterFilters:
    def test_baseline_returns_all(self, api_client, ibgc_dataset):
        ids = _roster_ids(api_client)
        assert ids == {ibgc_dataset["ibgcs"][k].id for k in ("mibig", "antismash", "chain")}

    def test_detector_tools_narrows_to_matching_ibgcs(self, api_client, ibgc_dataset):
        # The original regression: Detector = MIBiG must filter the iBGC
        # roster to iBGCs whose ``source_tools`` JSON includes MIBiG.
        ids = _roster_ids(api_client, detector_tools="MIBiG")
        assert ids == {ibgc_dataset["ibgcs"]["mibig"].id}

    def test_detector_tools_any_of(self, api_client, ibgc_dataset):
        # CSV is OR — any iBGC whose source_tools contains any listed tool.
        ids = _roster_ids(api_client, detector_tools="MIBiG,SanntiS")
        assert ids == {ibgc_dataset["ibgcs"]["mibig"].id, ibgc_dataset["ibgcs"]["chain"].id}

    def test_source_tools_legacy_alias(self, api_client, ibgc_dataset):
        # Old callers still send ``source_tools`` — keep accepting it.
        ids = _roster_ids(api_client, source_tools="MIBiG")
        assert ids == {ibgc_dataset["ibgcs"]["mibig"].id}

    def test_source_names_narrows_through_assembly_source(self, api_client, ibgc_dataset):
        ids = _roster_ids(api_client, source_names="MIBiG")
        assert ids == {ibgc_dataset["ibgcs"]["mibig"].id}

    def test_assembly_type(self, api_client, ibgc_dataset):
        ids = _roster_ids(api_client, assembly_type="metagenome")
        assert ids == {
            ibgc_dataset["ibgcs"]["antismash"].id,
            ibgc_dataset["ibgcs"]["chain"].id,
        }

    def test_bgc_class(self, api_client, ibgc_dataset):
        # Regression: bgc_class must filter on the chemical class path
        # held by source BGCs (``classification_path``), NOT on the iBGC's
        # ``gene_cluster_family`` (which is the leaf cluster path written
        # by the clustering pipeline). Picking BGC class = Polyketide
        # against a fresh clustering returned 0 iBGCs before this fix.
        ids = _roster_ids(api_client, bgc_class="Polyketide")
        assert ids == {ibgc_dataset["ibgcs"]["mibig"].id}

    def test_bgc_class_does_not_match_gene_cluster_family(
        self, api_client, ibgc_dataset
    ):
        # If we set ``gene_cluster_family`` to look like a class path,
        # the bgc_class filter must still IGNORE it — only
        # source_bgcs.classification_path counts.
        ibgc = ibgc_dataset["ibgcs"]["antismash"]
        ibgc.gene_cluster_family = "Polyketide.foo"
        ibgc.save()
        ids = _roster_ids(api_client, bgc_class="Polyketide")
        # Only the MIBiG iBGC whose source BGC has classification_path
        # "Polyketide" should match — not the antiSMASH iBGC whose
        # gene_cluster_family happens to start with "Polyketide".
        assert ids == {ibgc_dataset["ibgcs"]["mibig"].id}

    def test_assembly_accession(self, api_client, ibgc_dataset):
        ids = _roster_ids(api_client, assembly_accession="GTDB_001")
        assert ids == {
            ibgc_dataset["ibgcs"]["antismash"].id,
            ibgc_dataset["ibgcs"]["chain"].id,
        }

    def test_bgc_accession_substring(self, api_client, ibgc_dataset):
        ids = _roster_ids(api_client, bgc_accession="MGYB10000003")
        assert ids == {ibgc_dataset["ibgcs"]["chain"].id}

    def test_assembly_ids(self, api_client, ibgc_dataset):
        mibig_id = ibgc_dataset["assemblies"]["mibig"].id
        ids = _roster_ids(api_client, assembly_ids=str(mibig_id))
        assert ids == {ibgc_dataset["ibgcs"]["mibig"].id}

    def test_organism(self, api_client, ibgc_dataset):
        ids = _roster_ids(api_client, organism="Streptomyces")
        assert ids == {
            ibgc_dataset["ibgcs"]["antismash"].id,
            ibgc_dataset["ibgcs"]["chain"].id,
        }

    def test_combined_filters_intersect(self, api_client, ibgc_dataset):
        # Detector = antiSMASH AND bgc_class = RiPP → only the chain iBGC.
        ids = _roster_ids(
            api_client,
            detector_tools="antiSMASH",
            bgc_class="RiPP",
        )
        assert ids == {ibgc_dataset["ibgcs"]["chain"].id}

    def test_min_length_kb(self, api_client, ibgc_dataset):
        # Lengths: mibig 19kb, antismash 14kb, chain 15kb. Min=16 → only mibig.
        ids = _roster_ids(api_client, min_length_kb=16)
        assert ids == {ibgc_dataset["ibgcs"]["mibig"].id}

    def test_max_length_kb(self, api_client, ibgc_dataset):
        # Max=14.5 keeps only the antismash iBGC (14kb).
        ids = _roster_ids(api_client, max_length_kb=14.5)
        assert ids == {ibgc_dataset["ibgcs"]["antismash"].id}

    def test_length_range_both_bounds(self, api_client, ibgc_dataset):
        # 14.5–17 keeps only the chain iBGC (15kb).
        ids = _roster_ids(api_client, min_length_kb=14.5, max_length_kb=17)
        assert ids == {ibgc_dataset["ibgcs"]["chain"].id}

    def test_length_range_unbounded_returns_all(self, api_client, ibgc_dataset):
        # No length params = no length restriction.
        ids = _roster_ids(api_client)
        assert ids == {
            ibgc_dataset["ibgcs"][k].id
            for k in ("mibig", "antismash", "chain")
        }

    def test_chemont_ids(self, api_client, ibgc_dataset):
        # Wire up a per-CDS ChemOnt class on the MIBiG iBGC's source BGC.
        bgc = DashboardBgc.objects.get(integrated_bgc=ibgc_dataset["ibgcs"]["mibig"])
        cds = DashboardCds.objects.create(
            bgc=bgc,
            protein_id_str="cds_erythromycin_1",
            start_position=0,
            end_position=300,
            strand=1,
            protein_length=100,
        )
        DashboardCdsChemOnt.objects.create(
            cds=cds,
            chemont_id="CHEMONTID:0000048",
            chemont_name="Macrolides",
            probability=0.92,
            weight=2.1,
        )
        ids = _roster_ids(api_client, chemont_ids="CHEMONTID:0000048")
        assert ids == {ibgc_dataset["ibgcs"]["mibig"].id}


@pytest.mark.django_db
class TestIbgcScatterFilters:
    """Variables Map / UMAP must apply the same filter surface so the
    scatter stays in lockstep with the roster after Run Query."""

    def test_scatter_applies_detector_tools(self, api_client, ibgc_dataset):
        resp = api_client.get(
            "/api/dashboard/ibgcs/scatter/?detector_tools=MIBiG"
        )
        assert resp.status_code == 200
        data = json.loads(resp.content)
        ids = {p["id"] for p in data}
        assert ids == {ibgc_dataset["ibgcs"]["mibig"].id}

    def test_umap_applies_detector_tools(self, api_client, ibgc_dataset):
        resp = api_client.get(
            "/api/dashboard/ibgcs/umap/?detector_tools=MIBiG"
        )
        assert resp.status_code == 200
        data = json.loads(resp.content)
        ids = {p["id"] for p in data}
        assert ids == {ibgc_dataset["ibgcs"]["mibig"].id}


@pytest.mark.django_db
class TestIbgcIdsEndpoint:
    """``/ibgcs/ids/`` returns the iBGC id set for "Add all to shortlist".

    Pins the same filter surface as ``/ibgcs/roster/`` and the cap +
    ``truncated`` flag so the frontend can size buffers up front.
    """

    def _ids(self, api_client, **params):
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = (
            f"/api/dashboard/ibgcs/ids/?{qs}"
            if qs
            else "/api/dashboard/ibgcs/ids/"
        )
        resp = api_client.get(url)
        assert resp.status_code == 200, resp.content
        return json.loads(resp.content)

    def test_baseline_returns_all(self, api_client, ibgc_dataset):
        data = self._ids(api_client)
        assert set(data["ids"]) == {
            ibgc_dataset["ibgcs"][k].id
            for k in ("mibig", "antismash", "chain")
        }
        assert data["total_count"] == 3
        assert data["truncated"] is False

    def test_length_filter_narrows_ids(self, api_client, ibgc_dataset):
        data = self._ids(api_client, min_length_kb=16)
        assert data["ids"] == [ibgc_dataset["ibgcs"]["mibig"].id]
        assert data["total_count"] == 1

    def test_detector_tools_filter(self, api_client, ibgc_dataset):
        data = self._ids(api_client, detector_tools="antiSMASH")
        assert set(data["ids"]) == {
            ibgc_dataset["ibgcs"]["antismash"].id,
            ibgc_dataset["ibgcs"]["chain"].id,
        }

    def test_sort_by_size_kb_desc(self, api_client, ibgc_dataset):
        # 19kb > 15kb > 14kb → mibig, chain, antismash.
        data = self._ids(api_client, sort_by="size_kb", order="desc")
        assert data["ids"] == [
            ibgc_dataset["ibgcs"]["mibig"].id,
            ibgc_dataset["ibgcs"]["chain"].id,
            ibgc_dataset["ibgcs"]["antismash"].id,
        ]
