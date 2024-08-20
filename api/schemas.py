from ninja import Schema
from typing import Optional, List, Set
from enum import Enum
from .models import BgcDetector


class PfamStrategy(Enum):
    union: str = 'union'
    intersection: str = 'intersection'
    
class Aggregate(Enum):
    single: str = 'single'
    union: str = 'union'
    intersection: str = 'intersection'
    
class OutputType(Enum):
    genbank: str = 'gbk'
    json: str = 'json'
    fasta: str = 'fasta'

class BgcSearchCallSchema(Schema):
    antismash: Optional[bool] = True
    gecco: Optional[bool] = True
    sanntis: Optional[bool] = True
    mgyb: Optional[str] = None
    bgc_class_name: Optional[str] = None
    assembly_accession: Optional[str] = None
    biome_lineage: Optional[str] = None
    contig_mgyc: Optional[str] = None
    start_position: Optional[int] = None
    end_position: Optional[int] = None
    full_length: Optional[bool] = True
    single_truncated: Optional[bool] = True
    double_truncated: Optional[bool] = True
    protein_pfam: Optional[str] = None
    pfam_strategy: Optional[PfamStrategy] = PfamStrategy.union
    aggregate_strategy: Aggregate = Aggregate.single
    
class BgcSearchInputSchema(Schema):
    mgyb: Optional[int] = None
    assembly_accession: Optional[str] = None
    contig_mgyc: Optional[str] = None
    start_position: Optional[int] = None
    end_position: Optional[int] = None
    bgc_detector_name: Optional[str] = None
    bgc_class_name: Optional[str] = None

class BgcSearchOutputSchema(Schema):
    mgybs: List[int]
    assembly_accession: str
    contig_mgyc: str
    start_position: int
    end_position: int
    bgc_detector_names: List[str]
    bgc_class_names: List[str]

class BgcSearchUserOutputSchema(Schema):
    mgybs: List[int]
    assembly_accession: str
    contig_mgyc: str
    start_position: int
    end_position: int
    bgc_detector_names: List[str]
    bgc_class_names: List[str]
