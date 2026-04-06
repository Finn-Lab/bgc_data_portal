"""Export builders for discovery BGCs — FNA, FAA, and JSON formats.

GBK format is handled by ``gbk.py``.  All functions expect prefetched
querysets (contig, contig__seq, cds_list, cds_list__seq, bgc_domains).
"""

from __future__ import annotations

import json
from io import StringIO
from typing import TYPE_CHECKING

from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord

if TYPE_CHECKING:
    from discovery.models import DashboardBgc

FLANKING_WINDOW = 2000


def build_bgc_fna(bgc: DashboardBgc) -> str:
    """Nucleotide FASTA for the BGC region (with flanking window).

    Returns a single-record FASTA string.  Falls back to N-filled
    placeholder if contig sequence is unavailable.
    """
    contig = bgc.contig
    contig_seq_obj = getattr(contig, "seq", None) if contig else None

    if contig_seq_obj is None:
        length = max(1, bgc.end_position - bgc.start_position)
        seq = "N" * length
        description = f"BGC {bgc.bgc_accession} (sequence unavailable)"
        contig_acc = bgc.contig_accession or "unknown"
    else:
        contig_seq = contig_seq_obj.get_sequence()
        contig_len = len(contig_seq)
        window_start = max(0, bgc.start_position - FLANKING_WINDOW)
        window_end = min(contig_len, bgc.end_position + FLANKING_WINDOW)
        seq = contig_seq[window_start:window_end]
        contig_acc = bgc.contig_accession or contig.accession
        description = (
            f"Region {window_start}-{window_end} on "
            f"{contig_acc} (BGC {bgc.bgc_accession})"
        )

    record = SeqRecord(
        Seq(seq),
        id=contig_acc,
        name=contig_acc[:16],
        description=description,
    )

    handle = StringIO()
    SeqIO.write([record], handle, "fasta")
    return handle.getvalue()


def build_bgc_faa(bgc: DashboardBgc) -> str:
    """Amino acid FASTA for all CDS in the BGC.

    Returns a multi-record FASTA string (one record per CDS with sequence).
    """
    records = []
    for cds in bgc.cds_list.all():
        seq_obj = getattr(cds, "seq", None)
        aa_seq = seq_obj.get_sequence() if seq_obj else ""
        if not aa_seq:
            continue
        record = SeqRecord(
            Seq(aa_seq),
            id=cds.protein_id_str,
            name=cds.protein_id_str[:16],
            description=(
                f"CDS {cds.start_position}-{cds.end_position} "
                f"strand={cds.strand} BGC={bgc.bgc_accession}"
            ),
        )
        records.append(record)

    if not records:
        # Return a placeholder if no CDS sequences available
        records.append(SeqRecord(
            Seq(""),
            id=bgc.bgc_accession,
            description="No CDS sequences available",
        ))

    handle = StringIO()
    SeqIO.write(records, handle, "fasta")
    return handle.getvalue()


def build_bgc_json(bgc: DashboardBgc) -> dict:
    """JSON metadata dict for a single BGC.

    Includes assembly context, classification, scores, CDS list,
    and domain annotations.
    """
    assembly = bgc.assembly

    cds_items = []
    for cds in bgc.cds_list.all():
        cds_items.append({
            "protein_id": cds.protein_id_str,
            "start_position": cds.start_position,
            "end_position": cds.end_position,
            "strand": cds.strand,
            "protein_length": cds.protein_length,
            "gene_caller": cds.gene_caller,
            "cluster_representative": cds.cluster_representative,
        })

    domain_items = []
    for dom in bgc.bgc_domains.all():
        domain_items.append({
            "domain_acc": dom.domain_acc,
            "domain_name": dom.domain_name,
            "description": dom.domain_description,
            "ref_db": dom.ref_db,
            "start_position": dom.start_position,
            "end_position": dom.end_position,
            "score": dom.score,
        })

    return {
        "bgc_accession": bgc.bgc_accession,
        "assembly_accession": assembly.assembly_accession if assembly else None,
        "organism_name": assembly.organism_name if assembly else None,
        "contig_accession": bgc.contig_accession,
        "start_position": bgc.start_position,
        "end_position": bgc.end_position,
        "size_kb": bgc.size_kb,
        "classification": {
            "path": bgc.classification_path,
            "l1": bgc.classification_l1,
            "l2": bgc.classification_l2,
            "l3": bgc.classification_l3,
        },
        "scores": {
            "novelty_score": bgc.novelty_score,
            "domain_novelty": bgc.domain_novelty,
            "nearest_mibig_accession": bgc.nearest_mibig_accession,
            "nearest_mibig_distance": bgc.nearest_mibig_distance,
        },
        "flags": {
            "is_partial": bgc.is_partial,
            "is_validated": bgc.is_validated,
            "is_mibig": bgc.is_mibig,
        },
        "umap": {"x": bgc.umap_x, "y": bgc.umap_y},
        "cds": cds_items,
        "domains": domain_items,
    }
