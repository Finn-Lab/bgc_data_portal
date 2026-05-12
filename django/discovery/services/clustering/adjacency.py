"""Build the NRB × adjacent-domain-pair binary matrix.

For each :class:`discovery.models.NonRedundantBGC` (or extra
:class:`discovery.models.DashboardBgc` for reclassification), domains are:

1. **Filtered first** by ``ref_db`` against the supplied ``sources`` set
   (case-insensitive at the API boundary; stored value is upper-case).
   Domains from non-selected sources never appear in the adjacency sequence.
2. **Filtered second** to drop ``cds IS NULL`` rows (no genomic anchor → can't
   sit in a meaningful adjacency).
3. **Sorted** by ``(cds.start_position, BgcDomain.start_position)`` — joined
   across all source DashboardBgcs that fed the NRB. Duplicate
   ``(cds_start, domain_acc)`` rows collapse to a single position.
4. **Pair-extracted** via a sliding window of size 2 over the ordered
   domain_acc list. Each pair is canonicalized as a sorted tuple so the same
   unordered pair appears under exactly one column.

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
)

log = logging.getLogger(__name__)

CHUNK = 200_000


def build_nrb_adjacency_pair_matrix(
    *,
    sources: Sequence[str] = DEFAULT_DOMAIN_SOURCES,
    nrb_ids_subset: Sequence[int] | None = None,
    pair_vocab_subset: Sequence[tuple[str, str]] | None = None,
    extra_bgc_ids: Sequence[int] | None = None,
) -> tuple["sp.csr_matrix", "np.ndarray", "np.ndarray"]:
    """Build the NRB × adjacent-pair binary matrix.

    Returns
    -------
    M : sparse CSR uint8 (n_rows × n_pairs)
    row_ids : np.ndarray[int64] — positive NRB ids, optionally followed by
              negative ``-DashboardBgc.id`` entries from ``extra_bgc_ids``.
    pair_vocab : np.ndarray[object] of ``(acc_a, acc_b)`` tuples
                 (canonicalized sorted).
    """
    import numpy as np
    import scipy.sparse as sp

    from django.db.models.functions import Upper

    from discovery.models import BgcDomain

    upper_sources = _normalize_sources(sources)

    # Sequence rows per row_id. A list of (cds_start, dom_start, acc) tuples,
    # later sorted and projected to ordered acc sequences for windowing.
    seq_rows: dict[int, list[tuple[int, int, str]]] = defaultdict(list)

    # Case-insensitive ref_db match — the bulk loader stores values verbatim
    # from the ETL (mixed-case in practice). See membership.py for the same
    # treatment.
    qs = (
        BgcDomain.objects
        .annotate(ref_db_upper=Upper("ref_db"))
        .filter(
            ref_db_upper__in=upper_sources,
            cds__isnull=False,
            bgc__non_redundant_bgc__isnull=False,
        )
    )
    if nrb_ids_subset is not None:
        qs = qs.filter(bgc__non_redundant_bgc_id__in=list(nrb_ids_subset))

    rows_qs = qs.values_list(
        "bgc__non_redundant_bgc_id",
        "cds__start_position",
        "start_position",
        "domain_acc",
    )

    n = 0
    for row_id, cds_start, dom_start, acc in rows_qs.iterator(chunk_size=CHUNK):
        if not acc:
            continue
        seq_rows[int(row_id)].append((int(cds_start or 0), int(dom_start or 0), acc))
        n += 1
        if n % 1_000_000 == 0:
            log.info("build_nrb_adjacency_pair_matrix: streamed %d rows", n)

    if extra_bgc_ids:
        extra_qs = (
            BgcDomain.objects
            .annotate(ref_db_upper=Upper("ref_db"))
            .filter(
                ref_db_upper__in=upper_sources,
                cds__isnull=False,
                bgc_id__in=list(extra_bgc_ids),
            )
            .values_list("bgc_id", "cds__start_position", "start_position", "domain_acc")
        )
        for bgc_id, cds_start, dom_start, acc in extra_qs.iterator(chunk_size=CHUNK):
            if not acc:
                continue
            seq_rows[-int(bgc_id)].append((int(cds_start or 0), int(dom_start or 0), acc))

    # Build per-row pair sets and accumulate global vocab.
    row_pairs: dict[int, set[tuple[str, str]]] = {}
    pair_vocab: dict[tuple[str, str], int] = {}
    if pair_vocab_subset is not None:
        # Preserve caller ordering, normalize input pairs to sorted tuples.
        for pair in pair_vocab_subset:
            canonical = tuple(sorted(pair))  # type: ignore[arg-type]
            if canonical not in pair_vocab:
                pair_vocab[canonical] = len(pair_vocab)

    for row_id, entries in seq_rows.items():
        # Order by (cds_start, dom_start) — joined across source BGCs of an NRB.
        ordered = sorted(set(entries))
        accs = [acc for _, _, acc in ordered]
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
    # pair_vocab values are insertion-order ints; build a stable label array.
    pair_labels = np.empty(len(pair_vocab), dtype=object)
    for pair, idx in pair_vocab.items():
        pair_labels[idx] = pair

    log.info(
        "build_nrb_adjacency_pair_matrix: %d rows × %d pairs, nnz=%d (sources=%s)",
        M.shape[0], M.shape[1], M.nnz, upper_sources,
    )
    return (
        M,
        np.asarray(row_ids_sorted, dtype=np.int64),
        pair_labels,
    )
