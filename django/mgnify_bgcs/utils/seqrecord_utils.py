"""
Utilities for building and exporting BGC region data as Biopython SeqRecords.

Provides:
- EnhancedSeqRecord: SeqRecord subclass with convenience exporters
- build_bgc_record: constructs an EnhancedSeqRecord for a given BGC id
"""

from __future__ import annotations

from typing import List, Dict, Any
import json
from io import StringIO, BytesIO
import numpy as np
import gzip


from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from Bio.SeqFeature import SeqFeature, FeatureLocation

from django.db.models import Prefetch

from ..models import Contig, Bgc, Cds, ProteinDomain
from ..services.pfam_to_slim.pfam_annots import pfamToGoSlim
from ..services.region_plots import plot_contig_region


class EnhancedSeqRecord(SeqRecord):
    """A SeqRecord with convenience exporters for common formats.

    Notes:
    - This class stores features and annotations like a standard SeqRecord.
    - Exporters operate on the current record content.
    """

    @classmethod
    def from_genbank_text(cls, gbk_text: str) -> "EnhancedSeqRecord":
        """Construct an EnhancedSeqRecord from GenBank-formatted text.

        Parses the GenBank text, transfers id/name/description/annotations/features,
        ensures a Biopython-compatible annotations dict (molecule_type included),
        and returns an EnhancedSeqRecord instance.
        """

        rec = next(SeqIO.parse(StringIO(gbk_text), "genbank"))
        seq_obj = rec.seq
        if isinstance(seq_obj, str):
            seq_obj = Seq(seq_obj)

        new_rec = cls(
            seq_obj,
            id=getattr(rec, "id", "") or "",
            name=getattr(rec, "name", "") or "",
            description=getattr(rec, "description", "") or "",
            annotations=dict(getattr(rec, "annotations", {}) or {}),
            features=list(getattr(rec, "features", []) or []),
        )

        # Ensure molecule_type for downstream GenBank writer compatibility
        if "molecule_type" not in new_rec.annotations:
            new_rec.annotations["molecule_type"] = "DNA"

        return new_rec

    def to_gbk(self) -> str:
        """Return this record in GenBank format (string)."""
        # Ensure required annotation for Biopython GenBank writer
        if "molecule_type" not in self.annotations:
            self.annotations["molecule_type"] = "DNA"
        handle = StringIO()
        SeqIO.write(self, handle, "genbank")
        return handle.getvalue()

    def to_fna(self) -> str:
        """Return nucleotide FASTA (string)."""
        handle = StringIO()
        SeqIO.write(self, handle, "fasta")
        return handle.getvalue()

    def to_faa(self) -> str:
        """Return protein FASTA (string) for all CDS features with translations."""
        # Collect CDS features with translations
        cds_features = [
            f
            for f in self.features
            if f.type == "CDS" and f.qualifiers and "translation" in f.qualifiers
        ]
        # Build SeqRecords for each CDS
        cds_records = []
        for f in cds_features:
            prot_id = (f.qualifiers.get("ID") or ["unknown_protein"])[0]
            translation = (f.qualifiers.get("translation") or [""])[0]
            if translation:
                cds_rec = SeqRecord(Seq(translation), id=prot_id, description="")
                cds_records.append(cds_rec)
        # Write to FASTA format
        handle = StringIO()
        SeqIO.write(cds_records, handle, "fasta")
        return handle.getvalue()

    def to_json(self) -> str:
        """Placeholder JSON exporter. Returns a minimal JSON for now."""
        meta = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "annotations": self.annotations,
            "num_features": len(getattr(self, "features", [])),
        }
        return json.dumps(meta)

    def to_plotly_plot(self) -> str:
        """Save the interactive figure to HTML."""
        return plot_contig_region(self)

    def to_embedding_npy(self) -> bytes:
        """Return bytes in npy.gz format containing the BGC embedding."""
        bgc_id = self.annotations["bgc_pk"]
        embedding = Bgc.objects.values_list("embedding", flat=True).get(id=bgc_id)
        embedding_array = np.array(embedding, dtype="float32")
        buffer = BytesIO()
        with gzip.GzipFile(fileobj=buffer, mode="w") as f:
            np.save(f, embedding_array)
        return buffer.getvalue()

    def to_cds_info_dct(self) -> Dict[str, Dict[str, Any]]:
        """
        Build the cds_info_dict consumed by the Explore Region panel.
        """

        # Collect ANNOT features by accession with meta to enrich PFAM rows
        annot_meta: Dict[str, Dict[str, Any]] = {}
        for f in self.features:
            if f.type != "ANNOT":
                continue
            q = f.qualifiers or {}
            acc = (q.get("ID") or [""])[0]
            if not acc:
                continue
            gos = q.get("GOslim")
            annot_meta[acc] = {
                "GOslim": gos,
                "description": (q.get("description") or [""])[0],
                "score": (q.get("score") or [""])[0],
            }

        # Collect CDS features and assign overlapping ANNOTs as PFAMs
        cds_info: Dict[str, Dict[str, Any]] = {}
        # Pre-collect ANNOT features for interval checks
        annot_features = [f for f in self.features if f.type == "ANNOT"]

        for f in self.features:
            if f.type != "CDS":
                continue
            q = f.qualifiers or {}

            # Protein identifier key (prefer mgyp when present)
            mgyp = (q.get("mgyp") or [""])[0]
            prot_id = mgyp or (q.get("ID") or [""])[0]
            if not prot_id:
                # skip entries without an identifier
                continue

            # Coordinates
            loc = f.location or FeatureLocation(0, 0)
            cds_start_rel = int(getattr(loc, "start", 0))
            cds_end_rel = int(getattr(loc, "end", 0))
            cds_strand = int(getattr(loc, "strand", 0) or 0)

            # Protein metadata
            sequence = (q.get("translation") or [""])[0]
            rep = (q.get("cluster_representative") or [""])[0]
            gene_caller = (q.get("gene_caller") or [""])[0] or (
                q.get("source") or [""]
            )[0]

            # Build PFAM rows by interval overlap
            pfam_rows = []
            for ann in annot_features:
                # Overlap test within this CDS
                a_loc = ann.location or FeatureLocation(0, 0)
                a_start = int(getattr(a_loc, "start", 0))
                a_end = int(getattr(a_loc, "end", 0))
                if a_start < cds_start_rel or a_end > cds_end_rel:
                    continue

                aq = ann.qualifiers or {}
                acc = (aq.get("ID") or [""])[0]
                if not acc:
                    continue
                # Compute envelope positions in AA relative to protein
                env_start = max(0, (a_start - cds_start_rel) // 3)
                env_end = max(env_start, (a_end - cds_start_rel) // 3)

                meta = annot_meta.get(acc, {})
                go_terms = meta.get("GOslim", []) or []
                go_slim_str = ";".join(go_terms) if go_terms else ""

                pfam_rows.append(
                    {
                        "PFAM": acc,
                        "description": meta.get("description", ""),
                        "go_slim": go_slim_str,
                        "envelope_start": env_start,
                        "envelope_end": env_end,
                        "e-val": meta.get("score", ""),
                    }
                )

            cds_info[prot_id] = {
                "sequence": sequence,
                "cluster_representative": rep,
                "cluster_representative_url": (
                    f"https://www.ebi.ac.uk/metagenomics/proteins/{rep}/"
                    if rep
                    else None
                ),
                "protein_length": len(sequence or ""),
                "gene_caller": gene_caller or "",
                "start": cds_start_rel,
                "end": cds_end_rel,
                "strand": cds_strand,
                "pfam": pfam_rows,
            }

        return cds_info


def _crop(val: int, lo: int, hi: int) -> int:
    return max(lo, min(val, hi))


def build_bgc_record(
    bgc_id: str | int, extended_window: int = 2000
) -> EnhancedSeqRecord:
    """
    Construct an EnhancedSeqRecord covering a window around the BGC and embed
    CLUSTER/CDS/ANNOT features. See bgc_display.build_bgc_record (refactored).
    """
    bgc_pk = int(bgc_id)
    bgc_queryset = Bgc.objects.select_related(
        "contig",
        "contig__assembly",
        "contig__assembly__study",
        "contig__assembly__biome",
    )

    aggregated_bgc = bgc_queryset.get(id=bgc_pk)
    start_position, end_position = (
        aggregated_bgc.start_position,
        aggregated_bgc.end_position,
    )

    contig: Contig | None = aggregated_bgc.contig
    if contig is None:
        raise ValueError("BGC has no associated contig.")

    contig_accession = contig.name or contig.accession or contig.mgyc or str(contig.id)
    assembly_accession = contig.assembly.accession if contig.assembly else None
    biome_lineage = (
        contig.assembly.biome.lineage
        if (contig.assembly and contig.assembly.biome)
        else (
            contig.source_organism.get("name", "Unknown")
            if contig.source_organism
            else None
        )
    )

    window_start = max(0, start_position - extended_window)
    window_end = end_position + extended_window

    # BGCs and CDSs
    aggregated_ids = (aggregated_bgc.metadata or {}).get("aggregated_bgc_ids") or [
        aggregated_bgc.id
    ]
    bgcs = bgc_queryset.filter(id__in=aggregated_ids)

    protein_domains_qs = ProteinDomain.objects.select_related("domain").filter(
        domain__ref_db="Pfam"
    )

    cdss = (
        Cds.objects.filter(
            contig=contig,
            start_position__lte=window_end,
            end_position__gte=window_start,
        )
        .select_related("protein", "gene_caller")
        .prefetch_related(
            Prefetch(
                "protein__proteindomain_set",
                queryset=protein_domains_qs,
                to_attr="domain_hits",
            )
        )
    )

    # Features
    seq_features: List[SeqFeature] = []

    for bgc in bgcs:
        bgc_class_names = sorted(c.name for c in bgc.classes.all())
        _start = _crop(bgc.start_position, window_start, window_end)
        _end = _crop(bgc.end_position, window_start, window_end)
        rel_start, rel_end = _start - window_start, _end - window_start

        # Store BGC metadata directly in qualifiers instead of a JSON payload
        feat = SeqFeature(
            FeatureLocation(rel_start, rel_end),
            type="CLUSTER",
            qualifiers={
                "source": [bgc.detector.tool if bgc.detector else "Unknown detector"],
                "ID": [bgc.accession],
                "BGC_CLASS": bgc_class_names or ["Unknown"],
                "detector_version": [bgc.detector.version if bgc.detector else ""],
            },
        )
        seq_features.append(feat)

    for cds in cdss:
        protein = cds.protein
        gene_caller_name = cds.gene_caller.name if cds.gene_caller else "Unknown"

        pfam_json: List[dict] = []
        for hit in getattr(protein, "domain_hits", []):
            pfam_json.append(
                {
                    "PFAM": hit.domain.acc,
                    "envelope_start": hit.start_position,
                    "envelope_end": hit.end_position,
                }
            )

        cds_start = _crop(cds.start_position, window_start, window_end)
        cds_end = _crop(cds.end_position, window_start, window_end)
        cds_rel_start, cds_rel_end = cds_start - window_start, cds_end - window_start

        # Store CDS metadata in qualifiers directly
        cds_feat = SeqFeature(
            FeatureLocation(cds_rel_start, cds_rel_end, strand=cds.strand),
            type="CDS",
            qualifiers={
                "source": [gene_caller_name],
                "ID": [
                    protein.mgyp
                    or f"{contig_accession}_{cds.start_position}_{cds.end_position}"
                ],
                "cluster_representative": [protein.cluster_representative or ""],
                "mgyp": [protein.mgyp or ""],
                "translation": [protein.sequence or ""],
                "gene_caller": [gene_caller_name],
            },
        )
        seq_features.append(cds_feat)

        for dom_hit in getattr(protein, "domain_hits", []):
            nt_abs_start = cds.start_position + dom_hit.start_position * 3
            nt_abs_end = cds.start_position + dom_hit.end_position * 3

            _d_start = _crop(nt_abs_start, window_start, window_end)
            _d_end = _crop(nt_abs_end, window_start, window_end)
            d_rel_start, d_rel_end = _d_start - window_start, _d_end - window_start

            dom_acc = dom_hit.domain.acc
            # Store domain annotation metadata in qualifiers directly
            dom_feat = SeqFeature(
                FeatureLocation(d_rel_start, d_rel_end, strand=cds.strand),
                type="ANNOT",
                qualifiers={
                    "source": [dom_hit.domain.ref_db or "Domain"],
                    "score": [str(dom_hit.score) if dom_hit.score is not None else ""],
                    "ID": [dom_acc],
                    "GOslim": pfamToGoSlim.get(dom_acc, []),
                    "description": [
                        dom_hit.domain.description or "Domain of Unknown Function"
                    ],
                },
            )
            seq_features.append(dom_feat)

    # Build EnhancedSeqRecord
    contig_seq_str = contig.sequence or ""
    region_seq = contig_seq_str[window_start:window_end]

    record = EnhancedSeqRecord(
        Seq(region_seq),
        id=contig_accession,
        name=contig_accession,
        description=f"Region {window_start}-{window_end} on {contig_accession} (BGC {aggregated_bgc.accession})",
    )
    record.features.extend(seq_features)
    source_annotations = {
        "contig_accession": contig_accession,
        "assembly_accession": assembly_accession or "",
        "biome_lineage": biome_lineage or "",
        "bgc_accession": aggregated_bgc.accession,
        "bgc_pk": int(aggregated_bgc.id),
        # absolute window bounds on the contig sequence
        "start_position": start_position + 1,
        "end_position": end_position,
        # aggregated region bounds relative to the window (used in summary)
    }
    record.annotations["source"] = json.dumps(source_annotations)
    # Biopython GenBank writer requires 'molecule_type' in annotations
    # Default to DNA for nucleotide sequences
    if "molecule_type" not in record.annotations:
        record.annotations["molecule_type"] = "DNA"
    return record
