"""Integration tests for the Discovery Platform API endpoints.

All data is seeded using discovery models directly — no mgnify_bgcs dependencies.
"""

import json

import numpy as np
import pytest
from django.test import Client

from discovery.models import (
    BgcEmbedding,
    DashboardAssembly,
    DashboardBgc,
    DashboardBgcClass,
    DashboardContig,
    DashboardDomain,
    DashboardMibigReference,
    DashboardNaturalProduct,
)


@pytest.fixture
def api_client():
    return Client()


def _make_assembly(accession, taxonomy_path, is_type_strain=False, **kwargs):
    defaults = {
        "organism_name": f"Organism {accession}",
        "dominant_taxonomy_path": taxonomy_path,
        "dominant_taxonomy_label": f"Label {accession}",
        "biome_path": "root.Environmental.Terrestrial.Soil",
        "assembly_size_mb": 8.5,
        "assembly_quality": 0.95,
        "is_type_strain": is_type_strain,
        "bgc_count": 0,
        "l1_class_count": 0,
        "bgc_diversity_score": 0.6,
        "bgc_novelty_score": 0.4,
        "bgc_density": 0.3,
        "taxonomic_novelty": 0.5,
    }
    defaults.update(kwargs)
    return DashboardAssembly.objects.create(
        assembly_accession=accession,
        source_assembly_id=abs(hash(accession)) % 1_000_000,
        **defaults,
    )


def _make_contig(assembly, idx=0, taxonomy_path=""):
    return DashboardContig.objects.create(
        assembly=assembly,
        accession=f"CONTIG_{assembly.assembly_accession}_{idx}",
        length=100_000,
        taxonomy_path=taxonomy_path or assembly.dominant_taxonomy_path,
        source_contig_id=abs(hash(f"{assembly.pk}_{idx}")) % 1_000_000,
    )


def _make_bgc(assembly, contig, idx=0, class_l1="Polyketide"):
    return DashboardBgc.objects.create(
        assembly=assembly,
        contig=contig,
        bgc_accession=f"MGYB{abs(hash(f'{assembly.pk}_{idx}')):08d}.ANT.1.01",
        contig_accession=contig.accession,
        start_position=1000,
        end_position=20000,
        classification_path=class_l1,
        classification_l1=class_l1,
        novelty_score=0.35,
        domain_novelty=0.2,
        size_kb=19.0,
        nearest_mibig_accession="BGC0000001",
        nearest_mibig_distance=0.65,
        umap_x=1.0 + idx,
        umap_y=2.0 + idx,
        source_bgc_id=abs(hash(f"bgc_{assembly.pk}_{idx}")) % 1_000_000,
    )


@pytest.fixture
def seeded_data():
    """Create a minimal test dataset using discovery models exclusively."""
    tax_strepto = "Bacteria.Actinomycetota.Actinomycetia.Streptomycetales.Streptomycetaceae.Streptomyces"
    tax_pseudo = "Bacteria.Pseudomonadota.Gammaproteobacteria.Pseudomonadales.Pseudomonadaceae.Pseudomonas"

    a1 = _make_assembly("TEST_ERZ001", tax_strepto, is_type_strain=True)
    a2 = _make_assembly("TEST_ERZ002", tax_pseudo)

    c1 = _make_contig(a1, 0, tax_strepto)
    c2 = _make_contig(a2, 0, tax_pseudo)

    bgc1 = _make_bgc(a1, c1, 0, "Polyketide")
    bgc2 = _make_bgc(a1, c1, 1, "NRP")
    bgc3 = _make_bgc(a2, c2, 0, "RiPP")

    # Update assembly bgc_count
    a1.bgc_count = 2
    a1.l1_class_count = 2
    a1.save()
    a2.bgc_count = 1
    a2.l1_class_count = 1
    a2.save()

    # Embeddings for similarity queries
    vec1 = np.random.randn(1152).astype(np.float32).tolist()
    vec2 = np.random.randn(1152).astype(np.float32).tolist()
    vec3 = np.random.randn(1152).astype(np.float32).tolist()
    BgcEmbedding.objects.create(bgc=bgc1, vector=vec1)
    BgcEmbedding.objects.create(bgc=bgc2, vector=vec2)
    BgcEmbedding.objects.create(bgc=bgc3, vector=vec3)

    # MIBiG reference
    DashboardMibigReference.objects.create(
        accession="BGC0000001",
        compound_name="erythromycin",
        bgc_class="Polyketide",
        umap_x=-5.0,
        umap_y=3.0,
    )

    # Natural product
    DashboardNaturalProduct.objects.create(
        name="test_compound",
        smiles="CC(=O)O",
        chemical_class_l1="Polyketide",
        chemical_class_l2="Macrolide",
        bgc=bgc1,
    )

    # BGC class catalog
    DashboardBgcClass.objects.create(name="Polyketide", bgc_count=2)
    DashboardBgcClass.objects.create(name="NRP", bgc_count=1)
    DashboardBgcClass.objects.create(name="RiPP", bgc_count=1)

    # Domain catalog
    DashboardDomain.objects.create(acc="PF00109", name="Beta-ketoacyl synthase", ref_db="Pfam", bgc_count=1)

    return {
        "assemblies": [a1, a2],
        "bgcs": [bgc1, bgc2, bgc3],
    }


