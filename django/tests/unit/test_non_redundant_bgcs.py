"""Tests for the NonRedundantBGC builder.

Verifies the merge rules:
  * Validated BGCs (is_validated=True) are admitted as standalone NRBs
    regardless of tool or is_partial; they are never merged or absorbed.
  * GECCO + SanntiS predictions overlapping on the same contig collapse
    transitively into one NRB.
  * antiSMASH calls that overlap any already-built NRB are absorbed (no NRB
    row created; source DashboardBgc.non_redundant_bgc stays NULL).
  * Standalone antiSMASH calls (no overlap with merge predictors) become
    their own NRB.
  * Non-validated partial BGCs (is_partial=True, is_validated=False) are
    excluded from the build.
  * Non-latest detector versions are excluded via latest_version_bgcs().
"""

from __future__ import annotations

import pytest

from discovery.models import DashboardBgc, DashboardDetector, NonRedundantBGC
from discovery.services.clustering.non_redundant import build_non_redundant_bgcs
from tests.factories.discovery_models import DashboardContigFactory


pytestmark = pytest.mark.django_db


def _detector(tool: str, version: str, sort_key: int) -> DashboardDetector:
    code = tool[:3].upper()
    return DashboardDetector.objects.create(
        name=f"{tool} v{version}",
        tool=tool,
        version=version,
        tool_name_code=code,
        version_sort_key=sort_key,
    )


def _bgc(*, contig, detector, start, end, is_partial=False, is_validated=False):
    return DashboardBgc.objects.create(
        assembly=contig.assembly,
        contig=contig,
        bgc_accession=f"MGYB{DashboardBgc.objects.count() + 1:08d}",
        start_position=start,
        end_position=end,
        detector=detector,
        is_partial=is_partial,
        is_validated=is_validated,
    )


def test_overlapping_gecco_and_sanntis_merge_transitively():
    contig = DashboardContigFactory()
    gecco = _detector("GECCO", "0.9.8", 100)
    sanntis = _detector("SanntiS", "0.1.0", 100)

    # Three intervals; A∩B and B∩C overlap but A∩C empty → transitive merge.
    a = _bgc(contig=contig, detector=gecco, start=1_000, end=5_000)
    b = _bgc(contig=contig, detector=sanntis, start=4_000, end=8_000)
    c = _bgc(contig=contig, detector=gecco, start=7_000, end=12_000)

    result = build_non_redundant_bgcs()
    assert result["n_nrbs"] == 1
    nrb = NonRedundantBGC.objects.get()
    assert nrb.start_position == 1_000
    assert nrb.end_position == 12_000
    assert nrb.source_tools == ["GECCO", "SanntiS"]
    for bgc_id in (a.id, b.id, c.id):
        bgc = DashboardBgc.objects.get(pk=bgc_id)
        assert bgc.non_redundant_bgc_id == nrb.id
        assert bgc.classification_source == "merged"


def test_antismash_overlapping_merge_nrb_is_absorbed():
    contig = DashboardContigFactory()
    gecco = _detector("GECCO", "0.9.8", 100)
    antismash = _detector("antiSMASH", "7.1.0", 200)

    g = _bgc(contig=contig, detector=gecco, start=1_000, end=5_000)
    a = _bgc(contig=contig, detector=antismash, start=2_000, end=4_000)

    result = build_non_redundant_bgcs()
    assert result["n_nrbs"] == 1
    assert result["n_absorbed_antismash"] == 1
    nrb = NonRedundantBGC.objects.get()
    assert nrb.source_tools == ["GECCO"]

    g_after = DashboardBgc.objects.get(pk=g.id)
    a_after = DashboardBgc.objects.get(pk=a.id)
    assert g_after.non_redundant_bgc_id == nrb.id
    assert a_after.non_redundant_bgc_id is None


def test_standalone_antismash_becomes_own_nrb():
    contig = DashboardContigFactory()
    antismash = _detector("antiSMASH", "7.1.0", 200)
    a = _bgc(contig=contig, detector=antismash, start=1_000, end=4_000)

    result = build_non_redundant_bgcs()
    assert result["n_nrbs"] == 1
    nrb = NonRedundantBGC.objects.get()
    assert nrb.source_tools == ["antiSMASH"]
    assert DashboardBgc.objects.get(pk=a.id).non_redundant_bgc_id == nrb.id


