from django.shortcuts import render
from django.core.paginator import Paginator
from api.api import perform_keyword_search, perform_complex_search,get_contig_region_plot,dowload_bgcs


def landing_page(request):
    return render(request, 'landing_page.html')


def results_page(request):
    keyword = request.GET.get('keyword')
    complex_query_params = {
        'antismash': request.GET.get('antismash', 'true') == 'true',
        'gecco': request.GET.get('gecco', 'true') == 'true',
        'sanntis': request.GET.get('sanntis', 'true') == 'true',
        'bgc_class_name': request.GET.get('bgc_class_name'),
        'bgc_accession': request.GET.get('bgc_accession'),
        'assembly_accession': request.GET.get('assembly_accession'),
        'contig_mgyc': request.GET.get('contig_mgyc'),
        'complete': request.GET.get('complete', 'true') == 'true',
        'single_truncated': request.GET.get('single_truncated', 'true') == 'true',
        'double_truncated': request.GET.get('double_truncated', 'true') == 'true',
        'biome_lineage': request.GET.get('biome_lineage'),
        'protein_pfam': request.GET.getlist('protein_pfam'),
        'pfam_strategy': request.GET.get('pfam_strategy', 'intersection'),
        'aggragate_strategy': request.GET.get('aggragate_strategy', 'single')
    }

    if keyword:
        results = perform_keyword_search(keyword)
    else:
        results = perform_complex_search(**complex_query_params)
    
    paginator = Paginator(results, 10)  # 10 results per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'results_page.html', {'results': page_obj})


def bgc_page(request, mgyc,start_position,end_position):
    # Extract the relevant parameters for the plot from the request or use defaults
    start_position = int(start_position)
    end_position = int(end_position)

    print(mgyc,start_position,end_position)

    # Call the API function to get the plot HTML
    plot_html = get_contig_region_plot(request, mgyc=mgyc, start_position=start_position, end_position=end_position)

    # Render the BGC page with the plot
    return render(request, 'bgc_page.html', {'plot_html': plot_html})
    return render(request, 'bgc_page.html', context)

def download_bgcs(request, mgyc, start_position, end_position):
    start_position = int(start_position)
    end_position = int(end_position)
    output_type = request.GET.get('output_type', 'genbank')  # Default to GenBank if not specified

    # Call the API function to get the download data
    response = dowload_bgcs(
        request,
        mgyc=mgyc,
        start_position=start_position,
        end_position=end_position,
        output_type=output_type,
    )

    return response

def custom_404_view(request, exception):
    return render(request, '404.html', status=404)
