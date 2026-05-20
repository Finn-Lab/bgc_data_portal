"""Closed-form Sørensen–Dice similarity on a binary feature matrix.

The clustering pipeline runs Dice over two complementary feature matrices:

* ``M_domains`` — iBGC × domain accession binary matrix
* ``M_pairs``   — iBGC × adjacent-domain-pair binary matrix

Both share the same row ordering, so the composite similarity (see
``bgc_similarity.compute_composite_similarity``) is a weighted sum of two
sparse matrices of identical shape.

Heavy imports (numpy, scipy.sparse) are deferred inside the function body.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import scipy.sparse as sp

log = logging.getLogger(__name__)


def dice_similarity(M: "sp.csr_matrix") -> "sp.csr_matrix":
    """Sørensen–Dice on a binary BGC × feature matrix.

    ``dice(A, B) = 2 · |A ∩ B| / (|A| + |B|)``

    Implementation uses a single sparse matmul for the intersection counts:
    ``I = M @ M.T``; the per-row counts come from ``M.sum(axis=1)``. Division
    is performed only on non-zero intersection entries to keep the output
    sparse.

    The diagonal is *not* zeroed here — that's the orchestrator's job (see
    ``compute_composite_similarity``).
    """
    import numpy as np
    import scipy.sparse as sp

    if M.shape[0] == 0:
        return sp.csr_matrix((0, 0), dtype=np.float32)

    inter = (M.astype(np.float32) @ M.T.astype(np.float32)).tocoo(copy=False)
    if inter.nnz == 0:
        return sp.csr_matrix(inter.shape, dtype=np.float32)

    sizes = np.asarray(M.sum(axis=1), dtype=np.float32).ravel()
    denom = sizes[inter.row] + sizes[inter.col]
    safe = denom > 0
    values = np.zeros_like(inter.data, dtype=np.float32)
    values[safe] = 2.0 * inter.data[safe] / denom[safe]

    sim = sp.csr_matrix(
        (values, (inter.row, inter.col)),
        shape=inter.shape,
        dtype=np.float32,
    )
    sim.eliminate_zeros()
    return sim
