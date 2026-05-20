"""In-memory cBGC assignment for source-BGC ingestion.

A cBGC (``ConsensusBgc``) is the chained-overlap envelope of all source BGC
predictions that share at least one base on a contig. During bulk load each
incoming source prediction triggers one of three actions on its contig:

  - **create** a new cBGC when nothing overlaps,
  - **extend** an existing cBGC when exactly one overlaps,
  - **merge** existing cBGCs when two or more overlap (the survivor keeps
    the lowest db PK and the absorbed cBGCs are tombstoned, with their
    accessions written into ``AccessionAlias`` so old links still resolve).

cBGC accessions (``MGYB-XXXXXX``) are stable forever via the accession
registry: a cBGC reproduced with the same ``(contig_accession, start, end)``
on the next rebuild reuses its accession. Extension / merge updates the
registry row's coords inline so the final state remains lookup-able.

Source-BGC ``prediction_accession`` is derived per call as
``{cbgc.accession}.{tool_code}.{bgc_number:02}``, e.g. ``MGYB-ABC123.ANT.01``.
``bgc_number`` is monotonic within (cbgc, detector); the exclusion constraint
``excl_source_bgc_overlap_per_detector`` already prevents same-detector
predictions from sharing a range inside one contig.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from psycopg2.extras import NumericRange

from discovery.models import (
    AccessionAlias,
    AccessionEntityType,
    AccessionRegistry,
    ConsensusBgc,
    SourceBgcPrediction,
)
from discovery.services.accession_registry import lookup_or_mint_cbgc

logger = logging.getLogger(__name__)


def _range(start: int, end_inclusive: int) -> NumericRange:
    """Build the half-open ``int4range`` Postgres stores: ``[start, end+1)``."""
    return NumericRange(lower=int(start), upper=int(end_inclusive) + 1, bounds="[)")


@dataclass
class _Cbgc:
    """In-memory shadow of a ``ConsensusBgc`` row, plus per-detector counters."""

    db_id: int
    accession: str
    contig_accession: str
    start: int
    end: int
    next_bgc_number: dict[int, int] = field(default_factory=lambda: defaultdict(lambda: 1))


class CbgcAssigner:
    """Stateful helper that assigns source BGCs to cBGCs during a single load run.

    Maintains a per-contig sorted list of in-memory ``_Cbgc`` shadows so each
    overlap query is O(log n). All DB writes (create / extend / merge /
    alias / registry coord-sync) flow through this class so the caller
    stays oblivious to the cBGC bookkeeping.

    Usage::

        assigner = CbgcAssigner()
        for bgc_row in bgc_rows:
            cbgc_id, bgc_number, prediction_accession = assigner.assign(
                contig_id=...,
                contig_accession=...,
                start=...,
                end=...,
                detector_id=...,
                tool_code=...,
            )
    """

    def __init__(self) -> None:
        self._cbgcs: dict[int, list[_Cbgc]] = defaultdict(list)

    def assign(
        self,
        *,
        contig_id: int,
        contig_accession: str,
        start: int,
        end: int,
        detector_id: int,
        tool_code: str,
    ) -> tuple[int, int, str]:
        """Assign a source BGC at ``[start, end]`` (inclusive) to a cBGC.

        Returns ``(cbgc_id, bgc_number, prediction_accession)``.
        """
        overlaps = self._find_overlaps(contig_id, start, end)

        if not overlaps:
            cbgc = self._create(contig_id, contig_accession, start, end)
        elif len(overlaps) == 1:
            cbgc = self._extend(overlaps[0], contig_id, contig_accession, start, end)
        else:
            cbgc = self._merge(overlaps, contig_id, contig_accession, start, end)

        bgc_num = cbgc.next_bgc_number[detector_id]
        cbgc.next_bgc_number[detector_id] = bgc_num + 1
        prediction_accession = f"{cbgc.accession}.{tool_code}.{bgc_num:02}"
        return cbgc.db_id, bgc_num, prediction_accession

    # ── internal helpers ──────────────────────────────────────────────────

    def _find_overlaps(self, contig_id: int, start: int, end: int) -> list[_Cbgc]:
        return [c for c in self._cbgcs[contig_id] if c.start <= end and c.end >= start]

    def _create(
        self,
        contig_id: int,
        contig_accession: str,
        start: int,
        end: int,
    ) -> _Cbgc:
        cbgc_row = ConsensusBgc.objects.create(
            contig_id=contig_id,
            bgc_range=_range(start, end),
            accession="MGYB-PLACEHOLDR",  # overwritten next
        )
        mint = lookup_or_mint_cbgc(
            contig_accession=contig_accession,
            start_pos=start,
            end_pos=end,
            cbgc=cbgc_row,
        )
        if mint.accession != cbgc_row.accession:
            cbgc_row.accession = mint.accession
            cbgc_row.save(update_fields=["accession"])
        c = _Cbgc(
            db_id=cbgc_row.id,
            accession=mint.accession,
            contig_accession=contig_accession,
            start=start,
            end=end,
        )
        self._insert_sorted(contig_id, c)
        return c

    def _extend(
        self,
        cbgc: _Cbgc,
        contig_id: int,
        contig_accession: str,
        start: int,
        end: int,
    ) -> _Cbgc:
        new_start = min(cbgc.start, start)
        new_end = max(cbgc.end, end)
        if new_start == cbgc.start and new_end == cbgc.end:
            return cbgc
        ConsensusBgc.objects.filter(id=cbgc.db_id).update(
            bgc_range=_range(new_start, new_end),
        )
        # Keep the registry's identity tuple aligned to the final coords so
        # the next rebuild's lookup finds the same accession.
        AccessionRegistry.objects.filter(accession=cbgc.accession).update(
            start_pos=new_start,
            end_pos=new_end,
        )
        cbgc.start = new_start
        cbgc.end = new_end
        return cbgc

    def _merge(
        self,
        overlaps: list[_Cbgc],
        contig_id: int,
        contig_accession: str,
        start: int,
        end: int,
    ) -> _Cbgc:
        """Merge multiple overlapping cBGCs into the one with the lowest PK.

        Absorbed cBGCs are deleted; their accessions land in
        ``AccessionAlias`` so external links continue to resolve. Source BGC
        rows already pointing at the absorbed cBGCs are re-FK'd to the
        survivor.
        """
        overlaps.sort(key=lambda c: c.db_id)
        survivor = overlaps[0]
        absorbed = overlaps[1:]

        new_start = min(start, survivor.start, *(c.start for c in absorbed))
        new_end = max(end, survivor.end, *(c.end for c in absorbed))

        for c in absorbed:
            for det_id, num in c.next_bgc_number.items():
                survivor.next_bgc_number[det_id] = max(
                    survivor.next_bgc_number[det_id], num,
                )

        absorbed_ids = [c.db_id for c in absorbed]
        absorbed_accessions = [c.accession for c in absorbed]

        # Re-link any source predictions that already pointed at the absorbed
        # cBGCs (rare during a single load run; defensive).
        SourceBgcPrediction.objects.filter(cbgc_id__in=absorbed_ids).update(
            cbgc_id=survivor.db_id,
        )

        # Survivor's registry row absorbs the absorbed accessions as aliases.
        survivor_registry = AccessionRegistry.objects.get(accession=survivor.accession)
        AccessionAlias.objects.bulk_create(
            [
                AccessionAlias(alias_accession=acc, registry=survivor_registry)
                for acc in absorbed_accessions
            ],
            ignore_conflicts=True,
        )

        # Delete absorbed cBGC rows + tombstone their registry entries (set
        # current_cbgc=NULL via FK on_delete=SET_NULL).
        ConsensusBgc.objects.filter(id__in=absorbed_ids).delete()

        # Update survivor's range + registry coords.
        ConsensusBgc.objects.filter(id=survivor.db_id).update(
            bgc_range=_range(new_start, new_end),
        )
        AccessionRegistry.objects.filter(accession=survivor.accession).update(
            start_pos=new_start,
            end_pos=new_end,
        )
        survivor.start = new_start
        survivor.end = new_end

        # Drop absorbed from in-memory list.
        absorbed_set = set(absorbed_ids)
        self._cbgcs[contig_id] = [
            c for c in self._cbgcs[contig_id] if c.db_id not in absorbed_set
        ]

        return survivor

    def _insert_sorted(self, contig_id: int, cbgc: _Cbgc) -> None:
        lst = self._cbgcs[contig_id]
        lo, hi = 0, len(lst)
        while lo < hi:
            mid = (lo + hi) // 2
            if lst[mid].start < cbgc.start:
                lo = mid + 1
            else:
                hi = mid
        lst.insert(lo, cbgc)
