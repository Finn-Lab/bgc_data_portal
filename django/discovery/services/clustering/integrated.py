"""Build the ``IntegratedBGC`` table from latest-version BGC predictions.

The iBGC table is the complete registry of latest-version BGCs. It is also the
input unit for the domain/adjacency clustering pipeline, but the pipeline
itself filters down to the *clusterable* subset (iBGCs that contain at least
one ``is_partial=False`` or ``is_validated=True`` source BGC).

Construction rules (per contig):

  1. Pull all latest-version BGCs via
     :func:`discovery.querysets.latest_version_bgcs`.
  2. Emit one standalone iBGC per ``is_validated=True`` BGC, regardless of tool
     or ``is_partial``. Validated rows are ground truth — never merged into
     prediction iBGCs, never absorbed.
  3. Merge non-validated GECCO and SanntiS predictions on the same contig via
     *transitive* interval overlap, **regardless of ``is_partial``** (any
     positive intersection joins a component). Each component becomes one iBGC
     spanning ``min(starts) → max(ends)`` and carries a sorted ``source_tools``
     list. Then, for each chain iBGC, if **any** non-validated antiSMASH BGC on
     the same contig overlaps it, add ``'antiSMASH'`` to that chain's
     ``source_tools`` — antiSMASH coordinates are *never* used to widen the
     chain interval.
  4. For each non-validated antiSMASH BGC (regardless of ``is_partial``):
     if it overlaps any iBGC built in steps 2–3 (validated standalone or
     SanntiS/GECCO chain), it is absorbed — its ``DashboardBgc`` row keeps
     ``integrated_bgc=NULL`` and is reclassified later via KNN. Otherwise
     it becomes its own standalone iBGC.
  5. Dedup by ``(start, end)`` — different buckets can occasionally emit
     identical intervals; collapse them so we don't violate the
     ``uniq_ibgc_contig_pos`` DB constraint. Tools and member BGC ids are
     unioned into the surviving iBGC.
  6. Set ``DashboardBgc.integrated_bgc`` + ``classification_source='merged'``
     on every source row that fed an iBGC. Absorbed antiSMASH rows stay at
     ``integrated_bgc=NULL``.

This service is idempotent — calling it again wipes and rebuilds the table.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable, Iterable

from django.db import transaction

from discovery.models import DashboardBgc, IntegratedBGC
from discovery.querysets import latest_version_bgcs

log = logging.getLogger(__name__)

# Tool names as stored in DashboardDetector.tool (case-sensitive).
TOOL_GECCO = "GECCO"
TOOL_SANNTIS = "SanntiS"
TOOL_ANTISMASH = "antiSMASH"

MERGE_TOOLS = (TOOL_GECCO, TOOL_SANNTIS)


def build_integrated_bgcs(
    *,
    progress_cb: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any]:
    """Rebuild the IntegratedBGC table.

    Returns counts:
        {
            "n_ibgcs": int,
            "n_source_bgcs": int,
            "n_absorbed_antismash": int,
            "n_validated_standalone": int,
            "by_tool": {"GECCO": int, "SanntiS": int, "antiSMASH": int, ...},
        }

    ``n_absorbed_antismash`` counts non-validated antiSMASH BGCs whose
    ``DashboardBgc.integrated_bgc`` ended up NULL because they overlapped a
    validated standalone or a SanntiS/GECCO chain.
    """
    log.info("Wiping existing IntegratedBGC table")
    IntegratedBGC.objects.all().delete()
    # Defensive: clear stale FKs on every DashboardBgc row.
    DashboardBgc.objects.exclude(integrated_bgc=None).update(integrated_bgc=None)

    qs = (
        latest_version_bgcs()
        .select_related("detector")
        .only(
            "id",
            "contig_id",
            "start_position",
            "end_position",
            "is_partial",
            "is_validated",
            "detector__tool",
        )
    )

    # Group rows per contig in-memory. For datasets that don't fit in memory,
    # this could be re-implemented as a streamed per-contig fetch, but the
    # current table sizes (~10⁶ rows) comfortably fit.
    rows_by_contig: dict[int, list[tuple[int, int, int, str | None, bool, bool]]] = defaultdict(list)
    for bgc_id, contig_id, start, end, tool, is_partial, is_validated in qs.values_list(
        "id", "contig_id", "start_position", "end_position",
        "detector__tool", "is_partial", "is_validated",
    ):
        rows_by_contig[contig_id].append(
            (bgc_id, start, end, tool, bool(is_partial), bool(is_validated))
        )

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
        ibgcs, absorbed_anti, validated_standalone = _build_ibgcs_for_contig(
            contig_id, rows,
        )
        counts["n_absorbed_antismash"] += absorbed_anti
        counts["n_validated_standalone"] += validated_standalone
        with transaction.atomic():
            for interval_start, interval_end, source_tools, member_bgc_ids in ibgcs:
                ibgc = IntegratedBGC.objects.create(
                    contig_id=contig_id,
                    start_position=interval_start,
                    end_position=interval_end,
                    source_tools=sorted(source_tools),
                )
                DashboardBgc.objects.filter(id__in=member_bgc_ids).update(
                    integrated_bgc=ibgc,
                    classification_source="merged",
                )
                counts["n_ibgcs"] += 1
                counts["n_source_bgcs"] += len(member_bgc_ids)
                for tool in source_tools:
                    counts["by_tool"][tool] = counts["by_tool"].get(tool, 0) + 1

        if progress_cb is not None:
            progress_cb("contigs", processed, total_contigs)

    log.info("iBGC build complete: %s", counts)
    return counts


def _build_ibgcs_for_contig(
    contig_id: int,
    rows: list[tuple[int, int, int, str | None, bool, bool]],
) -> tuple[list[tuple[int, int, list[str], list[int]]], int, int]:
    """Return ``(iBGC tuples, n_absorbed_antismash, n_validated_standalone)``
    for a contig.

    Row format: ``(bgc_id, start, end, tool, is_partial, is_validated)``.
    Each iBGC tuple: ``(start, end, sorted_source_tools, member_bgc_ids)``.
    """
    validated_rows = [r for r in rows if r[5]]
    non_validated = [r for r in rows if not r[5]]
    # Partial flag no longer gates eligibility: SanntiS/GECCO partials merge
    # into chains, and partial antiSMASH goes through the same absorb logic
    # as non-partial antiSMASH.
    merge_rows = [r for r in non_validated if r[3] in MERGE_TOOLS]
    antismash_rows = [r for r in non_validated if r[3] == TOOL_ANTISMASH]

    ibgcs: list[tuple[int, int, list[str], list[int]]] = []

    # 1. Validated BGCs → one standalone iBGC each. Ground truth, never merged
    #    with predictions, never tagged with overlapping antiSMASH.
    n_validated_standalone = 0
    for bgc_id, start, end, tool, _, _ in validated_rows:
        tools = [tool] if tool else []
        ibgcs.append((start, end, tools, [bgc_id]))
        n_validated_standalone += 1

    # 2. Sort-and-sweep merge for non-validated GECCO + SanntiS (transitive,
    #    partial-agnostic). Track where chain iBGCs begin so step 3 can mutate
    #    only their source_tools.
    chain_start_idx = len(ibgcs)
    merge_rows.sort(key=lambda r: (r[1], r[2]))
    current: dict[str, Any] | None = None
    for bgc_id, start, end, tool, _, _ in merge_rows:
        if current is None or start > current["end"]:
            if current is not None:
                ibgcs.append(
                    (
                        current["start"],
                        current["end"],
                        sorted(set(current["tools"])),
                        current["bgc_ids"],
                    )
                )
            current = {
                "start": start,
                "end": end,
                "tools": [tool],
                "bgc_ids": [bgc_id],
            }
        else:
            current["end"] = max(current["end"], end)
            current["tools"].append(tool)
            current["bgc_ids"].append(bgc_id)
    if current is not None:
        ibgcs.append(
            (
                current["start"],
                current["end"],
                sorted(set(current["tools"])),
                current["bgc_ids"],
            )
        )

    # 3. Tag chain iBGCs with overlapping non-validated antiSMASH — source_tools
    #    only, no boundary change. antiSMASH coordinates never widen a chain.
    if antismash_rows:
        for i in range(chain_start_idx, len(ibgcs)):
            c_start, c_end, c_tools, c_ids = ibgcs[i]
            if any(
                a_start <= c_end and a_end >= c_start
                for _abgc, a_start, a_end, _t, _p, _v in antismash_rows
            ):
                ibgcs[i] = (
                    c_start,
                    c_end,
                    sorted(set(c_tools) | {TOOL_ANTISMASH}),
                    c_ids,
                )

    # 4. Non-validated antiSMASH: absorb if overlaps any iBGC built in steps
    #    1–2 (validated standalone or chain); else standalone iBGC. The chain
    #    iBGC's source_tools already records the antiSMASH overlap via step 3
    #    — the absorbed DashboardBgc row keeps integrated_bgc=NULL and is
    #    reclassified later via KNN.
    n_absorbed = 0
    for bgc_id, start, end, _tool, _, _ in antismash_rows:
        if _overlaps_any(start, end, ibgcs):
            n_absorbed += 1
            continue
        ibgcs.append((start, end, [TOOL_ANTISMASH], [bgc_id]))

    # 5. Dedup by (start, end) — defensive. Different buckets can legitimately
    #    emit identical intervals on the same contig; collapse them so we
    #    don't violate the ``uniq_ibgc_contig_pos`` DB constraint.
    ibgcs = _dedup_ibgcs_by_interval(ibgcs)

    return ibgcs, n_absorbed, n_validated_standalone


def _dedup_ibgcs_by_interval(
    ibgcs: list[tuple[int, int, list[str], list[int]]],
) -> list[tuple[int, int, list[str], list[int]]]:
    """Collapse iBGC tuples that share the same ``(start, end)`` interval.

    Tools are sorted-unique; member BGC ids are concatenated in encounter
    order. Used by :func:`_build_ibgcs_for_contig` to keep the per-contig
    output unique on ``(start, end)``.
    """
    by_key: dict[tuple[int, int], tuple[list[str], list[int]]] = {}
    for start, end, tools, bgc_ids in ibgcs:
        key = (start, end)
        if key in by_key:
            existing_tools, existing_ids = by_key[key]
            by_key[key] = (
                sorted(set(existing_tools) | set(tools)),
                existing_ids + list(bgc_ids),
            )
        else:
            by_key[key] = (sorted(set(tools)), list(bgc_ids))
    return [(s, e, tools, ids) for (s, e), (tools, ids) in by_key.items()]


def _overlaps_any(
    start: int,
    end: int,
    ibgcs: Iterable[tuple[int, int, list[str], list[int]]],
) -> bool:
    for ibgc_start, ibgc_end, _tools, _ids in ibgcs:
        if start <= ibgc_end and end >= ibgc_start:
            return True
    return False
