"""Unit tests for the shared GO term → GO-slim helper.

Pins the union-of-slim-names rule and the in-process caching behaviour
relied on by the ingestion loader and asset projection paths.
"""

from __future__ import annotations

import json
from unittest.mock import patch, mock_open

from discovery.services import go_slim as go_slim_mod
from discovery.services.go_slim import go_slim_for_terms


def _clear_cache():
    go_slim_mod._go_term_to_slims.cache_clear()


def _payload(map_obj: dict[str, list[str]]) -> str:
    return json.dumps(
        {
            "version": "test",
            "aspect": "molecular_function",
            "slim": "goslim_metagenomics",
            "map": map_obj,
        }
    )


def test_single_term_maps_to_its_slim():
    _clear_cache()
    with patch(
        "builtins.open",
        mock_open(read_data=_payload({"GO:0003824": ["Catalytic activity"]})),
    ):
        assert go_slim_for_terms(["GO:0003824"]) == ["Catalytic activity"]
    _clear_cache()


def test_multiple_terms_union_sorted_and_deduped():
    _clear_cache()
    payload = _payload(
        {
            "GO:0001": ["Catalytic activity"],
            "GO:0002": ["Catalytic activity", "Transferase activity"],
            "GO:0003": ["Binding"],
        }
    )
    with patch("builtins.open", mock_open(read_data=payload)):
        assert go_slim_for_terms(["GO:0001", "GO:0002", "GO:0003"]) == [
            "Binding",
            "Catalytic activity",
            "Transferase activity",
        ]
    _clear_cache()


def test_unknown_terms_skipped():
    _clear_cache()
    payload = _payload({"GO:0001": ["Catalytic activity"]})
    with patch("builtins.open", mock_open(read_data=payload)):
        assert go_slim_for_terms(["GO:0001", "GO:9999", ""]) == ["Catalytic activity"]
    _clear_cache()


def test_empty_inputs_return_empty_list():
    _clear_cache()
    with patch("builtins.open", mock_open(read_data=_payload({}))):
        assert go_slim_for_terms([]) == []
        assert go_slim_for_terms(None) == []
    _clear_cache()


def test_missing_file_returns_empty_mapping():
    _clear_cache()
    with patch("builtins.open", side_effect=FileNotFoundError):
        assert go_slim_for_terms(["GO:0003824"]) == []
    _clear_cache()


def test_malformed_payload_returns_empty_mapping():
    _clear_cache()
    with patch("builtins.open", mock_open(read_data='{"map": "not a dict"}')):
        assert go_slim_for_terms(["GO:0003824"]) == []
    _clear_cache()


def test_json_loaded_once_per_process():
    """lru_cache should mean a single read of go_slim_map.json."""
    _clear_cache()
    m = mock_open(read_data=_payload({"GO:0001": ["X"]}))
    with patch("builtins.open", m):
        go_slim_for_terms(["GO:0001"])
        go_slim_for_terms(["GO:0001"])
        go_slim_for_terms(["GO:9999"])
    assert m.call_count == 1
    _clear_cache()


def test_legacy_pfam_shim_returns_empty_list():
    """``go_slim_for(domain_acc)`` is a deprecated shim; must not raise."""
    from discovery.services.go_slim import go_slim_for

    assert go_slim_for("PF00001") == []
    assert go_slim_for("") == []
