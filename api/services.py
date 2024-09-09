import operator
import re
from django.db.models import Q, F
from functools import reduce
from operator import and_, or_
from .models import Bgc
from .filters import BgcKeywordFilter, MgybConverterFilter
from .models import Bgc
from .utils import mgyb_converter
from .aggregate_bgcs import BgcAggregator

def search_bgcs_by_keyword(keyword):
    # Initialize the filter with the keyword
    bgc_filter = BgcKeywordFilter({'keyword': keyword}, queryset=Bgc.objects.all())
    results = bgc_filter.qs

    # Convert the mgyb integers back to the "MGYB{:012}" format for display
    for bgc in results:
        mgyb_converted= mgyb_converter(bgc.mgyb,text_to_int=False)
        bgc.mgybs = [mgyb_converted]
        bgc.bgc_detector_names = [bgc.bgc_detector.bgc_detector_name]
        bgc.bgc_class_names = bgc.bgc_class.bgc_class_name.split(',')
    return results

def search_bgcs_by_advanced(criteria):
    """
    Get BGC queryset based on advanced search criteria.
    """


    qs = Bgc.objects.select_related('bgc_detector', 'bgc_class', 'mgyc__assembly__biome').all()

    qs = qs.filter(Q(bgc_detector__bgc_detector_name__in=criteria.get('detectors')))
    
    if criteria.get('bgc_class_name'):
        qs = qs.filter(bgc_class__bgc_class_name__icontains=criteria.get('bgc_class_name'))
    
    if criteria.get('mgyb'):
        qs = MgybConverterFilter(field_name='mgyb').filter(qs, criteria.get('mgyb')) 
    
    if criteria.get('assembly_accession'):
        qs = qs.filter(mgyc__assembly__accession=criteria.get('assembly_accession'))
    
    if criteria.get('mgyc'):
        qs = qs.filter(mgyc__mgyc=criteria.get('mgyc'))
    
    if criteria.get('biome_lineage'):
        qs = qs.filter(mgyc__assembly__biome__lineage__icontains=criteria.get('biome_lineage'))

    # TODO
    """
    # if criteria.get('completeness'):
        qs = qs.filter(Q(partial__partial_name__in=criteria.get('completeness')))
    """

    
    if criteria.get('pfam'):
        # Define the Pfam queries
        pfam_queries = [
            Q(
                mgyc__metadata__protein__pfam__icontains=pfam,
                mgyc__metadata__start_position__lte=F('end_position'),  # Metadata start is before or at BGC end
                mgyc__metadata__end_position__gte=F('start_position')   # Metadata end is after or at BGC start
            )
            for pfam in [_pfam.strip() for _pfam in re.split("[, ]",criteria.get('pfam'))]
        ]

        # Combine the queries using the specified strategy
        if criteria.get('pfam_strategy') =='intersection':
            qs = qs.filter(reduce(operator.and_, pfam_queries))
        elif criteria.get('pfam_strategy') == 'union':
            qs = qs.filter(reduce(operator.or_, pfam_queries))
            
    # Transform mgyb field
        # Convert the mgyb integers back to the "MGYB{:012}" format for display
    for bgc in qs:
        mgyb_converted= mgyb_converter(bgc.mgyb,text_to_int=False)
        bgc.mgybs = [mgyb_converted]
        bgc.bgc_detector_names = [bgc.bgc_detector.bgc_detector_name]
        bgc.bgc_class_names = bgc.bgc_class.bgc_class_name.split(',')

    aggregate_function = getattr(BgcAggregator,criteria.get('aggregate_strategy'))
    print('AGGREGATED ',len(aggregate_function))
    
    return aggregate_function(qs,n_detectors=len(criteria.get('detectors')))

