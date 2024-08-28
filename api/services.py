from django.db.models import Q, F
from functools import reduce
from operator import and_, or_
from .models import Bgc
from .filters import BgcFilter,BgcKeywordFilter
from .models import Bgc
from .utils import mgyb_converter

def search_bgcs_by_keyword(keyword):
    # Initialize the filter with the keyword
    bgc_filter = BgcKeywordFilter({'keyword': keyword}, queryset=Bgc.objects.all())
    results = bgc_filter.qs

    # Convert the mgyb integers back to the "MGYB{:012}" format for display
    for bgc in results:
        mgyb_converted= mgyb_converter(bgc.mgyb,text_to_int=False)
        bgc.mgybs = [mgyb_converted]
        bgc.bgc_detector_names = [bgc.bgc_detector.bgc_detector_name]
        bgc.bgc_class_names = [bgc.bgc_class.bgc_class_name]
    return results

def search_bgcs_by_advanced(criteria):


    """
    Get BGC queryset based on advanced search criteria.
    """
    # Initial queryset with necessary select_related to optimize queries
    qs = Bgc.objects.select_related('bgc_detector', 'bgc_class', 'mgyc__assembly__biome').all()

    # Apply Django Filter
    filter_set = BgcFilter(criteria, queryset=qs)
    qs = filter_set.qs

    # Process additional criteria not covered by BgcFilter
    detectors = criteria.get('detectors',[])
    if detectors:
        qs = qs.filter(bgc_detector__bgc_detector_name__in=detectors)

    partials = criteria.get('completeness',[])
    if partials:
        qs = qs.filter(partial__in=partials)

    # Pfam filtering logic
    pfam = criteria.get('protein_pfam')
    pfam_strategy = criteria.get('pfam_strategy', 'intersection')
    if pfam:
        pfam_queries = [
            Q(
                mgyc__metadata__protein__pfam__icontains=pfam_item,
                mgyc__metadata__start_position__lte=F('end_position'),
                mgyc__metadata__end_position__gte=F('start_position')
            )
            for pfam_item in pfam.split(',')  # Assuming multiple pfams are comma-separated
        ]

        if pfam_queries:
            if pfam_strategy == 'intersection':
                qs = qs.filter(reduce(and_, pfam_queries))
            elif pfam_strategy == 'union':
                qs = qs.filter(reduce(or_, pfam_queries))

    # Transform mgyb field
        # Convert the mgyb integers back to the "MGYB{:012}" format for display
    for bgc in qs:
        mgyb_converted= mgyb_converter(bgc.mgyb,text_to_int=False)
        bgc.mgybs = [mgyb_converted]
        bgc.bgc_detector_names = [bgc.bgc_detector.bgc_detector_name]
        bgc.bgc_class_names = [bgc.bgc_class.bgc_class_name]
    return qs
