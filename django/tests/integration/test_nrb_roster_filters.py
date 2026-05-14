"""Integration tests for the NRB filter surface.

Covers the regressions that surfaced in dev: the v2 Discovery dashboard
was sending the chip values silently for every dimension except a
handful, so picking e.g. ``Detector = MIBiG`` did not narrow the roster
at all. These tests pin the API contract — every chip listed in
``components/filters/FilterPanel.tsx`` must round-trip through
``/api/dashboard/nrbs/roster/`` and produce the expected narrowing.
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
    DashboardContig,
    DashboardDetector,
    DashboardNaturalProduct,
    NaturalProductChemOntClass,
    NonRedundantBGC,
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


def _make_nrb(contig, *, start, end, source_tools, gene_cluster_family=""):
    return NonRedundantBGC.objects.create(
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
def nrb_dataset():
    """Three NRBs across two assemblies with distinct detector/source/type."""
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

    # NRB1 — MIBiG-only, from the MIBiG assembly.
    nrb1 = _make_nrb(
        c_mibig, start=1_000, end=20_000, source_tools=["MIBiG"],
        gene_cluster_family="Polyketide",
    )
    # NRB2 — antiSMASH on the GTDB assembly.
    nrb2 = _make_nrb(
        c_gtdb, start=1_000, end=15_000, source_tools=["antiSMASH"],
        gene_cluster_family="NRP",
    )
    # NRB3 — antiSMASH + SanntiS chain on the GTDB assembly.
    nrb3 = _make_nrb(
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

    # Source DashboardBgc rows — one per NRB, wired to assembly + detector
    # so the helper's joins through ``source_bgcs`` resolve.
    DashboardBgc.objects.create(
        assembly=a_mibig, contig=c_mibig,
        bgc_accession="MGYB10000001.MIB.1.01",
        start_position=1_000, end_position=20_000,
        classification_path="Polyketide", detector=det_mibig,
        is_validated=True, non_redundant_bgc=nrb1,
    )
    DashboardBgc.objects.create(
        assembly=a_gtdb, contig=c_gtdb,
        bgc_accession="MGYB10000002.ANT.1.01",
        start_position=1_000, end_position=15_000,
        classification_path="NRP", detector=det_anti,
        non_redundant_bgc=nrb2,
    )
    DashboardBgc.objects.create(
        assembly=a_gtdb, contig=c_gtdb,
        bgc_accession="MGYB10000003.ANT.1.01",
        start_position=30_000, end_position=45_000,
        classification_path="RiPP", detector=det_anti,
        non_redundant_bgc=nrb3,
    )

    DashboardBgcClass.objects.create(name="Polyketide", bgc_count=1)
    DashboardBgcClass.objects.create(name="NRP", bgc_count=1)
    DashboardBgcClass.objects.create(name="RiPP", bgc_count=1)

    return {
        "assemblies": {"mibig": a_mibig, "gtdb": a_gtdb},
        "sources": {"mibig": src_mibig, "gtdb": src_gtdb},
        "nrbs": {"mibig": nrb1, "antismash": nrb2, "chain": nrb3},
    }


def _roster_ids(api_client, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"/api/dashboard/nrbs/roster/?{qs}" if qs else "/api/dashboard/nrbs/roster/"
    resp = api_client.get(url)
    assert resp.status_code == 200, resp.content
    data = json.loads(resp.content)
    return {item["id"] for item in data["items"]}


# ── Tests ────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestNrbRosterFilters:
    def test_baseline_returns_all(self, api_client, nrb_dataset):
        ids = _roster_ids(api_client)
        assert ids == {nrb_dataset["nrbs"][k].id for k in ("mibig", "antismash", "chain")}

    def test_detector_tools_narrows_to_matching_nrbs(self, api_client, nrb_dataset):
        # The original regression: Detector = MIBiG must filter the NRB
        # roster to NRBs whose ``source_tools`` JSON includes MIBiG.
        ids = _roster_ids(api_client, detector_tools="MIBiG")
        assert ids == {nrb_dataset["nrbs"]["mibig"].id}

    def test_detector_tools_any_of(self, api_client, nrb_dataset):
        # CSV is OR — any NRB whose source_tools contains any listed tool.
        ids = _roster_ids(api_client, detector_tools="MIBiG,SanntiS")
        assert ids == {nrb_dataset["nrbs"]["mibig"].id, nrb_dataset["nrbs"]["chain"].id}

    def test_source_tools_legacy_alias(self, api_client, nrb_dataset):
        # Old callers still send ``source_tools`` — keep accepting it.
        ids = _roster_ids(api_client, source_tools="MIBiG")
        assert ids == {nrb_dataset["nrbs"]["mibig"].id}

    def test_source_names_narrows_through_assembly_source(self, api_client, nrb_dataset):
        ids = _roster_ids(api_client, source_names="MIBiG")
        assert ids == {nrb_dataset["nrbs"]["mibig"].id}

    def test_assembly_type(self, api_client, nrb_dataset):
        ids = _roster_ids(api_client, assembly_type="metagenome")
        assert ids == {
            nrb_dataset["nrbs"]["antismash"].id,
            nrb_dataset["nrbs"]["chain"].id,
        }

    def test_bgc_class(self, api_client, nrb_dataset):
        # Regression: bgc_class must filter on the chemical class path
        # held by source BGCs (``classification_path``), NOT on the NRB's
        # ``gene_cluster_family`` (which is the leaf cluster path written
        # by the clustering pipeline). Picking BGC class = Polyketide
        # against a fresh clustering returned 0 NRBs before this fix.
        ids = _roster_ids(api_client, bgc_class="Polyketide")
        assert ids == {nrb_dataset["nrbs"]["mibig"].id}

    def test_bgc_class_does_not_match_gene_cluster_family(
        self, api_client, nrb_dataset
    ):
        # If we set ``gene_cluster_family`` to look like a class path,
        # the bgc_class filter must still IGNORE it — only
        # source_bgcs.classification_path counts.
        nrb = nrb_dataset["nrbs"]["antismash"]
        nrb.gene_cluster_family = "Polyketide.foo"
        nrb.save()
        ids = _roster_ids(api_client, bgc_class="Polyketide")
        # Only the MIBiG NRB whose source BGC has classification_path
        # "Polyketide" should match — not the antiSMASH NRB whose
        # gene_cluster_family happens to start with "Polyketide".
        assert ids == {nrb_dataset["nrbs"]["mibig"].id}

    def test_assembly_accession(self, api_client, nrb_dataset):
        ids = _roster_ids(api_client, assembly_accession="GTDB_001")
        assert ids == {
            nrb_dataset["nrbs"]["antismash"].id,
            nrb_dataset["nrbs"]["chain"].id,
        }

    def test_bgc_accession_substring(self, api_client, nrb_dataset):
        ids = _roster_ids(api_client, bgc_accession="MGYB10000003")
        assert ids == {nrb_dataset["nrbs"]["chain"].id}

    def test_assembly_ids(self, api_client, nrb_dataset):
        mibig_id = nrb_dataset["assemblies"]["mibig"].id
        ids = _roster_ids(api_client, assembly_ids=str(mibig_id))
        assert ids == {nrb_dataset["nrbs"]["mibig"].id}

    def test_organism(self, api_client, nrb_dataset):
        ids = _roster_ids(api_client, organism="Streptomyces")
        assert ids == {
            nrb_dataset["nrbs"]["antismash"].id,
            nrb_dataset["nrbs"]["chain"].id,
        }

    def test_combined_filters_intersect(self, api_client, nrb_dataset):
        # Detector = antiSMASH AND bgc_class = RiPP → only the chain NRB.
        ids = _roster_ids(
            api_client,
            detector_tools="antiSMASH",
            bgc_class="RiPP",
        )
        assert ids == {nrb_dataset["nrbs"]["chain"].id}

    def test_chemont_ids(self, api_client, nrb_dataset):
        # Wire up a ChemOnt class on the MIBiG NRB's source BGC.
        bgc = DashboardBgc.objects.get(non_redundant_bgc=nrb_dataset["nrbs"]["mibig"])
        np_ = DashboardNaturalProduct.objects.create(
            name="erythromycin",
            smiles="CC(=O)O",
            np_class_path="Polyketide.Macrolide",
            bgc=bgc,
        )
        NaturalProductChemOntClass.objects.create(
            natural_product=np_,
            chemont_id="CHEMONTID:0000048",
            chemont_name="Macrolides",
        )
        ids = _roster_ids(api_client, chemont_ids="CHEMONTID:0000048")
        assert ids == {nrb_dataset["nrbs"]["mibig"].id}


@pytest.mark.django_db
class TestNrbScatterFilters:
    """Variables Map / UMAP must apply the same filter surface so the
    scatter stays in lockstep with the roster after Run Query."""

    def test_scatter_applies_detector_tools(self, api_client, nrb_dataset):
        resp = api_client.get(
            "/api/dashboard/nrbs/scatter/?detector_tools=MIBiG"
        )
        assert resp.status_code == 200
        data = json.loads(resp.content)
        ids = {p["id"] for p in data}
        assert ids == {nrb_dataset["nrbs"]["mibig"].id}

    def test_umap_applies_detector_tools(self, api_client, nrb_dataset):
        resp = api_client.get(
            "/api/dashboard/nrbs/umap/?detector_tools=MIBiG"
        )
        assert resp.status_code == 200
        data = json.loads(resp.content)
        ids = {p["id"] for p in data}
        assert ids == {nrb_dataset["nrbs"]["mibig"].id}
