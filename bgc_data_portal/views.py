from django.shortcuts import render, redirect
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import HttpResponse
from django.views.generic import TemplateView
import os
from django.http import FileResponse, Http404
from django.conf import settings
from api.api import perform_keyword_search, perform_complex_search,get_contig_region_plot,download_bgcs
from api.schemas import BgcSearchCallSchema, OutputType, PfamStrategy,Aggregate
import logging
from collections import Counter
from bgc_plots.class_distribution_plots import generate_horizontal_bar_plot_html

from api.utils import get_region_features
from bgc_plots.contig_region_visualisation import ContigRegionViewer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


EXTENDED_NUCLEOTIDE_WINDOW = 7000

from django.views.generic import TemplateView
import os
from django.http import FileResponse, Http404
from django.conf import settings

class DocsView(TemplateView):

    def get(self, request, path='index.html', *args, **kwargs):
        # Construct the full path to the file

        file_path = os.path.join(settings.BASE_DIR, 'docs', '_site', path)

        if os.path.exists(file_path):
            return FileResponse(open(file_path, 'rb'))
        else:
            raise Http404("File not found")

def landing_page(request):
    return render(request, 'landing_page.html')

def explore(request):
    results = None
    _results = None
    page = request.GET.get('page', 1)
    keyword = request.GET.get('keyword', None)
    plot_html = None
    
    total_regions = None
    bgc_class_dist = None
    n_assemblies = None
    n_studies = None
    default_bgc_class_dist = {'TERPENE': 1001, 'NRPS': 1233, 'SACCHARIDE': 5824, 'POLYKETIDE': 637, 'NRP': 21310, 'RIPP': 417, 'UNKNOWN': 3342, 'ALKALOID': 124, 'OTHER': 540}
    defeult_total_regions = 50012
    default_n_studies= 4209
    default_n_assemblies = 5200

    if request.GET:
        try:
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
                _results,_bgcs = perform_keyword_search(keyword)
            elif request.GET:
                _results,_bgcs = perform_complex_search(complex_query_params)
                
            # generate class dist plots
            total_regions = len(_results)
            bgc_class_dist = dict(Counter([bgc.bgc_class_names[0].split(',')[0] for bgc in _results]))
            n_assemblies  = _bgcs.values('mgyc__assembly__accession').distinct().count()
            n_studies  = _bgcs.values('mgyc__assembly__study').distinct().count()
            # partials_dist = Counter([str(bgc.bgc_class_names).split(',')[0] for bgc in results])
            counters = [bgc_class_dist,bgc_class_dist]
            titles = ['', '']

            if not plot_html:
                plot_html = generate_horizontal_bar_plot_html(counters, titles)


            paginator = Paginator(_results, 10)  # Show 10 items per page
            try:
                results = paginator.page(page)
            except PageNotAnInteger:
                results = paginator.page(1)
            except EmptyPage:
                results = paginator.page(paginator.num_pages)

        except Exception as e:
            print('error:', e)
            results = None  # Ensure results is always defined even in case of an error

    # stats dictionary
    result_stats = {
        'total_regions':total_regions or defeult_total_regions,
        'bgc_class_dist': bgc_class_dist or default_bgc_class_dist,
        'n_assemblies': n_assemblies or default_n_assemblies,
        'n_studies': n_studies or default_n_studies,
        }

    print(result_stats)
    context = {
        'results': results,
        'request_params': request.GET,
        'plot_html':plot_html,
        'result_stats': result_stats,
    }

    # If it's an AJAX request, return the partial table
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'explore_table.html', context)
    
    # Otherwise, return the full page
    return render(request, 'explore_page.html', context)


def bgc_page(request, mgyc,start_position,end_position):
    # Extract the relevant parameters for the plot from the request or use defaults
    # print('ksksksks')
    try:
        start_position = int(start_position)
        end_position = int(end_position)

        contig, assembly_accession,features_df = get_region_features(
            mgyc,
            start_position,
            end_position,
            extended_window=EXTENDED_NUCLEOTIDE_WINDOW
            )
        
        # remove tails to avoid ploting more that the desired EXTENDED_NUCLEOTIDE_WINDOW
        features_df['start'] = features_df['start'].map(lambda x:max(start_position-EXTENDED_NUCLEOTIDE_WINDOW,x))
        features_df['end'] = features_df['end'].map(lambda x:min(end_position+EXTENDED_NUCLEOTIDE_WINDOW,x))
        # Call the API function to get the plot HTML
        plot_html = ContigRegionViewer.plot_contig_region(features_df)
        # Get summary details regarding
        cds_attribs = dict(features_df[features_df['type']=='CDS'].iloc[0]['attrib'])
        assembly_accession = cds_attribs.get('assembly_accession')
        assembly_url = "https://www.ebi.ac.uk/metagenomics/assemblies/{assembly_accession}"
        biome_lineage=cds_attribs.get('biome_lineage','').replace('root:','')
        
        aggr_df = features_df[ (features_df.start>=start_position) & (features_df.end<=end_position)]

        # predicted classes
        _predicted_classes_dict = {detector:sorted({individual_class for attrib in gr['attrib'] for individual_class in attrib['BGC_CLASS'].split(',') }) for detector,gr in aggr_df[(aggr_df['type']=='CLUSTER')&(aggr_df['source']!="Aggregated region")].sort_values('source').groupby('source')}
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
        pfam_info_dict = {attrib.get('ID'):attrib for attrib in features_df[features_df['type']=='ANNOT']['attrib']} 
        # add cluster_representative_url
        for p in cds_info_dict:
            cds_info_dict[p].update({
                'cluster_representative_url':f"https://www.ebi.ac.uk/metagenomics/proteins/{cds_info_dict[p]['cluster_representative']}/" if cds_info_dict[p]['cluster_representative'] else None,
                'protein_length':len(cds_info_dict[p]['sequence']),
            })
            for _pfam_dct in cds_info_dict[p]['pfam']:
                go_slim = pfam_info_dict.get(_pfam_dct['PFAM'],{}).get('GOslim',[None])
                _pfam_dct.update({
                    'go_slim':";".join(go_slim) if go_slim[0] else "",
                    'description':pfam_info_dict.get(_pfam_dct['PFAM'],{}).get('description',''),
                })

            # print(cds_info_dict[p]['pfam'])
        # format fetures for download
        download_features = features_df[(features_df['start']<=end_position)&(features_df['end']>=start_position)]
        download_features['start'] = download_features['start'].map(lambda x:max(start_position,x))
        download_features['end'] = download_features['end'].map(lambda x:min(end_position,x))
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
            'precomuted_data': (contig, assembly_accession, download_features)
        })
    except Exception as e:
        logging.error(f"Error in bgc_page view: {e}")
        return HttpResponse(f"An error occurred: {e}", status=500)

def download_bgc_data(request, mgyc, start_position, end_position, precomuted_data=False):
    # try:
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
            precomuted_data=precomuted_data,
        )

        return response
    # except Exception as e:
        # logging.error(f"Error in bgc_page view: {e}")
        # return HttpResponse(f"An error occurred: {e}", status=500)

def custom_404_view(request, exception):
    return render(request, '404.html', status=404)
