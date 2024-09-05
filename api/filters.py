import logging

import django_filters
from django.db.models import Q

from .models import Bgc
from .models import Metadata
from .utils import mgyb_converter


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

        filter_on_mgyb_accession = Q()
        if type(value) is str and value.lower().startswith('mgyb'):
            try:
                mgyb_id = int(value.lower().lstrip('mgyb'))
            except ValueError:
                logging.warning(f"Search keyword looked like an MGYB accession ({value}) but didn't parse as int")
            else:
                filter_on_mgyb_accession = Q(mgyb=mgyb_id)

        filter_on_parent_objects = (
            Q(mgyc__mgyc__icontains=value) |
            Q(mgyc__assembly__study__accession__icontains=value) |
            Q(mgyc__assembly__accession__icontains=value) |
            Q(mgyc__assembly__biome__lineage__icontains=value) |
            Q(bgc_metadata__icontains=value) |
            Q(bgc_detector__bgc_detector_name__icontains=value)
        )

        # Find proteins matching the keyword
        filter_on_metadata = Metadata.objects.filter(
            Q(mgyp__mgyp__icontains=value) |
            Q(mgyp__pfam__icontains=value)
        )
        # TODO: Metadata should have fk in the db to BGC so that a proper JOIN can be used
        bgcids_from_matching_metadata = filter_on_metadata.values_list("bgcdb_id", flat=True)
        filter_on_related_metadata = Q(mgyb__in=bgcids_from_matching_metadata)

        return queryset.filter(filter_on_parent_objects | filter_on_related_metadata | filter_on_mgyb_accession)

    keyword = django_filters.CharFilter(method='filter_by_keyword')

    class Meta:
        model = Bgc
        fields = []

