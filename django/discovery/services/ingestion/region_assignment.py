"""In-memory region assignment for BGC ingestion.

During bulk load, BGCs are assigned to aggregated regions on the fly.  An
interval tree per contig tracks existing regions so that overlap queries are
O(log n).  When a new BGC overlaps one or more existing regions, borders are
extended and — in the bridge case — regions are merged, with aliases recorded
for the absorbed accessions.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from discovery.models import DashboardRegion, RegionAccessionAlias

logger = logging.getLogger(__name__)


@dataclass
class _Region:
    """Lightweight in-memory representation of a region."""

    db_id: int
    start: int
    end: int
    next_bgc_number: dict[int, int] = field(default_factory=lambda: defaultdict(lambda: 1))


class RegionAssigner:
    """Stateful helper that assigns BGCs to regions during a single ingestion run.

    Keeps an in-memory sorted list of regions per contig for fast overlap
    detection.  All DB writes (create / update / alias) happen through this
    class so the caller can remain oblivious to the merging logic.

    Usage::

        assigner = RegionAssigner()
        for bgc_row in bgc_rows:
            region_id, bgc_number, accession = assigner.assign(
                contig_id=..., start=..., end=..., detector_id=..., tool_code=...,
            )
    """

    def __init__(self) -> None:
        # contig_id → sorted list of _Region (sorted by start)
        self._regions: dict[int, list[_Region]] = defaultdict(list)
        # Batch of DashboardRegion objects pending DB creation
        self._pending_creates: list[DashboardRegion] = []
        # Batch of (region_id, field, value) pending DB updates
        self._pending_updates: list[tuple[int, int, int]] = []
        # Aliases to create
        self._pending_aliases: list[RegionAccessionAlias] = []

    def assign(
        self,
        contig_id: int,
        start: int,
        end: int,
        detector_id: int,
        tool_code: str,
    ) -> tuple[int, int, str]:
        """Assign a BGC to a region.

        Returns ``(region_id, bgc_number, structured_accession)``.
        """
        overlaps = self._find_overlaps(contig_id, start, end)

        if not overlaps:
            region = self._create_region(contig_id, start, end)
        elif len(overlaps) == 1:
            region = overlaps[0]
            self._extend(region, start, end, contig_id)
        else:
            region = self._merge(overlaps, contig_id, start, end)

        bgc_num = region.next_bgc_number[detector_id]
        region.next_bgc_number[detector_id] = bgc_num + 1

        accession = f"MGYB{region.db_id:08}.{tool_code}.{detector_id}.{bgc_num:02}"
        return region.db_id, bgc_num, accession

    # ── internal helpers ──────────────────────────────────────────────────

    def _find_overlaps(self, contig_id: int, start: int, end: int) -> list[_Region]:
        """Return regions on *contig_id* that overlap [start, end]."""
        return [
            r
            for r in self._regions[contig_id]
            if r.start <= end and r.end >= start
        ]

    def _create_region(self, contig_id: int, start: int, end: int) -> _Region:
        obj = DashboardRegion.objects.create(
            contig_id=contig_id,
            start_position=start,
            end_position=end,
        )
        region = _Region(db_id=obj.id, start=start, end=end)
        self._insert_sorted(contig_id, region)
        return region

    def _extend(self, region: _Region, start: int, end: int, contig_id: int) -> None:
        changed = False
        if start < region.start:
            region.start = start
            changed = True
        if end > region.end:
            region.end = end
            changed = True
        if changed:
            DashboardRegion.objects.filter(id=region.db_id).update(
                start_position=region.start,
                end_position=region.end,
            )

    def _merge(
        self,
        overlaps: list[_Region],
        contig_id: int,
        start: int,
        end: int,
    ) -> _Region:
        """Merge multiple overlapping regions into the one with the lowest PK."""
        overlaps.sort(key=lambda r: r.db_id)
        survivor = overlaps[0]
        absorbed = overlaps[1:]

        new_start = min(start, survivor.start, *(r.start for r in absorbed))
        new_end = max(end, survivor.end, *(r.end for r in absorbed))

        # Merge bgc_number counters from absorbed into survivor
        for r in absorbed:
            for det_id, num in r.next_bgc_number.items():
                survivor.next_bgc_number[det_id] = max(
                    survivor.next_bgc_number[det_id], num
                )

        # Re-link BGCs from absorbed regions to survivor
        absorbed_ids = [r.db_id for r in absorbed]
        from discovery.models import DashboardBgc

        DashboardBgc.objects.filter(region_id__in=absorbed_ids).update(
            region_id=survivor.db_id
        )

        # Create aliases for absorbed regions
        aliases = [
            RegionAccessionAlias(
                alias_accession=f"MGYB{r.db_id:08}",
                region_id=survivor.db_id,
            )
            for r in absorbed
        ]
        RegionAccessionAlias.objects.bulk_create(aliases, ignore_conflicts=True)

        # Delete absorbed regions from DB
        DashboardRegion.objects.filter(id__in=absorbed_ids).delete()

        # Remove absorbed from in-memory list
        self._regions[contig_id] = [
            r for r in self._regions[contig_id] if r.db_id not in set(absorbed_ids)
        ]

        # Extend survivor
        survivor.start = new_start
        survivor.end = new_end
        DashboardRegion.objects.filter(id=survivor.db_id).update(
            start_position=new_start,
            end_position=new_end,
        )

        return survivor

    def _insert_sorted(self, contig_id: int, region: _Region) -> None:
        """Insert *region* into the sorted list for *contig_id*."""
        lst = self._regions[contig_id]
        lo, hi = 0, len(lst)
        while lo < hi:
            mid = (lo + hi) // 2
            if lst[mid].start < region.start:
                lo = mid + 1
            else:
                hi = mid
        lst.insert(lo, region)
