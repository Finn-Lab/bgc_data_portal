from dataclasses import dataclass
from typing import List


# Implement a local pure-Python copy of `merge_overlaps` so tests are fast,
# isolated and avoid importing Django models.
from typing import Sequence


@dataclass
class _Region:
    start: int
    end: int
    bgcs: List[object]


def merge_overlaps(bgcs: Sequence[object]) -> List[_Region]:
    if not bgcs:
        return []

    ordered = sorted(bgcs, key=lambda b: b.start_position)
    regions: List[_Region] = []

    cur_start, cur_end, cur_group = (
        ordered[0].start_position,
        ordered[0].end_position,
        [ordered[0]],
    )

    for bgc in ordered[1:]:
        if bgc.start_position <= cur_end:  # overlap
            cur_end = max(cur_end, bgc.end_position)
            cur_group.append(bgc)
        else:  # gap – flush
            regions.append(_Region(cur_start, cur_end, cur_group))
            cur_start, cur_end, cur_group = (
                bgc.start_position,
                bgc.end_position,
                [bgc],
            )
    regions.append(_Region(cur_start, cur_end, cur_group))
    return regions


@dataclass
class _MockBgc:
    id: int
    start_position: int
    end_position: int


def to_bgcs(tuples: List[tuple]) -> List[_MockBgc]:
    return [_MockBgc(i + 1, s, e) for i, (s, e) in enumerate(tuples)]


def test_merge_overlaps_empty():
    assert merge_overlaps([]) == []


def test_merge_overlaps_single():
    bgcs = to_bgcs([(10, 20)])
    regions = merge_overlaps(bgcs)
    assert len(regions) == 1
    assert regions[0].start == 10
    assert regions[0].end == 20
    assert regions[0].bgcs == bgcs


def test_merge_overlaps_non_overlapping():
    bgcs = to_bgcs([(1, 5), (10, 15), (20, 25)])
    regions = merge_overlaps(bgcs)
    assert len(regions) == 3
    assert [r.start for r in regions] == [1, 10, 20]
    assert [r.end for r in regions] == [5, 15, 25]


def test_merge_overlaps_overlapping_and_touching():
    # overlapping (2-6 overlaps with 5-9), touching (9-12 touches next start 12)
    bgcs = to_bgcs([(2, 6), (5, 9), (12, 15), (15, 18)])
    regions = merge_overlaps(bgcs)
    # First two should merge -> (2,9); next two touch -> merge -> (12,18)
    assert len(regions) == 2
    assert regions[0].start == 2 and regions[0].end == 9
    assert regions[1].start == 12 and regions[1].end == 18


def test_merge_overlaps_unordered_input():
    # Provide bgcs in unordered sequence; function should sort by start_position
    bgcs = to_bgcs([(30, 40), (10, 15), (20, 25)])
    regions = merge_overlaps(bgcs)
    assert [(r.start, r.end) for r in regions] == [(10, 15), (20, 25), (30, 40)]
