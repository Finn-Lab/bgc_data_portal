import django_filters
from django.db.models import Q, F
from functools import reduce
from operator import and_, or_
from .models import Bgc, Contig, Protein, Metadata
import django_filters
from django.db.models import Q, F
from .models import Bgc, Contig, Protein, Metadata
from .utils import mgyb_converter
import django_filters
from django.db.models import Q, F
from functools import reduce
from operator import and_, or_
from .models import Bgc

class MgybConverterFilter(django_filters.CharFilter):
    def filter(self, qs, value):
        # Check if the value starts with "MGYB" and the rest are digits
        if value and value.startswith("MGYB") and value[4:].isdigit():
            # Convert the value using mgyb_converter
            value = mgyb_converter(value, text_to_int=True)
            if value is not None:
                # Apply the converted value to the queryset
                return super().filter(qs, value)
        # If value is not valid, return an empty queryset
        return qs.none()
    
class BgcKeywordFilter(django_filters.FilterSet):

    @staticmethod
    def filter_by_keyword(queryset, name, value):
        # Build the BGC query
        bgc_query = Q(bgc_detector__bgc_detector_name__icontains=value)
        bgc_query |= Q(bgc_metadata__icontains=value)
        # print(len(queryset.filter(bgc_query).values_list('mgyb', flat=True).all()))
        
        mgyb_filtered_qs = MgybConverterFilter(field_name='mgyb').filter(queryset, value)       
        # Filter Contig by the keyword
        contig_query = Q(mgyc=value)
        contig_query |= Q(
            Q(assembly__accession=value) |
            Q(assembly__study__accession=value) |
            Q(assembly__biome__lineage__icontains=value)
        )
        
        # Find matching contigs
        matching_contigs = Contig.objects.filter(contig_query)
        mgybs_from_contigs = Bgc.objects.filter(mgyc__in=matching_contigs).values_list('mgyb', flat=True)
        
        # Find proteins matching the keyword
        matching_proteins = Protein.objects.filter(
            Q(pfam__icontains=value) | Q(mgyp=value)
            )
        matching_metadata = Metadata.objects.filter(mgyp__in=matching_proteins)
        
        # BGCs that overlap with proteins/metadata on the same contig
        mgybs_from_protein_metadata = Bgc.objects.filter(
            Q(mgyc__metadata__in=matching_metadata) &
            Q(start_position__lte=F('mgyc__metadata__end_position')) &
            Q(end_position__gte=F('mgyc__metadata__start_position'))
        ).values_list('mgyb', flat=True)
        
        print(len(queryset.filter(mgyb__in=set(mgybs_from_protein_metadata) ).all()))
        # Combine all found BGC ids
        print(len(queryset.filter(mgyb__in=set(mgybs_from_contigs) | set(mgybs_from_protein_metadata) | set(queryset.filter(bgc_query).values_list('mgyb', flat=True)) | set(mgyb_filtered_qs.values_list('mgyb', flat=True))).all()))
        combined_mgybs = set(mgybs_from_contigs) | set(mgybs_from_protein_metadata) | set(queryset.filter(bgc_query).values_list('mgyb', flat=True)) | set(mgyb_filtered_qs.values_list('mgyb', flat=True))
        return queryset.filter(mgyb__in=combined_mgybs)

    keyword = django_filters.CharFilter(method='filter_by_keyword')

    class Meta:
        model = Bgc
        fields = []


class BgcFilter(django_filters.FilterSet):
    bgc_class_name = django_filters.CharFilter(field_name='bgc_class__bgc_class_name', lookup_expr='icontains')
    mgyb = MgybConverterFilter(field_name='mgyb', lookup_expr='exact')
    assembly_accession = django_filters.CharFilter(field_name='mgyc__assembly__accession', lookup_expr='exact')
    mgyc = django_filters.CharFilter(field_name='mgyc__mgyc', lookup_expr='exact')
    biome_lineage = django_filters.CharFilter(field_name='mgyc__assembly__biome__lineage', lookup_expr='icontains')

    # Add detectors filter using MultipleChoiceFilter with a custom method
    detectors = django_filters.MultipleChoiceFilter(
        choices= [
            ('antismash', 'antiSMASH'),
            ('gecco', 'GECCO'),
            ('sanntis', 'SanntiS'),
        ],
        method='filter_by_detectors',
        label='Select Detectors'
    )

    # Add completeness filter
    completeness = django_filters.MultipleChoiceFilter(
        choices=[
            (0, 'Full-Length'),  # Assuming full_length corresponds to 0
            (1, 'Single-Truncated'),
            (2, 'Double-Truncated'),
        ],
        method='filter_by_completeness',
        label='Select Completeness'
    )

    # Add Pfam filter with custom method to handle strategy
    protein_pfam = django_filters.CharFilter(
        method='filter_by_protein_pfam',
        label='Protein Pfam'
    )

    pfam_strategy = django_filters.ChoiceFilter(
        choices=[('intersection', 'AND'), ('union', 'OR')],
        method='filter_by_protein_pfam',
        label='Pfam Strategy',
        initial='intersection'
    )

    class Meta:
        model = Bgc
        fields = [
            'bgc_class_name', 'mgyb', 'assembly_accession', 'mgyc', 
            'biome_lineage', 'detectors', 'completeness', 'protein_pfam', 'pfam_strategy'
        ]

    def filter_by_detectors(self, queryset, name, value):
        """
        Custom filter method to filter queryset by selected detectors.
        """
        if value:
            queryset = queryset.filter(bgc_detector__bgc_detector_name__in=value)
        return queryset

    def filter_by_completeness(self, queryset, name, value):
        """
        Custom filter method to filter queryset by completeness.
        """
        if value:
            queryset = queryset.filter(partial__in=value)
        return queryset

    def filter_by_protein_pfam(self, queryset, name, value):
        """
        Custom filter method to filter queryset by protein Pfam and strategy.
        """
        pfam = self.data.get('protein_pfam', '')
        pfam_strategy = self.data.get('pfam_strategy', 'intersection')
        
        if pfam:
            # Define the Pfam queries
            pfam_queries = [
                Q(
                    mgyc__metadata__protein__pfam__icontains=pfam_item,
                    mgyc__metadata__start_position__lte=F('end_position'),  # Metadata start is before or at BGC end
                    mgyc__metadata__end_position__gte=F('start_position')   # Metadata end is after or at BGC start
                )
                for pfam_item in pfam.split(',')  # Assuming multiple pfams are comma-separated
            ]

            # Combine the queries using the specified strategy
            if pfam_queries:
                if pfam_strategy == 'intersection':
                    queryset = queryset.filter(reduce(and_, pfam_queries))
                elif pfam_strategy == 'union':
                    queryset = queryset.filter(reduce(or_, pfam_queries))

        return queryset