def test_partial_bgcs_excluded_from_build():
    contig = DashboardContigFactory()
    gecco = _detector("GECCO", "0.9.8", 100)
    partial = _bgc(contig=contig, detector=gecco, start=1_000, end=5_000, is_partial=True)

    result = build_non_redundant_bgcs()
    assert result["n_nrbs"] == 0
    assert DashboardBgc.objects.get(pk=partial.id).non_redundant_bgc_id is None


def test_validated_partial_is_admitted_as_standalone_nrb():
    contig = DashboardContigFactory()
    gecco = _detector("GECCO", "0.9.8", 100)
    v = _bgc(
        contig=contig, detector=gecco, start=1_000, end=5_000,
        is_partial=True, is_validated=True,
    )

    result = build_non_redundant_bgcs()
    assert result["n_nrbs"] == 1
    assert result["n_validated_standalone"] == 1
    nrb = NonRedundantBGC.objects.get()
    assert nrb.source_tools == ["GECCO"]
    assert DashboardBgc.objects.get(pk=v.id).non_redundant_bgc_id == nrb.id


def test_validated_mibig_tool_is_admitted_outside_whitelist():
    contig = DashboardContigFactory()
    mibig = _detector("mibig", "4.0", 50)
    v = _bgc(
        contig=contig, detector=mibig, start=1_000, end=5_000,
        is_partial=True, is_validated=True,
    )

    result = build_non_redundant_bgcs()
    assert result["n_nrbs"] == 1
    assert result["n_validated_standalone"] == 1
    nrb = NonRedundantBGC.objects.get()
    assert nrb.source_tools == ["mibig"]
    assert DashboardBgc.objects.get(pk=v.id).non_redundant_bgc_id == nrb.id


def test_validated_bgc_overlapping_gecco_sanntis_does_not_merge():
    contig = DashboardContigFactory()
    gecco = _detector("GECCO", "0.9.8", 100)
    sanntis = _detector("SanntiS", "0.1.0", 100)
    mibig = _detector("mibig", "4.0", 50)

    g = _bgc(contig=contig, detector=gecco, start=1_000, end=5_000)
    s = _bgc(contig=contig, detector=sanntis, start=4_000, end=8_000)
    v = _bgc(
        contig=contig, detector=mibig, start=2_000, end=7_000,
        is_validated=True,
    )

    result = build_non_redundant_bgcs()
    # One merged GECCO+SanntiS NRB + one standalone validated NRB.
    assert result["n_nrbs"] == 2
    assert result["n_validated_standalone"] == 1

    validated_nrb = NonRedundantBGC.objects.get(source_tools=["mibig"])
    merged_nrb = NonRedundantBGC.objects.get(source_tools=["GECCO", "SanntiS"])

    assert DashboardBgc.objects.get(pk=v.id).non_redundant_bgc_id == validated_nrb.id
    assert DashboardBgc.objects.get(pk=g.id).non_redundant_bgc_id == merged_nrb.id
    assert DashboardBgc.objects.get(pk=s.id).non_redundant_bgc_id == merged_nrb.id


def test_antismash_overlapping_validated_nrb_is_absorbed():
    contig = DashboardContigFactory()
    mibig = _detector("mibig", "4.0", 50)
    antismash = _detector("antiSMASH", "7.1.0", 200)

    v = _bgc(
        contig=contig, detector=mibig, start=1_000, end=5_000,
        is_validated=True,
    )
    a = _bgc(contig=contig, detector=antismash, start=2_000, end=4_000)

    result = build_non_redundant_bgcs()
    assert result["n_nrbs"] == 1
    assert result["n_absorbed_antismash"] == 1
    assert result["n_validated_standalone"] == 1
    nrb = NonRedundantBGC.objects.get()
    assert nrb.source_tools == ["mibig"]
    assert DashboardBgc.objects.get(pk=v.id).non_redundant_bgc_id == nrb.id
    assert DashboardBgc.objects.get(pk=a.id).non_redundant_bgc_id is None


def test_only_latest_detector_version_contributes():
    contig = DashboardContigFactory()
    older = _detector("antiSMASH", "6.0.0", 100)
    newer = _detector("antiSMASH", "7.1.0", 200)

    a_old = _bgc(contig=contig, detector=older, start=1_000, end=5_000)
    a_new = _bgc(contig=contig, detector=newer, start=1_000, end=5_000)

    result = build_non_redundant_bgcs()
    # Only the latest-version row enters; one NRB created.
    assert result["n_nrbs"] == 1
    assert DashboardBgc.objects.get(pk=a_new.id).non_redundant_bgc_id is not None
    assert DashboardBgc.objects.get(pk=a_old.id).non_redundant_bgc_id is None
