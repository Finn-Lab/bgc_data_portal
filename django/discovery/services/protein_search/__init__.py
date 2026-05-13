"""On-disk phmmer-based protein search for the Discovery Dashboard.

The reference DB is a FASTA file (sha256-keyed) plus an Easel SSI index, stored
on the ``PROTEIN_SEARCH_INDEX_DIR`` volume so all Celery workers share it.
A ``VERSION`` stamp next to the FASTA lets each worker detect updates and
swap in a fresh ``DigitalSequenceBlock`` on the next query.

Public entry points:

* :func:`discovery.services.protein_search.build.rebuild_index` —
  full FASTA rewrite from ``DashboardCds``.
* :func:`discovery.services.protein_search.build.update_index` —
  append-only update for newly ingested proteins.
* :func:`discovery.services.protein_search.search.phmmer_search` —
  run phmmer with a query AA sequence; returns
  ``{sha256: ProteinHitMetrics}`` (bitscore, pident, qcoverage).
* :data:`discovery.services.protein_search.index.protein_search_index` —
  module-level singleton handed the loaded ``DigitalSequenceBlock``.
"""

from .build import rebuild_index, update_index, index_paths
from .index import protein_search_index
from .search import ProteinHitMetrics, phmmer_search

__all__ = [
    "rebuild_index",
    "update_index",
    "index_paths",
    "protein_search_index",
    "phmmer_search",
    "ProteinHitMetrics",
]
