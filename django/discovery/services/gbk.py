"""GenBank record builder for discovery iBGCs.

Generates multi-record GBK files from ``IntegratedBgc`` rows. Each record
is one iBGC region with a flanking window of ``FLANKING_WINDOW`` bp on the
parent contig. Features include:

  * one ``iBGC`` feature for the consolidated range
  * one ``BGC`` feature per overlapping ``SourceBgcPrediction`` (per-tool)
  * ``CDS`` features for every ``ContigCds`` overlapping the iBGC range;
    each carries a ``claimed_by`` qualifier listing the tools whose
    predictions overlap that CDS
  * ``misc_feature`` per ``ContigDomain`` attached to each CDS

Sequences come from the on-demand ``ContigSequence`` / ``CdsSequence``
tables in the discovery schema.
"""

import io
import json
import zipfile
from io import StringIO
from typing import List

from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import FeatureLocation, SeqFeature
from Bio.SeqRecord import SeqRecord

from discovery.models import (
    ContigCds,
    ContigDomain,
    IntegratedBgc,
    SourceBgcPrediction,
)

FLANKING_WINDOW = 2000


def _crop(val: int, lo: int, hi: int) -> int:
    return max(lo, min(val, hi))


def _claimed_by_tools_for_cds(
    cds: ContigCds, predictions: list[SourceBgcPrediction],
) -> list[str]:
    """Return sorted unique tool codes whose ``bgc_range`` overlaps the CDS."""
    tools: set[str] = set()
    for pred in predictions:
        if pred.bgc_range is None or cds.cds_range is None:
            continue
        if pred.bgc_range.lower < cds.cds_range.upper and \
           cds.cds_range.lower < pred.bgc_range.upper:
            tool = pred.detector.tool if pred.detector_id else ""
            if tool:
                tools.add(tool)
    return sorted(tools)


def build_ibgc_genbank_record(ibgc: IntegratedBgc) -> SeqRecord:
    """Build a single SeqRecord for an iBGC with flanking window.

    Expects ``ibgc.contig`` and its ``seq`` to be prefetched. The CDS pool
    is fetched on the fly via the range-overlap query.
    """
    contig = ibgc.contig
    contig_seq_obj = getattr(contig, "seq", None) if contig else None

    if contig_seq_obj is None:
        return _build_placeholder_record(ibgc)

    contig_seq = contig_seq_obj.get_sequence()
    contig_len = len(contig_seq)

    window_start = max(0, ibgc.start_position - FLANKING_WINDOW)
    window_end = min(contig_len, ibgc.end_position + FLANKING_WINDOW)
    region_seq = contig_seq[window_start:window_end]

    contig_acc = contig.accession or contig.sequence_sha256

    predictions = list(
        SourceBgcPrediction.objects.filter(integrated_bgc_id=ibgc.id)
        .select_related("detector")
    )

    cds_list = list(
        ContigCds.objects.filter(
            contig_id=ibgc.contig_id,
            cds_range__overlap=ibgc.bgc_range,
        ).select_related("seq").order_by("cds_range")
    )

    domains_by_cds: dict[int, list[ContigDomain]] = {}
    if cds_list:
        cds_ids = [c.id for c in cds_list]
        for dom in ContigDomain.objects.filter(cds_id__in=cds_ids).order_by(
            "cds_id", "start_position",
        ):
            domains_by_cds.setdefault(dom.cds_id, []).append(dom)

    record = SeqRecord(
        Seq(region_seq),
        id=contig_acc,
        name=contig_acc[:16],  # GenBank LOCUS max 16 chars
        description=(
            f"Region {window_start}-{window_end} on "
            f"{contig_acc} (iBGC {ibgc.accession})"
        ),
    )

    assembly = predictions[0].assembly if predictions else None
    record.annotations["molecule_type"] = "DNA"
    record.annotations["topology"] = "linear"
    record.annotations["organism"] = assembly.organism_name if assembly else "Unknown"
    record.annotations["source"] = json.dumps({
        "contig_accession": contig_acc,
        "assembly_accession": assembly.assembly_accession if assembly else "",
        "ibgc_accession": ibgc.accession,
        "cbgc_accession": ibgc.cbgc.accession if ibgc.cbgc_id else "",
        "start_position": ibgc.start_position + 1,
        "end_position": ibgc.end_position,
    })

    features: List[SeqFeature] = []

    # ── iBGC feature ─────────────────────────────────────────────────────
    ibgc_rel_start = _crop(ibgc.start_position, window_start, window_end) - window_start
    ibgc_rel_end = _crop(ibgc.end_position, window_start, window_end) - window_start
    if ibgc_rel_end > ibgc_rel_start:
        ibgc_qualifiers = {
            "ID": [ibgc.accession],
            "start": [str(ibgc.start_position + 1)],
            "end": [str(ibgc.end_position)],
            "source_tools": [",".join(ibgc.source_tools or [])],
        }
        if ibgc.gene_cluster_family:
            ibgc_qualifiers["gene_cluster_family"] = [ibgc.gene_cluster_family]
        if ibgc.novelty_score is not None:
            ibgc_qualifiers["novelty_score"] = [f"{ibgc.novelty_score:.4f}"]
        if ibgc.domain_novelty is not None:
            ibgc_qualifiers["domain_novelty"] = [f"{ibgc.domain_novelty:.4f}"]
        features.append(SeqFeature(
            FeatureLocation(ibgc_rel_start, ibgc_rel_end),
            type="iBGC",
            qualifiers=ibgc_qualifiers,
        ))

    # ── BGC feature per overlapping SourceBgcPrediction ─────────────────
    for pred in predictions:
        if pred.bgc_range is None:
            continue
        rel_start = _crop(pred.start_position, window_start, window_end) - window_start
        rel_end = _crop(pred.end_position, window_start, window_end) - window_start
        if rel_end <= rel_start:
            continue
        tool = pred.detector.tool if pred.detector_id else "Unknown"
        features.append(SeqFeature(
            FeatureLocation(rel_start, rel_end),
            type="BGC",
            qualifiers={
                "ID": [pred.prediction_accession],
                "detector": [tool],
                "tool": [tool],
                "contig_edge": ["True" if pred.is_partial else "False"],
                "validated": ["True" if pred.is_validated else "False"],
            },
        ))

    # ── CDS features (with per-domain misc_feature children) ─────────────
    for cds in cds_list:
        cds_start = _crop(cds.start_position, window_start, window_end)
        cds_end = _crop(cds.end_position, window_start, window_end)
        rel_start = cds_start - window_start
        rel_end = cds_end - window_start

        seq_obj = getattr(cds, "seq", None)
        aa_seq = seq_obj.get_sequence() if seq_obj else ""

        claimed_by = _claimed_by_tools_for_cds(cds, predictions)

        qualifiers: dict[str, list[str]] = {
            "ID": [cds.protein_id_str],
            "gene_caller": [cds.gene_caller or ""],
        }
        if claimed_by:
            qualifiers["claimed_by"] = [";".join(claimed_by)]
        if aa_seq:
            qualifiers["translation"] = [aa_seq]
            qualifiers["protein_id"] = [cds.protein_id_str]
        if cds.cluster_representative:
            qualifiers["cluster_representative"] = [cds.cluster_representative]

        features.append(SeqFeature(
            FeatureLocation(rel_start, rel_end, strand=cds.strand),
            type="CDS",
            qualifiers=qualifiers,
        ))

        for dom in domains_by_cds.get(cds.id, []):
            dom_rel_start, dom_rel_end = _domain_dna_window(
                dom, cds, window_start, window_end,
            )
            if dom_rel_end <= dom_rel_start:
                continue
            dom_qualifiers: dict[str, list[str]] = {
                "signature_acc": [dom.domain_acc or ""],
                "ref_db": [dom.ref_db or ""],
                "name": [dom.domain_name or ""],
                "aa_start": [str(dom.start_position or 0)],
                "aa_end": [str(dom.end_position or 0)],
                "cds": [cds.protein_id_str],
            }
            if dom.interpro_entry_acc:
                dom_qualifiers["interpro_entry_acc"] = [dom.interpro_entry_acc]
                if dom.interpro_entry_description:
                    dom_qualifiers["interpro_entry_description"] = [
                        dom.interpro_entry_description
                    ]
            if dom.domain_description:
                dom_qualifiers["description"] = [dom.domain_description]
            if dom.score is not None:
                dom_qualifiers["score"] = [str(dom.score)]
            features.append(
                SeqFeature(
                    FeatureLocation(
                        dom_rel_start, dom_rel_end, strand=cds.strand,
                    ),
                    type="misc_feature",
                    qualifiers=dom_qualifiers,
                )
            )

    record.features = features
    return record


