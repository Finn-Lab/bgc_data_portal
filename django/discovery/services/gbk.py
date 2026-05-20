"""GenBank record builder for discovery BGCs.

Generates multi-record GBK files from DashboardBgc data, using contig
sequences and CDS translations stored in the discovery schema's on-demand
sequence tables (ContigSequence, CdsSequence).
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

from discovery.models import DashboardBgc

FLANKING_WINDOW = 2000


def _crop(val: int, lo: int, hi: int) -> int:
    return max(lo, min(val, hi))


def build_bgc_genbank_record(bgc: DashboardBgc) -> SeqRecord:
    """Build a single SeqRecord for a BGC with flanking window.

    Expects ``bgc.contig`` and ``bgc.contig.seq`` to be prefetched.
    CDS entries should have ``seq`` prefetched via ``cds_list`` + ``cds_list__seq``.
    """
    contig = bgc.contig
    contig_seq_obj = getattr(contig, "seq", None) if contig else None

    if contig_seq_obj is None:
        return _build_placeholder_record(bgc)

    contig_seq = contig_seq_obj.get_sequence()
    contig_len = len(contig_seq)

    window_start = max(0, bgc.start_position - FLANKING_WINDOW)
    window_end = min(contig_len, bgc.end_position + FLANKING_WINDOW)
    region_seq = contig_seq[window_start:window_end]

    contig_acc = contig.accession or contig.sequence_sha256
    assembly = bgc.assembly

    record = SeqRecord(
        Seq(region_seq),
        id=contig_acc,
        name=contig_acc[:16],  # GenBank LOCUS name max 16 chars
        description=(
            f"Region {window_start}-{window_end} on "
            f"{contig_acc} (BGC {bgc.bgc_accession})"
        ),
    )

    record.annotations["molecule_type"] = "DNA"
    record.annotations["topology"] = "linear"
    record.annotations["organism"] = assembly.organism_name if assembly else "Unknown"
    record.annotations["source"] = json.dumps({
        "contig_accession": contig_acc,
        "assembly_accession": assembly.assembly_accession if assembly else "",
        "bgc_accession": bgc.bgc_accession,
        "start_position": bgc.start_position + 1,
        "end_position": bgc.end_position,
    })

    features: List[SeqFeature] = []

    # ── Region feature (antiSMASH-style aggregate window) ────────────────────
    region = getattr(bgc, "region", None)
    if region is not None:
        reg_rel_start = _crop(region.start_position, window_start, window_end) - window_start
        reg_rel_end = _crop(region.end_position, window_start, window_end) - window_start
        if reg_rel_end > reg_rel_start:
            features.append(SeqFeature(
                FeatureLocation(reg_rel_start, reg_rel_end),
                type="Region",
                qualifiers={
                    "ID": [region.accession],
                    "start": [str(region.start_position + 1)],
                    "end": [str(region.end_position)],
                },
            ))

    # ── iBGC feature (consolidated integrated BGC) ─────────────────────────
    ibgc = getattr(bgc, "integrated_bgc", None)
    if ibgc is not None:
        ibgc_rel_start = _crop(ibgc.start_position, window_start, window_end) - window_start
        ibgc_rel_end = _crop(ibgc.end_position, window_start, window_end) - window_start
        if ibgc_rel_end > ibgc_rel_start:
            ibgc_qualifiers = {
                "ID": [f"iBGC-{ibgc.id}"],
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

    # ── BGC feature (the SanntiS / antiSMASH / GECCO prediction) ─────────────
    bgc_rel_start = bgc.start_position - window_start
    bgc_rel_end = bgc.end_position - window_start

    parts = bgc.classification_path.split(".") if bgc.classification_path else []
    classification = "/".join(parts)
    bgc_class_l1 = parts[0] if parts else "Unknown"
    bgc_feat = SeqFeature(
        FeatureLocation(bgc_rel_start, bgc_rel_end),
        type="BGC",
        qualifiers={
            "ID": [bgc.bgc_accession],
            "BGC_CLASS": [bgc_class_l1],
            "classification": [classification or "Unknown"],
            "detector": [bgc.detector.name if bgc.detector else "Unknown"],
            "tool": [bgc.detector.name if bgc.detector else "Unknown"],
            "contig_edge": ["True" if bgc.is_partial else "False"],
        },
    )
    features.append(bgc_feat)

    # ── CDS features ─────────────────────────────────────────────────────────
    for cds in bgc.cds_list.all():
        cds_start = _crop(cds.start_position, window_start, window_end)
        cds_end = _crop(cds.end_position, window_start, window_end)
        rel_start = cds_start - window_start
        rel_end = cds_end - window_start

        seq_obj = getattr(cds, "seq", None)
        aa_seq = seq_obj.get_sequence() if seq_obj else ""

        qualifiers = {
            "ID": [cds.protein_id_str],
            "gene_caller": [cds.gene_caller or ""],
        }
        if aa_seq:
            qualifiers["translation"] = [aa_seq]
            qualifiers["protein_id"] = [cds.protein_id_str]
        if cds.cluster_representative:
            qualifiers["cluster_representative"] = [cds.cluster_representative]

        cds_feat = SeqFeature(
            FeatureLocation(rel_start, rel_end, strand=cds.strand),
            type="CDS",
            qualifiers=qualifiers,
        )
        features.append(cds_feat)

    record.features = features
    return record


def _build_placeholder_record(bgc: DashboardBgc) -> SeqRecord:
    """Build a minimal record when contig sequence is unavailable."""
    length = max(1, bgc.end_position - bgc.start_position)
    record = SeqRecord(
        Seq("N" * length),
        id=(bgc.contig.accession if bgc.contig else None) or "unknown",
        name=bgc.bgc_accession[:16],
        description=f"BGC {bgc.bgc_accession} (sequence unavailable)",
    )
    record.annotations["molecule_type"] = "DNA"
    return record


def _fetch_bgcs_for_gbk(filter_kwargs: dict):
    return (
        DashboardBgc.objects.filter(**filter_kwargs)
        .select_related(
            "assembly",
            "contig",
            "contig__seq",
            "detector",
            "region",
            "integrated_bgc",
        )
        .prefetch_related("cds_list", "cds_list__seq")
        .order_by("integrated_bgc_id", "id")
    )


def build_multi_bgc_gbk(bgc_ids: List[int]) -> str:
    """Build a multi-record GBK string for a list of dashboard BGC IDs."""
    bgcs = _fetch_bgcs_for_gbk({"id__in": bgc_ids})
    records = [build_bgc_genbank_record(bgc) for bgc in bgcs]
    handle = StringIO()
    SeqIO.write(records, handle, "genbank")
    return handle.getvalue()


def build_shortlist_gbk_zip(ibgc_ids: List[int]) -> bytes:
    """Build a zip archive of GBK files, one per source DashboardBgc.

    Source BGCs are grouped by their parent iBGC; files are named
    ``iBGC-{ibgc_id}/{bgc_accession}.gbk`` so the resulting tree reflects the
    iBGC → source-BGC hierarchy. Returns the zip bytes (in-memory).
    """
    bgcs = list(_fetch_bgcs_for_gbk({"integrated_bgc_id__in": list(ibgc_ids)}))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for bgc in bgcs:
            record = build_bgc_genbank_record(bgc)
            handle = StringIO()
            SeqIO.write([record], handle, "genbank")
            ibgc_id = bgc.integrated_bgc_id or 0
            filename = f"iBGC-{ibgc_id}/{bgc.bgc_accession}.gbk"
            zf.writestr(filename, handle.getvalue())
    return buf.getvalue()
