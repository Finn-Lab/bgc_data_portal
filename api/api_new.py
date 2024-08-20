# api.py

import re
from ninja import NinjaAPI, Router, Schema, ModelSchema
from ninja.pagination import paginate
from ninja.errors import HttpError
from typing import List, Optional, Union
from enum import Enum
from django.db.models import Q
from ninja import Query
from .models import Bgc, BgcClass, BgcDetector, Contig, Assembly, Biome, Protein, Metadata
from .schemas import Aggregate, PfamStrategy
from .schemas import BgcSearchOutputSchema, BgcSearchUserOutputSchema, BgcSearchInputSchema, OutputType, BgcSearchCallSchema
from .utils import RegionFeatureError, get_region_features, complex_bgc_search, search_keyword_in_models
from .generate_outputs import WriteRegion
from .aggregate_bgcs import BgcAggregator
from django.http import Http404, HttpResponse
from bgc_plots.contig_region_visualisation import ContigRegionViewer
from bgc_data_portal import __version__, __name__, __description__

api = NinjaAPI(
    title="Biosynthetic Gene Cluster (BGC) Portal API",
    description="API for accessing and retrieving biosynthetic gene cluster predictions from metagenomic assemblies.",
    version=__version__,
    docs_url="/api/docs"
)

@api.exception_handler(HttpError)
def custom_error_handler(request, exc):
    """Handle custom errors with a detailed message."""
    return api.create_response(
        request,
        {"detail": str(exc)},
        status=exc.status_code,
    )

# Constants for search filtering
_partials = ['full_length', 'single_truncated', 'double_truncated']
_detectors = ['antiSMASH', 'GECCO', 'SanntiS']

def perform_keyword_search(keyword: Optional[str] = None):
    """Search BGCs by a specific keyword, returning relevant records."""
    if keyword is None:
        bgcs = Bgc.objects.all()
    else:
        matching_bgcs = search_keyword_in_models(keyword)
        bgcs = Bgc.objects.filter(mgyb__in=matching_bgcs)

    return [
        BgcSearchUserOutputSchema(
            mgybs=[bgc.mgyb],
            assembly_accession=bgc.mgyc.assembly.accession,
            contig_mgyc=bgc.mgyc.mgyc,
            start_position=bgc.start_position,
            end_position=bgc.end_position,
            bgc_detector_names=[bgc.bgc_detector.bgc_detector_name],
            bgc_class_names=[bgc.bgc_class.bgc_class_name]
        )
        for bgc in bgcs
    ]

def perform_complex_search(_params):
    """Perform a complex BGC search based on multiple criteria."""
    detectors = [name for name, value in zip(_detectors, [_params.antismash, _params.gecco, _params.sanntis]) if value]
    _pfams = re.split("[,\s]", _params.protein_pfam)
    bgcs = complex_bgc_search(
        detectors,
        _params.bgc_class_name,
        _params.mgyb,
        _params.assembly_accession,
        _params.contig_mgyc,
        _params.full_length,
        _params.single_truncated,
        _params.double_truncated,
        _params.biome_lineage,
        _pfams,
        _params.pfam_strategy.value,
    )

    individual_bgcs = [
        BgcSearchInputSchema(
            mgyb=bgc.mgyb,
            assembly_accession=bgc.mgyc.assembly.accession,
            contig_mgyc=bgc.mgyc.mgyc,
            start_position=bgc.start_position,
            end_position=bgc.end_position,
            bgc_detector_name=bgc.bgc_detector.bgc_detector_name,
            bgc_class_name=bgc.bgc_class.bgc_class_name,
        )
        for bgc in bgcs
    ]

    # Aggregate strategy function
    aggregate_function = getattr(BgcAggregator, _params.aggregate_strategy.value)
    aggregated_bgcs = aggregate_function(individual_bgcs, detectors)

    return [
        BgcSearchUserOutputSchema(
            mgybs=aggregated_bgc.mgybs,
            assembly_accession=aggregated_bgc.assembly_accession,
            contig_mgyc=aggregated_bgc.contig_mgyc,
            start_position=aggregated_bgc.start_position,
            end_position=aggregated_bgc.end_position,
            bgc_detector_names=aggregated_bgc.bgc_detector_names,
            bgc_class_names=aggregated_bgc.bgc_class_names,
        )
        for aggregated_bgc in aggregated_bgcs
    ]


@api.get("/search/", response=List[BgcSearchUserOutputSchema], tags=["Search"], summary="Keyword Search for BGCs")
@paginate
def search_by_keyword(request, keyword: str):
    """
    Perform a keyword search across the BGC Portal.

    Use this endpoint to retrieve BGCs based on keywords or accession numbers. 
    This is equivalent to the portal's keyword search feature.
    """
    return perform_keyword_search(keyword)


@api.get("/bgcs/", response=List[BgcSearchUserOutputSchema], tags=["Search"], summary="Advanced Search for BGCs")
@paginate
def search_bgcs(request, params: BgcSearchCallSchema = Query(...)):
    """
    Execute a detailed search across the BGC Portal.

    This endpoint allows for advanced queries using various criteria such as BGC class, 
    detector names, biome lineage, Pfam domains, and more. 
    The search results reflect the data shown on the "Explore BGCs" page of the portal.
    """
    return perform_complex_search(params)


@api.get("/contig_region/", tags=["Data Download"], summary="Download BGC Data by Contig Region")
def download_bgcs(request, 
                 mgyc: str = None, 
                 start_position: int = None, 
                 end_position: int = None,
                 output_type: OutputType = OutputType.fasta):
    """
    Download data related to a specific BGC region within a contig.

    Provide the MGYC, start position, and end position to retrieve the BGC data 
    in your desired format (FASTA, GeneBank, JSON, GFF3).
    """
    try:
        # Get region features using the utility function
        contig, assembly_accession, bgcs, protein_metadata = get_region_features(mgyc, start_position, end_position)
    except RegionFeatureError as e:
        raise Http404(str(e))

    # Generate the requested file format
    write_output_function = getattr(WriteRegion, output_type.value)
    output_content = write_output_function(contig, start_position, end_position, assembly_accession, bgcs, protein_metadata)

    # Return the file as a response
    response = HttpResponse(output_content, content_type=f'contig_region/{output_type}')
    response['Content-Disposition'] = f'attachment; filename="{mgyc}_{start_position}_{end_position}.{output_type.value}"'
    return response

@api.get("/contig_region_plot/", tags=["Visualization"], summary="Visualize a BGC Region")
def get_contig_region_plot(request, 
                           mgyc: str = None, 
                           start_position: int = None, 
                           end_position: int = None):
    """
    Generate and return a plot visualizing the BGC region within a contig.

    Provide the MGYC, start position, and end position to view the BGC region. 
    The plot includes coding regions, Pfam annotations, and BGC predictions from various detectors.
    """
    plot_html = ContigRegionViewer.plot_contig_region(mgyc, start_position, end_position)
    return plot_html
