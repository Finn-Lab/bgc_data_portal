"""Resolve a landing-page keyword to the best-matching dashboard filter.

The resolver checks discovery models in priority order and returns the
first match as a dict containing the dashboard redirect URL and metadata.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlencode

from django.conf import settings


# Compiled patterns for accession detection
_BGC_ACCESSION_RE = re.compile(r"^MGYB\d+$", re.IGNORECASE)
_ASSEMBLY_ACCESSION_RE = re.compile(r"^(ERZ|GCA_|GCF_)\w+$", re.IGNORECASE)
_DOMAIN_ACCESSION_RE = re.compile(r"^(PF\d{5}|TIGR\d{5})$", re.IGNORECASE)


def _build_result(
    filter_param: str,
    filter_value: str,
    match_type: str,
) -> dict:
    """Build the resolver result dict with a dashboard redirect URL."""
    base = getattr(settings, "FORCE_SCRIPT_NAME", "") or ""
    params = urlencode({"mode": "query", filter_param: filter_value})
    return {
        "redirect_url": f"{base}/dashboard/?{params}",
        "match_type": match_type,
        "filter_param": filter_param,
        "filter_value": filter_value,
    }


def resolve_keyword(keyword: str) -> dict:
    """Resolve *keyword* to the single best-matching dashboard filter.

    Returns a dict with ``redirect_url``, ``match_type``, ``filter_param``,
    and ``filter_value``.  Always returns a result — the fallback maps
    the raw keyword to the dashboard ``search`` param.
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return _build_result("search", "", "fallback")

    # Try each resolver in priority order; first match wins.
    for resolver in _RESOLVERS:
        result = resolver(keyword)
        if result is not None:
            return result

    # Fallback: pass the raw keyword to the dashboard search box.
    return _build_result("search", keyword, "fallback")


# ── Individual resolvers (private) ───────────────────────────────────────────


def _try_bgc_accession(keyword: str) -> Optional[dict]:
    if not _BGC_ACCESSION_RE.match(keyword):
        return None
    from discovery.models import DashboardBgc

    if DashboardBgc.objects.filter(bgc_accession__iexact=keyword).exists():
        return _build_result("search", keyword.upper(), "bgc_accession")
    return None


def _try_assembly_accession(keyword: str) -> Optional[dict]:
    if not _ASSEMBLY_ACCESSION_RE.match(keyword):
        return None
    from discovery.models import DashboardAssembly

    match = (
        DashboardAssembly.objects.filter(assembly_accession__iexact=keyword)
        .values_list("assembly_accession", flat=True)
        .first()
    )
    if match:
        return _build_result("search", match, "assembly_accession")
    return None


def _try_domain_accession(keyword: str) -> Optional[dict]:
    if not _DOMAIN_ACCESSION_RE.match(keyword):
        return None
    from discovery.models import DashboardDomain

    match = (
        DashboardDomain.objects.filter(acc__iexact=keyword)
        .values_list("acc", flat=True)
        .first()
    )
    if match:
        return _build_result("search", match, "domain_accession")
    return None


def _try_bgc_class(keyword: str) -> Optional[dict]:
    from discovery.models import DashboardBgcClass

    # Exact match first
    exact = (
        DashboardBgcClass.objects.filter(name__iexact=keyword)
        .values_list("name", flat=True)
        .first()
    )
    if exact:
        return _build_result("bgc_class", exact, "bgc_class")

    # Partial match — pick the one with the most BGCs
    partial = (
        DashboardBgcClass.objects.filter(name__icontains=keyword)
        .order_by("-bgc_count")
        .values_list("name", flat=True)
        .first()
    )
    if partial:
        return _build_result("bgc_class", partial, "bgc_class")
    return None


def _try_detector(keyword: str) -> Optional[dict]:
    from discovery.models import DashboardDetector

    # Exact tool name
    exact = (
        DashboardDetector.objects.filter(tool__iexact=keyword)
        .values_list("tool", flat=True)
        .first()
    )
    if exact:
        return _build_result("search", exact, "detector")

    # Partial match on human-readable name
    partial = (
        DashboardDetector.objects.filter(name__icontains=keyword)
        .values_list("tool", flat=True)
        .first()
    )
    if partial:
        return _build_result("search", partial, "detector")
    return None


def _try_biome(keyword: str) -> Optional[dict]:
    from discovery.models import DashboardAssembly

    # Find the first distinct biome_path that contains the keyword
    match = (
        DashboardAssembly.objects.filter(biome_path__icontains=keyword)
        .exclude(biome_path="")
        .values_list("biome_path", flat=True)
        .distinct()[:1]
    )
    if match:
        # Extract the deepest matching segment as the filter value
        path = match[0]
        # Find the segment of the ltree path that contains the keyword
        segments = path.split(".")
        for seg in reversed(segments):
            if keyword.lower() in seg.lower():
                return _build_result("biome_lineage", seg, "biome")
        # If no single segment matches, use the keyword directly
        return _build_result("biome_lineage", keyword, "biome")
    return None


def _try_taxonomy(keyword: str) -> Optional[dict]:
    from discovery.models import DashboardContig

    match = (
        DashboardContig.objects.filter(taxonomy_path__icontains=keyword)
        .exclude(taxonomy_path="")
        .values_list("taxonomy_path", flat=True)
        .distinct()[:1]
    )
    if match:
        path = match[0]
        # Build the prefix up to and including the matching segment
        segments = path.split(".")
        prefix_parts = []
        for seg in segments:
            prefix_parts.append(seg)
            if keyword.lower() in seg.lower():
                return _build_result(
                    "taxonomy_path", ".".join(prefix_parts), "taxonomy"
                )
        # Keyword spans segments or is a substring; use it directly
        return _build_result("taxonomy_path", keyword, "taxonomy")
    return None


def _try_organism_name(keyword: str) -> Optional[dict]:
    from discovery.models import DashboardAssembly

    if DashboardAssembly.objects.filter(organism_name__icontains=keyword).exists():
        return _build_result("search", keyword, "organism_name")
    return None


def _try_natural_product(keyword: str) -> Optional[dict]:
    from discovery.models import DashboardNaturalProduct

    if DashboardNaturalProduct.objects.filter(name__icontains=keyword).exists():
        return _build_result("search", keyword, "natural_product")
    return None


# Resolution order — first match wins.
_RESOLVERS = [
    _try_bgc_accession,
    _try_assembly_accession,
    _try_domain_accession,
    _try_bgc_class,
    _try_detector,
    _try_biome,
    _try_taxonomy,
    _try_organism_name,
    _try_natural_product,
]
