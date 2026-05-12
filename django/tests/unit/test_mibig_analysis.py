"""Tests for the post-clustering MIBiG analysis artifacts.

Verifies:
  * TSV has the expected columns and only rows for MIBiG DashboardBgcs
    (is_validated=True with an NRB).
  * Per-leaf-cluster purity columns compute correctly.
  * Both Plotly HTMLs are written and contain the plotly.js marker.
  * Empty-MIBiG fallback: no TSV, no heatmap, but the monochrome UMAP HTML
    is still emitted and no exception is raised.
  * Artifact path is CLUSTERING_ARTIFACTS_DIR / <sha[:12]>/.
"""

from __future__ import annotations

import numpy as np
import pytest

from django.conf import settings

from discovery.models import (
    ClusteringRun,
    DashboardBgc,
    NonRedundantBGC,
)
from discovery.services.clustering.mibig_analysis import (
    emit_run_artifacts,
    _sample_background_coords,
)
from tests.factories.discovery_models import DashboardContigFactory


pytestmark = pytest.mark.django_db


def _bgc(contig, *, is_validated=False, classification_path=""):
    return DashboardBgc.objects.create(
        assembly=contig.assembly,
        contig=contig,
        bgc_accession=f"BGC{DashboardBgc.objects.count() + 1:07d}",
        start_position=1,
        end_position=10_000,
        is_validated=is_validated,
        classification_path=classification_path,
    )


def _nrb(contig, *, source_bgcs, start=1, end=10_000):
    nrb = NonRedundantBGC.objects.create(
        contig=contig, start_position=start, end_position=end,
        source_tools=["GECCO"],
    )
    DashboardBgc.objects.filter(id__in=[b.id for b in source_bgcs]).update(
        non_redundant_bgc=nrb,
    )
    return nrb


def _run(sha):
    return ClusteringRun.objects.create(
        sha256=sha, knn_k=5, seed=42,
        domain_sources=["PFAM", "NCBIFAM"], score_weights=[0.5, 0.5],
        leiden_resolutions=[0.03, 0.08, 0.15, 0.25],
    )


def test_artifact_dir_and_files_emitted_for_mibig_run(tmp_path, settings):
    settings.CLUSTERING_ARTIFACTS_DIR = tmp_path

    contig_a = DashboardContigFactory()
    contig_b = DashboardContigFactory()

    # Two Polyketide MIBiGs in leaf "cluster.0001.0001" (cluster A);
    # one NRP MIBiG in leaf "cluster.0002.0001" (cluster B);
    # one non-MIBiG NRB also in cluster A.
    poly_a = _bgc(contig_a, is_validated=True, classification_path="Polyketide.Macrolide")
    poly_b = _bgc(contig_a, is_validated=True, classification_path="Polyketide.PKSI")
    nrp = _bgc(contig_b, is_validated=True, classification_path="NRP.Glycopeptide")
    other = _bgc(contig_a, is_validated=False)

    nrb_a1 = _nrb(contig_a, source_bgcs=[poly_a])
    nrb_a2 = _nrb(contig_a, source_bgcs=[poly_b], start=20_000, end=30_000)
    nrb_b = _nrb(contig_b, source_bgcs=[nrp])
    nrb_other = _nrb(contig_a, source_bgcs=[other], start=40_000, end=50_000)

    run = _run("c" * 64)
    nrb_ids = np.array([nrb_a1.id, nrb_a2.id, nrb_b.id, nrb_other.id], dtype=np.int64)
    leaf_paths = [
        "cluster.0001.0001",
        "cluster.0001.0001",
        "cluster.0002.0001",
        "cluster.0001.0001",
    ]
    coords = np.array([
        [1.0, 1.0],
        [1.1, 1.1],
        [-5.0, -5.0],
        [1.2, 0.9],
    ])

    out_dir = emit_run_artifacts(run, nrb_ids=nrb_ids, leaf_paths=leaf_paths, coords=coords)
    assert out_dir == tmp_path / run.sha256[:12]
    assert out_dir.exists()

    tsv = out_dir / "mibig_validation.tsv"
    assert tsv.exists()
    content = tsv.read_text().splitlines()
    header = content[0].split("\t")
    assert "mibig_accession" in header
    assert "leaf_cluster_mibig_purity" in header
    assert "level_0_cluster" in header
    # Three MIBiG rows.
    assert len(content) == 4  # header + 3

    # The two Polyketide entries land in the same leaf → leaf size 2, purity 1.0
    # for both. The NRP entry is alone in its leaf → purity 1.0.
    purity_col = header.index("leaf_cluster_mibig_purity")
    purities = [float(row.split("\t")[purity_col]) for row in content[1:]]
    assert all(p == pytest.approx(1.0) for p in purities)

    umap_html = (out_dir / "umap_scatter.html").read_text()
    assert "plotly" in umap_html.lower()
    heatmap_html = (out_dir / "mibig_class_cluster_heatmap.html").read_text()
    assert "plotly" in heatmap_html.lower()


def test_background_sample_caps_non_mibig_and_keeps_all_mibig():
    # 10 NRBs total; ids 1..3 are MIBiG (always excluded from background — they
    # are drawn separately via per-class colored overlays), ids 4..10 are
    # non-MIBiG candidates for the gray cloud.
    nrb_lookup = {
        i: (f"cluster.{i:04d}", float(i), float(-i))
        for i in range(1, 11)
    }
    mibig_ids = {1, 2, 3}

    # Cap below the number of non-MIBiG NRBs forces sampling.
    sampled, total = _sample_background_coords(
        nrb_lookup, mibig_ids, cap=3, seed=42,
    )
    assert total == 7  # 10 − 3 MIBiG
    assert len(sampled) == 3
    sampled_xs = {x for x, _ in sampled}
    # No MIBiG coords leak into the gray background.
    for mibig_id in mibig_ids:
        mibig_x = float(mibig_id)
        assert mibig_x not in sampled_xs

    # Deterministic: same seed → identical sample order.
    sampled_again, _ = _sample_background_coords(
        nrb_lookup, mibig_ids, cap=3, seed=42,
    )
    assert sampled == sampled_again

    # Different seeds typically yield different subsets.
    sampled_other, _ = _sample_background_coords(
        nrb_lookup, mibig_ids, cap=3, seed=7,
    )
    assert sampled_other != sampled

    # Cap >= total non-MIBiG: returns every non-MIBiG NRB, no random draw.
    sampled_full, total_full = _sample_background_coords(
        nrb_lookup, mibig_ids, cap=100, seed=42,
    )
    assert total_full == 7
    assert len(sampled_full) == 7


def test_empty_mibig_fallback_only_emits_umap(tmp_path, settings):
    settings.CLUSTERING_ARTIFACTS_DIR = tmp_path

    contig = DashboardContigFactory()
    bgc = _bgc(contig, is_validated=False)
    nrb = _nrb(contig, source_bgcs=[bgc])

    run = _run("d" * 64)
    nrb_ids = np.array([nrb.id], dtype=np.int64)
    leaf_paths = ["cluster.0001"]
    coords = np.array([[0.0, 0.0]])

    out_dir = emit_run_artifacts(run, nrb_ids=nrb_ids, leaf_paths=leaf_paths, coords=coords)

    assert (out_dir / "umap_scatter.html").exists()
    assert not (out_dir / "mibig_validation.tsv").exists()
    assert not (out_dir / "mibig_class_cluster_heatmap.html").exists()
