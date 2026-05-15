"""Pooled positional domain architecture for BGCs and NRBs.

Single source of truth for the *ordered* domain sequence used by:

* ``nrb_detail`` / ``bgc_detail`` (``domain_architecture`` field)
* the new ``GET /nrbs/{id}/architecture/`` endpoint (clipboard payload)
* future consumers that need the same ordering rule the clustering
  pipeline saw (see :mod:`discovery.services.clustering.adjacency`).

Ordering rule: ``(cds.start_position, BgcDomain.start_position, domain_acc)``
across all source BGCs of the NRB, with duplicate ``(cds_start, dom_start,
acc)`` tuples collapsed — each remaining entry corresponds to one distinct
domain hit on a CDS. ``ref_db`` is filtered to PFAM/NCBIFAM by default
(``DEFAULT_DOMAIN_SOURCES``) so the surfaced architecture matches the
vocabulary the composite-Dice scoring cache uses.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from django.db.models.functions import Upper

from discovery.models import BgcDomain
from discovery.services.clustering.membership import (
    DEFAULT_DOMAIN_SOURCES,
    _normalize_sources,
)


def _ordered_entries(
    bgc_ids: Iterable[int],
    sources: Sequence[str],
) -> list[dict]:
    """Return ordered, deduplicated domain hits across ``bgc_ids``.

    Each item carries ``domain_acc``, ``domain_name``, ``ref_db``, ``url`` —
    enough to render the existing ``DomainArchitectureItem`` schema.
    """
    upper_sources = _normalize_sources(sources)
    rows = (
        BgcDomain.objects
        .annotate(ref_db_upper=Upper("ref_db"))
        .filter(
            bgc_id__in=list(bgc_ids),
            ref_db_upper__in=upper_sources,
            cds__isnull=False,
        )
        .values(
            "domain_acc",
            "domain_name",
            "ref_db",
            "url",
            "cds__start_position",
            "start_position",
        )
    )
    seen: set[tuple[int, int, str]] = set()
    ordered: list[tuple[int, int, dict]] = []
    for r in rows:
        cds_start = int(r["cds__start_position"] or 0)
        dom_start = int(r["start_position"] or 0)
        acc = r["domain_acc"]
        if not acc:
            continue
        key = (cds_start, dom_start, acc)
        if key in seen:
            continue
        seen.add(key)
        ordered.append((cds_start, dom_start, r))
    ordered.sort(key=lambda t: (t[0], t[1], t[2]["domain_acc"]))
    return [t[2] for t in ordered]


def bgc_architecture(
    bgc_id: int,
    sources: Sequence[str] = DEFAULT_DOMAIN_SOURCES,
) -> list[dict]:
    """Ordered architecture for a single DashboardBgc."""
    return _ordered_entries([bgc_id], sources)


def nrb_architecture(
    member_bgc_ids: Sequence[int],
    sources: Sequence[str] = DEFAULT_DOMAIN_SOURCES,
) -> list[dict]:
    """Ordered architecture pooled across all member BGCs of an NRB.

    Matches the rule used by
    :func:`discovery.services.clustering.adjacency.build_nrb_adjacency_pair_matrix`
    so the rendered sequence is the one the clustering pipeline scored.
    """
    return _ordered_entries(member_bgc_ids, sources)
