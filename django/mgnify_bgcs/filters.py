import re

import django_filters
from django.db.models import Q, Exists, OuterRef

from .models import (
    Bgc,
    BgcClass,
    BgcDetector,
)
from .utils.helpers import mgyb_converter
from django.conf import settings
import logging

log = logging.getLogger(__name__)
numeric_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
log.setLevel(numeric_level)


class MgybConverterFilter(django_filters.CharFilter):
    """
    Convert the public MGYB accession to the internal integer PK
    ( e.g. MGYB000000123 → 123 ) and filter on Bgc.id.
    """

    def filter(self, qs, value):
        if value and value.upper().startswith("MGYB") and value[4:].isdigit():
            pk = mgyb_converter(value, text_to_int=True)
            if pk is not None:
                return qs.filter(id=pk)
        return qs.none()


class BgcKeywordFilter(django_filters.FilterSet):
    """
    One free-text field that smart-detects what the user is typing
    and routes the query down the cheapest possible path.
    """

    # ------------------------------------------------------------------ #
    # Helper predicates
    # ------------------------------------------------------------------ #
    _ERP_RE = re.compile(r"^erp\d+$", re.I)
    _ERZ_RE = re.compile(r"^erz\d+$", re.I)
    _MGYC_RE = re.compile(r"^mgyc\d+$", re.I)
    _MGYB_RE = re.compile(r"^mgyb\d+$", re.I)
    _PFAM_RE = re.compile(r"^pf\d{5}$", re.I)
    _MGYP_RE = re.compile(r"^mgyp\d+", re.I)

    @staticmethod
    def _is_mixed_alphanum(s: str) -> bool:
        return any(c.isalpha() for c in s) and any(c.isdigit() for c in s)

    # ------------------------------------------------------------------ #
    # Core filter
    # ------------------------------------------------------------------ #
    @staticmethod
    def filter_by_keyword(queryset, name, value: str):
        if not value:
            return queryset

        value = value.strip()
        value_up = value.upper()

        # 1. very short strings are too expensive to broadcast
        if len(value) < 3:
            log.warning(
                "Keyword %s did not match any field and is too short for metadata search",
                value,
            )
            return queryset.none()

        # ------------------------------------------------------------------
        # 2. direct accession / identifier look-ups
        # ------------------------------------------------------------------
        if BgcKeywordFilter._ERP_RE.match(value):
            log.info("Direct study %s look-up", value_up)
            return queryset.filter(contig__assembly__study__accession=value_up)

        if BgcKeywordFilter._ERZ_RE.match(value):
            log.info("Direct assembly %s look-up", value_up)
            return queryset.filter(contig__assembly__accession=value_up)

        if BgcKeywordFilter._MGYC_RE.match(value):
            log.info("Direct MGYC %s look-up", value_up)
            return queryset.filter(contig__mgyc=value_up)

        if BgcKeywordFilter._MGYB_RE.match(value):
            try:
                pk = int(value_up.lstrip("MGYB"))
            except ValueError:
                log.warning("MGYB string %s did not parse to int", value)
            else:
                return queryset.filter(id=pk)

        # ------------------------------------------------------------------
        # 3. protein / domain shortcuts
        # ------------------------------------------------------------------
        if BgcKeywordFilter._PFAM_RE.match(value):
            log.info("Domain (Pfam) %s look-up through ProteinDomain", value_up)
            # Domains are unique – single hit foreign-key straight into a sub-query.
            return queryset.filter(
                contig__cds__protein__domains__acc=value_up
            ).distinct()

        if BgcKeywordFilter._MGYP_RE.match(value):
            log.info("Protein identifier %s look-up", value_up)
            return queryset.filter(
                contig__cds__protein_identifier__icontains=value_up
            ).distinct()

        # ------------------------------------------------------------------
        # 4. class / detector vocabulary
        # ------------------------------------------------------------------
        class_qs = BgcClass.objects.filter(name__iregex=value)
        if class_qs.exists():
            log.info("BgcClass %s vocabulary hit", value)
            aggregated_with_class = Bgc.objects.filter(
                is_aggregated_region=True, classes__in=class_qs
            )
            return queryset.filter(
                Exists(
                    aggregated_with_class.filter(
                        contig_id=OuterRef("contig_id"),
                        start_position__lte=OuterRef("end_position"),
                        end_position__gte=OuterRef("start_position"),
                    )
                )
            ).distinct()

        detector_qs = BgcDetector.objects.filter(name__iregex=rf"^{re.escape(value)}$")
        if detector_qs.exists():
            log.info("Detector %s vocabulary hit", value)
            return queryset.filter(detector__in=detector_qs).distinct()

        # ------------------------------------------------------------------
        # 5. misc. accessions
        # ------------------------------------------------------------------
        if BgcKeywordFilter._is_mixed_alphanum(value):
            # could be an INSDC assembly of a different format
            log.info("Mixed alpha-numeric assembly candidate %s", value_up)
            return queryset.filter(contig__assembly__accession=value_up)

        # ------------------------------------------------------------------
        # 6. free-text biome / JSON metadata search
        # ------------------------------------------------------------------
        if value.isalpha():
            log.info("Free-text biome/metadata search for %s", value)
            return queryset.filter(
                Q(contig__assembly__biome__lineage__icontains=value)
                | Q(metadata__icontains=rf"^{re.escape(value)}$")
                | Q(contig__cds__protein__domains__name=rf"^{re.escape(value)}$")
            ).distinct()

        # fallthrough
        return queryset.none()

    # exposed filter
    keyword = django_filters.CharFilter(method="filter_by_keyword")

    class Meta:
        model = Bgc
        fields = []  # all handled manually above
