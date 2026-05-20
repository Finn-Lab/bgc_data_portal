"""Pooled positional domain architecture for source BGCs and iBGCs.

Single source of truth for the *ordered* domain sequence used by:

* ``ibgc_detail`` / ``bgc_detail`` (``domain_architecture`` field)
* ``GET /ibgcs/{id}/architecture/`` (clipboard payload)
* the clustering pipeline (see
  :mod:`discovery.services.clustering.adjacency`)

Ordering rule: ``(cds.cds_range.lower, ContigDomain.start_position, domain_acc)``
across all CDS whose ``cds_range`` overlaps the iBGC's / source-BGC's
``bgc_range`` on the same contig. Duplicate ``(cds_start, dom_start, acc)``
tuples are collapsed. ``ref_db`` is filtered to PFAM/NCBIFAM by default
(``DEFAULT_DOMAIN_SOURCES``) so the surfaced architecture matches the
vocabulary the composite-Dice scoring cache uses.

This module also hosts :func:`collapse_to_interpro_rows`, which folds
per-signature ``ContigDomain`` rows into one row per InterPro entry for
the Protein Information card. That collapse runs *unfiltered* across all
ref_dbs — the clustering filter only applies to the pooled architecture
views above.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Sequence

from django.db.models import F
from django.db.models.functions import Upper
from psycopg2.extras import NumericRange

from discovery.models import ContigDomain, IntegratedBgc, SourceBgcPrediction
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

    Accepts any object with the ContigDomain attribute surface
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


# ── Ordered architecture (range-overlap query) ───────────────────────────────


def _ordered_entries(
    contig_id: int,
    bgc_range: NumericRange,
    sources: Sequence[str],
) -> list[dict]:
    """Return ordered, deduplicated domain hits within ``bgc_range`` on ``contig_id``.

    The pool is every ``ContigDomain`` whose parent CDS's ``cds_range``
    overlaps ``bgc_range``. ``ref_db`` is filtered to ``sources`` (PFAM /
    NCBIFAM by default). When a row has a non-blank ``interpro_entry_acc``,
    its accession / name / URL are projected to the InterPro entry;
    otherwise the raw signature values are returned. This is the
    **positional, per-hit** sequence — contiguous repeats are NOT collapsed
    (that rule is local to M_pairs construction).
    """
    upper_sources = _normalize_sources(sources)
    rows = (
        ContigDomain.objects
        .annotate(ref_db_upper=Upper("ref_db"))
        .filter(
            contig_id=contig_id,
            cds__cds_range__overlap=bgc_range,
            ref_db_upper__in=upper_sources,
        )
        .annotate(cds_lower=F("cds__cds_range"))  # row carries cds_range; we read lower from it
        .values(
            "domain_acc",
            "domain_name",
            "domain_description",
            "ref_db",
            "url",
            "interpro_entry_acc",
            "interpro_entry_description",
            "cds__cds_range",
            "start_position",
        )
    )
    seen: set[tuple[int, int, str]] = set()
    ordered: list[tuple[int, int, dict]] = []
    for r in rows:
        cds_range = r.get("cds__cds_range")
        cds_start = int(cds_range.lower) if cds_range is not None and cds_range.lower is not None else 0
        dom_start = int(r["start_position"] or 0)
        acc = r["domain_acc"]
        if not acc:
            continue
        ipr_acc = (r.get("interpro_entry_acc") or "").strip()
        if ipr_acc:
            ipr_desc = r.get("interpro_entry_description") or ""
            projected = {
                "domain_acc": ipr_acc,
                "domain_name": ipr_desc or r.get("domain_name", "") or "",
                "ref_db": "InterPro",
                "url": _interpro_url(ipr_acc),
            }
        else:
            projected = {
                "domain_acc": acc,
                "domain_name": r.get("domain_name", "") or "",
                "ref_db": r.get("ref_db", "") or "",
                "url": r.get("url", "") or "",
            }
        key = (cds_start, dom_start, projected["domain_acc"])
        if key in seen:
            continue
        seen.add(key)
        ordered.append((cds_start, dom_start, projected))
    ordered.sort(key=lambda t: (t[0], t[1], t[2]["domain_acc"]))
    return [t[2] for t in ordered]


def bgc_architecture(
    source_bgc_id: int,
    sources: Sequence[str] = DEFAULT_DOMAIN_SOURCES,
) -> list[dict]:
    """Ordered architecture for a single ``SourceBgcPrediction``.

    Domains are pooled across CDS overlapping the prediction's
    ``bgc_range`` on its contig.
    """
    sbgc = SourceBgcPrediction.objects.only("contig_id", "bgc_range").filter(
        id=source_bgc_id,
    ).first()
    if sbgc is None or sbgc.bgc_range is None:
        return []
    return _ordered_entries(sbgc.contig_id, sbgc.bgc_range, sources)


def ibgc_architecture(
    ibgc_id: int,
    sources: Sequence[str] = DEFAULT_DOMAIN_SOURCES,
) -> list[dict]:
    """Ordered architecture pooled across all CDS overlapping the iBGC's range.

    Matches the rule used by
    :func:`discovery.services.clustering.adjacency.build_ibgc_adjacency_pair_matrix`
    so the rendered sequence is the one the clustering pipeline scored.
    """
    ibgc = IntegratedBgc.objects.only("contig_id", "bgc_range").filter(
        id=ibgc_id,
    ).first()
    if ibgc is None or ibgc.bgc_range is None:
        return []
    return _ordered_entries(ibgc.contig_id, ibgc.bgc_range, sources)
