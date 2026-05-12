"""Domain + adjacency hierarchical-CPM-Leiden clustering for BGCs.

Public API surface for the discovery clustering pipeline. Heavy imports
(numpy, scipy.sparse, igraph, leidenalg, umap-learn, plotly) are deferred
inside the individual modules' function bodies so this package can be
imported on the web container without ML dependencies installed.

See ``services/clustering/pipeline.py`` for the orchestrator,
``services/clustering/non_redundant.py`` for the NRB builder, and
``services/clustering/reclassify.py`` for the post-hoc step.
"""

from discovery.services.clustering.adjacency import (
    build_nrb_adjacency_pair_matrix,
)
from discovery.services.clustering.bgc_similarity import (
    compute_composite_similarity,
)
from discovery.services.clustering.knn_graph import build_knn_graph
from discovery.services.clustering.membership import build_nrb_domain_matrix
from discovery.services.clustering.metrics import dice_similarity
from discovery.services.clustering.mibig_analysis import emit_run_artifacts
from discovery.services.clustering.non_redundant import build_non_redundant_bgcs
from discovery.services.clustering.pipeline import (
    DEFAULT_DOMAIN_SOURCES,
    DEFAULT_RESOLUTIONS,
    DEFAULT_SCORE_WEIGHTS,
    run_clustering_pipeline,
)
from discovery.services.clustering.reclassify import (
    ALLOWED_SCOPES,
    SCOPE_ALL_NON_PRIMARY,
    SCOPE_PARTIAL,
    SCOPE_STALE,
    reclassify_bgcs,
)

__all__ = [
    "build_nrb_domain_matrix",
    "build_nrb_adjacency_pair_matrix",
    "compute_composite_similarity",
    "build_knn_graph",
    "dice_similarity",
    "emit_run_artifacts",
    "build_non_redundant_bgcs",
    "DEFAULT_DOMAIN_SOURCES",
    "DEFAULT_RESOLUTIONS",
    "DEFAULT_SCORE_WEIGHTS",
    "run_clustering_pipeline",
    "reclassify_bgcs",
    "ALLOWED_SCOPES",
    "SCOPE_PARTIAL",
    "SCOPE_STALE",
    "SCOPE_ALL_NON_PRIMARY",
]
