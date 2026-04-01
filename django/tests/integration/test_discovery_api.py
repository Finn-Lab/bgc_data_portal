"""Integration tests for the Discovery Platform API endpoints."""

import json

import pytest
from django.test import Client

from mgnify_bgcs.models import Assembly, Bgc, BgcClass, BgcBgcClass, Contig, Domain, Protein, Cds, ProteinDomain, GeneCaller
from discovery.models import (
    BgcScore,
    GCF,
    GCFMembership,
    GenomeScore,
    MibigReference,
    NaturalProduct,
)

import numpy as np


@pytest.fixture
def api_client():
    return Client()


def _make_assembly(accession, family="Streptomycetaceae", is_type_strain=False):
    return Assembly.objects.create(
        accession=accession,
        taxonomy_kingdom="Bacteria",
        taxonomy_phylum="Actinomycetota",
        taxonomy_class="Actinomycetes",
        taxonomy_order="Streptomycetales",
        taxonomy_family=family,
        taxonomy_genus="Streptomyces",
        taxonomy_species="Streptomyces coelicolor",
        organism_name=f"S. coelicolor {accession}",
        is_type_strain=is_type_strain,
        genome_size_mb=8.5,
        genome_quality=0.95,
    )


def _make_bgc(assembly, idx=0, class_name="Polyketide"):
    contig = Contig.objects.create(
        assembly=assembly,
        sequence_sha256=f"test_sha_{assembly.accession}_{idx}",
        mgyc=f"MGYC_test_{assembly.accession}_{idx}",
        length=100000,
        sequence="ACGT" * 25000,
    )
    bgc = Bgc.objects.create(
        contig=contig,
        identifier=f"test_bgc_{assembly.accession}_{idx}",
        start_position=1000,
        end_position=20000,
        embedding=np.random.randn(1152).astype(np.float32).tolist(),
        metadata={"umap_x_coord": 1.0 + idx, "umap_y_coord": 2.0 + idx},
    )
    bc, _ = BgcClass.objects.get_or_create(name=class_name)
    BgcBgcClass.objects.create(bgc=bgc, bgc_class=bc)
    return bgc


def _score_assembly(assembly, bgcs):
    GenomeScore.objects.create(
        assembly=assembly,
        bgc_count=len(bgcs),
        bgc_diversity_score=0.6,
        bgc_novelty_score=0.4,
        bgc_density=0.3,
        taxonomic_novelty=0.5,
        genome_quality=0.9,
        l1_class_count=2,
    )


def _score_bgc(bgc, classification_l1="Polyketide"):
    BgcScore.objects.create(
        bgc=bgc,
        novelty_score=0.35,
        domain_novelty=0.2,
        nearest_mibig_accession="BGC0000001",
        nearest_mibig_distance=0.65,
        size_kb=19.0,
        classification_l1=classification_l1,
    )


@pytest.fixture
def seeded_data():
    """Create a minimal test dataset."""
    a1 = _make_assembly("TEST_ERZ001", family="Streptomycetaceae", is_type_strain=True)
    a2 = _make_assembly("TEST_ERZ002", family="Pseudomonadaceae")

    bgc1 = _make_bgc(a1, 0, "Polyketide")
    bgc2 = _make_bgc(a1, 1, "NRP")
    bgc3 = _make_bgc(a2, 0, "RiPP")

    _score_assembly(a1, [bgc1, bgc2])
    _score_assembly(a2, [bgc3])

    _score_bgc(bgc1, "Polyketide")
    _score_bgc(bgc2, "NRP")
    _score_bgc(bgc3, "RiPP")

    MibigReference.objects.create(
        accession="BGC0000001",
        compound_name="erythromycin",
        bgc_class="Polyketide",
        umap_x=-5.0,
        umap_y=3.0,
    )

    NaturalProduct.objects.create(
        name="test_compound",
        smiles="CC(=O)O",
        chemical_class_l1="Polyketide",
        chemical_class_l2="Macrolide",
        bgc=bgc1,
    )

    return {
        "assemblies": [a1, a2],
        "bgcs": [bgc1, bgc2, bgc3],
    }


_WEIGHT_QS = "w_diversity=0.25&w_novelty=0.4&w_density=0.15&w_taxonomic=0.1&w_quality=0.1"


