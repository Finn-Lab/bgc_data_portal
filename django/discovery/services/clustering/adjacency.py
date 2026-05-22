"""Build the iBGC × adjacent-domain-pair binary matrix.

For each :class:`discovery.models.IntegratedBgc`, the per-row build steps
run in this exact order:

1. **Pool domain hits** by joining ``ContigDomain → ContigCds → IntegratedBgc``
   on the same contig with ``bgc_range && cds_range``. Filter by ``ref_db``
   against the supplied ``sources`` set (case-insensitive). Drop rows where
   ``domain_acc`` is empty.
2. **Sort** by ``(cds_start, dom_start)``. Duplicate ``(cds_start, dom_start,
   domain_acc)`` tuples collapse to a single position.
3. **Project** each entry's accession to ``interpro_entry_acc`` when set,
   else the raw signature ``domain_acc`` (see
   :func:`discovery.services.clustering.membership.project_to_ipr`).
4. **Collapse contiguous repeats** in the projected sequence: e.g.
   ``[A, A, B, A]`` → ``[A, B, A]``. Non-adjacent repeats are preserved.
5. **Pair-extract** via a sliding window of size 2 over the collapsed list.
   Each pair is canonicalised as a sorted tuple so the same unordered pair
   appears under exactly one column.

Heavy imports (numpy, scipy.sparse) are deferred inside the function body.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    import numpy as np
    import scipy.sparse as sp

from discovery.services.clustering.membership import (
    DEFAULT_DOMAIN_SOURCES,
    _normalize_sources,
    project_to_ipr,
)

log = logging.getLogger(__name__)

CHUNK = 200_000


def build_ibgc_adjacency_pair_matrix(
    *,
    sources: Sequence[str] = DEFAULT_DOMAIN_SOURCES,
    ibgc_ids_subset: Sequence[int] | None = None,
    pair_vocab_subset: Sequence[tuple[str, str]] | None = None,
) -> tuple["sp.csr_matrix", "np.ndarray", "np.ndarray"]:
    """Build the iBGC × adjacent-pair binary matrix.

    Returns
    -------
    M : sparse CSR uint8 (n_rows × n_pairs)
    row_ids : np.ndarray[int64] — IntegratedBgc.id per row.
    pair_vocab : np.ndarray[object] of ``(acc_a, acc_b)`` tuples
                 (canonicalized sorted).
    """
    import numpy as np
    import scipy.sparse as sp

    from django.db import connection

    upper_sources = _normalize_sources(sources)

    sql = """
        SELECT i.id              AS ibgc_id,
               lower(cc.cds_range) AS cds_start,
               cd.start_position AS dom_start,
               cd.domain_acc     AS domain_acc,
               cd.interpro_entry_acc AS ipr_acc
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

    # Sequence rows per row_id: (cds_start, dom_start, label) tuples.
    seq_rows: dict[int, list[tuple[int, int, str]]] = defaultdict(list)
    n = 0
    with connection.cursor() as cur:
        cur.execute(sql, params)
        while True:
            rows = cur.fetchmany(CHUNK)
            if not rows:
                break
            for row_id, cds_start, dom_start, acc, ipr_acc in rows:
                if not acc:
                    continue
                label = project_to_ipr(acc, ipr_acc)
                seq_rows[int(row_id)].append(
                    (int(cds_start or 0), int(dom_start or 0), label),
                )
                n += 1
            if n // 1_000_000 and (n // 1_000_000) != ((n - len(rows)) // 1_000_000):
                log.info("build_ibgc_adjacency_pair_matrix: streamed %d rows", n)

    # Build per-row pair sets and accumulate global vocab.
    row_pairs: dict[int, set[tuple[str, str]]] = {}
    pair_vocab: dict[tuple[str, str], int] = {}
    if pair_vocab_subset is not None:
        for pair in pair_vocab_subset:
            canonical = tuple(sorted(pair))  # type: ignore[arg-type]
            if canonical not in pair_vocab:
                pair_vocab[canonical] = len(pair_vocab)

    for row_id, entries in seq_rows.items():
        ordered = sorted(set(entries))
        # Collapse contiguous repeats of the same projected label so an IPR
        # entry that fans out across several signature hits at adjacent
        # protein positions doesn't generate self-pairs. Non-adjacent repeats
        # are preserved — e.g. [A, A, B, A] → [A, B, A].
        accs: list[str] = []
        for _, _, label in ordered:
            if accs and accs[-1] == label:
                continue
            accs.append(label)
        if len(accs) < 2:
            row_pairs[row_id] = set()
            continue
        pair_set: set[tuple[str, str]] = set()
        for i in range(len(accs) - 1):
            pair = tuple(sorted((accs[i], accs[i + 1])))
            pair_set.add(pair)
            if pair_vocab_subset is None and pair not in pair_vocab:
                pair_vocab[pair] = len(pair_vocab)
        row_pairs[row_id] = pair_set

    if not row_pairs or not pair_vocab:
        empty = sp.csr_matrix((max(len(row_pairs), 0), 0), dtype=np.uint8)
        return (
            empty,
            np.asarray(sorted(row_pairs), dtype=np.int64),
            np.empty(0, dtype=object),
        )

    row_ids_sorted = sorted(row_pairs)
    row_index = {r: i for i, r in enumerate(row_ids_sorted)}

    rows_out: list[int] = []
    cols_out: list[int] = []
    for row_id, pair_set in row_pairs.items():
        ri = row_index[row_id]
        for pair in pair_set:
            ci = pair_vocab.get(pair)
            if ci is None:
                continue
            rows_out.append(ri)
            cols_out.append(ci)

    data = np.ones(len(rows_out), dtype=np.uint8)
    M = sp.csr_matrix(
        (
            data,
            (
                np.asarray(rows_out, dtype=np.int64),
                np.asarray(cols_out, dtype=np.int64),
            ),
        ),
        shape=(len(row_ids_sorted), len(pair_vocab)),
        dtype=np.uint8,
    )
    pair_labels = np.empty(len(pair_vocab), dtype=object)
    for pair, idx in pair_vocab.items():
        pair_labels[idx] = pair

    log.info(
        "build_ibgc_adjacency_pair_matrix: %d rows × %d pairs, nnz=%d (sources=%s)",
        M.shape[0], M.shape[1], M.nnz, upper_sources,
    )
    return (
        M,
        np.asarray(row_ids_sorted, dtype=np.int64),
        pair_labels,
    )
