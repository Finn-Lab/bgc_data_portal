import logging

import django_filters
from django.db.models import Q

from .models import Bgc, BgcDetector
from .models import Metadata
from .models import BgcClass
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

        # Check if search is too vague
        if type(value) is str and len(value)<4:
            logging.warning(f"Keyword {value} didnot matched any field and is too vague for metadata")
            return queryset.none()
        
        # If query looks like an ERP, use direct lookup if possible
        if type(value) is str and value.lower().strip().startswith('erp'):
            logging.warning(f"Using study accession ONLY lookup for keyword {value}")
            return queryset.filter(mgyc__assembly__study__accession=value.upper())
        
        # If query looks like an ERZ, use direct lookup if possible
        if type(value) is str and value.lower().strip().startswith('erz'):
            logging.warning(f"Using assembly accession ONLY lookup for keyword {value}")
            return queryset.filter(mgyc__assembly__accession=value.upper())
        
        # If query looks like an MGYC, use direct lookup if possible
        if type(value) is str and value.lower().strip().startswith('mgyc'):
            logging.warning(f"Using MGYC ONLY lookup for keyword {value}")
            return queryset.filter(mgyc=value.upper())
            
        # If query looks like an MGYB, use direct lookup if possible
        if type(value) is str and value.lower().strip().startswith('mgyb'):
            try:
                mgyb_id = int(value.lower().lstrip('mgyb'))
            except ValueError:
                logging.warning(f"Search keyword looked like an MGYB accession ({value}) but didn't parse as int")
            else:
                return queryset.filter(mgyb=mgyb_id.upper())

        # If query looks like Pfam, do lookup only from protein side for efficiency
        if type(value) is str and value.lower().strip().startswith('pf') and len(value.strip()) == 7:
            logging.warning(f"Using protein-metadata ONLY lookup for keyword {value}")
            # TODO: metadata should have an FK to MGC so that this doesn't use an expensive string lookup
            return queryset.filter(mgyc__metadata__mgyp__pfam__icontains=value)

        # If query looks like MGYP, do lookup from protein side for efficiency
        if type(value) is str and value.lower().strip().startswith('mgyp'):
            logging.warning(f"Using protein-metadata ONLY lookup for keyword {value}")
            metadata = Metadata.objects.filter(mgyp__mgyp__icontains=value)
            return queryset.filter(mgyb__in=metadata.values_list("bgcdb_id", flat=True))

        # Check if matches in one of the classes
        _class_q = Q(bgc_class_name__regex=fr'(?i)\b{value}\b')
        _class_queryset = BgcClass.objects.filter(_class_q)

        if _class_queryset.exists():  # Check if there are any results in BgcClass
            logging.warning(f"Using Bgc Class ONLY lookup for keyword {value}")
            # Extract the IDs of the matching BgcClass objects
            matching_class_ids = _class_queryset.values_list('bgc_class_id', flat=True)
            return queryset.filter(bgc_class__bgc_class_id__in=matching_class_ids)

        # Check if matches in one of the detectors
        _detector_q = Q(bgc_detector_name__regex=fr'(?i)\b{value}\b')
        _detector_queryset = BgcDetector.objects.filter(_detector_q)

        # Check if there are any results in BgcClass
        if _detector_queryset.exists():  
            logging.warning(f"Using Bgc Detector ONLY lookup for keyword {value}")
            # Extract the IDs of the matching BgcClass objects
            matching_detector_ids = _detector_queryset.values_list('bgc_detector_id', flat=True)
            return queryset.filter(bgc_detector__bgc_detector_id__in=matching_detector_ids)
        

        if type(value) is str and any(char.isdigit() for char in value) and any(char.isalpha() for char in value):
            logging.warning(f"Check odd assembly accession for keyword {value}")
            return queryset.filter(mgyc__assembly__accession=value.upper())
        
        elif value.isalpha():
            logging.warning(f"Check metadata and biome for keyword {value}")
            filter_on_parent_objects = (
                Q(mgyc__assembly__biome__lineage__icontains=value) |
                Q(bgc_metadata__icontains=value) 
            )

            return queryset.filter(filter_on_parent_objects)
        
        return queryset.none()

    keyword = django_filters.CharFilter(method='filter_by_keyword')

    class Meta:
        model = Bgc
        fields = []