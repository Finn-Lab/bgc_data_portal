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
from .api import api as ninja_api
from discovery.api import discovery_router

ninja_api.add_router("/discovery/", discovery_router)

handler404 = "bgc_data_portal.views.custom_404_view"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("about/", views.about, name="about"),
    path("docs/", views.DocsView.as_view(), {"path": "index.html"}, name="docs_index"),
    path("docs/<path:path>", views.DocsView.as_view(), name="docs_file"),
    path("docs/<path:path>/", views.DocsView.as_view(), name="docs"),
    path("", views.landing_page, name="landing_page"),
    path("dashboard/", views.dashboard_spa, name="dashboard"),
    re_path(r"^dashboard/.*$", views.dashboard_spa),
    path("api/", ninja_api.urls, name="api"),
] + debug_toolbar_urls()
