"""
Unit tests for BgcKeywordFilter — exercises filter_by_keyword routing.

These tests require database access because the filter executes real ORM
queries; factory-created objects give full relational context.
"""

import pytest

from mgnify_bgcs.models import Bgc, BgcBgcClass
from mgnify_bgcs.filters import BgcKeywordFilter
from tests.factories.models import (
    BgcClassFactory,
    BgcFactory,
    ContigFactory,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _apply(value: str):
    """Run filter_by_keyword against all non-aggregated BGCs."""
    qs = Bgc.objects.filter(is_aggregated_region=False)
    return BgcKeywordFilter.filter_by_keyword(qs, "keyword", value)


# ---------------------------------------------------------------------------
# BGC class keyword search (the reverse-traversal fix)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_class_keyword_returns_non_aggregated_bgcs():
    """
    Searching by BGC class name (e.g. "Polyketide") must return non-aggregated
    BGCs that spatially overlap an aggregated region carrying that class.

    Before the fix, this always returned 0 results because the filter applied
    the class directly to the non-aggregated queryset, where no class links exist.
    """
    contig = ContigFactory()
    bgc_class = BgcClassFactory(name="Polyketide")

    # Non-aggregated BGC: positions 1000–3000
    non_agg = BgcFactory(
        contig=contig,
        start_position=1000,
        end_position=3000,
        is_aggregated_region=False,
    )

    # Aggregated region that overlaps: positions 500–3500, carries the class
    aggregated = BgcFactory(
        contig=contig,
        start_position=500,
        end_position=3500,
        is_aggregated_region=True,
    )
    BgcBgcClass.objects.create(bgc=aggregated, bgc_class=bgc_class)

    result = _apply("Polyketide")

    assert non_agg in result, "non-aggregated BGC overlapping a classed aggregated region must appear in results"
    assert aggregated not in result, "aggregated BGCs must not appear in the non-aggregated queryset"


@pytest.mark.django_db
def test_class_keyword_excludes_non_overlapping_bgcs():
    """
    Non-aggregated BGCs on the same contig that do NOT spatially overlap an
    aggregated region with the searched class should be excluded.
    """
    contig = ContigFactory()
    bgc_class = BgcClassFactory(name="Terpene")

    # Non-overlapping non-aggregated BGC: far away on the same contig
    non_overlapping = BgcFactory(
        contig=contig,
        start_position=10_000,
        end_position=12_000,
        is_aggregated_region=False,
    )

    # Aggregated region with the class at a different location
    aggregated = BgcFactory(
        contig=contig,
        start_position=100,
        end_position=2_000,
        is_aggregated_region=True,
    )
    BgcBgcClass.objects.create(bgc=aggregated, bgc_class=bgc_class)

    result = _apply("Terpene")

    assert non_overlapping not in result


@pytest.mark.django_db
def test_class_keyword_no_aggregated_region_returns_empty():
    """
    If no aggregated region carries the searched class, the result must be empty
    even when non-aggregated BGCs exist.
    """
    BgcClassFactory(name="RiPP")  # class exists but no aggregated BGC uses it
    BgcFactory(is_aggregated_region=False)

    result = _apply("RiPP")

    assert result.count() == 0


@pytest.mark.django_db
def test_class_keyword_case_insensitive():
    """Class name lookup must be case-insensitive (uses iregex)."""
    contig = ContigFactory()
    bgc_class = BgcClassFactory(name="NRP")

    non_agg = BgcFactory(
        contig=contig,
        start_position=0,
        end_position=2000,
        is_aggregated_region=False,
    )
    aggregated = BgcFactory(
        contig=contig,
        start_position=0,
        end_position=2000,
        is_aggregated_region=True,
    )
    BgcBgcClass.objects.create(bgc=aggregated, bgc_class=bgc_class)

    assert non_agg in _apply("nrp")
    assert non_agg in _apply("NRP")
    assert non_agg in _apply("Nrp")
