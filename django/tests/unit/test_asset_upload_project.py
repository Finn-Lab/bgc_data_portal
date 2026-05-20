"""Asset projection unit tests — covers virtual-iBGC construction and
KNN projection against a synthetic primary scoring cache.

The projection step pulls the latest ``ClusteringRun`` row from the DB and
its scoring cache from disk. We stub both with a tiny in-memory primary
universe to keep the test hermetic.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest
import scipy.sparse as sp

from discovery.services.asset_upload.matrices import (
    build_asset_adjacency_pair_matrix,
    build_asset_domain_matrix,
)
from discovery.services.asset_upload.project import (
    VirtualIbgc,
    build_virtual_ibgcs,
)
from discovery.services.asset_upload.schemas import (
    AssetAssembly,
    AssetBgc,
    AssetCds,
    AssetContig,
    AssetData,
    AssetDetector,
    AssetDomain,
)


def _seed_data() -> AssetData:
    data = AssetData()
    data.assemblies.append(
        AssetAssembly(
            assembly_accession="A1",
            organism_name="Foo bar",
            biome_path="root.Env",
            is_type_strain=True,
        )
    )
    data.contigs.append(
        AssetContig(assembly_accession="A1", sequence_sha256="c1", accession="C1")
    )
    data.detectors.extend(
        [
            AssetDetector(name="antiSMASH:1", tool="antiSMASH", version="1.0"),
            AssetDetector(name="GECCO v1", tool="GECCO", version="1.0"),
            AssetDetector(name="SanntiS v1", tool="SanntiS", version="1.0"),
        ]
    )
    data.bgcs.extend(
        [
            AssetBgc(
                contig_sha256="c1",
                detector_name="GECCO v1",
                start_position=0,
                end_position=500,
            ),
            AssetBgc(
                contig_sha256="c1",
                detector_name="SanntiS v1",
                start_position=100,
                end_position=600,
            ),
            AssetBgc(
                contig_sha256="c1",
                detector_name="antiSMASH:1",
                start_position=2000,
                end_position=2500,
            ),
        ]
    )
    data.cds.extend(
        [
            AssetCds(
                bgc_key=("c1", 0, 500, "GECCO v1"),
                protein_id_str="P1",
                start_position=10,
                end_position=200,
                strand=1,
            ),
            AssetCds(
                bgc_key=("c1", 0, 500, "GECCO v1"),
                protein_id_str="P2",
                start_position=200,
                end_position=400,
                strand=1,
            ),
            AssetCds(
                bgc_key=("c1", 100, 600, "SanntiS v1"),
                protein_id_str="P3",
                start_position=110,
                end_position=400,
                strand=1,
            ),
            AssetCds(
                bgc_key=("c1", 2000, 2500, "antiSMASH:1"),
                protein_id_str="P4",
                start_position=2010,
                end_position=2200,
                strand=1,
            ),
        ]
    )
    data.domains.extend(
        [
            AssetDomain(
                bgc_key=("c1", 0, 500, "GECCO v1"),
                cds_protein_id="P1",
                domain_acc="PF00001",
                ref_db="Pfam",
                start_position=0,
                end_position=100,
            ),
            AssetDomain(
                bgc_key=("c1", 0, 500, "GECCO v1"),
                cds_protein_id="P2",
                domain_acc="PF00002",
                ref_db="Pfam",
                start_position=0,
                end_position=100,
            ),
            AssetDomain(
                bgc_key=("c1", 2000, 2500, "antiSMASH:1"),
                cds_protein_id="P4",
                domain_acc="PF00003",
                ref_db="Pfam",
                start_position=0,
                end_position=100,
            ),
        ]
    )
    return data


def test_build_virtual_ibgcs_chains_gecco_sanntis():
    """Overlapping GECCO + SanntiS predictions merge into one iBGC; standalone
    antiSMASH becomes its own iBGC. Both get negative ids."""
    virtual = build_virtual_ibgcs(_seed_data())
    assert len(virtual) == 2

    chain = next(v for v in virtual if "SanntiS" in v.source_tools)
    assert sorted(chain.source_tools) == ["GECCO", "SanntiS"]
    assert chain.start_position == 0
    assert chain.end_position == 600
    assert {b.detector_name for b in chain.member_bgcs} == {"GECCO v1", "SanntiS v1"}
    assert chain.neg_id < 0

    antismash = next(v for v in virtual if "antiSMASH" in v.source_tools and "GECCO" not in v.source_tools)
    assert antismash.start_position == 2000
    assert antismash.end_position == 2500
    assert antismash.neg_id < 0
    assert chain.neg_id != antismash.neg_id

    # Domains + CDS got attached to the correct virtual iBGC.
    assert {d.domain_acc for d in chain.domains} == {"PF00001", "PF00002"}
    assert {d.domain_acc for d in antismash.domains} == {"PF00003"}


def test_asset_domain_matrix_uses_fixed_vocab():
    virtual = build_virtual_ibgcs(_seed_data())
    dom_accs = ["PF00001", "PF00002", "PF00099"]  # PF00099 absent in upload
    M = build_asset_domain_matrix(virtual, sources=("PFAM",), domain_accs=dom_accs)
    assert M.shape == (len(virtual), len(dom_accs))
    # Chain iBGC carries PF00001 + PF00002, antiSMASH iBGC carries neither
    # (PF00003 is outside vocab).
    chain_idx = next(
        i for i, v in enumerate(virtual) if "GECCO" in v.source_tools
    )
    chain_row = M.getrow(chain_idx).toarray().reshape(-1)
    assert chain_row[0] == 1 and chain_row[1] == 1 and chain_row[2] == 0


def test_asset_domain_matrix_filters_by_source():
    virtual = build_virtual_ibgcs(_seed_data())
    # Force everything out by demanding TIGRFAM — none of our domains carry that.
    M = build_asset_domain_matrix(virtual, sources=("TIGRFAM",), domain_accs=["PF00001"])
    assert M.nnz == 0


def test_asset_adjacency_pair_matrix_emits_canonical_pairs():
    virtual = build_virtual_ibgcs(_seed_data())
    pair_vocab = [("PF00001", "PF00002"), ("PF00002", "PF00003")]
    M = build_asset_adjacency_pair_matrix(
        virtual, sources=("PFAM",), pair_vocab=pair_vocab
    )
    chain_idx = next(
        i for i, v in enumerate(virtual) if "GECCO" in v.source_tools
    )
    chain_row = M.getrow(chain_idx).toarray().reshape(-1)
    # Chain has P1@10:PF00001 then P2@200:PF00002 → (PF00001, PF00002) emitted.
    assert chain_row[0] == 1
    assert chain_row[1] == 0


def test_project_asset_against_synthetic_primary(monkeypatch, tmp_path):
    """Project an asset against a tiny in-memory primary universe and
    verify the four derived fields land on the virtual iBGC."""

    from discovery.services.asset_upload import cache as asset_cache
    from discovery.services.asset_upload import project as proj_mod

    data = _seed_data()
    virtual = build_virtual_ibgcs(data)

    # Fake primary universe: two iBGCs, one with the same domain composition
    # as our chain (PF00001+PF00002) so the chain projects onto it.
    pri_M_dom = sp.csr_matrix(
        np.array(
            [
                [1, 1, 0],  # primary 0 — identical to chain
                [0, 0, 1],  # primary 1 — antiSMASH-like
            ],
            dtype=np.uint8,
        )
    )
    pri_M_pair = sp.csr_matrix(np.zeros((2, 1), dtype=np.uint8))
    pri_ibgc_ids = np.array([1001, 1002], dtype=np.int64)
    dom_accs = np.array(["PF00001", "PF00002", "PF00003"], dtype=object)
    pair_vocab = np.array([("PF00001", "PF00002")], dtype=object)
    leaf_paths = ["cluster.000.000", "cluster.000.001"]

    class FakeRun:
        id = 999
        sha256 = "abc123abc123abc123abc123abc123abc123abc123abc123abc123abc123abcd"
        domain_sources = ["PFAM"]
        score_weights = [0.5, 0.5]

    monkeypatch.setattr(proj_mod, "_latest_clustering_run", lambda: FakeRun())
    from discovery.services.clustering import ibgc_scoring as ibgc_scoring_mod

    monkeypatch.setattr(
        ibgc_scoring_mod,
        "load_scoring_cache",
        lambda artifacts_dir: {
            "M_domains": pri_M_dom,
            "M_pairs": pri_M_pair,
            "ibgc_ids": pri_ibgc_ids,
            "domain_accs": dom_accs,
            "pair_vocab": pair_vocab,
            "leaf_paths": leaf_paths,
        },
    )

    # No IntegratedBGC / DashboardBgc rows in the test DB — patch the
    # ORM-touching queries to return empty.
    class _Empty:
        def __init__(self, *_, **__):
            pass

        def filter(self, *a, **kw):
            return self

        def values_list(self, *a, **kw):
            return []

        def only(self, *a, **kw):
            return []

    from discovery import models as discovery_models

    monkeypatch.setattr(discovery_models.IntegratedBGC, "objects", _Empty())
    monkeypatch.setattr(discovery_models.DashboardBgc, "objects", _Empty())

    summary = proj_mod.project_asset("tok-test", data, task_id="task-1")
    assert summary["n_ibgcs"] == 2
    assert summary["projected"] is True

    roster = asset_cache.read_ibgc_list("tok-test")
    assert roster is not None and len(roster) == 2
    chain_row = next(r for r in roster if "SanntiS" in r["source_tools"])
    # Chain should pick up primary 0's leaf path and project to its UMAP coords.
    assert chain_row["classification_path"] == "cluster.000.000"
    assert chain_row["umap_projected"] is True

    detail = asset_cache.read_ibgc_detail("tok-test", chain_row["id"])
    assert detail is not None
    assert detail["label"].startswith("iBGC-A")
    assert len(detail["member_bgcs"]) == 2


def test_project_asset_no_clustering_run(monkeypatch):
    """Without a ClusteringRun, virtual iBGCs still get persisted but
    projection fields stay at None."""
    from discovery.services.asset_upload import cache as asset_cache
    from discovery.services.asset_upload import project as proj_mod

    data = _seed_data()
    monkeypatch.setattr(proj_mod, "_latest_clustering_run", lambda: None)

    summary = proj_mod.project_asset("tok-no-run", data, task_id="task-2")
    assert summary["n_ibgcs"] == 2
    assert summary["projected"] is False
    roster = asset_cache.read_ibgc_list("tok-no-run")
    assert all(r["umap_projected"] is False for r in roster)
    assert all(r["novelty_score"] is None for r in roster)
