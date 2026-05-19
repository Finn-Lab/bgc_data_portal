"""Unit tests for :func:`collapse_to_interpro_rows`.

Pins the Protein-Information-card grouping rules: dedupe by InterPro entry
when set (fallback to signature accession), union of slim names, min/max
envelope, best (smallest) e-value, entry-preferred description and URL.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from discovery.services.architecture import collapse_to_interpro_rows


@dataclass
class FakeDomain:
    """Mirrors the BgcDomain attribute surface used by the helper."""

    domain_acc: str
    domain_name: str = ""
    domain_description: str = ""
    interpro_entry_acc: str = ""
    interpro_entry_description: str = ""
    start_position: int = 0
    end_position: int = 0
    score: float | None = None
    url: str = ""
    go_slim: list[str] = field(default_factory=list)


def test_two_signatures_same_ips_entry_collapse_to_one_row():
    domains = [
        FakeDomain(
            domain_acc="PF00001",
            domain_description="Pfam description",
            interpro_entry_acc="IPR000123",
            interpro_entry_description="IPR entry",
            start_position=10,
            end_position=80,
            score=1e-30,
            url="https://pfam.org/family/PF00001",
            go_slim=["Catalytic activity"],
        ),
        FakeDomain(
            domain_acc="SM00355",
            domain_description="SMART description",
            interpro_entry_acc="IPR000123",
            interpro_entry_description="IPR entry",
            start_position=5,  # earlier start → should win envelope_start
            end_position=120,  # later end → should win envelope_end
            score=1e-50,  # better → should win e_value
            url="https://smart.org/SM00355",
            go_slim=["Transferase activity"],
        ),
    ]

    rows = collapse_to_interpro_rows(domains)

    assert len(rows) == 1
    row = rows[0]
    assert row["accession"] == "IPR000123"
    assert row["description"] == "IPR entry"
    assert row["go_slim"] == ["Catalytic activity", "Transferase activity"]
    assert row["envelope_start"] == 5
    assert row["envelope_end"] == 120
    assert row["e_value"] == "1e-50"
    assert row["url"] == "https://www.ebi.ac.uk/interpro/entry/InterPro/IPR000123/"


def test_signature_without_entry_falls_back_to_signature_acc():
    domains = [
        FakeDomain(
            domain_acc="SM00355",
            domain_description="SMART description",
            start_position=20,
            end_position=70,
            score=1e-12,
            url="https://smart.org/SM00355",
            go_slim=["Binding"],
        ),
    ]
    rows = collapse_to_interpro_rows(domains)
    assert len(rows) == 1
    assert rows[0]["accession"] == "SM00355"
    assert rows[0]["description"] == "SMART description"
    assert rows[0]["go_slim"] == ["Binding"]
    assert rows[0]["url"] == "https://smart.org/SM00355"


def test_mixed_entry_and_signature_rows_are_separate():
    domains = [
        FakeDomain(domain_acc="PF00001", interpro_entry_acc="IPR000123", start_position=10, end_position=50),
        FakeDomain(domain_acc="SM00355", start_position=60, end_position=90),
    ]
    rows = collapse_to_interpro_rows(domains)
    assert {r["accession"] for r in rows} == {"IPR000123", "SM00355"}


def test_rows_sorted_by_envelope_start():
    domains = [
        FakeDomain(domain_acc="A", start_position=200, end_position=250),
        FakeDomain(domain_acc="B", start_position=10, end_position=50),
        FakeDomain(domain_acc="C", start_position=100, end_position=150),
    ]
    rows = collapse_to_interpro_rows(domains)
    assert [r["accession"] for r in rows] == ["B", "C", "A"]


def test_slim_for_callable_overrides_attribute():
    """Asset-upload path passes a slim_for callable instead of storing go_slim."""

    @dataclass
    class AssetLikeDomain:
        domain_acc: str
        go_terms: list[str]
        interpro_entry_acc: str = ""
        interpro_entry_description: str = ""
        domain_name: str = ""
        domain_description: str = ""
        start_position: int = 0
        end_position: int = 0
        score: float | None = None
        url: str = ""

    domains = [AssetLikeDomain(domain_acc="PF00001", go_terms=["GO:1"])]
    rows = collapse_to_interpro_rows(
        domains, slim_for=lambda d: ["Resolved slim"]
    )
    assert rows[0]["go_slim"] == ["Resolved slim"]


def test_empty_input_returns_empty_list():
    assert collapse_to_interpro_rows([]) == []


def test_skips_rows_with_no_accession():
    domains = [FakeDomain(domain_acc="")]
    assert collapse_to_interpro_rows(domains) == []
