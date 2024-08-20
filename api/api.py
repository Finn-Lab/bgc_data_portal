
import re
from ninja import NinjaAPI, Router, Schema, ModelSchema
from ninja.pagination import paginate
from ninja.errors import HttpError
from typing import List, Optional,Union
from enum import Enum
from django.db.models import Q
from ninja import Query
from .models import Bgc, BgcClass, BgcDetector, Contig, Assembly, Biome, Protein, Metadata
from .schemas import Aggregate,PfamStrategy
from .schemas import BgcSearchOutputSchema, BgcSearchUserOutputSchema, BgcSearchInputSchema, OutputType, BgcSearchCallSchema
from .utils import RegionFeatureError, get_region_features,complex_bgc_search,search_keyword_in_models
from .generate_outputs import WriteRegion#, generate_json, generate_fasta
from .aggregate_bgcs import BgcAggregator
from django.http import Http404, HttpResponse
from bgc_plots.contig_region_visualisation import ContigRegionViewer
from bgc_data_portal import __version__,__name__,__description__


api = NinjaAPI(
    title=__name__,
    description=__description__,
    version=__version__
)

@api.exception_handler(HttpError)
def custom_error_handler(request, exc):
    return api.create_response(
        request,
        {"detail": str(exc)},
        status=exc.status_code,
    )

_partials = ['full_length','single_truncated','double_truncated']
_detectors = ['antiSMASH','GECCO','SanntiS']

def perform_keyword_search(keyword: Optional[str] = None):
    """Core logic to search BGCs by keyword"""
    if keyword==None:
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
    """Core logic for complex BGC searches"""
    detectors = [name for name, value in zip(_detectors, [_params.antismash, _params.gecco, _params.sanntis]) if value]
    _pfams = re.split("[,\s]",_params.protein_pfam)
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
    aggregate_function = getattr(BgcAggregator, _params.aggragate_strategy.value)
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


@api.get("/search/", response=List[BgcSearchUserOutputSchema])
@paginate
def search_by_keyword(request, keyword: str):
    return perform_keyword_search(keyword)


@api.get("/bgcs/", response=List[BgcSearchUserOutputSchema])
@paginate
def search_bgcs(request, params: BgcSearchCallSchema = Query(...)):
    # print(params)
# def search_bgcs(request, **kwargs):
    return perform_complex_search(params)
    # return perform_complex_search(**kwargs)


@api.get("/contig_region/")
def dowload_bgcs(request, 
              mgyc: str = None, 
              start_position: int = None, 
              end_position: int = None,
              output_type: OutputType = OutputType.fasta,
    ):
    " Function to download data in specified format given an MGYC and location"
    try:
        # Get region features using the utility function
        contig, assembly_accession, bgcs, protein_metadata = get_region_features(mgyc, start_position, end_position)
    except RegionFeatureError as e:
        raise Http404(str(e))

    # Generate GenBank file
    write_output_function = getattr(WriteRegion,output_type.value)
    output_content = write_output_function(contig, start_position, end_position, assembly_accession, bgcs, protein_metadata)

    # Return the GenBank file as a response
    response = HttpResponse(output_content, content_type=f'contig_region/{output_type}')
    response['Content-Disposition'] = f'attachment; filename="{mgyc}_{start_position}_{end_position}.{output_type.value}"'
    return response

@api.get("/contig_region_plot/")
def get_contig_region_plot(request, 
            mgyc: str = None, 
            start_position: int = None, 
            end_position: int = None
            ):
    " plot a BGC region"
    print(mgyc,start_position,end_position)
    plot_html = ContigRegionViewer.plot_contig_region(mgyc,start_position,end_position)
    return plot_html #HttpResponse(plot_html, content_type='text/html')
    