def _domain_dna_window(domain, cds, window_start: int, window_end: int) -> tuple[int, int]:
    """Project a domain's protein-aa span onto the relative DNA coords."""
    aa_start = max(1, int(domain.start_position or 1))
    aa_end = max(aa_start, int(domain.end_position or aa_start))
    if (cds.strand or 1) >= 0:
        d_start_abs = cds.start_position + (aa_start - 1) * 3
        d_end_abs = cds.start_position + aa_end * 3
    else:
        d_end_abs = cds.end_position - (aa_start - 1) * 3
        d_start_abs = cds.end_position - aa_end * 3
    rel_start = _crop(d_start_abs, window_start, window_end) - window_start
    rel_end = _crop(d_end_abs, window_start, window_end) - window_start
    return rel_start, rel_end


def _build_placeholder_record(ibgc: IntegratedBgc) -> SeqRecord:
    """Build a minimal record when contig sequence is unavailable."""
    length = max(1, ibgc.end_position - ibgc.start_position)
    contig_acc = ibgc.contig.accession if ibgc.contig else None
    record = SeqRecord(
        Seq("N" * length),
        id=contig_acc or "unknown",
        name=ibgc.accession[:16],
        description=f"iBGC {ibgc.accession} (sequence unavailable)",
    )
    record.annotations["molecule_type"] = "DNA"
    return record


def _fetch_ibgcs_for_gbk(filter_kwargs: dict):
    return (
        IntegratedBgc.objects.filter(**filter_kwargs)
        .select_related("contig", "contig__seq", "cbgc")
        .order_by("id")
    )


def build_multi_ibgc_gbk(ibgc_ids: List[int]) -> str:
    """Build a multi-record GBK string for a list of iBGC IDs."""
    ibgcs = _fetch_ibgcs_for_gbk({"id__in": list(ibgc_ids)})
    records = [build_ibgc_genbank_record(ibgc) for ibgc in ibgcs]
    handle = StringIO()
    SeqIO.write(records, handle, "genbank")
    return handle.getvalue()


def build_shortlist_gbk_zip(ibgc_ids: List[int]) -> bytes:
    """Build a zip archive of GBK files, one per iBGC.

    Files are named ``<ibgc_accession>.gbk`` at the top level. Returns the
    zip bytes (in-memory).
    """
    ibgcs = list(_fetch_ibgcs_for_gbk({"id__in": list(ibgc_ids)}))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for ibgc in ibgcs:
            record = build_ibgc_genbank_record(ibgc)
            handle = StringIO()
            SeqIO.write([record], handle, "genbank")
            filename = f"{ibgc.accession}.gbk"
            zf.writestr(filename, handle.getvalue())
    return buf.getvalue()
