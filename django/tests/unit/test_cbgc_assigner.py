"""Unit tests for the in-memory cBGC assigner.

CbgcAssigner owns the create / extend / merge decision per incoming
source BGC prediction. Tests confirm:

  * **create** — first prediction on a contig mints a new cBGC and a
    fresh registry row.
  * **extend** — overlapping single neighbour widens the existing cBGC
    and re-syncs its registry coords without reassigning the accession.
  * **merge** — two pre-existing cBGCs bridged by a new prediction
    collapse to the lowest-PK survivor; absorbed accessions land in
    ``AccessionAlias`` and resolve to the survivor.
  * Disjointness within a contig (the exclusion constraint must hold
    after the assigner runs).
  * ``prediction_accession`` follows ``MGYB-XXXXXX.<TOOL>.<NN>`` and the
    NN counter is monotonic per (cbgc, detector).
"""

from __future__ import annotations

import pytest

from discovery.models import (
    AccessionAlias,
    AccessionRegistry,
    ConsensusBgc,
)
from discovery.services.ingestion.cbgc_assigner import CbgcAssigner

from tests.factories.discovery_models import (
    DashboardContigFactory,
    DashboardDetectorFactory,
)


@pytest.fixture
def contig(db):
    return DashboardContigFactory()


@pytest.fixture
def detector(db):
    return DashboardDetectorFactory(tool="antiSMASH", tool_name_code="ANT")


@pytest.fixture
def assigner():
    return CbgcAssigner()


# ── create ────────────────────────────────────────────────────────────────────


class TestCreate:
    def test_first_prediction_mints_cbgc(self, contig, detector, assigner):
        cbgc_id, bgc_num, pred_acc = assigner.assign(
            contig_id=contig.id,
            contig_accession=contig.accession,
            start=1000,
            end=11_000,
            detector_id=detector.id,
            tool_code=detector.tool_name_code,
        )
        assert bgc_num == 1
        cbgc = ConsensusBgc.objects.get(id=cbgc_id)
        assert cbgc.bgc_range.lower == 1000
        assert cbgc.bgc_range.upper == 11_001  # half-open
        assert pred_acc == f"{cbgc.accession}.ANT.01"

    def test_registry_row_minted_alongside(self, contig, detector, assigner):
        cbgc_id, *_ = assigner.assign(
            contig_id=contig.id, contig_accession=contig.accession,
            start=1000, end=11_000,
            detector_id=detector.id, tool_code=detector.tool_name_code,
        )
        cbgc = ConsensusBgc.objects.get(id=cbgc_id)
        registry = AccessionRegistry.objects.get(accession=cbgc.accession)
        assert registry.current_cbgc_id == cbgc_id
        assert registry.start_pos == 1000
        assert registry.end_pos == 11_000


# ── extend ────────────────────────────────────────────────────────────────────


class TestExtend:
    def test_overlap_widens_cbgc(self, contig, detector, assigner):
        cbgc_id_a, *_ = assigner.assign(
            contig_id=contig.id, contig_accession=contig.accession,
            start=1000, end=5_000,
            detector_id=detector.id, tool_code=detector.tool_name_code,
        )
        cbgc_id_b, _, pred_acc_b = assigner.assign(
            contig_id=contig.id, contig_accession=contig.accession,
            start=4_500, end=10_000,
            detector_id=detector.id, tool_code=detector.tool_name_code,
        )
        assert cbgc_id_a == cbgc_id_b
        cbgc = ConsensusBgc.objects.get(id=cbgc_id_a)
        assert cbgc.bgc_range.lower == 1000
        assert cbgc.bgc_range.upper == 10_001
        # bgc_number increments per detector within the same cBGC.
        assert pred_acc_b == f"{cbgc.accession}.ANT.02"

    def test_registry_coords_track_extension(self, contig, detector, assigner):
        cbgc_id, *_ = assigner.assign(
            contig_id=contig.id, contig_accession=contig.accession,
            start=1000, end=5_000,
            detector_id=detector.id, tool_code=detector.tool_name_code,
        )
        assigner.assign(
            contig_id=contig.id, contig_accession=contig.accession,
            start=4_500, end=10_000,
            detector_id=detector.id, tool_code=detector.tool_name_code,
        )
        cbgc = ConsensusBgc.objects.get(id=cbgc_id)
        registry = AccessionRegistry.objects.get(accession=cbgc.accession)
        assert registry.start_pos == 1000
        assert registry.end_pos == 10_000

    def test_subsumed_prediction_does_not_widen(self, contig, detector, assigner):
        # Second prediction sits entirely inside the first: range stays put.
        cbgc_id, *_ = assigner.assign(
            contig_id=contig.id, contig_accession=contig.accession,
            start=1000, end=10_000,
            detector_id=detector.id, tool_code=detector.tool_name_code,
        )
        assigner.assign(
            contig_id=contig.id, contig_accession=contig.accession,
            start=4_000, end=6_000,
            detector_id=detector.id, tool_code=detector.tool_name_code,
        )
        cbgc = ConsensusBgc.objects.get(id=cbgc_id)
        assert cbgc.bgc_range.lower == 1000
        assert cbgc.bgc_range.upper == 10_001


