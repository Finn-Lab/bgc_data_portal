# Copyright 2024 EMBL - European Bioinformatics Institute
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from ninja import NinjaAPI
from ninja.pagination import paginate
from ninja.errors import HttpError
from typing import  List
from api.services import search_bgcs_by_keyword, search_bgcs_by_advanced
from ninja import Query
from .schemas import AdvancedSearchInput
from .schemas import BgcSearchOutput, GetContigRegionInput, GetContigRegionVisualisationInput
from .utils import RegionFeatureError, get_region_features
from .generate_outputs import WriteRegion
from django.http import Http404, HttpResponse
from bgc_plots.contig_region_visualisation import ContigRegionViewer
from bgc_data_portal import __version__, __name__, __description__

api = NinjaAPI(
    title="MGnify Biosynthetic Gene Clusters Portal API",
    description="API for accessing and retrieving biosynthetic gene cluster predictions from metagenomic assemblies.",
    version=__version__,
    docs_url="/docs/"
)

@api.exception_handler(HttpError)
def custom_error_handler(request, exc):
    """
    Handles errors returned by the API, providing a clear error message.
    """
    return api.create_response(
        request,
        {"detail": str(exc)},
        status=exc.status_code,
    )


@api.get("/keyword_search/", response=List[BgcSearchOutput], tags=["Search"], summary="Keyword search for BGCs")
@paginate
def search_by_keyword(request, keyword: str):
    """
    Perform a keyword search across the BGC Portal.

    Use this endpoint to retrieve BGCs based on keywords or accession numbers.
    This is equivalent to the portal's keyword search.
    """
    search_results = search_bgcs_by_keyword(keyword)


    return [ BgcSearchOutput( mgybs=bgc.mgybs,
                    assembly_accession=bgc.mgyc.assembly.accession,
                    contig_mgyc=bgc.mgyc.mgyc,
                    start_position=bgc.start_position,
                    end_position=bgc.end_position,
                    bgc_detector_names=bgc.bgc_detector_names,
                    bgc_class_names=bgc.bgc_class_names
            ) 
            for bgc in search_results 
    ]

@api.get("/advanced_search/", response=List[BgcSearchOutput], tags=["Search"], summary="Advanced search for BGCs")
@paginate
def search_by_advanced(request, params: AdvancedSearchInput = Query(...)):
    """
    Execute a detailed search across the BGC Portal.

    This endpoint allows for advanced queries using various criteria such as BGC class, 
    detector names, biome lineage, Pfam domains, and more. 
    The search results reflect the data shown on the "Explore BGCs" page of the portal.
    """
    search_results = search_bgcs_by_advanced(params.dict())

    return [ BgcSearchOutput( mgybs=bgc.mgybs,
                    assembly_accession=bgc.mgyc.assembly.accession,
                    contig_mgyc=bgc.mgyc.mgyc,
                    start_position=bgc.start_position,
                    end_position=bgc.end_position,
                    bgc_detector_names=bgc.bgc_detector_names,
                    bgc_class_names=bgc.bgc_class_names
            ) 
            for bgc in search_results 
    ]


@api.get("/contig_region/", tags=["Data download"], summary="Download BGC data by contig region")
def get_contig_region(request, params: GetContigRegionInput = Query(...)):
    """
    Download data related to a specific BGC region within a contig.

    Provide the MGYC, start position, and end position to retrieve the BGC data 
    in your desired format (FASTA, GeneBank, JSON, GFF3).
    - **precomuted_data**: Should be set as false
    """

    if params.precomuted_data:
       contig, assembly_accession, features_df = params.precomuted_data
    else:
        try:
            contig, assembly_accession, features_df = get_region_features(params.mgyc, params.start_position, params.end_position)
        except RegionFeatureError as e:
            raise Http404(str(e))

    # Generate the requested output format
    write_output_function = getattr(WriteRegion, params.output_type)
    output_content = write_output_function(contig, params.start_position, params.end_position, assembly_accession, features_df)

    # Return the file as an HTTP response
    response = HttpResponse(output_content, content_type=f'contig_region/{params.output_type}')
    response['Content-Disposition'] = f'attachment; filename="{params.mgyc}_{params.start_position}_{params.end_position}.{params.output_type}"'
    return response

@api.get("/contig_region_plot/", tags=["Visualisation"], summary="Visualise a BGC Region")
def get_contig_region_plot(request, params: GetContigRegionVisualisationInput = Query(...)):
    """
    Generate and return a plot visualizing the BGC region within a contig.

    Provide the MGYC, start position, and end position to view the BGC region. 
    The plot includes coding regions, Pfam annotations, and BGC predictions from various detectors.
    - **precomuted_data**: Should be set as false
    """
    if params.precomuted_data:
       _, _, features_df = params.precomuted_data
    else:
        try:
            _, _, features_df = get_region_features(params.mgyc, params.start_position, params.end_position)
        except RegionFeatureError as e:
            raise Http404(str(e))
    
    plot_html = ContigRegionViewer.plot_contig_region(features_df)
    return plot_html
