"""Redis cache helpers for the ephemeral asset-upload pipeline.

Key layout (TTL = ``ASSET_TTL_SECONDS``):

* ``asset:{token}:status``        — ``{state, task_id, progress?, error?, summary?}``
* ``asset:{token}:manifest``      — summary dict (n_ibgcs, n_bgcs, assembly, …)
* ``asset:{token}:ibgcs``          — list of iBGC roster rows (negative ids)
* ``asset:{token}:domain_hits``   — flat list of ``{ibgc_id, domain_acc, …, go_slim}``
  rows (per-iBGC dedup on ``domain_acc``); mirrors the SQL ``domain_pairs``
  shape consumed by ``report.build_report_payload``.
* ``asset:{token}:ibgc:{neg_id}``  — full ``IbgcDetail`` payload (dict)
* ``asset:{token}:region:{neg_id}`` — region (CDS + protein) payload (dict)
* ``asset:{token}:architecture:{neg_id}`` — ordered domain accessions (list[str])
* ``asset:{token}:upload``        — raw uploaded tar.gz bytes (short TTL,
  deleted by the worker once it has read them).

Negative IDs are always passed as ``int`` and converted to their absolute
value for the suffix to keep keys clean (``asset:abc:ibgc:42`` not ``…:-42``).
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.cache import cache

log = logging.getLogger(__name__)

ASSET_TTL_SECONDS = 6 * 60 * 60  # 6h
# Upload bytes only need to survive the dispatch → worker hop. Keep this short
# so a crashed worker can't pin ~100 MB in Redis for the full asset TTL.
UPLOAD_TTL_SECONDS = 60 * 60  # 1h


# ── Key builders ────────────────────────────────────────────────────────────


def _k_status(token: str) -> str:
    return f"asset:{token}:status"


def _k_manifest(token: str) -> str:
    return f"asset:{token}:manifest"


def _k_ibgcs(token: str) -> str:
    return f"asset:{token}:ibgcs"


def _k_domain_hits(token: str) -> str:
    return f"asset:{token}:domain_hits"


def _k_ibgc(token: str, neg_id: int) -> str:
    return f"asset:{token}:ibgc:{abs(neg_id)}"


def _k_region(token: str, neg_id: int) -> str:
    return f"asset:{token}:region:{abs(neg_id)}"


def _k_architecture(token: str, neg_id: int) -> str:
    return f"asset:{token}:architecture:{abs(neg_id)}"


def _k_upload(token: str) -> str:
    return f"asset:{token}:upload"


# ── Status helpers ──────────────────────────────────────────────────────────


def write_status(token: str, payload: dict[str, Any]) -> None:
    cache.set(_k_status(token), payload, ASSET_TTL_SECONDS)


def read_status(token: str) -> dict[str, Any] | None:
    return cache.get(_k_status(token))


def mark_pending(token: str, task_id: str) -> None:
    write_status(token, {"state": "PENDING", "task_id": task_id})


def mark_running(token: str, task_id: str, progress: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {"state": "RUNNING", "task_id": task_id}
    if progress is not None:
        payload["progress"] = progress
    write_status(token, payload)


def mark_failed(token: str, task_id: str, error: str) -> None:
    write_status(token, {"state": "FAILED", "task_id": task_id, "error": error})


def mark_success(token: str, task_id: str, summary: dict[str, Any]) -> None:
    write_status(token, {"state": "SUCCESS", "task_id": task_id, "summary": summary})


# ── Payload helpers ─────────────────────────────────────────────────────────


def write_manifest(token: str, manifest: dict[str, Any]) -> None:
    cache.set(_k_manifest(token), manifest, ASSET_TTL_SECONDS)


def read_manifest(token: str) -> dict[str, Any] | None:
    return cache.get(_k_manifest(token))


def write_ibgc_list(token: str, rows: list[dict[str, Any]]) -> None:
    cache.set(_k_ibgcs(token), rows, ASSET_TTL_SECONDS)


def read_ibgc_list(token: str) -> list[dict[str, Any]] | None:
    return cache.get(_k_ibgcs(token))


def write_domain_hits(token: str, rows: list[dict[str, Any]]) -> None:
    """Persist the flat per-iBGC-deduped domain-hit list for the asset.

    Each row matches the shape report.build_report_payload expects in
    ``extra_domain_rows``: ``{ibgc_id, domain_acc, domain_name,
    domain_description, go_slim}``.
    """
    cache.set(_k_domain_hits(token), rows, ASSET_TTL_SECONDS)


def read_domain_hits(token: str) -> list[dict[str, Any]] | None:
    return cache.get(_k_domain_hits(token))


def write_ibgc_detail(token: str, neg_id: int, payload: dict[str, Any]) -> None:
    cache.set(_k_ibgc(token, neg_id), payload, ASSET_TTL_SECONDS)


def read_ibgc_detail(token: str, neg_id: int) -> dict[str, Any] | None:
    return cache.get(_k_ibgc(token, neg_id))


def write_region(token: str, neg_id: int, payload: dict[str, Any]) -> None:
    cache.set(_k_region(token, neg_id), payload, ASSET_TTL_SECONDS)


def read_region(token: str, neg_id: int) -> dict[str, Any] | None:
    return cache.get(_k_region(token, neg_id))


def write_architecture(token: str, neg_id: int, ordered_accs: list[str]) -> None:
    cache.set(_k_architecture(token, neg_id), list(ordered_accs), ASSET_TTL_SECONDS)


def read_architecture(token: str, neg_id: int) -> list[str] | None:
    return cache.get(_k_architecture(token, neg_id))


def stash_upload(token: str, raw: bytes) -> None:
    """Park the uploaded tar.gz bytes in Redis for the worker to pick up."""
    cache.set(_k_upload(token), raw, UPLOAD_TTL_SECONDS)


def read_upload(token: str) -> bytes | None:
    """Return the parked upload bytes (or ``None`` if the TTL elapsed)."""
    return cache.get(_k_upload(token))


def evict_upload(token: str) -> None:
    """Drop the parked upload bytes — called by the worker once consumed."""
    cache.delete(_k_upload(token))


def evict_asset(token: str) -> None:
    """Delete every key under ``asset:{token}:*`` we know about.

    Reads the iBGC list first so we can drop the per-iBGC payloads, then drops
    the index keys. If the manifest TTL already expired the call is a no-op.
    """
    rows = read_ibgc_list(token) or []
    for row in rows:
        neg_id = int(row.get("id", 0))
        if neg_id < 0:
            cache.delete(_k_ibgc(token, neg_id))
            cache.delete(_k_region(token, neg_id))
            cache.delete(_k_architecture(token, neg_id))
    cache.delete(_k_ibgcs(token))
    cache.delete(_k_domain_hits(token))
    cache.delete(_k_manifest(token))
    cache.delete(_k_status(token))
    cache.delete(_k_upload(token))
    log.info("evict_asset: cleared cache for token=%s (%d rows)", token, len(rows))
