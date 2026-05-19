"""Build the NRB × domain-accession membership matrix.

Each row is a :class:`discovery.models.NonRedundantBGC`; each column is a
unique domain accession (e.g. ``PF00001``). The matrix is binary: a 1 means
the NRB carries that domain at least once across any of its source
DashboardBgc rows. Domains are first filtered by ``ref_db`` source
(case-insensitive at the API boundary — ``ref_db`` is stored upper-case),
then deduplicated by ``(nrb_id, domain_acc, cds.start_position)`` so the
same accession appearing on multiple CDS positions counts once *per
position* but the binary projection collapses to a single column entry per
NRB.

Heavy imports (numpy, scipy.sparse) are deferred inside the function body
so this module can be imported on the web container without ML deps.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    import numpy as np
    import scipy.sparse as sp

log = logging.getLogger(__name__)


CHUNK = 200_000

DEFAULT_DOMAIN_SOURCES: tuple[str, ...] = ("PFAM", "NCBIFAM")


def _normalize_sources(sources: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({s.upper() for s in sources}))


def _bigint_array_in(ids: Sequence[int]):
    """Return an expression usable as the RHS of an ``__in`` lookup that sends
    the id list as a single ``bigint[]`` bind parameter.

    Why: PostgreSQL's wire protocol caps bind parameters at 65 535 (uint16).
    The ORM's default ``__in=[...]`` expansion sends one param per id, so any
    NRB / BGC id list larger than that raises ``OperationalError("number of
    parameters must be between 0 and 65535")``. Wrapping in ``ANY(%s::bigint[])``
    keeps the whole list as one param.
    """
    from django.db.models.expressions import RawSQL

    return RawSQL("SELECT unnest(%s::bigint[])", [list(ids)])


def build_nrb_domain_matrix(
    *,
    sources: Sequence[str] = DEFAULT_DOMAIN_SOURCES,
    nrb_ids_subset: Sequence[int] | None = None,
    domain_accs_subset: Sequence[str] | None = None,
    extra_bgc_ids: Sequence[int] | None = None,
) -> tuple["sp.csr_matrix", "np.ndarray", "np.ndarray"]:
    """Build the NRB × domain-accession binary matrix.

    Parameters
    ----------
    sources:
        ``ref_db`` values to keep. Normalized to upper-case at the boundary.
    nrb_ids_subset:
        Optional explicit list of ``NonRedundantBGC.id`` values to include.
        Used by the reclassifier path to project rows onto the primary run's
        vocabulary.
    domain_accs_subset:
        Optional column vocabulary. When supplied, columns outside this set
        are dropped; ordering is preserved.
    extra_bgc_ids:
        Optional list of *raw* ``DashboardBgc.id`` values to include as
        additional rows (i.e. virtual NRBs sized as a single source row).
        Used by the reclassifier so partial BGCs can be stacked under the
        same column layout. Rows from this list are keyed by negative
        ``bgc_id`` to avoid collision with real NRB ids.

    Returns
    -------
    M : sparse CSR uint8 (n_rows × n_domain_accs)
    row_ids : np.ndarray[int64] — row label per row; positive = NRB id,
              negative = ``-DashboardBgc.id`` for ``extra_bgc_ids`` rows.
    domain_accs : np.ndarray[object] — column label per column.
    """
    import numpy as np
    import scipy.sparse as sp

    from django.db.models.functions import Upper

    from discovery.models import BgcDomain

    upper_sources = _normalize_sources(sources)

    # Case-insensitive ref_db match: the bulk loader stores ref_db verbatim
    # from the ETL (typically mixed-case like "Pfam"/"NCBIfam"/"TIGRfam"),
    # while the API contract is upper-case at the boundary. Annotating with
    # Upper() lets us compare without depending on stored casing.
    qs = (
        BgcDomain.objects
        .annotate(ref_db_upper=Upper("ref_db"))
        .filter(
            ref_db_upper__in=upper_sources,
            bgc__non_redundant_bgc__isnull=False,
        )
    )
    if nrb_ids_subset is not None:
        qs = qs.filter(
            bgc__non_redundant_bgc_id__in=_bigint_array_in(nrb_ids_subset)
        )
    nrb_qs = qs.values_list(
        "bgc__non_redundant_bgc_id",
        "domain_acc",
        "cds__start_position",
    )

    # Set keyed on row identity, accession, and on-protein anchor for dedup.
    pair_set: set[tuple[int, str, int]] = set()
    n = 0
    for row_id, acc, cds_start in nrb_qs.iterator(chunk_size=CHUNK):
        if not acc:
            continue
        pair_set.add((int(row_id), acc, int(cds_start or 0)))
        n += 1
        if n % 1_000_000 == 0:
            log.info("build_nrb_domain_matrix: streamed %d nrb-domain rows", n)

    # Extra single-DashboardBgc rows (e.g. partials being reclassified).
    if extra_bgc_ids:
        extra_qs = (
            BgcDomain.objects
            .annotate(ref_db_upper=Upper("ref_db"))
            .filter(
                ref_db_upper__in=upper_sources,
                bgc_id__in=_bigint_array_in(extra_bgc_ids),
            )
            .values_list("bgc_id", "domain_acc", "cds__start_position")
        )
        for bgc_id, acc, cds_start in extra_qs.iterator(chunk_size=CHUNK):
            if not acc:
                continue
            pair_set.add((-int(bgc_id), acc, int(cds_start or 0)))

    if not pair_set:
        empty = sp.csr_matrix((0, 0), dtype=np.uint8)
        return empty, np.empty(0, dtype=np.int64), np.empty(0, dtype=object)

    row_ids_unique = sorted({row_id for row_id, _, _ in pair_set})
    if domain_accs_subset is not None:
        domain_accs_unique = list(domain_accs_subset)
    else:
        domain_accs_unique = sorted({acc for _, acc, _ in pair_set})

    row_index = {r: i for i, r in enumerate(row_ids_unique)}
    col_index = {a: j for j, a in enumerate(domain_accs_unique)}

    # Project per-position dedup to per-(row, acc) binary membership.
    membership: set[tuple[int, int]] = set()
    for row_id, acc, _cds_start in pair_set:
        col = col_index.get(acc)
        if col is None:
            continue
        membership.add((row_index[row_id], col))

    rows = np.fromiter((r for r, _ in membership), dtype=np.int64, count=len(membership))
    cols = np.fromiter((c for _, c in membership), dtype=np.int64, count=len(membership))
    data = np.ones(len(membership), dtype=np.uint8)

    M = sp.csr_matrix(
        (data, (rows, cols)),
        shape=(len(row_ids_unique), len(domain_accs_unique)),
        dtype=np.uint8,
    )
    log.info(
        "build_nrb_domain_matrix: %d rows × %d domains, nnz=%d (sources=%s)",
        M.shape[0], M.shape[1], M.nnz, upper_sources,
    )
    return (
        M,
        np.asarray(row_ids_unique, dtype=np.int64),
        np.asarray(domain_accs_unique, dtype=object),
    )
