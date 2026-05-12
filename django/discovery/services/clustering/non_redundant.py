"""Build the ``NonRedundantBGC`` table from latest-version BGC predictions.

The NRB table is the input unit for the domain/adjacency clustering pipeline.
Construction rules (per contig):

  1. Pull latest-version BGCs that are either ``is_partial=False`` or
     ``is_validated=True`` via :func:`discovery.querysets.latest_version_bgcs`.
  2. Emit one standalone NRB per ``is_validated=True`` BGC, regardless of tool
     or ``is_partial``. Validated rows are ground truth — never merged into
     prediction NRBs, never absorbed.
  3. Merge non-validated GECCO and SanntiS predictions on the same contig via
     *transitive* interval overlap (any positive intersection joins a
     component). Each component becomes one NRB spanning
     ``min(starts) → max(ends)`` and carries a sorted ``source_tools`` list.
  4. Admit non-validated antiSMASH predictions as their own NRB iff they do
     **not** overlap any already-built NRB on the same contig (validated
     standalones included). Overlapping antiSMASH calls are absorbed (their
     source ``DashboardBgc`` rows get ``non_redundant_bgc=NULL`` and are
     reclassified later via KNN).
  5. Set ``DashboardBgc.non_redundant_bgc`` + ``classification_source='merged'``
     on every source row that fed an NRB. Non-contributing BGCs get
     ``non_redundant_bgc=NULL``.

This service is idempotent — calling it again wipes and rebuilds the table.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable, Iterable

from django.db import transaction
from django.db.models import Q

from discovery.models import DashboardBgc, NonRedundantBGC
from discovery.querysets import latest_version_bgcs

log = logging.getLogger(__name__)

# Tool names as stored in DashboardDetector.tool (case-sensitive).
TOOL_GECCO = "GECCO"
TOOL_SANNTIS = "SanntiS"
TOOL_ANTISMASH = "antiSMASH"

MERGE_TOOLS = (TOOL_GECCO, TOOL_SANNTIS)


def build_non_redundant_bgcs(
    *,
    progress_cb: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any]:
    """Rebuild the NonRedundantBGC table.

    Returns counts:
        {
            "n_nrbs": int,
            "n_source_bgcs": int,
            "n_absorbed_antismash": int,
            "n_validated_standalone": int,
            "by_tool": {"GECCO": int, "SanntiS": int, "antiSMASH": int, ...},
        }
    """
    log.info("Wiping existing NonRedundantBGC table")
    NonRedundantBGC.objects.all().delete()
    # Defensive: clear stale FKs on every DashboardBgc row.
    DashboardBgc.objects.exclude(non_redundant_bgc=None).update(non_redundant_bgc=None)

    qs = (
        latest_version_bgcs()
        .filter(Q(is_partial=False) | Q(is_validated=True))
        .select_related("detector")
        .only(
            "id",
            "contig_id",
            "start_position",
            "end_position",
            "is_validated",
            "detector__tool",
        )
    )

    # Group rows per contig in-memory. For datasets that don't fit in memory,
    # this could be re-implemented as a streamed per-contig fetch, but the
    # current table sizes (~10⁶ rows) comfortably fit.
    rows_by_contig: dict[int, list[tuple[int, int, int, str | None, bool]]] = defaultdict(list)
    for bgc_id, contig_id, start, end, tool, is_validated in qs.values_list(
        "id", "contig_id", "start_position", "end_position",
        "detector__tool", "is_validated",
    ):
        rows_by_contig[contig_id].append((bgc_id, start, end, tool, bool(is_validated)))

    total_contigs = len(rows_by_contig)
    log.info("Building NRBs for %d contigs", total_contigs)

    counts = {
        "n_nrbs": 0,
        "n_source_bgcs": 0,
        "n_absorbed_antismash": 0,
        "n_validated_standalone": 0,
        "by_tool": {TOOL_GECCO: 0, TOOL_SANNTIS: 0, TOOL_ANTISMASH: 0},
    }

    for processed, (contig_id, rows) in enumerate(rows_by_contig.items(), start=1):
        nrbs, absorbed_anti, validated_standalone = _build_nrbs_for_contig(contig_id, rows)
        counts["n_absorbed_antismash"] += absorbed_anti
        counts["n_validated_standalone"] += validated_standalone
        with transaction.atomic():
            for interval_start, interval_end, source_tools, member_bgc_ids in nrbs:
                nrb = NonRedundantBGC.objects.create(
                    contig_id=contig_id,
                    start_position=interval_start,
                    end_position=interval_end,
                    source_tools=sorted(source_tools),
                )
                DashboardBgc.objects.filter(id__in=member_bgc_ids).update(
                    non_redundant_bgc=nrb,
                    classification_source="merged",
                )
                counts["n_nrbs"] += 1
                counts["n_source_bgcs"] += len(member_bgc_ids)
                for tool in source_tools:
                    counts["by_tool"][tool] = counts["by_tool"].get(tool, 0) + 1

        if progress_cb is not None:
            progress_cb("contigs", processed, total_contigs)

    log.info("NRB build complete: %s", counts)
    return counts


def _build_nrbs_for_contig(
    contig_id: int,
    rows: list[tuple[int, int, int, str | None, bool]],
) -> tuple[list[tuple[int, int, list[str], list[int]]], int, int]:
    """Return (NRB tuples, n_absorbed_antismash, n_validated_standalone) for a contig.

    Each NRB tuple: (start, end, sorted_source_tools, member_bgc_ids).
    """
    validated_rows = [r for r in rows if r[4]]
    non_validated = [r for r in rows if not r[4]]
    merge_rows = [r for r in non_validated if r[3] in MERGE_TOOLS]
    antismash_rows = [r for r in non_validated if r[3] == TOOL_ANTISMASH]

    nrbs: list[tuple[int, int, list[str], list[int]]] = []

    # 1. Validated BGCs → one standalone NRB each. Ground truth, never merged.
    n_validated_standalone = 0
    for bgc_id, start, end, tool, _ in validated_rows:
        tools = [tool] if tool else []
        nrbs.append((start, end, tools, [bgc_id]))
        n_validated_standalone += 1

    # 2. Sort-and-sweep merge for non-validated GECCO + SanntiS (transitive).
    merge_rows.sort(key=lambda r: (r[1], r[2]))
    current: dict[str, Any] | None = None
    for bgc_id, start, end, tool, _ in merge_rows:
        if current is None or start > current["end"]:
            if current is not None:
                nrbs.append(
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
        nrbs.append(
            (
                current["start"],
                current["end"],
                sorted(set(current["tools"])),
                current["bgc_ids"],
            )
        )

    # 3. Admit non-validated antiSMASH iff non-overlapping with any existing
    #    NRB on this contig (including validated standalones).
    n_absorbed = 0
    for bgc_id, start, end, _tool, _ in antismash_rows:
        if _overlaps_any(start, end, nrbs):
            n_absorbed += 1
            continue
        nrbs.append((start, end, [TOOL_ANTISMASH], [bgc_id]))

    return nrbs, n_absorbed, n_validated_standalone


def _overlaps_any(
    start: int,
    end: int,
    nrbs: Iterable[tuple[int, int, list[str], list[int]]],
) -> bool:
    for nrb_start, nrb_end, _tools, _ids in nrbs:
        if start <= nrb_end and end >= nrb_start:
            return True
    return False
