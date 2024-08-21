
from functools import reduce
import operator

from api.schemas import PfamStrategy
from .models import Bgc, BgcClass, BgcDetector, Contig, Assembly, Biome, Protein, Metadata
from typing import List, Optional,Union
from django.db.models import Q,F
import re


class RegionFeatureError(Exception):
    """Custom exception for errors related to region features."""
    pass


def search_keyword_in_models(keyword: str):
    # Build a Q object for filtering BGC based on its own fields
    bgc_query = Q(
        Q(bgc_metadata__icontains=keyword)
    )

    if keyword.startswith("MGYB") and keyword[4:].isdigit():
        bgc_query |= Q(Q(mgyb=int(keyword[4:])))
    
    # Filter Contig by the keyword in its fields
    contig_query = Q(
        Q(mgyc=keyword) 
    )

    # Include related Assembly and Biome fields in the search
    contig_query |= Q(
        Q(assembly__accession__icontains=keyword) |
        Q(assembly__study__accession__icontains=keyword) |
        Q(assembly__biome__lineage__icontains=keyword)
    )

    # Find matching contigs
    matching_contigs = Contig.objects.filter(contig_query)
    
    # Get BGCs associated with the matching contigs
    mgybs_from_contigs = Bgc.objects.filter(mgyc__in=matching_contigs).values_list('mgyb', flat=True)

    # Find proteins matching the keyword
    matching_proteins = Protein.objects.filter(
        Q(pfam__icontains=keyword)
    )

    # Get Metadata that matches the keyword and check positional overlap
    matching_metadata = Metadata.objects.filter(
        Q(mgyp__in=matching_proteins) 
    )

    # Get BGCs that overlap with the matching proteins/metadata on the same contig
    mgybs_from_protein_metadata = Bgc.objects.filter(
        Q(mgyc__metadata__in=matching_metadata) &
        Q(start_position__lte=F('mgyc__metadata__end_position')) &
        Q(end_position__gte=F('mgyc__metadata__start_position'))
    ).values_list('mgyb', flat=True)

    # Combine all found BGC ids
    mgybs = set(mgybs_from_contigs) | set(mgybs_from_protein_metadata) | set(Bgc.objects.filter(bgc_query).values_list('mgyb', flat=True))

    return mgybs

def complex_bgc_search(
              _detectors : Optional[list] = None,
              _bgc_class_name: Optional[str] = None, 
              _mgyb: Optional[str] = None, 
              _assembly_accession: Optional[str] = None, 
              _contig_mgyc: Optional[str] = None, 
              _complete: bool = True, # TODO, FUNCTION WRITEN BUT NEEDS DB MODEL AND POPULATE
              _single_truncated: bool = True, 
              _double_truncated: bool = True, 
              _biome_lineage: Optional[str] = None, 
            #   _keyword: Optional[str] = None, 
              _protein_pfam: list = None, # TODO
              _pfam_strategy: Optional[str] = None # TODO
              ):

    try: 
        qs = Bgc.objects.select_related('bgc_detector', 'bgc_class', 'mgyc__assembly__biome').all()

        if _detectors:
            qs = qs.filter(Q(bgc_detector__bgc_detector_name__in=_detectors))
        
        if _bgc_class_name:
            qs = qs.filter(bgc_class__bgc_class_name__icontains=_bgc_class_name)
        
        if _mgyb:
            qs = qs.filter(mgyb=_mgyb)
        
        if _assembly_accession:
            qs = qs.filter(mgyc__assembly__accession=_assembly_accession)
        
        if _contig_mgyc:
            qs = qs.filter(mgyc__mgyc=_contig_mgyc)
        
        if _biome_lineage:
            qs = qs.filter(mgyc__assembly__biome__lineage__icontains=_biome_lineage)

        # TODO
        """
        partials = [name for name,value in zip(_partials,[full_length,single_truncated,double_truncated]) if value!=False]    
        if partials:
            qs = qs.filter(Q(partial__partial_name__in=partials))
        """

        
        if _protein_pfam:
            # Define the Pfam queries
            pfam_queries = [
                Q(
                    mgyc__metadata__protein__pfam__icontains=pfam,
                    mgyc__metadata__start_position__lte=F('end_position'),  # Metadata start is before or at BGC end
                    mgyc__metadata__end_position__gte=F('start_position')   # Metadata end is after or at BGC start
                )
                for pfam in _protein_pfam
            ]

            # Combine the queries using the specified strategy
            if _pfam_strategy == PfamStrategy.intersection:
                qs = qs.filter(reduce(operator.and_, pfam_queries))
            elif _pfam_strategy == PfamStrategy.union:
                qs = qs.filter(reduce(operator.or_, pfam_queries))
    except Exception as e:
        print(e)

    return qs


