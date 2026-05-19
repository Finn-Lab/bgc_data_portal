"""Asset region payload pins the contract RegionPlot.tsx depends on.

``RegionPlot.tsx`` (frontend) builds the per-CDS dominant GO-slim colour
map exclusively from ``data.domain_list[*]`` — ``cds_list[*].pfam`` is
only used by the CDS-click protein info table. So the asset region
payload must mirror the persisted path's ``domain_list`` shape:
``parent_cds_id`` set, AA-to-NT positions computed, ``go_slim`` carried
as ``list[str]``.

Slim names now come from per-signature ``go_terms`` via
:func:`discovery.services.go_slim.go_slim_for_terms`; the asset projection
folds them at render time.
"""

from __future__ import annotations

import pytest

from discovery.services import go_slim as go_slim_mod
from discovery.services.asset_upload.project import VirtualNrb, _region_payload
from discovery.services.asset_upload.schemas import AssetCds, AssetDomain


SLIM_MAP = {
    "GO:0016491": ["Oxidoreductase activity"],
}


@pytest.fixture(autouse=True)
def _stub_slim_map(monkeypatch):
    go_slim_mod._go_term_to_slims.cache_clear()
    monkeypatch.setattr(
        go_slim_mod, "_go_term_to_slims", lambda: SLIM_MAP, raising=True
    )
    yield
    go_slim_mod._go_term_to_slims.cache_clear()


def _vnrb_with_domain(
    domain_acc: str = "PF01593", go_terms: list[str] | None = None
) -> VirtualNrb:
    """Single CDS on the forward strand with one domain in AA[0:100]."""
    bgc_key = ("c1", 1000, 5000, "antiSMASH v7.1")
    cds = AssetCds(
        bgc_key=bgc_key,
        protein_id_str="Ga0181741_11_94",
        start_position=1100,
        end_position=1400,
        strand=1,
        protein_length=100,
    )
    domain = AssetDomain(
        bgc_key=bgc_key,
        cds_protein_id=cds.protein_id_str,
        domain_acc=domain_acc,
        domain_name="OxRed_like",
        domain_description="Oxidoreductase family",
        ref_db="Pfam",
        start_position=0,
        end_position=100,
        score=1.5,
        url="https://pfam.example/PF01593",
        go_terms=list(go_terms or []),
    )
    return VirtualNrb(
        neg_id=-1,
        contig_sha256="c1",
        contig_accession="CONTIG_1",
        assembly_accession="A1",
        organism_name="Asset organism",
        is_type_strain=False,
        start_position=1000,
        end_position=5000,
        source_tools=["antiSMASH"],
        member_bgcs=[],
        is_partial=False,
        is_validated=False,
        cds=[cds],
        domains=[domain],
    )


def test_region_payload_populates_domain_list_for_coloring():
    vnrb = _vnrb_with_domain("PF01593", go_terms=["GO:0016491"])
    payload = _region_payload(vnrb)

    # Per-CDS pfam list is still there (CDS click panel) — list-typed go_slim.
    cds = payload["cds_list"][0]
    assert cds["pfam"][0]["go_slim"] == ["Oxidoreductase activity"]

    # domain_list carries the per-CDS slim list for the plot's colouring map.
    assert len(payload["domain_list"]) == 1
    dom = payload["domain_list"][0]
    assert dom["accession"] == "PF01593"
    assert dom["parent_cds_id"] == "Ga0181741_11_94"
    assert dom["go_slim"] == ["Oxidoreductase activity"]
    # NT coords relative to the NRB window (forward strand: CDS@1100, AA[0:100]
    # → NT[1100, 1400] → relative [100, 400] after subtracting window_start=1000).
    assert dom["start"] == 100
    assert dom["end"] == 400


def test_region_payload_empty_go_terms_yields_empty_slim_list():
    """No go_terms ⇒ list[str] shape preserved, no false colour."""
    vnrb = _vnrb_with_domain("PF99999", go_terms=[])
    payload = _region_payload(vnrb)
    dom = payload["domain_list"][0]
    assert dom["go_slim"] == []
    assert payload["cds_list"][0]["pfam"][0]["go_slim"] == []


def test_region_payload_reverse_strand_converts_coords():
    vnrb = _vnrb_with_domain("PF01593", go_terms=["GO:0016491"])
    vnrb.cds[0].strand = -1
    payload = _region_payload(vnrb)
    dom = payload["domain_list"][0]
    # Reverse strand: AA[0:100] over CDS NT[1100,1400] (300nt) flips to
    # NT[end - 100*3, end - 0*3] = [1100, 1400] → relative [100, 400].
    assert dom["start"] == 100
    assert dom["end"] == 400
    assert dom["strand"] == -1
