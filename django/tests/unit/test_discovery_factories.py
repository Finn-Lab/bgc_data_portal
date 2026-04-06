"""Tests for discovery model factories."""

import pytest

from tests.factories.discovery_models import (
    BgcEmbeddingFactory,
    DashboardAssemblyFactory,
    DashboardBgcClassFactory,
    DashboardBgcFactory,
    DashboardContigFactory,
    DashboardDomainFactory,
    DashboardGCFFactory,
    DashboardMibigReferenceFactory,
    DashboardNaturalProductFactory,
)


@pytest.mark.django_db
class TestDiscoveryFactories:
    def test_assembly_factory(self):
        asm = DashboardAssemblyFactory()
        assert asm.pk is not None
        assert asm.assembly_accession.startswith("GCA_TEST_")
        assert 0.0 <= asm.bgc_diversity_score <= 1.0
        assert 0.0 <= asm.bgc_novelty_score <= 1.0
        assert 0.0 <= asm.bgc_density <= 1.0
        assert asm.l1_class_count >= 1

    def test_contig_factory(self):
        contig = DashboardContigFactory()
        assert contig.pk is not None
        assert contig.assembly is not None
        assert contig.length >= 50_000

    def test_bgc_factory(self):
        bgc = DashboardBgcFactory()
        assert bgc.pk is not None
        assert bgc.assembly is not None
        assert bgc.contig is not None
        assert bgc.classification_l1 in (
            "Polyketide", "NRP", "Alkaloid", "RiPP",
            "Terpene", "Saccharide", "Other",
        )
        assert bgc.size_kb >= 5.0
        assert bgc.end_position > bgc.start_position

    def test_gcf_factory(self):
        gcf = DashboardGCFFactory()
        assert gcf.pk is not None
        assert gcf.family_id.startswith("GCF_")
        assert gcf.member_count >= 3

    def test_natural_product_factory(self):
        np_ = DashboardNaturalProductFactory()
        assert np_.pk is not None
        assert np_.smiles
        assert np_.chemical_class_l1 in (
            "Polyketide", "NRP", "Alkaloid", "RiPP",
            "Terpene", "Saccharide", "Other",
        )
        assert np_.bgc is not None

    def test_mibig_reference_factory(self):
        ref = DashboardMibigReferenceFactory()
        assert ref.pk is not None
        assert ref.accession.startswith("BGC")
        assert ref.compound_name
        assert ref.embedding is not None
        assert len(ref.embedding) == 1152

    def test_bgc_embedding_factory(self):
        emb = BgcEmbeddingFactory()
        assert emb.bgc is not None
        assert emb.vector is not None
        assert len(emb.vector) == 1152

    def test_bgc_class_factory(self):
        cls = DashboardBgcClassFactory()
        assert cls.pk is not None
        assert cls.name in (
            "Polyketide", "NRP", "Alkaloid", "RiPP",
            "Terpene", "Saccharide", "Other",
        )
        assert cls.bgc_count >= 1

    def test_domain_factory(self):
        dom = DashboardDomainFactory()
        assert dom.pk is not None
        assert dom.acc.startswith("PF")
        assert dom.ref_db == "Pfam"
        assert dom.bgc_count >= 1
