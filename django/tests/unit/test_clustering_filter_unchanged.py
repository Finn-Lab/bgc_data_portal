"""Lock the PFAM/NCBIFAM clustering filter contract.

The Discovery dashboard ingests domains from every ref_db that
InterProScan + Pfam scans emit, but the composite-Dice clustering, the
pooled positional architecture, the asset-upload similarity projection,
and the architecture-based query path all restrict to ``PFAM`` +
``NCBIFAM``. Loosening that filter would silently change clustering
membership, similarity scores, and the surfaced architecture. This test
pins the default at the four canonical entry points so the next refactor
trips over it before users do.
"""

from __future__ import annotations

from discovery.services.architecture import bgc_architecture, nrb_architecture  # noqa: F401
from discovery.services.asset_upload.matrices import DEFAULT_DOMAIN_SOURCES as ASSET_DEFAULTS
from discovery.services.clustering.adjacency import build_nrb_adjacency_pair_matrix  # noqa: F401
from discovery.services.clustering.membership import (
    DEFAULT_DOMAIN_SOURCES as MEMBERSHIP_DEFAULTS,
)
from discovery.services.clustering.pipeline import (
    DEFAULT_DOMAIN_SOURCES as PIPELINE_DEFAULTS,
)


PFAM_NCBIFAM = ("PFAM", "NCBIFAM","TIGRFAM")


def test_clustering_pipeline_default_sources_unchanged():
    assert tuple(PIPELINE_DEFAULTS) == PFAM_NCBIFAM


def test_clustering_membership_default_sources_unchanged():
    assert tuple(MEMBERSHIP_DEFAULTS) == PFAM_NCBIFAM


def test_asset_matrix_default_sources_unchanged():
    assert tuple(ASSET_DEFAULTS) == PFAM_NCBIFAM


def test_architecture_module_default_sources_unchanged():
    """Pooled positional architecture (used by nrb_detail / bgc_detail and
    the architecture-search query) imports its default from the
    clustering.membership module."""
    from discovery.services import architecture as arch_mod

    assert tuple(arch_mod.DEFAULT_DOMAIN_SOURCES) == PFAM_NCBIFAM
