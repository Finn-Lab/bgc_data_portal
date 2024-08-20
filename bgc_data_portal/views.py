from django.shortcuts import render, redirect
from django.core.paginator import Paginator
from django.http import HttpResponse
from api.api import perform_keyword_search, perform_complex_search,get_contig_region_plot,download_bgcs
from api.schemas import BgcSearchCallSchema, OutputType, PfamStrategy,Aggregate
# import logging

# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)
                        

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
            # print(complex_query_params)
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
        plot_html = get_contig_region_plot(request, mgyc=mgyc, start_position=start_position, end_position=end_position)
        # print(mgyc,start_position,end_position)
        # print(mgyc,start_position,end_position)
        # Render the BGC page with the plot
        # return render(request, 'bgc_page.html', {'plot_html': plot_html})
        return render(request, 'bgc_page.html', {
            'plot_html': plot_html,
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
        
        print(mgyc,start_position,end_position)
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
        print('eeee',e)
        logging.error(f"Error in bgc_page view: {e}")
        return HttpResponse(f"An error occurred: {e}", status=500)

def custom_404_view(request, exception):
    return render(request, '404.html', status=404)
