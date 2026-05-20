"""Build the ``IntegratedBgc`` table from latest-version source predictions.

iBGCs are strictly disjoint within their containing ``ConsensusBgc``. Each
iBGC's accession is minted via the stable-forever accession registry
(``MGYB-XXXXXX-YY``) and never reused.

Construction rules (per contig, applied within each contig's source
predictions):

  1. Pull all latest-version source predictions via
     :func:`discovery.querysets.latest_version_bgcs`.
  2. Emit one standalone iBGC per ``is_validated=True`` row regardless of
     tool or ``is_partial``. Validated rows are ground truth — never merged
     into prediction iBGCs, never absorbed.
  3. Merge non-validated GECCO and SanntiS predictions via transitive
     interval overlap (any positive intersection joins a component).
     Each component becomes one iBGC spanning ``min(starts) → max(ends)``
     and carries a sorted ``source_tools`` list. For each chain iBGC, if
     any non-validated antiSMASH prediction overlaps it, ``'antiSMASH'`` is
     added to ``source_tools`` — antiSMASH coordinates are *never* used
     to widen a chain interval.
  4. For each non-validated antiSMASH prediction:
       * if it overlaps any iBGC from steps 2–3, the prediction's
         ``integrated_bgc`` FK is set to that iBGC (so ``claimed_by_tools``
         attribution survives) — the iBGC's coords are NOT widened.
       * otherwise it becomes its own standalone iBGC inside the same cBGC.
  5. Mint each iBGC's accession; set ``cbgc`` FK from any member's cbgc_id;
     set ``contig`` FK; set source predictions' ``integrated_bgc`` FK.

This service is idempotent — calling it again wipes and rebuilds the table
(including tombstoning registry rows for iBGCs that no longer exist).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable, Iterable

from django.db import transaction
from psycopg2.extras import NumericRange

from discovery.models import (
    AccessionEntityType,
    ConsensusBgc,
    DashboardContig,
    IntegratedBgc,
    SourceBgcPrediction,
)
from discovery.querysets import latest_version_bgcs
from discovery.services.accession_registry import (
    lookup_or_mint_ibgc,
    tombstone_unused,
)

log = logging.getLogger(__name__)

# Tool names as stored in DashboardDetector.tool (case-sensitive).
TOOL_GECCO = "GECCO"
TOOL_SANNTIS = "SanntiS"
TOOL_ANTISMASH = "antiSMASH"

MERGE_TOOLS = (TOOL_GECCO, TOOL_SANNTIS)


def _range(start: int, end_inclusive: int) -> NumericRange:
    """Half-open ``[start, end+1)`` int4range value for Postgres."""
    return NumericRange(lower=int(start), upper=int(end_inclusive) + 1, bounds="[)")


def build_integrated_bgcs(
    *,
    progress_cb: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any]:
    """Rebuild the IntegratedBgc table.

    Returns counts:
        {
            "n_ibgcs": int,
            "n_source_bgcs": int,
            "n_absorbed_antismash": int,
            "n_validated_standalone": int,
            "by_tool": {"GECCO": int, "SanntiS": int, "antiSMASH": int, ...},
        }

    ``n_absorbed_antismash`` counts non-validated antiSMASH predictions
    that overlapped an existing iBGC — they get ``integrated_bgc`` set to
    that iBGC (for ``claimed_by_tools`` attribution) but did not widen
    its interval.
    """
    log.info("Wiping existing IntegratedBgc table")
    IntegratedBgc.objects.all().delete()
    SourceBgcPrediction.objects.exclude(integrated_bgc=None).update(integrated_bgc=None)

    qs = (
        latest_version_bgcs()
        .select_related("detector", "contig")
        .only(
            "id",
            "contig_id",
            "contig__accession",
            "cbgc_id",
            "bgc_range",
            "is_partial",
            "is_validated",
            "detector__tool",
        )
    )

    # Group rows per contig in-memory. Tuple:
    # (sbgc_id, cbgc_id, start, end, tool, is_partial, is_validated, contig_accession)
    rows_by_contig: dict[int, list[tuple[int, int, int, int, str | None, bool, bool, str]]] = defaultdict(list)
    for sbgc in qs.iterator():
        rng = sbgc.bgc_range
        if rng is None or rng.lower is None or rng.upper is None:
            continue
        start = int(rng.lower)
        end_inclusive = int(rng.upper) - 1
        rows_by_contig[sbgc.contig_id].append((
            sbgc.id,
            sbgc.cbgc_id,
            start,
            end_inclusive,
            sbgc.detector.tool if sbgc.detector_id else None,
            bool(sbgc.is_partial),
            bool(sbgc.is_validated),
            sbgc.contig.accession or "",
        ))

    total_contigs = len(rows_by_contig)
    log.info("Building iBGCs for %d contigs", total_contigs)

    counts = {
        "n_ibgcs": 0,
        "n_source_bgcs": 0,
        "n_absorbed_antismash": 0,
        "n_validated_standalone": 0,
        "by_tool": {TOOL_GECCO: 0, TOOL_SANNTIS: 0, TOOL_ANTISMASH: 0},
    }

    for processed, (contig_id, rows) in enumerate(rows_by_contig.items(), start=1):
        ibgcs, absorbed_anti, validated_standalone = _build_ibgcs_for_contig(rows)
        counts["n_absorbed_antismash"] += absorbed_anti
        counts["n_validated_standalone"] += validated_standalone

        contig_accession = rows[0][7] if rows else ""

        with transaction.atomic():
            for interval_start, interval_end, source_tools, member_sbgc_ids, absorbed_sbgc_ids in ibgcs:
                # Every member shares the same cBGC (overlapping predictions on a
                # contig land in the same cBGC envelope by construction in the
                # loader).
                cbgc_id = next(
                    (
                        cbgc_id
                        for sbgc_id, cbgc_id, *_ in rows
                        if sbgc_id in member_sbgc_ids and cbgc_id is not None
                    ),
                    None,
                )
                if cbgc_id is None:
                    log.warning(
                        "iBGC at contig=%s [%d,%d] has no cBGC; skipping",
                        contig_id, interval_start, interval_end,
                    )
                    continue

                cbgc = ConsensusBgc.objects.get(id=cbgc_id)
                ibgc = IntegratedBgc.objects.create(
                    accession="MGYB-PLACEHOLD-XX",  # overwritten below
                    cbgc=cbgc,
                    contig_id=contig_id,
                    bgc_range=_range(interval_start, interval_end),
                    source_tools=sorted(source_tools),
                )
                mint = lookup_or_mint_ibgc(
                    cbgc=cbgc,
                    contig_accession=contig_accession,
                    start_pos=interval_start,
                    end_pos=interval_end,
                    ibgc=ibgc,
                )
                if mint.accession != ibgc.accession:
                    ibgc.accession = mint.accession
                    ibgc.save(update_fields=["accession"])

                all_member_ids = list(member_sbgc_ids) + list(absorbed_sbgc_ids)
                SourceBgcPrediction.objects.filter(id__in=all_member_ids).update(
                    integrated_bgc=ibgc,
                )
                counts["n_ibgcs"] += 1
                counts["n_source_bgcs"] += len(all_member_ids)
                for tool in source_tools:
                    counts["by_tool"][tool] = counts["by_tool"].get(tool, 0) + 1

        if progress_cb is not None:
            progress_cb("contigs", processed, total_contigs)

    # Tombstone iBGC registry entries whose underlying row no longer exists.
    tombstoned = tombstone_unused(AccessionEntityType.IBGC)
    log.info("Tombstoned %d stale iBGC registry rows", tombstoned)

    log.info("iBGC build complete: %s", counts)
    return counts


def _build_ibgcs_for_contig(
    rows: list[tuple[int, int, int, int, str | None, bool, bool, str]],
) -> tuple[
    list[tuple[int, int, list[str], list[int], list[int]]],
    int,
    int,
]:
    """Return ``(iBGCs, n_absorbed_antismash, n_validated_standalone)``.

    Row format: ``(sbgc_id, cbgc_id, start, end, tool, is_partial, is_validated, contig_accession)``.
    Each iBGC tuple: ``(start, end, sorted_source_tools, member_sbgc_ids, absorbed_sbgc_ids)``.
    Members widen the interval; absorbed predictions do not but their FK is
    still set to the iBGC.
    """
    validated_rows = [r for r in rows if r[6]]
    non_validated = [r for r in rows if not r[6]]
    merge_rows = [r for r in non_validated if r[4] in MERGE_TOOLS]
    antismash_rows = [r for r in non_validated if r[4] == TOOL_ANTISMASH]

    ibgcs: list[tuple[int, int, list[str], list[int], list[int]]] = []

    # 1. Validated → one standalone iBGC each.
    n_validated_standalone = 0
    for sbgc_id, _cbgc_id, start, end, tool, _, _, _ in validated_rows:
        tools = [tool] if tool else []
        ibgcs.append((start, end, tools, [sbgc_id], []))
        n_validated_standalone += 1

    # 2. Transitive sort-and-sweep merge for GECCO/SanntiS (partial-agnostic).
    chain_start_idx = len(ibgcs)
    merge_rows.sort(key=lambda r: (r[2], r[3]))
    current: dict[str, Any] | None = None
    for sbgc_id, _cbgc_id, start, end, tool, _, _, _ in merge_rows:
        if current is None or start > current["end"]:
            if current is not None:
                ibgcs.append((
                    current["start"], current["end"],
                    sorted(set(current["tools"])),
                    current["sbgc_ids"], [],
                ))
            current = {"start": start, "end": end, "tools": [tool], "sbgc_ids": [sbgc_id]}
        else:
            current["end"] = max(current["end"], end)
            current["tools"].append(tool)
            current["sbgc_ids"].append(sbgc_id)
    if current is not None:
        ibgcs.append((
            current["start"], current["end"],
            sorted(set(current["tools"])),
            current["sbgc_ids"], [],
        ))

    # 3. & 4. antiSMASH: tag chain source_tools where overlapping; set
    # integrated_bgc FK (absorbed_sbgc_ids) for predictions that overlap any
    # existing iBGC; else emit as their own standalone iBGC.
    n_absorbed = 0
    for sbgc_id, _cbgc_id, start, end, _tool, _, _, _ in antismash_rows:
        overlapping_idx = _find_overlapping_idx(start, end, ibgcs)
        if overlapping_idx is not None:
            c_start, c_end, c_tools, c_members, c_absorbed = ibgcs[overlapping_idx]
            new_tools = sorted(set(c_tools) | {TOOL_ANTISMASH})
            ibgcs[overlapping_idx] = (
                c_start, c_end, new_tools, c_members, c_absorbed + [sbgc_id],
            )
            n_absorbed += 1
            continue
        ibgcs.append((start, end, [TOOL_ANTISMASH], [sbgc_id], []))

    # 5. Dedup by (start, end) — defensive against rare duplicate intervals
    # from validated + chain mergers.
    ibgcs = _dedup_ibgcs_by_interval(ibgcs)

    return ibgcs, n_absorbed, n_validated_standalone


def _dedup_ibgcs_by_interval(
    ibgcs: list[tuple[int, int, list[str], list[int], list[int]]],
) -> list[tuple[int, int, list[str], list[int], list[int]]]:
    by_key: dict[tuple[int, int], tuple[list[str], list[int], list[int]]] = {}
    for start, end, tools, members, absorbed in ibgcs:
        key = (start, end)
        if key in by_key:
            t, m, a = by_key[key]
            by_key[key] = (
                sorted(set(t) | set(tools)),
                m + list(members),
                a + list(absorbed),
            )
        else:
            by_key[key] = (sorted(set(tools)), list(members), list(absorbed))
    return [(s, e, t, m, a) for (s, e), (t, m, a) in by_key.items()]


def _find_overlapping_idx(
    start: int,
    end: int,
    ibgcs: Iterable[tuple[int, int, list[str], list[int], list[int]]],
) -> int | None:
    for idx, (ibgc_start, ibgc_end, _t, _m, _a) in enumerate(ibgcs):
        if start <= ibgc_end and end >= ibgc_start:
            return idx
    return None
