from ninja import Schema
from typing import Optional, List, Set, Any, Tuple
from enum import Enum
from .models import BgcDetector
from ninja import Schema, Field
from typing import List, Optional
from pydantic import conlist

    
class BgcSearchInputSchema(Schema):
    pass

class BgcSearchOutputSchema(Schema):
    pass

class BgcSearchOutput(Schema):
    mgybs: List[str]
    assembly_accession: str
    contig_mgyc: str
    start_position: int
    end_position: int
    bgc_detector_names: List[str]
    bgc_class_names: List[str]

class AdvancedSearchInput(Schema):
    bgc_class_name: Optional[str] = Field(
        None, 
        max_length=255,
        title='BGC Class Name',
        description='The BGC Class name is used to classify the biosynthetic gene clusters based on their type.'
    )
    mgyb: Optional[str] = Field(
        None, 
        max_length=255,
        title='BGC Accession',
        description='The BGC Accession is the unique identifier assigned to a biosynthetic gene cluster.'
    )
    assembly_accession: Optional[str] = Field(
        None, 
        max_length=255,
        title='Assembly Accession',
        description='The Assembly accession is the identifier for the assembled sequence from which the BGC was predicted.'
    )
    mgyc: Optional[str] = Field(
        None, 
        max_length=255,
        title='MGYC',
        description='The Contig MGYC is the identifier for the contig that contains the BGC.'
    )
    biome_lineage: Optional[str] = Field(
        None, 
        max_length=255,
        title='Biome Lineage',
        description='The Biome refers to the ecological community where the BGC was found.'
    )
    completeness: Optional[List[int]] = Field(
        None, 
        title='Select Completeness',
        description=(
            'Filter BGCs detected by completeness. '
            '0: `Complete` indicates a BGC prediction fully contained within contig booundaries.'
            '1: `Single bounded` indicates if the BGC is truncated in one contig edge.'
            '2: `Double bounded` indicates if the BGC is truncated in both contig edges.'
        ),
        example=[0, 1, 2]
    )
    protein_pfam: Optional[str] = Field(
        None, 
        max_length=255,
        title='Pfam',
        description='Enter one or more Pfam accession separated by comma or space. Pfam is a database of protein families, each represented by multiple sequence alignments and hidden Markov models (HMMs).',
    )
    pfam_strategy: Optional[str] = Field(
        'intersection', 
        title='Pfam Strategy',
        description='Choose "AND" to include BGCs that match all Pfams, or "OR" to include BGCs that match any Pfam.',
        enum=['intersection', 'union']
    )
    detectors: Optional[List[str]] = Field(
        None, 
        title='BGC Detectors',
        description='Filter BGCs detected by the selected detectors.',
        example=['antiSMASH', 'GECCO', 'SanntiS']
    )
    aggregate_strategy: Optional[str] = Field(
        'single', 
        title='Aggregate Strategy',
        description='Select the aggregate strategy for how results should be combined. See `Documentation` for detailed information',
        enum=['single', 'union', 'intersection']
    )

class GetContigRegionInput(Schema):
    mgyc: str = Field(
        None,
        title="Contig MGYC",
        description="The identifier for the contig that contains the BGC.",
        example='MGYC001221489635'
    )
    start_position: int = Field(
        None,
        title="Start Position",
        description="The start position of the sequence."
    )
    end_position: int = Field(
        None,
        title="End Position",
        description="The end position of the sequence."
    )
    output_type: str = Field(
        'fasta',
        title="Output Type",
        description="The output format type for the result.",
        enum=['fasta', 'gbk', 'json'],
    )



class GetContigRegionVisualisationInput(Schema):
    mgyc: str = Field(
        None,
        title="Contig MGYC",
        description="The identifier for the contig that contains the BGC.",
        example='MGYC001221489635'
    )
    start_position: int = Field(
        None,
        title="Start Position",
        description="The start position of the sequence."
    )
    end_position: int = Field(
        None,
        title="End Position",
        description="The end position of the sequence."
    )