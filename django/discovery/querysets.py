"""Reusable queryset helpers for the Discovery Platform."""

from __future__ import annotations

from django.db.models import OuterRef, QuerySet, Subquery

from discovery.models import DashboardBgc


def latest_version_bgcs(qs: QuerySet | None = None) -> QuerySet:
    """Filter a DashboardBgc queryset to only the latest detector version per
    tool per contig.

    For each (contig, tool) pair, keeps only the BGCs whose detector has the
    highest ``version_sort_key``.  BGCs with no detector are always included.

    Parameters
    ----------
    qs : QuerySet, optional
        Base queryset.  Defaults to ``DashboardBgc.objects.all()``.

    Returns
    -------
    QuerySet
        Filtered queryset.
    """
    if qs is None:
        qs = DashboardBgc.objects.all()

    latest_detector_subq = (
        DashboardBgc.objects.filter(
            contig=OuterRef("contig"),
            detector__tool=OuterRef("detector__tool"),
        )
        .order_by("-detector__version_sort_key")
        .values("detector_id")[:1]
    )

    return qs.filter(
        # Keep BGCs whose detector matches the per-contig-per-tool latest,
        # OR that have no detector at all (e.g. MIBiG references).
        detector_id__in=Subquery(latest_detector_subq),
    ) | qs.filter(detector__isnull=True)
