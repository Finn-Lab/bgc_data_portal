"""Reusable queryset helpers for the Discovery Platform."""

from __future__ import annotations

from django.db.models import OuterRef, QuerySet, Subquery

from discovery.models import SourceBgcPrediction


def latest_version_bgcs(qs: QuerySet | None = None) -> QuerySet:
    """Filter a ``SourceBgcPrediction`` queryset to only the latest detector
    version per tool per contig.

    For each (contig, tool) pair, keeps only the source predictions whose
    detector has the highest ``version_sort_key``. Predictions with no
    detector are always included.
    """
    if qs is None:
        qs = SourceBgcPrediction.objects.all()

    latest_detector_subq = (
        SourceBgcPrediction.objects.filter(
            contig=OuterRef("contig"),
            detector__tool=OuterRef("detector__tool"),
        )
        .order_by("-detector__version_sort_key")
        .values("detector_id")[:1]
    )

    return qs.filter(
        detector_id__in=Subquery(latest_detector_subq),
    ) | qs.filter(detector__isnull=True)
