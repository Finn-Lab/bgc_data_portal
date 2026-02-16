from __future__ import annotations

from typing import Iterable, Any


# Bulk insert chunk size used across ingestion tasks
BULK_INSERT_SIZE = 10_000  # bulk-insert chunk size


def _bulk_get_or_create(model, objs: Iterable[Any], *, key: str):
    """
    Very thin wrapper around bulk_create that returns a dict{key: instance}.
    `key` is a unique field on `model` (e.g. "accession" for Study).
    """
    objs = list(objs)
    if not objs:
        return {}

    existing = {
        getattr(o, key): o
        for o in model.objects.filter(**{f"{key}__in": [getattr(x, key) for x in objs]})
    }
    to_create = [
        model(**o.model_dump(exclude_unset=True, by_alias=True))
        for o in objs
        if getattr(o, key) not in existing
    ]
    model.objects.bulk_create(
        to_create, ignore_conflicts=True, batch_size=BULK_INSERT_SIZE
    )

    created = {
        getattr(o, key): o
        for o in model.objects.filter(**{f"{key}__in": [getattr(x, key) for x in objs]})
    }
    existing.update(created)
    return existing
