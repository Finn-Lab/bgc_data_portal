import operator
import re
from functools import reduce

from django.db.models import Q, F, Value, TextField
from django.db.models.functions import Concat
from django.db import models
import pandas as pd
from django.core.cache import cache


from .aggregate_bgcs import BgcAggregator
from .filters import BgcKeywordFilter, MgybConverterFilter
from .models import Bgc, BgcClass, BgcDetector
from .utils import mgyb_converter, process_bgc_results
import pandas as pd
from django.core.cache import cache
from urllib.parse import parse_qs, urlencode

from .forms import BgcAdvancedSearchForm
from .utils import class_counter
from bgc_data_portal.settings import CACHE_TIMEOUT



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



def get_results_and_stats(pageless_query_params, sort_column=None, sort_order='asc'):
    """
    Retrieves or computes the results DataFrame and stats based on the given query parameters.

    Args:
        pageless_query_params (dict): Query parameters used to filter the data.
        sort_column (str, optional): Column name to sort the DataFrame by.
        sort_order (str, optional): Sorting order, either 'asc' for ascending or 'desc' for descending.

    Returns:
        results_df (DataFrame): The resulting DataFrame.
        result_stats (dict): A dictionary containing statistics about the results.
    """
    # Create query string for cache key
    parsed_params = parse_qs(pageless_query_params)
    # Convert lists to single values where applicable
    query_params = {key: value[0] if len(value) == 1 else value for key, value in parsed_params.items()}

    current_advanced_form = BgcAdvancedSearchForm(query_params or None) 
    current_advanced_form = current_advanced_form if current_advanced_form.is_valid() else BgcAdvancedSearchForm()
    # Try to get results from the cache
    results_df, result_stats = cache.get(pageless_query_params, (pd.DataFrame([]), None))

    # If results are not cached, perform the search
    if not result_stats and query_params:
        if query_params.get('keyword'):
            results_df = search_bgcs_by_keyword(query_params.get('keyword'))
        elif current_advanced_form.is_valid():
            results_df = search_bgcs_by_advanced(current_advanced_form.cleaned_data)
        else:
            results_df = pd.DataFrame([])
            current_advanced_form = BgcAdvancedSearchForm()

        # Compute statistics
        result_stats = {
            'total_regions': results_df.shape[0],
            'bgc_class_dist': class_counter(results_df['bgc_class_names']) if not results_df.empty else {},
            'n_assemblies': results_df['assembly_accession'].nunique() if not results_df.empty else 0,
            'n_studies': results_df['study_accession'].nunique() if not results_df.empty else 0,
        }

        # Cache the results
        cache.set(pageless_query_params, (results_df, result_stats), timeout=CACHE_TIMEOUT)

    # Sort the DataFrame if sorting parameters are provided
    if sort_column:
        ascending = sort_order == 'asc'
        results_df = results_df.sort_values(by=sort_column, ascending=ascending)
        cache.set(pageless_query_params, (results_df, result_stats), timeout=CACHE_TIMEOUT)


    return results_df, result_stats,current_advanced_form