import operator
import re
from functools import reduce

from django.db.models import Q, F, Value, TextField
from django.db.models.functions import Concat
from django.db import models
import pandas as pd

from .aggregate_bgcs import BgcAggregator
from .filters import BgcKeywordFilter, MgybConverterFilter
from .models import Bgc, BgcClass, BgcDetector
from .utils import mgyb_converter, process_bgc_results

from tqdm import tqdm

def search_bgcs_by_keyword(keyword):
    """
    Get BGC queryset based on keyword search criteria.
    """
    # Initialize the filter with the keyword
    if not keyword:
        return pd.DataFrame([])
    bgc_filter = BgcKeywordFilter({'keyword': keyword}, queryset=Bgc.objects_with_contigs)
    query_df = process_bgc_results(bgc_filter.qs)
    return query_df

def search_bgcs_by_advanced(criteria):
    """
    Get BGC queryset based on advanced search criteria.
    """
    
    queryset = Bgc.objects.select_related('bgc_detector', 'bgc_class', 'mgyc__assembly__biome').all()

    queryset = queryset.filter(Q(bgc_detector__bgc_detector_name__in=criteria.get('detectors')))
    
    if criteria.get('bgc_class_name'):
        queryset = queryset.filter(bgc_class__bgc_class_name__icontains=criteria.get('bgc_class_name'))
    
    if criteria.get('mgyb'):
        queryset = MgybConverterFilter(field_name='mgyb').filter(queryset, criteria.get('mgyb')) 
    
    if criteria.get('assembly_accession'):
        queryset = queryset.filter(mgyc__assembly__accession=criteria.get('assembly_accession'))
    
    if criteria.get('mgyc'):
        queryset = queryset.filter(mgyc__mgyc=criteria.get('mgyc'))
    
    if criteria.get('biome_lineage'):
        queryset = queryset.filter(mgyc__assembly__biome__lineage__icontains=criteria.get('biome_lineage'))

    if criteria.get('completeness'):
        queryset = queryset.filter(Q(partial__in=map(int,criteria.get('completeness'))))
    
    if criteria.get('protein_pfam'):
        # Define the Pfam queries
        pfam_queries = [
            Q(
                mgyc__metadata__mgyp__pfam__icontains=pfam,
                mgyc__metadata__start_position__lte=F('end_position'),  # Metadata start is before or at BGC end
                mgyc__metadata__end_position__gte=F('start_position')   # Metadata end is after or at BGC start
            )
            for pfam in [_pfam.strip() for _pfam in re.split("[, ]",criteria.get('protein_pfam'))]
        ]

        # Combine the queries using the specified strategy
        if criteria.get('pfam_strategy') =='intersection':
            for _query in pfam_queries:
                queryset = queryset.filter(_query)
        elif criteria.get('pfam_strategy') == 'union':
            queryset = queryset.filter(reduce(operator.or_, pfam_queries))
    
    query_df = process_bgc_results(queryset)
    
    aggregate_function = getattr(BgcAggregator,criteria.get('aggregate_strategy'))
    
    return aggregate_function(query_df,n_detectors=len(criteria.get('detectors')))