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

import hashlib
import json
import logging
import os
from urllib.parse import urlencode
from typing import Any, cast, List, Dict
from io import StringIO

from django.conf import settings
from django.core.cache import cache
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.generic import TemplateView

from django.http import JsonResponse, HttpResponseBadRequest
from django.utils.safestring import mark_safe
from django.views.decorators.cache import never_cache


# Biopython / record helpers for downloads

from mgnify_bgcs.utils.seqrecord_utils import EnhancedSeqRecord

from bgc_data_portal.forms import (
    BgcKeywordSearchForm,
    BgcAdvancedSearchForm,
    SequenceSearchForm,
    ChemicalStructureSearchForm,
    BgcDetailsForm,
)
from mgnify_bgcs import tasks as bgc_tasks
from mgnify_bgcs.utils.helpers import get_latest_stats
from mgnify_bgcs.cache_utils import (
    get_job_status,
)

log = logging.getLogger(__name__)
numeric_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
log.setLevel(numeric_level)

log.setLevel(logging.DEBUG)  # DEBUG for detailed logging

EXTENDED_NUCLEOTIDE_WINDOW = 7000
UMAP_PLOT_SAMPLE = 1_000


class DocsView(TemplateView):
    def get(self, request, path="index.html", *args, **kwargs):
        # Construct the full path to the file

        file_path = os.path.join(settings.BASE_DIR, "docs", "_site", path)

        if os.path.exists(file_path):
            return FileResponse(open(file_path, "rb"))
        else:
            raise Http404("File not found")


def landing_page(request):
    """
    Render the landing page.
    """
    return render(request, "landing_page.html")


def about(request):
    """
    Render the about page.
    """
    return render(request, "about.html")


def search(request):
    """
    Handle the search page
    """
    post_params = {k: request.GET.getlist(k) for k in sorted(request.GET)}
    form_type = post_params.pop("form_type", [None])[0]
    if form_type is None:
        return render(
            request,
            "search.html",
            {
                "advanced_form": BgcAdvancedSearchForm,
                "sequence_form": SequenceSearchForm,
                "chemical_form": ChemicalStructureSearchForm,
                "result_stats": get_latest_stats(),
                "serialized_string": "",
            },
        )
    else:
        encoded_params = urlencode(post_params, doseq=True)

        if cache.get(encoded_params) is not None:
            log.info(f"Cache hit for params: {post_params}")
            return redirect(reverse("results_view") + "?" + encoded_params)

        if form_type == "keyword":
            form = BgcKeywordSearchForm(request.GET)
            if form.is_valid():
                clean_params = form.cleaned_data
                log.info(f"Keyword search key: {clean_params}")
                cast(Any, bgc_tasks.keyword_search).delay(encoded_params, clean_params)
                return redirect(reverse("results_view") + "?" + encoded_params)

        elif form_type == "advanced":
            form = BgcAdvancedSearchForm(request.GET)
            if form.is_valid():
                clean_params = form.cleaned_data
                log.info(f"advanced_search key: {clean_params}")
                cast(Any, bgc_tasks.advanced_search).delay(encoded_params, clean_params)
                return redirect(reverse("results_view") + "?" + encoded_params)

        elif form_type == "sequence":
            form = SequenceSearchForm(request.GET)
            if form.is_valid():
                clean_params = form.cleaned_data
                log.info(f"sequence_search key: {clean_params}")
                cast(Any, bgc_tasks.sequence_search).delay(encoded_params, clean_params)
                return redirect(reverse("results_view") + "?" + encoded_params)

        elif form_type == "chemical":
            form = ChemicalStructureSearchForm(request.GET)
            if form.is_valid():
                clean_params = form.cleaned_data
                log.info(f"compound_search key: {clean_params}")
                cast(Any, bgc_tasks.compound_search).delay(encoded_params, clean_params)
                return redirect(reverse("results_view") + "?" + encoded_params)

        else:
            return HttpResponseBadRequest("Unknown form_type")


def job_status(request):
    post_params = {k: request.GET.getlist(k) for k in sorted(request.GET)}
    encoded_params = urlencode(post_params, doseq=True)
    if not post_params:
        log.error("No post_params provided in job_status")
        return JsonResponse(
            {"status": "ERROR", "error": "No post_params provided"}, status=400
        )

    result_status = get_job_status(search_key=encoded_params)
    if result_status is not None:
        return JsonResponse({"status": result_status["status"]}, status=200)
    else:
        return JsonResponse(
            {"status": "FAILURE", "error": "No pending task found for this task"}
        )