# ── merge ─────────────────────────────────────────────────────────────────────


class TestMerge:
    def test_bridge_prediction_merges_two_cbgcs(self, contig, assigner):
        det1 = DashboardDetectorFactory(name="t1", tool="t1", version="1")
        det2 = DashboardDetectorFactory(name="t2", tool="t2", version="1")
        # Two disjoint cBGCs on the same contig, each via a different detector
        # so the per-detector exclusion constraint doesn't fire.
        cbgc_a, *_ = assigner.assign(
            contig_id=contig.id, contig_accession=contig.accession,
            start=1000, end=4_000,
            detector_id=det1.id, tool_code="AAA",
        )
        cbgc_b, *_ = assigner.assign(
            contig_id=contig.id, contig_accession=contig.accession,
            start=8_000, end=12_000,
            detector_id=det2.id, tool_code="BBB",
        )
        assert cbgc_a != cbgc_b
        accession_b_before = ConsensusBgc.objects.get(id=cbgc_b).accession

        # Bridging prediction spans both.
        det3 = DashboardDetectorFactory(name="t3", tool="t3", version="1")
        cbgc_bridge, *_ = assigner.assign(
            contig_id=contig.id, contig_accession=contig.accession,
            start=3_500, end=9_000,
            detector_id=det3.id, tool_code="CCC",
        )

        # Survivor is the lowest-PK pre-existing cBGC.
        survivor_id = min(cbgc_a, cbgc_b)
        absorbed_id = max(cbgc_a, cbgc_b)
        assert cbgc_bridge == survivor_id

        survivor = ConsensusBgc.objects.get(id=survivor_id)
        assert survivor.bgc_range.lower == 1000
        assert survivor.bgc_range.upper == 12_001
        # Absorbed row is gone.
        assert not ConsensusBgc.objects.filter(id=absorbed_id).exists()
        # Absorbed accession lives on as an alias of the survivor's registry.
        absorbed_accession = accession_b_before if cbgc_b == absorbed_id else \
            ConsensusBgc.objects.filter(id=absorbed_id).values_list("accession", flat=True).first() or accession_b_before
        registry = AccessionRegistry.objects.get(accession=survivor.accession)
        aliases = list(
            AccessionAlias.objects.filter(registry=registry).values_list(
                "alias_accession", flat=True,
            )
        )
        assert absorbed_accession in aliases


# ── disjointness invariant ────────────────────────────────────────────────────


class TestDisjointness:
    def test_assigner_leaves_no_overlapping_cbgcs(self, contig, detector, assigner):
        # 50 partially-overlapping predictions should collapse to a single
        # cBGC (or a handful of disjoint cBGCs after merge), never two
        # overlapping ones.
        for i in range(50):
            start = 1000 + 100 * i
            end = start + 5_000
            assigner.assign(
                contig_id=contig.id, contig_accession=contig.accession,
                start=start, end=end,
                detector_id=detector.id, tool_code="ANT",
            )
        ranges = sorted(
            (c.bgc_range.lower, c.bgc_range.upper)
            for c in ConsensusBgc.objects.filter(contig_id=contig.id)
        )
        for (l1, u1), (l2, u2) in zip(ranges, ranges[1:]):
            # Half-open intervals are disjoint iff one's upper ≤ the next's
            # lower. (PG would reject otherwise via the exclusion constraint.)
            assert u1 <= l2, f"cBGCs [{l1},{u1}) and [{l2},{u2}) overlap"


# ── bgc_number sequencing ─────────────────────────────────────────────────────


class TestBgcNumberSequencing:
    def test_separate_detectors_have_independent_counters(self, contig, assigner):
        ant = DashboardDetectorFactory(name="a", tool="antiSMASH", version="7", tool_name_code="ANT")
        gec = DashboardDetectorFactory(name="g", tool="GECCO", version="0.10", tool_name_code="GEC")
        # First prediction creates the cBGC.
        _, _, pred_ant_1 = assigner.assign(
            contig_id=contig.id, contig_accession=contig.accession,
            start=1000, end=10_000,
            detector_id=ant.id, tool_code="ANT",
        )
        # Second prediction (different detector, overlapping) extends the same cBGC.
        _, _, pred_gec_1 = assigner.assign(
            contig_id=contig.id, contig_accession=contig.accession,
            start=2_000, end=8_000,
            detector_id=gec.id, tool_code="GEC",
        )
        # A second antiSMASH inside the same cBGC.
        _, _, pred_ant_2 = assigner.assign(
            contig_id=contig.id, contig_accession=contig.accession,
            start=3_000, end=5_000,
            detector_id=ant.id, tool_code="ANT",
        )
        assert pred_ant_1.endswith(".ANT.01")
        assert pred_gec_1.endswith(".GEC.01")
        assert pred_ant_2.endswith(".ANT.02")
