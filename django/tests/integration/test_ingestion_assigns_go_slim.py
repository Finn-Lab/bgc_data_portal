"""Ingestion populates ``BgcDomain.go_slim`` inline from ``go_terms``.

Pins the post-Pfam-era behaviour: the loader does not look up slim names
from the old pfam2goSlim.json. Instead it folds the per-signature
``go_terms`` column emitted by InterProScan through
:func:`discovery.services.go_slim.go_slim_for_terms` and stores the
resulting deduplicated list on ``BgcDomain.go_slim``.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import pytest

from discovery.models import (
    AssemblySource,
    AssemblyType,
    BgcDomain,
    DashboardAssembly,
    DashboardBgc,
    DashboardContig,
    DashboardDetector,
)
from discovery.services import go_slim as go_slim_mod
from discovery.services.ingestion.loader import load_domains


SLIM_MAP: dict[str, list[str]] = {
    "GO:0003824": ["Catalytic activity"],
    "GO:0016740": ["Transferase activity"],
}


def _seed_parent_rows():
    src = AssemblySource.objects.create(name="GTDB")
    assembly = DashboardAssembly.objects.create(
        assembly_accession="A1",
        organism_name="Test sp.",
        source=src,
        assembly_type=AssemblyType.GENOME,
        biome_path="root.Env",
    )
    contig = DashboardContig.objects.create(
        assembly=assembly,
        sequence_sha256=hashlib.sha256(b"c1").hexdigest(),
        accession="CONTIG_1",
        length=10_000,
    )
    detector = DashboardDetector.objects.create(
        name="antiSMASH v7.1",
        tool="antiSMASH",
        version="7.1.0",
        tool_name_code="ANT",
        version_sort_key=710,
    )
    bgc = DashboardBgc.objects.create(
        assembly=assembly,
        contig=contig,
        bgc_accession="MGYB10000001.ANT.1.01",
        start_position=1_000,
        end_position=5_000,
        classification_path="Polyketide",
        detector=detector,
    )
    return contig, bgc


@pytest.fixture(autouse=True)
def _stub_slim_map(monkeypatch):
    """Replace the on-disk slim-map loader with a deterministic dict.

    Avoids touching the bundled JSON (which is a placeholder) and decouples
    the test from goatools / OBO availability.
    """
    go_slim_mod._go_term_to_slims.cache_clear()
    monkeypatch.setattr(
        go_slim_mod, "_go_term_to_slims", lambda: SLIM_MAP, raising=True
    )
    yield
    go_slim_mod._go_term_to_slims.cache_clear()


@pytest.mark.django_db
def test_load_domains_populates_go_slim_from_go_terms(tmp_path: Path):
    contig, bgc = _seed_parent_rows()

    detector_name = "antiSMASH v7.1"
    bgc_lookup = {
        (contig.sequence_sha256, bgc.start_position, bgc.end_position, detector_name): bgc.id
    }
    cds_lookup: dict = {}

    tsv_path = tmp_path / "domains.tsv"
    with open(tsv_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            delimiter="\t",
            fieldnames=[
                "contig_sha256",
                "bgc_start",
                "bgc_end",
                "detector_name",
                "protein_id_str",
                "domain_acc",
                "domain_name",
                "domain_description",
                "ref_db",
                "start_position",
                "end_position",
                "score",
                "url",
                "interpro_entry_acc",
                "interpro_entry_description",
                "go_terms",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "contig_sha256": contig.sequence_sha256,
            "bgc_start": bgc.start_position,
            "bgc_end": bgc.end_position,
            "detector_name": detector_name,
            "protein_id_str": "",
            "domain_acc": "PF00001",
            "domain_name": "Pf001",
            "domain_description": "GPCR-like",
            "ref_db": "Pfam",
            "start_position": "0",
            "end_position": "100",
            "score": "1.5",
            "url": "",
            "interpro_entry_acc": "IPR000001",
            "interpro_entry_description": "GPCR entry",
            "go_terms": "GO:0003824|GO:0016740",
        })

    rows_loaded = load_domains(tmp_path, bgc_lookup, cds_lookup)
    assert rows_loaded == 1

    row = BgcDomain.objects.get(bgc=bgc, domain_acc="PF00001")
    assert row.go_terms == ["GO:0003824", "GO:0016740"]
    assert row.go_slim == ["Catalytic activity", "Transferase activity"]
    assert row.interpro_entry_acc == "IPR000001"
    assert row.interpro_entry_description == "GPCR entry"


@pytest.mark.django_db
def test_load_domains_handles_empty_go_terms(tmp_path: Path):
    contig, bgc = _seed_parent_rows()
    detector_name = "antiSMASH v7.1"
    bgc_lookup = {
        (contig.sequence_sha256, bgc.start_position, bgc.end_position, detector_name): bgc.id
    }

    tsv_path = tmp_path / "domains.tsv"
    with open(tsv_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            delimiter="\t",
            fieldnames=[
                "contig_sha256", "bgc_start", "bgc_end", "detector_name",
                "protein_id_str", "domain_acc", "ref_db", "go_terms",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "contig_sha256": contig.sequence_sha256,
            "bgc_start": bgc.start_position,
            "bgc_end": bgc.end_position,
            "detector_name": detector_name,
            "protein_id_str": "",
            "domain_acc": "SM00355",
            "ref_db": "SMART",
            "go_terms": "",
        })

    load_domains(tmp_path, bgc_lookup, {})
    row = BgcDomain.objects.get(bgc=bgc, domain_acc="SM00355")
    assert row.go_terms == []
    assert row.go_slim == []
