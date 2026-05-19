"""GO-term → GO-slim mapping, shared between ingestion and asset projection.

Replaces the old Pfam-keyed lookup (``pfam2goSlim.json``). Now every
``BgcDomain`` row — regardless of ``ref_db`` — carries the GO terms that
InterProScan attached to the underlying signature (``BgcDomain.go_terms``).
This module folds that list down to a deduplicated set of GO-slim term
*names* (capitalised) suitable for direct display and palette lookup.

The mapping itself is precomputed offline by
``scripts/refresh_go_slim_map.py`` (a standalone Python script — the only
place ``goatools`` is imported) and committed to the repo as
``services/data/go_slim_map.json``. Runtime stays dependency-free.

Callers should populate ``BgcDomain.go_slim`` (or its asset-side equivalent)
inline at write time using :func:`go_slim_for_terms`.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Iterable

log = logging.getLogger(__name__)

_DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "go_slim_map.json")


@lru_cache(maxsize=1)
def _go_term_to_slims() -> dict[str, list[str]]:
    """Return ``{GO_id: [slim_term_name, ...]}`` from the bundled JSON.

    Missing or malformed file → empty mapping (logged once); callers then get
    ``[]`` from :func:`go_slim_for_terms` and the CDS renders without colour.
    """
    try:
        with open(_DATA_FILE) as f:
            raw = json.load(f)
    except FileNotFoundError:
        log.warning(
            "go_slim_map.json not found at %s — GO slims will be empty. "
            "Run `python scripts/refresh_go_slim_map.py --download` to regenerate.",
            _DATA_FILE,
        )
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Failed to load go_slim_map.json (%s) — GO slims will be empty", exc)
        return {}

    payload = raw.get("map", raw) if isinstance(raw, dict) else {}
    if not isinstance(payload, dict):
        log.warning("go_slim_map.json has no 'map' object — GO slims will be empty")
        return {}

    return {
        str(go_id): [str(s) for s in slims]
        for go_id, slims in payload.items()
        if isinstance(slims, list)
    }


def go_slim_for_terms(go_terms: Iterable[str] | None) -> list[str]:
    """Return the sorted, deduplicated GO-slim term names for ``go_terms``.

    ``go_terms`` is the list InterProScan emits per signature (e.g.
    ``["GO:0003824", "GO:0008152"]``). Unknown IDs and blanks are ignored.
    Empty input → ``[]``. The result preserves the names as they appear in
    the precomputed map (typically capitalised first letter for palette
    compatibility).
    """
    if not go_terms:
        return []
    mapping = _go_term_to_slims()
    seen: set[str] = set()
    for term in go_terms:
        if not term:
            continue
        for slim in mapping.get(str(term).strip(), ()):
            if slim:
                seen.add(slim)
    return sorted(seen)


def go_slim_for(domain_acc: str) -> list[str]:  # pragma: no cover - back-compat shim
    """Deprecated. The previous ``Pfam → slim`` rule has been retired.

    Kept so any in-flight branch that still calls this name still imports.
    Always returns ``[]``; callers should switch to
    :func:`go_slim_for_terms` and pass ``BgcDomain.go_terms``.
    """
    return []
