import io
import logging
from typing import Optional

from Bio import SeqIO
from Bio.SeqRecord import SeqRecord
from Bio.SeqFeature import SeqFeature, FeatureLocation
import re
from Bio.Seq import Seq
from Bio.Data import CodonTable

import pyrodigal
from ..utils.lazy_loaders import protein_embedder, umap_model

# Configure logger for the module
log = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)


def detect_format_from_string(data) -> str:
    """
    Detect if the given string is in FASTA or GenBank format.

    Returns:
        'fasta', 'genbank', or 'unknown'
    """

    for line in data:
        line = line.strip()
        if line.startswith(">"):
            return "fasta"
        elif line.startswith("LOCUS") or line.startswith("DEFINITION"):
            return "gbk"
        elif not line:
            continue
    return "unknown"


class SeqAnnotator:
    """
    Annotates nucleotide sequences from FASTA (.fna/.fa) or GenBank (.gbk) files.
    For FASTA inputs, genes are predicted with pyrodigal; for GenBank, existing CDS
    features are used. Protein sequences are transformed via the protain_embeddings module,
    and embeddings are attached as qualifiers to each CDS feature.
    """

    def __init__(self):
        """
        Initialize the annotator.

        :param gene_finder: Optional pyrodigal.GeneFinder instance. If None,
                            a default meta-aware finder is created.
        """
        self.gene_finder = pyrodigal.GeneFinder(meta=True)

    def annotate_sequence_file(
        self,
        file_string: str,
        molecule_type: Optional[str] = None,
        unit_of_comparison=str,
        similarity_measure=str,
    ) -> SeqRecord:
        """
        Main entry point: load and annotate a sequence file.

        :param input_path: Path to a .gbk, .fa, .fna, or .fasta file.
        :return: Annotated Biopython SeqRecord.

        :raises ValueError: If file format is unsupported or parsing fails.
        """
        normalized_file_string = file_string.replace("\r\n", "\n").replace("\r", "\n")

        # Step 2: Ensure final newline
        if not normalized_file_string.endswith("\n"):
            normalized_file_string += "\n"

        fasta_io = io.StringIO(normalized_file_string)

        fasta_io.seek(0)  # Reset the StringIO object to the beginning
        fmt = detect_format_from_string(fasta_io)
        log.info("Detected format '%s'", fmt)

        fasta_io.seek(0)
        if fmt == "gbk":
            record = self._load_genbank(fasta_io)
        elif fmt == "fasta" or fmt == None:
            record = self._load_fasta(fasta_io, mol_type=molecule_type)
        else:
            raise ValueError(f"Unsupported format: {fmt}")

        annotated_record = self._annotate_record(record)

        log.info("Annotation complete for record: %s", record.id)
        return annotated_record

    def _annotate_record(self, record: SeqRecord) -> SeqRecord:
        """
        Annotate protein sequences in a SeqRecord with embeddings.
        This method is called internally after loading the record.
        """
        protein_seqs = {
            ix: feature.qualifiers["translation"][0]
            for ix, feature in enumerate(record.features)
            if feature.type == "CDS" and "translation" in feature.qualifiers
        }

        if not protein_seqs:
            log.warning(
                "No protein sequences found in record %s. Skipping embedding.",
                record.id,
            )
            return record

        embedder = protein_embedder()

        embeddings, bgc_embedding = embedder.embed_gene_cluster(
            protein_sequences=protein_seqs.values()
        )

        for ix, embedding in zip(protein_seqs.keys(), embeddings):
            feature = record.features[ix]
            if feature.type == "CDS":
                # Add embedding as a qualifier
                feature.qualifiers["embedding"] = [embedding]

        record.annotations["bgc_embedding"] = bgc_embedding

        umap = umap_model()
        umap_coords = umap.transform([bgc_embedding])
        record.annotations["umap_x_coord"] = umap_coords[0][0]
        record.annotations["umap_y_coord"] = umap_coords[0][1]

        return record

    def _load_genbank(self, fasta_io: str) -> SeqRecord:
        """
        Load and annotate a GenBank file. Existing CDS features with translations
        are enriched with protein embeddings.
        """
        return SeqIO.read(fasta_io, "genbank")

    def _load_fasta(
        self, fasta_io, mol_type=None, unit_of_comparison=None
    ) -> SeqRecord:
        """
        Load and annotate a FASTA file.
        If the sequence is nucleotide, genes are predicted via pyrodigal.
        If the sequence is protein, it creates a single CDS with optional back-translated nucleotide sequence.
        """
        record = SeqIO.read(fasta_io, "fasta")
        sequence = str(record.seq).upper()

        is_nucleotide = re.fullmatch(r"[ACGTUNWSMKRYBDHV]+", sequence) is not None

        if is_nucleotide and (mol_type is None or mol_type == "nucleotide"):
            seq_bytes = bytes(record.seq)
            for idx, pred in enumerate(self.gene_finder.find_genes(seq_bytes), start=1):
                prot_seq = pred.translate()
                start = int(pred.begin)
                end = int(pred.end)
                strand = pred.strand
                location = FeatureLocation(start, end, strand=strand)
                qualifiers = {
                    "locus_tag": [f"{record.id}_{idx}"],
                    "protein_id": [f"{record.id}_{idx}"],
                    "translation": [prot_seq],
                }
                feature = SeqFeature(
                    location=location, type="CDS", qualifiers=qualifiers
                )
                record.features.append(feature)
        else:
            log.debug("Detected protein sequence in record %s", record.id)
            # Attempt to back-translate using default codon usage (ambiguous)
            protein_seq = record.seq
            try:
                # Use standard codon table for back-translation (this is not unique)
                codon_table = CodonTable.unambiguous_dna_by_name["Standard"]
                back_translated = Seq(
                    "".join(codon_table.back_table.get(aa, "NNN") for aa in protein_seq)
                )
            except Exception as e:
                log.warning("Failed back-translation for %s: %s", record.id, e)
                back_translated = Seq("N" * (len(protein_seq) * 3))

            # Replace the original protein sequence with synthesized nucleotide sequence
            record.seq = back_translated

            location = FeatureLocation(0, len(back_translated), strand=1)
            qualifiers = {
                "locus_tag": [f"{record.id}_1"],
                "protein_id": [f"{record.id}_1"],
                "translation": [str(protein_seq)],
            }
            feature = SeqFeature(location=location, type="CDS", qualifiers=qualifiers)
            record.features.append(feature)
            log.debug("Annotated protein sequence as CDS in record %s", record.id)

        return record
