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

This module also hosts :func:`collapse_to_interpro_rows`, which folds
per-signature ``BgcDomain`` rows into one row per InterPro entry for the
Protein Information card. That collapse runs *unfiltered* across all
ref_dbs — the clustering filter only applies to the pooled architecture
views above.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Sequence

from django.db.models.functions import Upper

from discovery.models import BgcDomain
from discovery.services.clustering.membership import (
    DEFAULT_DOMAIN_SOURCES,
    _normalize_sources,
)


def _interpro_url(entry_acc: str) -> str:
    return f"https://www.ebi.ac.uk/interpro/entry/InterPro/{entry_acc}/"


def collapse_to_interpro_rows(
    domains: Iterable[Any],
    slim_for: Callable[[Any], Iterable[str]] | None = None,
) -> list[dict[str, Any]]:
    """Group per-signature domain rows by InterPro entry for the Protein Info card.

    Accepts any object with the BgcDomain attribute surface
    (``interpro_entry_acc``, ``interpro_entry_description``, ``domain_acc``,
    ``domain_name``, ``domain_description``, ``start_position``,
    ``end_position``, ``score``, ``url``). ``slim_for`` lets callers that
    don't store a precomputed ``go_slim`` list (e.g. the asset-upload path,
    which carries ``go_terms`` on AssetDomain) compute slim names on the
    fly; when omitted, the row is expected to expose ``.go_slim``.

    Rules:
      * Grouping key: ``interpro_entry_acc`` when set; otherwise the
        signature ``domain_acc`` (so signatures without an IPS entry stay
        visible).
      * Within a group: union of ``go_slim`` terms, min start, max end,
        best (smallest) e-value, description/URL prefer the IPS entry
        (with a deterministic fallback to the signature description /
        URL when the entry has neither set).
      * Output rows are sorted by ``envelope_start`` for stable rendering.

    Returns a list of dicts with the same keys the API serializer needs to
    build :class:`InterproAnnotationOut`. Empty input → ``[]``.
    """
    groups: dict[str, dict[str, Any]] = {}
    for d in domains:
        key = (d.interpro_entry_acc or "").strip() or d.domain_acc
        if not key:
            continue
        has_entry = bool((d.interpro_entry_acc or "").strip())
        if slim_for is not None:
            slim_list = list(slim_for(d) or [])
        else:
            slim_list = list(getattr(d, "go_slim", None) or [])

        bucket = groups.get(key)
        if bucket is None:
            bucket = {
                "accession": d.interpro_entry_acc if has_entry else d.domain_acc,
                "description": (
                    d.interpro_entry_description
                    if has_entry and d.interpro_entry_description
                    else (d.domain_description or d.domain_name or "")
                ),
                "go_slim": set(slim_list),
                "envelope_start": d.start_position,
                "envelope_end": d.end_position,
                "_best_score": d.score,
                "url": _interpro_url(d.interpro_entry_acc) if has_entry else (d.url or ""),
                "_has_entry": has_entry,
            }
            groups[key] = bucket
            continue

        bucket["go_slim"].update(slim_list)
        bucket["envelope_start"] = min(bucket["envelope_start"], d.start_position)
        bucket["envelope_end"] = max(bucket["envelope_end"], d.end_position)
        if d.score is not None and (
            bucket["_best_score"] is None or d.score < bucket["_best_score"]
        ):
            bucket["_best_score"] = d.score
        if not bucket["description"]:
            bucket["description"] = (
                d.interpro_entry_description
                if has_entry and d.interpro_entry_description
                else (d.domain_description or d.domain_name or "")
            )

    rows: list[dict[str, Any]] = []
    for bucket in groups.values():
        rows.append(
            {
                "accession": bucket["accession"],
                "description": bucket["description"],
                "go_slim": sorted(bucket["go_slim"]),
                "envelope_start": bucket["envelope_start"],
                "envelope_end": bucket["envelope_end"],
                "e_value": (
                    str(bucket["_best_score"])
                    if bucket["_best_score"] is not None
                    else None
                ),
                "url": bucket["url"],
            }
        )
    rows.sort(key=lambda r: (r["envelope_start"], r["accession"]))
    return rows


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