def results_view(request):
    """
    Once the client sees SUCCESS, it will redirect here. We then:
    """
    post_params = {k: request.GET.getlist(k) for k in sorted(request.GET)}
    sort = post_params.pop("sort", ["assembly_accession"])[0]
    order = post_params.pop("order", ["asc"])[0]
    page = int(post_params.pop("page", ["1"])[0])
    encoded_params = urlencode(post_params, doseq=True)

    status = get_job_status(search_key=encoded_params)
    if not status or status.get("status") != "SUCCESS":
        log.info(
            "Results not ready yet for search_keys=%s; status=%s",
            encoded_params,
            (status or {}).get("status"),
        )
        return render(
            request,
            "results.html",
            {
                "results": None,
                "result_stats": None,
                "encoded_params": mark_safe(encoded_params),
            },
        )

    payload = status.get("result") or {}
    df = payload.get("df")
    result_stats = payload.get("stats") or {}
    scatter_data = payload.get("scatter_data") or []
    display_columns = payload.get("display_columns") or []

    if df is not None and hasattr(df, "sort_values"):
        df_sorted = df.sort_values(
            by=sort,
            ascending=(order == "asc"),
            kind="mergesort",  # stable sort
        )
    else:
        df_sorted = df

    records: List[Dict[str, Any]] = []
    if df_sorted is not None:
        to_dict = getattr(df_sorted, "to_dict", None)
        if callable(to_dict):
            try:
                records = cast(List[Dict[str, Any]], to_dict("records"))
            except Exception:
                records = []
        else:
            try:
                records = list(df_sorted)
            except Exception:
                records = []
    paginator = Paginator(records, 10)
    page_obj = paginator.get_page(page)

    plot_message = (
        f"Showing {len(scatter_data)} BGCs in the UMAP plot."
        if len(scatter_data) < result_stats.get("total_regions", 1)
        else ""
    )

    try:
        log.info(
            "Scatter data points: %s",
            len(scatter_data) if hasattr(scatter_data, "__len__") else "n/a",
        )
    except Exception:
        pass

    context = {
        "results": page_obj,
        "encoded_params": mark_safe(encoded_params),
        "result_stats": result_stats,
        "columns": display_columns,
        "sort": sort,
        "order": order,
        "scatter_json": mark_safe(json.dumps(scatter_data)),
        "plot_message": plot_message,
    }

    return render(request, "results.html", context)


@never_cache
def bgc_page(request):
    """
    Render the BGC detail page with visualization and metadata.
    """
    log.info("Search GET request received")
    bgc_id = request.GET.get("bgc_id")
    if not bgc_id:
        log.error("No bgc_id provided")
        return HttpResponseBadRequest("Missing bgc_id parameter")

    post_params = {k: request.GET.getlist(k) for k in sorted(request.GET)}
    encoded_params = urlencode(post_params, doseq=True)

    status = get_job_status(search_key=encoded_params)

    if status.get("status") == "SUCCESS":
        payload = status.get("result") or {}
        return render(request, "bgc_page.html", payload)

    else:
        if status.get("status") == "UNKNOWN":
            ## Trigger the task if not already running
            form = BgcDetailsForm(request.GET)
            if form.is_valid():
                clean_params = form.cleaned_data
                log.info(f"compound_search key: {clean_params}")
                task = cast(Any, bgc_tasks.collect_bgc_data).delay(
                    encoded_params, clean_params
                )
                log.info(
                    "No pending task found for search_keys=%s; starting new task=%s",
                    clean_params,
                    task.id,
                )
            else:
                log.error("Invalid form data for bgc_id=%s", bgc_id)
                return HttpResponseBadRequest("Invalid bgc_id parameter")
        return render(
            request,
            "bgc_page.html",
            {
                "encoded_params": mark_safe(encoded_params),
                "message": "Collecting BGC data, please wait...",
            },
        )