@pytest.mark.django_db
class TestAssemblyRoster:
    def test_returns_paginated_list(self, api_client, seeded_data):
        r = api_client.get("/api/dashboard/assemblies/")
        assert r.status_code == 200
        data = json.loads(r.content)
        assert "items" in data
        assert "pagination" in data
        assert data["pagination"]["total_count"] == 2

    def test_pagination(self, api_client, seeded_data):
        r = api_client.get("/api/dashboard/assemblies/?page=1&page_size=1")
        data = json.loads(r.content)
        assert len(data["items"]) == 1
        assert data["pagination"]["total_pages"] == 2

    def test_type_strain_filter(self, api_client, seeded_data):
        r = api_client.get("/api/dashboard/assemblies/?type_strain_only=true")
        data = json.loads(r.content)
        assert data["pagination"]["total_count"] == 1
        assert data["items"][0]["is_type_strain"] is True

    def test_taxonomy_filter(self, api_client, seeded_data):
        r = api_client.get("/api/dashboard/assemblies/?taxonomy_path=Bacteria.Pseudomonadota")
        data = json.loads(r.content)
        assert data["pagination"]["total_count"] == 1

    def test_search(self, api_client, seeded_data):
        r = api_client.get("/api/dashboard/assemblies/?search=TEST_ERZ001")
        data = json.loads(r.content)
        assert data["pagination"]["total_count"] == 1

    def test_sort_by_bgc_count(self, api_client, seeded_data):
        r = api_client.get("/api/dashboard/assemblies/?sort_by=bgc_count&order=desc")
        data = json.loads(r.content)
        assert data["items"][0]["bgc_count"] >= data["items"][1]["bgc_count"]


@pytest.mark.django_db
class TestAssemblyDetail:
    def test_returns_detail(self, api_client, seeded_data):
        aid = seeded_data["assemblies"][0].id
        r = api_client.get(f"/api/dashboard/assemblies/{aid}/")
        assert r.status_code == 200
        data = json.loads(r.content)
        assert data["accession"] == "TEST_ERZ001"
        assert data["assembly_size_mb"] == 8.5
        assert data["is_type_strain"] is True

    def test_404_for_missing(self, api_client, seeded_data):
        r = api_client.get("/api/dashboard/assemblies/99999/")
        assert r.status_code == 404


@pytest.mark.django_db
class TestAssemblyBgcRoster:
    def test_returns_bgcs_for_assembly(self, api_client, seeded_data):
        aid = seeded_data["assemblies"][0].id
        r = api_client.get(f"/api/dashboard/assemblies/{aid}/bgcs/")
        assert r.status_code == 200
        data = json.loads(r.content)
        assert len(data) == 2

    def test_empty_for_unknown(self, api_client, seeded_data):
        r = api_client.get("/api/dashboard/assemblies/99999/bgcs/")
        assert r.status_code == 200
        assert json.loads(r.content) == []


@pytest.mark.django_db
class TestAssemblyScatter:
    def test_returns_points(self, api_client, seeded_data):
        r = api_client.get("/api/dashboard/assembly-scatter/")
        assert r.status_code == 200
        data = json.loads(r.content)
        assert len(data) == 2
        assert "x" in data[0]
        assert "y" in data[0]
        assert "dominant_taxonomy_label" in data[0]

    def test_bad_axis_returns_400(self, api_client, seeded_data):
        r = api_client.get("/api/dashboard/assembly-scatter/?x_axis=invalid")
        assert r.status_code == 400


