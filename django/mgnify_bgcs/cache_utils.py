"""Small cache helper utilities for search/jobs caching.

Provides:
- set_search_cache(search_key: str, results: Any, task_id: str, timeout: int)
- get_search_status(search_key: str) -> dict | None

These normalize how we write/read the cache keys used by `api.py` and
`tasks.py`.
"""

from __future__ import annotations

import json
import hashlib

from typing import Any, Dict, Optional
from django.core.cache import cache
from django.conf import settings
from celery.result import AsyncResult


def generate_job_key_from_dict(cleaned_data: dict) -> str:
    """
    Given the cleaned_data dict from SearchForm, produce a reproducible
    key by JSON‐dumping with sorted keys and hashing with SHA-256.
    """
    j = json.dumps(cleaned_data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(j.encode("utf-8")).hexdigest()


def set_job_cache(
    search_key: str,
    task_id: str,
    results: Optional[dict] = None,
    timeout: Optional[int] = None,
) -> None:
    """Store the results and task id under consistent cache keys.

    - results: the object to cache for the search (could be dict, DataFrame, etc.)
    - task_id: the celery task id handling the job
    - timeout: seconds until expiry; defaults to settings.CACHE_TIMEOUT
    """
    ttl = timeout if timeout is not None else getattr(settings, "CACHE_TIMEOUT", None)
    cache.set(task_id, search_key, ttl)
    if results is None:
        results = {}
    results["task_id"] = task_id
    cache.set(search_key, results, ttl)


def get_job_status(
    search_key: Optional[str] = None, task_id: Optional[str] = None
) -> Dict[str, Any]:
    """Return a dictionary with task_id, search_key, status, result (if available).

    Important: We consider a job SUCCESS if a cached result exists, even if
    the Celery backend cannot report readiness (e.g., when no result backend
    is configured). This allows frontends to poll reliably by task_id alone.
    """

    # 1) If caller supplied a search_key, check for cached result first.
    if task_id:
        search_key = cache.get(task_id)

    if search_key:
        result = cache.get(search_key, {})
        # If we have a cached result that has more than just the task_id, return it
        task_id = result.pop("task_id", None)

        if result:
            return {"search_key": search_key, "status": "SUCCESS", "result": result}

    try:
        res = AsyncResult(task_id)
        data: Dict[str, Any] = {
            "task_id": task_id,
            "search_key": search_key,
            "status": res.status,
        }
        if res.ready():
            try:
                data["result"] = cache.get(search_key)
            except Exception:
                data["result"] = None
        return data
    except Exception:
        # If anything fails, return minimal mapping info with unknown status
        return {"task_id": task_id, "search_key": search_key, "status": "UNKNOWN"}