@never_cache
def download_bgc(request):
    """
    Download the currently viewed BGC region in different formats using
    EnhancedSeqRecord exporters. Prefers cached GenBank text if available.

    Query params:
      - search_key: cache key for the prepared record (required unless bgc_id provided)
      - output_type: one of {gbk, fna, faa, json} (default: gbk)
      - bgc_id: optional fallback if cache is missing to rebuild the record
    """
    post_params = {k: request.GET.getlist(k) for k in sorted(request.GET)}
    output_type = post_params.pop("output_type", ["gbk"])[0].lower()
    encoded_params = urlencode(post_params, doseq=True)

    search_key = request.GET.get("search_key")
    bgc_id = request.GET.get("bgc_id")

    if output_type not in {"gbk", "fna", "faa", "json"}:
        return HttpResponseBadRequest(
            "Invalid output_type; choose gbk, fna, faa, or json"
        )

    status = get_job_status(search_key=encoded_params)

    if status.get("status") != "SUCCESS":
        return HttpResponseBadRequest(
            "No cached record found. Provide a valid search_key or bgc_id"
        )

    else:
        payload = status.get("result") or {}
        try:
            # Properly reconstruct the EnhancedSeqRecord from cached GenBank text
            record = EnhancedSeqRecord.from_genbank_text(
                payload["record_genebank_text"]
            )
        except Exception:
            log.exception(
                "Failed to reconstruct EnhancedSeqRecord from cache for search_key=%s",
                search_key,
            )
            return HttpResponseBadRequest(
                "Failed to reconstruct BGC record for download"
            )

    # record.annotations['source'] may be a dict or a JSON-encoded string
    source_meta = record.annotations.get("source", {})
    if isinstance(source_meta, str):
        try:
            source_meta = json.loads(source_meta)
        except Exception:
            source_meta = {}
    if isinstance(source_meta, dict):
        bgc_acc = source_meta.get("bgc_accession") or str(bgc_id)
    else:
        bgc_acc = str(bgc_id)

    if output_type == "gbk":
        payload = record.to_gbk()
        content_type = "application/genbank"
        ext = "gbk"
    elif output_type == "fna":
        payload = record.to_fna()
        content_type = "text/x-fasta"
        ext = "fna"
    elif output_type == "faa":
        payload = record.to_faa()
        content_type = "text/x-fasta"
        ext = "faa"
    else:  # json
        payload = record.to_json()
        content_type = "application/json"
        ext = "json"

    filename = f"{bgc_acc}.{ext}"
    resp = HttpResponse(payload, content_type=content_type)
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def download_results_tsv(request):
    """
    Generate and return a TSV file of the search results.
    """
    post_params = {k: request.GET.getlist(k) for k in sorted(request.GET)}
    sort = post_params.pop("sort", ["assembly_accession"])[0]
    order = post_params.pop("order", ["asc"])[0]
    encoded_params = urlencode(post_params, doseq=True)

    status = get_job_status(search_key=encoded_params)
    if not status or status.get("status") != "SUCCESS":
        log.info(
            "Results not ready yet for search_keys=%s; status=%s",
            encoded_params,
            (status or {}).get("status"),
        )
        return HttpResponse("No results available", status=400)

    payload = status.get("result") or {}
    df = payload.get("df")
    display_columns = [
        "accession",
        "assembly_accession",
        "contig_accession",
        "start_position_plus_one",
        "end_position",
        "detector_names",
        "class_names",
    ]

    if df is not None and hasattr(df, "sort_values"):
        df_sorted = df.sort_values(
            by=sort,
            ascending=(order == "asc"),
            kind="mergesort",  # stable sort
        )
    else:
        df_sorted = df

    filename = (
        f"bgc_search_results_{hashlib.md5(encoded_params.encode()).hexdigest()}.tsv"
    )
    response = HttpResponse(content_type="text/tab-separated-values")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    buf = StringIO()
    try:
        cast(Any, df_sorted)[display_columns].to_csv(buf, sep="\t", index=False)
    except Exception:
        # fallback: entire df
        cast(Any, df_sorted).to_csv(buf, sep="\t", index=False)

    response.write(buf.getvalue())
    buf.close()
    return response


def dashboard_spa(request):
    """Serve the React SPA for the Discovery Platform."""
    return render(request, "dashboard.html", {
        "FORCE_SCRIPT_NAME": settings.FORCE_SCRIPT_NAME,
        "DEBUG": settings.DEBUG,
    })


def custom_404_view(request, exception):
    """
    Custom 404 error view.
    """
    return render(request, "404.html", status=404)
