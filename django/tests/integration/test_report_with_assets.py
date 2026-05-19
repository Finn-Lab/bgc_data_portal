"""Report payload assembly with asset NRB rows + domain hits.

Pins the contract that ``build_report_payload`` weaves asset roster rows
and asset domain-hit rows into the panels that previously skipped them:
domain composition, domain × GO slim matrix, GCF distribution, and the
source distribution (asset NRBs collapse into a single 'Assets' bucket).
"""

from __future__ import annotations

import hashlib

import pytest

from discovery.models import (
    AssemblySource,
    AssemblyType,
    BgcDomain,
    DashboardAssembly,
    DashboardBgc,
    DashboardContig,
    DashboardDetector,
    NonRedundantBGC,
)
from discovery.services.report import build_report_payload


def _make_persistent_nrb_with_domain():
    """One persisted NRB with a single BgcDomain row carrying a known slim."""
    src = AssemblySource.objects.create(name="GTDB")
    assembly = DashboardAssembly.objects.create(
        assembly_accession="A1",
        organism_name="Streptomyces test",
        source=src,
        assembly_type=AssemblyType.GENOME,
        biome_path="root.Env",
    )
    contig = DashboardContig.objects.create(
        assembly=assembly,
        sequence_sha256=hashlib.sha256(b"c1").hexdigest(),
        accession="CONTIG_1",
        length=100_000,
        taxonomy_path="Bacteria.Actinomycetota",
    )
    detector = DashboardDetector.objects.create(
        name="antiSMASH v7.1",
        tool="antiSMASH",
        version="7.1.0",
        tool_name_code="ANT",
        version_sort_key=710,
    )
    nrb = NonRedundantBGC.objects.create(
        contig=contig,
        start_position=1_000,
        end_position=15_000,
        source_tools=["antiSMASH"],
        gene_cluster_family="Polyketide",
        umap_x=1.0,
        umap_y=2.0,
        umap_projected=False,
        novelty_score=0.4,
        domain_novelty=0.2,
    )
    bgc = DashboardBgc.objects.create(
        assembly=assembly,
        contig=contig,
        bgc_accession="MGYB10000001.ANT.1.01",
        start_position=1_000,
        end_position=15_000,
        classification_path="Polyketide",
        detector=detector,
        non_redundant_bgc=nrb,
    )
    BgcDomain.objects.create(
        bgc=bgc,
        domain_acc="PF00001",
        domain_name="Pf001",
        domain_description="GPCR-like",
        ref_db="Pfam",
        start_position=0,
        end_position=100,
        go_slim=["Signal transducer activity"],
    )
    return nrb


@pytest.mark.django_db
def test_assets_feed_domain_gcf_and_source_panels():
    """Persisted NRB sharing one Pfam with an asset NRB; both must appear in
    the domain composition tiers, GO slim matrix, GCF distribution, and the
    source distribution (asset under 'Assets')."""
    nrb = _make_persistent_nrb_with_domain()

    asset_id = -1
    asset_rows = [
        {
            "id": asset_id,
            "label": "NRB-A1",
            "classification_path": "RiPP",
            "size_kb": 12.0,
            "n_source_bgcs": 1,
            "source_tools": ["SanntiS"],
            "novelty_score": 0.7,
            "domain_novelty": 0.5,
            "is_partial": False,
            "is_validated": False,
            "is_type_strain": False,
            "umap_projected": True,
            "umap_x": 0.0,
            "umap_y": 0.0,
            "parent_assembly_id": None,
            "parent_assembly_accession": "ASSET_ASM",
            "organism_name": "Asset organism",
            "contig_accession": "ASSET_CONTIG",
            "is_asset": True,
        }
    ]
    domain_hits = [
        # Shared with the persisted NRB → should sit in the same composition
        # row and drive a non-zero "Signal transducer activity" matrix cell.
        {
            "nrb_id": asset_id,
            "domain_acc": "PF00001",
            "domain_name": "Pf001",
            "domain_description": "GPCR-like",
            "go_slim": ["Signal transducer activity"],
        },
        # Asset-only domain → should still show in the composition table.
        {
            "nrb_id": asset_id,
            "domain_acc": "PF00009",
            "domain_name": "Pf009",
            "domain_description": "Asset-only",
            "go_slim": ["Catalytic activity"],
        },
    ]

    payload = build_report_payload(
        [nrb.id, asset_id],
        extra_nrb_rows=asset_rows,
        extra_domain_rows=domain_hits,
    )

    # ── Domain composition ────────────────────────────────────────────────
    composition_accs = {row["domain_acc"] for row in payload["domain_composition"]["rows"]}
    assert {"PF00001", "PF00009"}.issubset(composition_accs)

    shared_row = next(
        r for r in payload["domain_composition"]["rows"] if r["domain_acc"] == "PF00001"
    )
    # Shared Pfam hit by both NRBs (1 persisted + 1 asset of 2 total).
    assert shared_row["nrb_count"] == 2

    # ── Domain × GO slim matrix ───────────────────────────────────────────
    matrix = payload["domain_goslim_matrix"]
    sig_cell = next(
        c for c in matrix["cells"] if c["category"] == "Signal transducer activity"
    )
    assert sig_cell["count"] >= 1
    # Asset's catalytic-activity Pfam must surface as a category too.
    assert "Catalytic activity" in matrix["categories"]

    # ── GCF distribution ──────────────────────────────────────────────────
    gcf_paths = {row["classification_path"] for row in payload["gcf_distribution"]}
    assert "Polyketide" in gcf_paths  # from persisted NRB
    assert "RiPP" in gcf_paths        # from asset's KNN-projected classification

    # ── Source distribution ───────────────────────────────────────────────
    source_buckets = {row["name"]: row["count"] for row in payload["source_distribution"]}
    assert source_buckets.get("GTDB") == 1   # persisted NRB's collection
    assert source_buckets.get("Assets") == 1  # single bucket for asset NRBs


@pytest.mark.django_db
def test_unclassified_asset_goes_into_unclassified_bucket():
    """An asset NRB whose KNN projection didn't yield a leaf path must still
    appear in the GCF distribution, falling into '(unclassified)'."""
    nrb = _make_persistent_nrb_with_domain()
    asset_rows = [
        {
            "id": -2,
            "label": "NRB-A2",
            "classification_path": "",  # no projection
            "size_kb": 5.0,
            "n_source_bgcs": 1,
            "source_tools": ["GECCO"],
            "novelty_score": None,
            "domain_novelty": None,
            "is_partial": False,
            "is_validated": False,
            "is_type_strain": False,
            "umap_projected": False,
            "umap_x": None,
            "umap_y": None,
            "parent_assembly_accession": "ASSET_ASM2",
            "organism_name": "Asset organism 2",
            "contig_accession": "ASSET_CONTIG_2",
            "is_asset": True,
        }
    ]
    payload = build_report_payload(
        [nrb.id, -2],
        extra_nrb_rows=asset_rows,
        extra_domain_rows=[],
    )
    gcf_buckets = {row["classification_path"]: row["nrb_count"] for row in payload["gcf_distribution"]}
    assert gcf_buckets.get("(unclassified)") == 1
    source_buckets = {row["name"]: row["count"] for row in payload["source_distribution"]}
    assert source_buckets.get("Assets") == 1