@pytest.mark.django_db
class TestGenomeRoster:
    def test_returns_paginated_list(self, api_client, seeded_data):
        r = api_client.get(f"/api/dashboard/genomes/?{_WEIGHT_QS}")
        assert r.status_code == 200
        data = json.loads(r.content)
        assert "items" in data
        assert "pagination" in data
        assert data["pagination"]["total_count"] == 2

    def test_pagination(self, api_client, seeded_data):
        r = api_client.get(f"/api/dashboard/genomes/?page=1&page_size=1&{_WEIGHT_QS}")
        data = json.loads(r.content)
        assert len(data["items"]) == 1
        assert data["pagination"]["total_pages"] == 2

    def test_type_strain_filter(self, api_client, seeded_data):
        r = api_client.get(f"/api/dashboard/genomes/?type_strain_only=true&{_WEIGHT_QS}")
        data = json.loads(r.content)
        assert data["pagination"]["total_count"] == 1
        assert data["items"][0]["is_type_strain"] is True

    def test_taxonomy_filter(self, api_client, seeded_data):
        r = api_client.get(f"/api/dashboard/genomes/?taxonomy_family=Pseudomonadaceae&{_WEIGHT_QS}")
        data = json.loads(r.content)
        assert data["pagination"]["total_count"] == 1

    def test_search(self, api_client, seeded_data):
        r = api_client.get(f"/api/dashboard/genomes/?search=TEST_ERZ001&{_WEIGHT_QS}")
        data = json.loads(r.content)
        assert data["pagination"]["total_count"] == 1

    def test_sort_by_bgc_count(self, api_client, seeded_data):
        r = api_client.get(f"/api/dashboard/genomes/?sort_by=bgc_count&order=desc&{_WEIGHT_QS}")
        data = json.loads(r.content)
        assert data["items"][0]["bgc_count"] >= data["items"][1]["bgc_count"]


@pytest.mark.django_db
class TestGenomeDetail:
    def test_returns_detail(self, api_client, seeded_data):
        aid = seeded_data["assemblies"][0].id
        r = api_client.get(f"/api/dashboard/genomes/{aid}/?{_WEIGHT_QS}")
        assert r.status_code == 200
        data = json.loads(r.content)
        assert data["accession"] == "TEST_ERZ001"
        assert data["genome_size_mb"] == 8.5
        assert data["is_type_strain"] is True

    def test_404_for_missing(self, api_client, seeded_data):
        r = api_client.get(f"/api/dashboard/genomes/99999/?{_WEIGHT_QS}")
        assert r.status_code == 404


@pytest.mark.django_db
class TestGenomeBgcRoster:
    def test_returns_bgcs_for_genome(self, api_client, seeded_data):
        aid = seeded_data["assemblies"][0].id
        r = api_client.get(f"/api/dashboard/genomes/{aid}/bgcs/")
        assert r.status_code == 200
        data = json.loads(r.content)
        assert len(data) == 2

    def test_empty_for_unknown(self, api_client, seeded_data):
        r = api_client.get("/api/dashboard/genomes/99999/bgcs/")
        assert r.status_code == 200
        assert json.loads(r.content) == []


@pytest.mark.django_db
class TestGenomeScatter:
    def test_returns_points(self, api_client, seeded_data):
        r = api_client.get(f"/api/dashboard/genome-scatter/?{_WEIGHT_QS}")
        assert r.status_code == 200
        data = json.loads(r.content)
        assert len(data) == 2
        assert "x" in data[0]
        assert "y" in data[0]
        assert "composite_score" in data[0]

    def test_bad_axis_returns_400(self, api_client, seeded_data):
        r = api_client.get(f"/api/dashboard/genome-scatter/?x_axis=invalid&{_WEIGHT_QS}")
        assert r.status_code == 400


@pytest.mark.django_db
class TestBgcDetail:
    def test_returns_detail(self, api_client, seeded_data):
        bid = seeded_data["bgcs"][0].id
        r = api_client.get(f"/api/dashboard/bgcs/{bid}/")
        assert r.status_code == 200
        data = json.loads(r.content)
        assert data["classification_l1"] == "Polyketide"
        assert data["parent_genome"] is not None
        assert data["parent_genome"]["accession"] == "TEST_ERZ001"

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
            f"/api/dashboard/query/similar-bgc/{bid}/?max_distance=2.0&w_similarity=0.4&w_novelty=0.3&w_completeness=0.15&w_domain_novelty=0.15",
            content_type="application/json",
        )
        assert r.status_code == 200
        data = json.loads(r.content)
        assert "items" in data
        # All items should not include the source BGC
        assert all(item["id"] != bid for item in data["items"])

    def test_404_for_missing_bgc(self, api_client, seeded_data):
        r = api_client.post(
            "/api/dashboard/query/similar-bgc/99999/?w_similarity=0.4&w_novelty=0.3&w_completeness=0.15&w_domain_novelty=0.15",
            content_type="application/json",
        )
        assert r.status_code == 404


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
    def test_genome_csv_export(self, api_client, seeded_data):
        ids = [a.id for a in seeded_data["assemblies"]]
        r = api_client.post(
            "/api/dashboard/shortlist/genome/export/",
            data=json.dumps({"ids": ids}),
            content_type="application/json",
        )
        assert r.status_code == 200
        assert r["Content-Type"] == "text/csv"
        assert "genome_shortlist.csv" in r["Content-Disposition"]
        content = r.content.decode()
        assert "accession" in content
        assert "TEST_ERZ001" in content

    def test_genome_export_empty_ids(self, api_client, seeded_data):
        r = api_client.post(
            "/api/dashboard/shortlist/genome/export/",
            data=json.dumps({"ids": []}),
            content_type="application/json",
        )
        assert r.status_code == 400

    def test_genome_export_max_20(self, api_client, seeded_data):
        r = api_client.post(
            "/api/dashboard/shortlist/genome/export/",
            data=json.dumps({"ids": list(range(1, 25))}),
            content_type="application/json",
        )
        assert r.status_code == 400
