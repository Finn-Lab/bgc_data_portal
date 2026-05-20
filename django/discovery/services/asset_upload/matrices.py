"""In-memory builders for the iBGC × domain and iBGC × adjacency-pair matrices.

These mirror :mod:`discovery.services.clustering.membership` and
:mod:`discovery.services.clustering.adjacency`, but consume an in-memory
``AssetData`` (the parsed upload) rather than querying the ORM. They emit
sparse CSR matrices with the **same column ordering** as the persisted
scoring cache so they can be horizontally stacked under the primary
matrices for composite-Dice similarity.

Vocabulary handling: callers pass the primary run's ``domain_accs`` and
``pair_vocab`` (loaded from the scoring cache) so asset matrices use the
exact same column space; asset rows lose vocabulary not seen by the
primary run, which is fine — that's what the projection math expects.

The asset row order is determined by ``virtual_ibgcs`` — the same dict the
projection step uses to walk results back into Redis. Row N in the
returned matrix corresponds to the Nth ``VirtualIbgc``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Sequence

from discovery.services.clustering.membership import project_to_ipr

if TYPE_CHECKING:
    import numpy as np
    import scipy.sparse as sp

    from .project import VirtualIbgc

log = logging.getLogger(__name__)

DEFAULT_DOMAIN_SOURCES: tuple[str, ...] = ("PFAM", "NCBIFAM","TIGRFAM")


def _normalize_sources(sources: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({s.upper() for s in sources}))


def build_asset_domain_matrix(
    virtual_ibgcs: Sequence["VirtualIbgc"],
    *,
    sources: Sequence[str] = DEFAULT_DOMAIN_SOURCES,
    domain_accs: Sequence[str],
) -> "sp.csr_matrix":
    """Return the asset's iBGC × domain binary matrix on the given vocabulary.

    Rows are ordered to match ``virtual_ibgcs``; columns to match
    ``domain_accs`` (the primary run's vocabulary, **already IPR-projected**).
    Each asset domain is projected via
    :func:`discovery.services.clustering.membership.project_to_ipr` to the
    same label space before lookup. Domains from non-selected ``ref_db``
    sources are silently dropped, mirroring the persistent builder's
    behaviour. Per-protein-anchor dedup matches the persistent path:
    ``(virtual_ibgc_index, label, cds_protein_id)`` collapses to a single
    binary entry.
    """
    import numpy as np
    import scipy.sparse as sp

    upper_sources = _normalize_sources(sources)
    col_index = {acc: i for i, acc in enumerate(domain_accs)}

    rows_out: list[int] = []
    cols_out: list[int] = []
    seen: set[tuple[int, int, str]] = set()

    for row_idx, vibgc in enumerate(virtual_ibgcs):
        for domain in vibgc.domains:
            if not domain.domain_acc:
                continue
            if domain.ref_db and domain.ref_db.upper() not in upper_sources:
                continue
            label = project_to_ipr(domain.domain_acc, domain.interpro_entry_acc)
            col_idx = col_index.get(label)
            if col_idx is None:
                continue
            anchor = domain.cds_protein_id or ""
            key = (row_idx, col_idx, anchor)
            if key in seen:
                continue
            seen.add(key)
            rows_out.append(row_idx)
            cols_out.append(col_idx)

    if not rows_out:
        return sp.csr_matrix(
            (len(virtual_ibgcs), len(domain_accs)), dtype=np.uint8
        )

    # Project the per-anchor entries down to (row, col) binary membership.
    pairs = {(r, c) for r, c, _ in seen}
    rows_arr = np.fromiter((r for r, _ in pairs), dtype=np.int64, count=len(pairs))
    cols_arr = np.fromiter((c for _, c in pairs), dtype=np.int64, count=len(pairs))
    data = np.ones(len(pairs), dtype=np.uint8)
    M = sp.csr_matrix(
        (data, (rows_arr, cols_arr)),
        shape=(len(virtual_ibgcs), len(domain_accs)),
        dtype=np.uint8,
    )
    log.info(
        "build_asset_domain_matrix: %d rows × %d domains, nnz=%d",
        M.shape[0],
        M.shape[1],
        M.nnz,
    )
    return M


def build_asset_adjacency_pair_matrix(
    virtual_ibgcs: Sequence["VirtualIbgc"],
    *,
    sources: Sequence[str] = DEFAULT_DOMAIN_SOURCES,
    pair_vocab: Sequence[tuple[str, str]],
) -> "sp.csr_matrix":
    """Return the asset's iBGC × adjacent-domain-pair binary matrix.

    Mirrors :func:`discovery.services.clustering.adjacency.build_ibgc_adjacency_pair_matrix`:

    1. Filter domains by ``ref_db`` ∈ ``sources``, drop rows without a CDS anchor.
    2. Sort by ``(cds_start, domain_start)`` across all member BGCs of the iBGC.
    3. Project each accession to IPR-when-available
       (see :func:`discovery.services.clustering.membership.project_to_ipr`).
    4. Collapse contiguous repeats of the same projected label.
    5. Sliding-window-2 over the collapsed list; canonicalise each pair to
       a sorted tuple.

    Pairs outside the supplied ``pair_vocab`` are dropped (matches the
    column projection used by ``reclassify._align_rows``).
    """
    import numpy as np
    import scipy.sparse as sp

    upper_sources = _normalize_sources(sources)
    pair_index = {tuple(sorted(p)): i for i, p in enumerate(pair_vocab)}

    rows_out: list[int] = []
    cols_out: list[int] = []
    seen: set[tuple[int, int]] = set()

    for row_idx, vibgc in enumerate(virtual_ibgcs):
        # Position-sorted (cds_start, domain_start, acc) entries. cds_start
        # comes from the CDS that owns each domain — look it up from the
        # virtual iBGC's CDS list, keyed on (bgc_key, protein_id).
        cds_start_by_id: dict[tuple[tuple[str, int, int, str], str], int] = {}
        for cds in vibgc.cds:
            cds_start_by_id[(cds.bgc_key, cds.protein_id_str)] = cds.start_position

        entries: list[tuple[int, int, str]] = []
        for domain in vibgc.domains:
            if not domain.domain_acc:
                continue
            if domain.ref_db and domain.ref_db.upper() not in upper_sources:
                continue
            cds_start = cds_start_by_id.get(
                (domain.bgc_key, domain.cds_protein_id)
            )
            if cds_start is None:
                # No genomic anchor → can't sit in an adjacency.
                continue
            label = project_to_ipr(domain.domain_acc, domain.interpro_entry_acc)
            entries.append((cds_start, domain.start_position, label))

        ordered = sorted(set(entries))
        if len(ordered) < 2:
            continue

        # Collapse contiguous repeats of the same projected label (see
        # discovery.services.clustering.adjacency for the rule).
        accs: list[str] = []
        for _, _, label in ordered:
            if accs and accs[-1] == label:
                continue
            accs.append(label)
        if len(accs) < 2:
            continue
        for i in range(len(accs) - 1):
            pair = tuple(sorted((accs[i], accs[i + 1])))
            col_idx = pair_index.get(pair)
            if col_idx is None:
                continue
            key = (row_idx, col_idx)
            if key in seen:
                continue
            seen.add(key)
            rows_out.append(row_idx)
            cols_out.append(col_idx)

    if not rows_out:
        return sp.csr_matrix(
            (len(virtual_ibgcs), len(pair_vocab)), dtype=np.uint8
        )

    rows_arr = np.asarray(rows_out, dtype=np.int64)
    cols_arr = np.asarray(cols_out, dtype=np.int64)
    data = np.ones(len(rows_out), dtype=np.uint8)
    M = sp.csr_matrix(
        (data, (rows_arr, cols_arr)),
        shape=(len(virtual_ibgcs), len(pair_vocab)),
        dtype=np.uint8,
    )
    log.info(
        "build_asset_adjacency_pair_matrix: %d rows × %d pairs, nnz=%d",
        M.shape[0],
        M.shape[1],
        M.nnz,
    )
    return M
