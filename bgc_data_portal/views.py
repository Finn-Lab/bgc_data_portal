from django.shortcuts import render, redirect
from django.core.paginator import Paginator
from django.http import HttpResponse
from api.api import perform_keyword_search, perform_complex_search,get_contig_region_plot,download_bgcs
from api.schemas import BgcSearchCallSchema, OutputType, PfamStrategy,Aggregate
import logging

from bgc_plots.contig_region_visualisation import ContigRegionViewer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def landing_page(request):
    return render(request, 'landing_page.html')

def results_page(request):
    try:
        keyword = request.GET.get('keyword')
        complex_query_params = BgcSearchCallSchema(
            antismash=request.GET.get('antismash', 'true') == 'true',
            gecco=request.GET.get('gecco', 'true') == 'true',
            sanntis=request.GET.get('sanntis', 'true') == 'true',
            bgc_class_name=request.GET.get('bgc_class_name'),
            mgyb=request.GET.get('mgyb'),
            assembly_accession=request.GET.get('assembly_accession'),
            contig_mgyc=request.GET.get('contig_mgyc'),
            full_length=request.GET.get('full_length', 'true') == 'true',
            single_truncated=request.GET.get('single_truncated', 'true') == 'true',
            double_truncated=request.GET.get('double_truncated', 'true') == 'true',
            biome_lineage=request.GET.get('biome_lineage'),
            protein_pfam=request.GET.get('protein_pfam',''),
            pfam_strategy=PfamStrategy(request.GET.get('pfam_strategy', 'intersection')),
            aggregate_strategy=Aggregate(request.GET.get('aggregate_strategy', 'single'))
        )

        if keyword:
            results = perform_keyword_search(keyword)
        else:
            results = perform_complex_search(complex_query_params)
    except Exception as e:
        print('error:',e)

    
    paginator = Paginator(results, 10)  # 10 results per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'results_page.html', {'results': page_obj})


def bgc_page(request, mgyc,start_position,end_position):
    # Extract the relevant parameters for the plot from the request or use defaults
    try:
        start_position = int(start_position)
        end_position = int(end_position)

        # Call the API function to get the plot HTML
        plot_html, features_df = ContigRegionViewer.plot_contig_region(mgyc=mgyc, start_position=start_position, end_position=end_position)
        # Get summary details regarding
        cds_attribs = dict(features_df[features_df['type']=='CDS'].iloc[0]['attrib'])
        assembly_accession = cds_attribs.get('assembly_accession')
        assembly_url = "https://www.ebi.ac.uk/metagenomics/assemblies/{assembly_accession}"
        biome_lineage=cds_attribs.get('biome_lineage','').replace('root:','')
        
        aggr_df = features_df[ (features_df.start>=start_position) & (features_df.end<=end_position)]

        # predicted classes
        _predicted_classes_dict = {detector:sorted({individual_class for attrib in gr['attrib'] for individual_class in attrib['BGC_CLASS'].split(',') }) for detector,gr in aggr_df[aggr_df['type']=='CLUSTER'].sort_values('source').groupby('source')}
        predicted_classes_dict = {k:_predicted_classes_dict[k] for k in sorted(_predicted_classes_dict,key=lambda x:x.lower())}

        # functional_annotation_dict
        MAX_GOSLIM_COLUM=7
        functional_annotation_dict = {}
        aggr_go_slims = sorted({term for attrib in aggr_df[aggr_df['type']=='ANNOT']['attrib'] for term in attrib.get('GOslim',[])} - {None})
        col_name = 'GOslim description'
        for i,term in enumerate(aggr_go_slims):
            if i!=0 and i%MAX_GOSLIM_COLUM==0:
                col_name+='_next'
            functional_annotation_dict.setdefault(col_name,[]).append(f"- {term}")


        # cds_info_dict
        cds_info_dict = {attrib.get('mgyp'):attrib for attrib in features_df[features_df['type']=='CDS']['attrib']} 
        # add cluster_representative_url
        for p in cds_info_dict:
            cds_info_dict[p].update({
                'cluster_representative_url':f"https://www.ebi.ac.uk/metagenomics/proteins/{cds_info_dict[p]['cluster_representative']}/" if cds_info_dict[p]['cluster_representative'] else None,
                'protein_length':len(cds_info_dict[p]['sequence']),
            })
            print(cds_info_dict[p]['pfam'])
        # cds_info_dict = {attrib.get('mgyp') for attrib in aggr_df[aggr_df['type']!='CLUSTER']['attrib']}
        # Render the BGC page with the plot
        return render(request, 'bgc_page.html', {
            'plot_html': plot_html,
            'assembly_accession': assembly_accession,
            'assembly_url': assembly_url,
            'biome_lineage':biome_lineage,
            'predicted_classes_dict': predicted_classes_dict,
            'functional_annotation_dict':functional_annotation_dict,
            'cds_info_dict': cds_info_dict,
            'mgyc': mgyc,
            'start_position': start_position,
            'end_position': end_position,
        })
    except Exception as e:
        logging.error(f"Error in bgc_page view: {e}")
        return HttpResponse(f"An error occurred: {e}", status=500)

def download_bgc_data(request, mgyc, start_position, end_position):
    try:
        
        start_position = int(start_position)
        end_position = int(end_position)
        
        output_type = request.GET.get('output_type', 'gbk')  # Default to GenBank if not specified

        # Call the API function to get the download data
        response = download_bgcs(
            request,
            mgyc=mgyc,
            start_position=start_position,
            end_position=end_position,
            output_type=OutputType(output_type),
        )

        return response
    except Exception as e:
        logging.error(f"Error in bgc_page view: {e}")
        return HttpResponse(f"An error occurred: {e}", status=500)

def custom_404_view(request, exception):
    return render(request, '404.html', status=404)
