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

from django.contrib import admin
from django.urls import path, re_path
from debug_toolbar.toolbar import debug_toolbar_urls

from . import views
from mgnify_bgcs import api as mgnify_api
from discovery.api import discovery_router

mgnify_api.api.add_router("/dashboard/", discovery_router)

handler404 = "bgc_data_portal.views.custom_404_view"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("about/", views.about, name="about"),
    path("docs/", views.DocsView.as_view(), {"path": "index.html"}, name="docs_index"),
    path("docs/<path:path>", views.DocsView.as_view(), name="docs_file"),
    path("docs/<path:path>/", views.DocsView.as_view(), name="docs"),
    path("", views.landing_page, name="landing_page"),
    path(
        "bgc/",
        views.bgc_page,
        name="bgc_page",
    ),
    path("bgc/download/", views.download_bgc, name="download_bgc"),
    path("search/", views.search, name="search"),
    path("search/status/", views.job_status, name="job_status"),
    path("results/", views.results_view, name="results_view"),
    path(
        "results/download-tsv/", views.download_results_tsv, name="download_results_tsv"
    ),
    path("dashboard/", views.dashboard_spa, name="dashboard"),
    re_path(r"^dashboard/.*$", views.dashboard_spa),
    path("api/", mgnify_api.api.urls, name="api"),
] + debug_toolbar_urls()
