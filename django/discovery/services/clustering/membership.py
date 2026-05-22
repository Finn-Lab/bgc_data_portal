"""Build the iBGC × domain-label membership matrix.

Each row is a :class:`discovery.models.IntegratedBgc`; each column is a
unique **domain label**. The matrix is binary: a 1 means at least one
``ContigDomain`` whose parent CDS's ``cds_range`` overlaps the iBGC's
``bgc_range`` on the same contig carries that label.

**Contig-anchored join** — there is no direct FK between ``ContigDomain``
and ``IntegratedBgc`` in the v2 schema. The two are reached via:

    ContigDomain → ContigCds (cds_id)
                 → DashboardContig (contig_id)
                 → IntegratedBgc (contig_id == cds.contig_id
                                  AND bgc_range && cds_range)

This is expressed as a single SQL join below; GIN on ``bgc_range`` and
the FK index on ``cds_id`` keep it cheap.

**IPR-when-available projection** — each row's label is its
``interpro_entry_acc`` when non-blank (e.g. ``IPR000123``), else the raw
signature ``domain_acc`` (e.g. ``PF00001``). Input rows are gated by
``ref_db`` ∈ ``{PFAM, NCBIFAM, TIGRFAM}`` (case-insensitive). See
:func:`project_to_ipr`.

Dedup runs on the projected label: ``(ibgc_id, label, cds_start)`` counts
each label once per CDS position, and the binary projection then collapses
to a single column entry per iBGC.

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

DEFAULT_DOMAIN_SOURCES: tuple[str, ...] = ("PFAM", "NCBIFAM", "TIGRFAM")


def project_to_ipr(domain_acc: str, interpro_entry_acc: str | None) -> str:
    """Return the IPR entry accession when set, else the raw signature acc.

    Single source of truth for the IPR-when-available projection used by
    every matrix builder and architecture surface. ``interpro_entry_acc``
    is stripped to tolerate stored whitespace; a blank entry falls back to
    the signature ``domain_acc``.
    """
    if interpro_entry_acc:
        stripped = interpro_entry_acc.strip()
        if stripped:
            return stripped
    return domain_acc


def _normalize_sources(sources: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({s.upper() for s in sources}))


def build_ibgc_domain_matrix(
    *,
    sources: Sequence[str] = DEFAULT_DOMAIN_SOURCES,
    ibgc_ids_subset: Sequence[int] | None = None,
    domain_accs_subset: Sequence[str] | None = None,
) -> tuple["sp.csr_matrix", "np.ndarray", "np.ndarray"]:
    """Build the iBGC × domain-accession binary matrix.

    Parameters
    ----------
    sources:
        ``ref_db`` values to keep. Normalized to upper-case at the boundary.
    ibgc_ids_subset:
        Optional explicit list of ``IntegratedBgc.id`` values to include.
    domain_accs_subset:
        Optional column vocabulary. When supplied, columns outside this set
        are dropped; ordering is preserved.

    Returns
    -------
    M : sparse CSR uint8 (n_rows × n_domain_accs)
    row_ids : np.ndarray[int64] — IntegratedBgc.id per row.
    domain_accs : np.ndarray[object] — column label per column.
    """
    import numpy as np
    import scipy.sparse as sp

    from django.db import connection

    upper_sources = _normalize_sources(sources)

    sql = """
        SELECT i.id              AS ibgc_id,
               cd.domain_acc     AS domain_acc,
               cd.interpro_entry_acc AS ipr_acc,
               lower(cc.cds_range)   AS cds_start
        FROM discovery_contig_domain cd
        JOIN discovery_cds cc ON cc.id = cd.cds_id
        JOIN discovery_ibgc i
          ON i.contig_id = cc.contig_id
         AND i.bgc_range && cc.cds_range
        WHERE UPPER(cd.ref_db) = ANY(%s::text[])
    """
    params: list = [list(upper_sources)]
    if ibgc_ids_subset is not None:
        sql += " AND i.id = ANY(%s::bigint[])"
        params.append(list(ibgc_ids_subset))

    pair_set: set[tuple[int, str, int]] = set()
    n = 0
    with connection.cursor() as cur:
        cur.execute(sql, params)
        while True:
            rows = cur.fetchmany(CHUNK)
            if not rows:
                break
            for row_id, acc, ipr_acc, cds_start in rows:
                if not acc:
                    continue
                label = project_to_ipr(acc, ipr_acc)
                pair_set.add((int(row_id), label, int(cds_start or 0)))
                n += 1
            if n // 1_000_000 and (n // 1_000_000) != ((n - len(rows)) // 1_000_000):
                log.info("build_ibgc_domain_matrix: streamed %d ibgc-domain rows", n)

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
        "build_ibgc_domain_matrix: %d rows × %d domains, nnz=%d (sources=%s)",
        M.shape[0], M.shape[1], M.nnz, upper_sources,
    )
    return (
        M,
        np.asarray(row_ids_unique, dtype=np.int64),
        np.asarray(domain_accs_unique, dtype=object),
    )