@pytest.mark.django_db
class TestBgcDetail:
    def test_returns_detail(self, api_client, seeded_data):
        bid = seeded_data["bgcs"][0].id
        r = api_client.get(f"/api/dashboard/bgcs/{bid}/")
        assert r.status_code == 200
        data = json.loads(r.content)
        assert data["classification_l1"] == "Polyketide"
        assert data["parent_assembly"] is not None
        assert data["parent_assembly"]["accession"] == "TEST_ERZ001"

    def test_404_for_missing(self, api_client, seeded_data):
        r = api_client.get("/api/dashboard/bgcs/99999/")
        assert r.status_code == 404


@pytest.mark.django_db
class TestBgcScatter:
    def test_returns_bgc_and_mibig_points(self, api_client, seeded_data):
        r = api_client.get("/api/dashboard/bgc-scatter/?include_mibig=true")
        assert r.status_code == 200
        data = json.loads(r.content)
        mibig = [p for p in data if p["is_mibig"]]
        bgcs = [p for p in data if not p["is_mibig"]]
        assert len(mibig) == 1
        assert len(bgcs) == 3

    def test_without_mibig(self, api_client, seeded_data):
        r = api_client.get("/api/dashboard/bgc-scatter/?include_mibig=false")
        data = json.loads(r.content)
        assert all(not p["is_mibig"] for p in data)


@pytest.mark.django_db
class TestSimilarBgcQuery:
    def test_finds_similar(self, api_client, seeded_data):
        bid = seeded_data["bgcs"][0].id
        r = api_client.post(
            f"/api/dashboard/query/similar-bgc/{bid}/?max_distance=2.0",
            content_type="application/json",
        )
        assert r.status_code == 200
        data = json.loads(r.content)
        assert "items" in data
        assert all(item["id"] != bid for item in data["items"])

    def test_400_for_missing_embedding(self, api_client, seeded_data):
        # Create a BGC without an embedding
        a = seeded_data["assemblies"][0]
        c = a.contigs.first()
        bgc = DashboardBgc.objects.create(
            assembly=a, contig=c,
            bgc_accession="MGYB_NO_EMB.ANT.1.01",
            contig_accession=c.accession,
            start_position=1, end_position=100,
            source_bgc_id=999999,
        )
        r = api_client.post(
            f"/api/dashboard/query/similar-bgc/{bgc.id}/?max_distance=2.0",
            content_type="application/json",
        )
        assert r.status_code == 400


@pytest.mark.django_db
class TestFilters:
    def test_taxonomy_tree(self, api_client, seeded_data):
        r = api_client.get("/api/dashboard/filters/taxonomy/")
        assert r.status_code == 200
        data = json.loads(r.content)
        assert len(data) > 0
        assert data[0]["rank"] == "kingdom"

    def test_bgc_classes(self, api_client, seeded_data):
        r = api_client.get("/api/dashboard/filters/bgc-classes/")
        assert r.status_code == 200
        data = json.loads(r.content)
        names = {c["name"] for c in data}
        assert "Polyketide" in names

    def test_np_classes(self, api_client, seeded_data):
        r = api_client.get("/api/dashboard/filters/np-classes/")
        assert r.status_code == 200
        data = json.loads(r.content)
        assert len(data) > 0

    def test_domain_list(self, api_client, seeded_data):
        r = api_client.get("/api/dashboard/filters/domains/")
        assert r.status_code == 200
        data = json.loads(r.content)
        assert "items" in data
        assert "pagination" in data


@pytest.mark.django_db
class TestExports:
    def test_assembly_csv_export(self, api_client, seeded_data):
        ids = [a.id for a in seeded_data["assemblies"]]
        r = api_client.post(
            "/api/dashboard/shortlist/assembly/export/",
            data=json.dumps({"ids": ids}),
            content_type="application/json",
        )
        assert r.status_code == 200
        assert r["Content-Type"] == "text/csv"
        assert "assembly_shortlist.csv" in r["Content-Disposition"]
        content = r.content.decode()
        assert "accession" in content
        assert "TEST_ERZ001" in content

    def test_assembly_export_empty_ids(self, api_client, seeded_data):
        r = api_client.post(
            "/api/dashboard/shortlist/assembly/export/",
            data=json.dumps({"ids": []}),
            content_type="application/json",
        )
        assert r.status_code == 400

    def test_assembly_export_max_20(self, api_client, seeded_data):
        r = api_client.post(
            "/api/dashboard/shortlist/assembly/export/",
            data=json.dumps({"ids": list(range(1, 25))}),
            content_type="application/json",
        )
        assert r.status_code == 400