# def complex_bgc_search(
#               _detectors : Optional[list] = None,
#               _bgc_class_name: Optional[str] = None, 
#               _mgyb: Optional[str] = None, 
#               _assembly_accession: Optional[str] = None, 
#               _contig_mgyc: Optional[str] = None, 
#               _complete: bool = True, # TODO, FUNCTION WRITEN BUT NEEDS DB MODEL AND POPULATE
#               _single_truncated: bool = True, 
#               _double_truncated: bool = True, 
#               _biome_lineage: Optional[str] = None, 
#             #   _keyword: Optional[str] = None, 
#               _protein_pfam: str = None, # TODO
#               _pfam_strategy: Optional[str] = None # TODO
#               ):

#     qs = Bgc.objects.select_related('bgc_detector', 'bgc_class', 'mgyc__assembly__biome').all()

#     if _detectors:
#         qs = qs.filter(Q(bgc_detector__bgc_detector_name__in=_detectors))
    
#     if _bgc_class_name:
#         qs = qs.filter(bgc_class__bgc_class_name__icontains=_bgc_class_name)
    
#     if _mgyb:
#         qs = qs.filter(mgyb__icontains=_mgyb)
    
#     if _assembly_accession:
#         qs = qs.filter(mgyc__assembly__accession__icontains=_assembly_accession)
    
#     if _contig_mgyc:
#         qs = qs.filter(mgyc__mgyc__icontains=_contig_mgyc)
    

#     # TODO
#     """
#     partials = [name for name,value in zip(_partials,[full_length,single_truncated,double_truncated]) if value!=False]    
#     if partials:
#         qs = qs.filter(Q(partial__partial_name__in=partials))
#     """

#     if _biome_lineage:
#         qs = qs.filter(mgyc__assembly__biome__lineage__icontains=_biome_lineage)
    
#     if _protein_pfam:
        
#         pfam_queries = [Q(mgyc__metadata__protein__pfam__icontains=pfam) for pfam in _protein_pfam]

#         if pfam_strategy == 'AND':
#             qs = qs.filter(reduce(operator.and_, pfam_queries))
#         elif pfam_strategy == 'OR':
#             qs = qs.filter(reduce(operator.or_, pfam_queries))

#         # qs = qs.filter(mgyc__metadata__protein__pfam__icontains=_protein_pfam)

#     return qs


def get_region_features( 
              mgyc: str = None, 
              start_position: int = None, 
              end_position: int = None,
    ):

    try:
        # Query the database to get the contig and associated assembly
        contig = Contig.objects.get(pk=mgyc)
    except Contig.DoesNotExist:
        raise RegionFeatureError(f"No Contig matches the given query for MGYC: {mgyc}")

    assembly_accession = contig.assembly.accession

    # Retrieve BGCs that are within or partially overlap with the specified region
    bgcs = Bgc.objects.filter(
        mgyc=mgyc,
        start_position__lte=end_position,
        end_position__gte=start_position
    )

    # Retrieve proteins within or partially overlapping the specified region
    protein_metadata = Metadata.objects.filter(
        mgyc=mgyc,
        start_position__lte=end_position,
        end_position__gte=start_position
    ).select_related('mgyp')

    return contig,assembly_accession,bgcs,protein_metadata