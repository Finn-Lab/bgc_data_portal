"""Tests for the asset-upload Redis cache helpers, especially the new
``stash_upload`` / ``read_upload`` / ``evict_upload`` pair that the API and
the Celery worker use to exchange the uploaded tarball bytes across pods.
"""

from __future__ import annotations

import pytest
from django.core.cache import cache

from discovery.services.asset_upload import cache as asset_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def test_stash_and_read_upload_round_trip():
    raw = b"\x1f\x8b" + b"payload-bytes"
    asset_cache.stash_upload("tok-1", raw)
    assert asset_cache.read_upload("tok-1") == raw


def test_read_upload_missing_token_returns_none():
    assert asset_cache.read_upload("never-stashed") is None


def test_evict_upload_drops_the_key():
    asset_cache.stash_upload("tok-2", b"abc")
    asset_cache.evict_upload("tok-2")
    assert asset_cache.read_upload("tok-2") is None


def test_evict_asset_also_drops_upload_key():
    asset_cache.stash_upload("tok-3", b"abc")
    asset_cache.mark_pending("tok-3", task_id="t")
    asset_cache.evict_asset("tok-3")
    assert asset_cache.read_upload("tok-3") is None
    assert asset_cache.read_status("tok-3") is None


def test_task_fails_cleanly_when_upload_key_missing():
    """If the upload TTL elapses (or the key is evicted) before the worker
    picks the task up, ``process_asset_upload_task`` must mark FAILED with a
    descriptive error instead of raising."""
    from discovery.tasks import process_asset_upload_task

    token = "tok-missing"
    asset_cache.mark_pending(token, task_id="task-x")
    result = process_asset_upload_task.run(token)

    assert result["state"] == "FAILED"
    assert "missing from cache" in result["error"].lower()
    status = asset_cache.read_status(token)
    assert status is not None
    assert status["state"] == "FAILED"
