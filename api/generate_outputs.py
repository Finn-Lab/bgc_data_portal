import io
import json
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from Bio.SeqFeature import SeqFeature, FeatureLocation
from Bio import SeqIO
from bgc_data_portal import __version__,__name__,__description__

class WriteRegion:
    @staticmethod
    def gbk(contig, start_position, end_position,assembly_accession, bgcs, protein_metadata):
        # Create a SeqRecord for the contig sequence
        contig_seq = Seq(contig.sequence[start_position-1:end_position])
        description = (
            f"Nucleotide sequence extracted from "
            f"Assembly: {assembly_accession}, "
            f"Contig: {contig.mgyc}, "
            f"Region: {start_position}-{end_position}, "
            f"Generated using {__name__} version {__version__}."
        )
        record = SeqRecord(
            contig_seq, 
            id=f"{contig.mgyc}:{start_position}-{end_position}", 
            description=description,
            annotations={"molecule_type": "DNA"}
        )

        # Add features for each BGC
        for bgc in bgcs:
            feature = SeqFeature(
                location=FeatureLocation(
                    max(bgc.start_position,start_position), 
                    min(bgc.end_position,end_position)
                    ),
                type="BGC",
                qualifiers={
                    "mgyb": bgc.mgyb,
                    "bgc_class": bgc.bgc_class.bgc_class_name if bgc.bgc_class else "Unknown",
                    "bgc_detector": bgc.bgc_detector.bgc_detector_name if bgc.bgc_detector else "Unknown",
                }
            )
            record.features.append(feature)

        # Add features for each protein with strand information
        for meta in protein_metadata:
            protein = meta.mgyp
            meta_start_position = max(meta.start_position,start_position)
            meta_end_position = min(meta.end_position,end_position)
            feature = SeqFeature(
                location=FeatureLocation(
                    meta_start_position, 
                    meta_end_position,
                    strand=meta.strand),
                type="CDS",
                qualifiers={
                    "protein_id": protein.mgyp,
                    "translation": protein.sequence,
                    "pfam": protein.pfam,
                }
            )
            record.features.append(feature)
            pfam_json = json.loads(protein.pfam)
            if type(pfam_json)==list:
                for pfam in json.loads(protein.pfam):
                    pfam_start_postiion = meta.start_position + (pfam.get('envelope_start')*3)
                    pfam_end_position = meta.start_position + (pfam.get('envelope_end')*3)
                    qualifiers = dict(pfam)
                    qualifiers.update({"protein_id": protein.mgyp})
                    feature = SeqFeature(
                        location=FeatureLocation(pfam_start_postiion, pfam_end_position, strand=meta.strand),
                        type="PFAM",
                        qualifiers=qualifiers
                    )

            record.features.append(feature)

        # Create a file-like object to store the GenBank data
        genbank_io = io.StringIO()
        SeqIO.write(record, genbank_io, "genbank")
        genbank_data = genbank_io.getvalue()
        genbank_io.close()

        return genbank_data

    @staticmethod
    def json(contig, start_position, end_position,assembly_accession, bgcs, protein_metadata):
        """
        Generate an output follwing the antiSMASH JSON format dor sideloading
        """
        
        tool_info = {
            "name": __name__,
            "version": __version__,
            "description": f"{__description__} This subregion was created using the portal module to generate JSON files for antiSMASH sideloading.",
        }

        # Consolidate BGC details
        contig_description = (
            f"Nucleotide sequence extracted from "
            f"Assembly: {assembly_accession}, "
            f"Contig: {contig.mgyc}, "
            f"Region: {start_position}-{end_position}, "
            f"Generated using {__name__} version {__version__}."
        )
        details = {'Detected BGCs':[],'Sequence description':"".join(contig_description)}
        for bgc in bgcs:
            bgc_key_prefix = f"bgc_{bgc.mgyb}"
            mgyb = bgc.mgyb
            detector = bgc.bgc_detector.bgc_detector_name if bgc.bgc_detector else "Unknown"
            detector_version = bgc.bgc_detector.version if bgc.bgc_detector else "Unknown"
            bgc_class = bgc.bgc_class.bgc_class_name if bgc.bgc_class else "Unknown"
            start_position = str(max(bgc.start_position,start_position))
            end_position = str(min(bgc.end_position,end_position))
            details["Detected BGCs"].append(
                f"Accession: {mgyb};Start {start_position}; End: {end_position}; Detector: {detector}v{detector_version};Class: {bgc_class}; "
            )
        # Prepare the single subregion with consolidated details
        subregion = {
            "start": start_position,
            "end": end_position,
            "label": f"{contig.mgyc}:{start_position}-{end_position}",
            "details": details
        }

        # Prepare the record information with only one subregion
        record_info = {
            "name": contig.mgyc,
            "subregions": [subregion],
            "protoclusters": []  # Assuming no protoclusters for this example; fill in if needed
        }

        # Combine tool and record information
        output_data = {
            "tool": tool_info,
            "record": record_info
        }

        output_content = json.dumps(output_data, indent=4)
        return output_content
    
    @staticmethod
    def fasta(contig, start_position, end_position,assembly_accession, bgcs, protein_metadata):
        # Extract the nucleotide sequence for the specified region
        sequence_region = contig.sequence[start_position-1:end_position]  # Adjust for 0-based index

        # Create a description for the FASTA header
        description = (
            f"Nucleotide sequence extracted from "
            f"Assembly: {assembly_accession}, "
            f"Contig: {contig.mgyc}, "
            f"Region: {start_position}-{end_position}, "
            f"Generated using {__name__} version {__version__}."
        )

        # Create a SeqRecord for the FASTA file
        seq_record = SeqRecord(
            Seq(sequence_region),
            id=f"{contig.mgyc}:{start_position}-{end_position}",
            description=description
        )

        # Create a file-like object to store the FASTA data
        fasta_io = io.StringIO()
        SeqIO.write(seq_record, fasta_io, "fasta")
        fasta_data = fasta_io.getvalue()
        fasta_io.close()

        return fasta_data