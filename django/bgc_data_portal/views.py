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

"""Project-level views.

Trimmed in the v2 refactor: legacy ``search``/``results``/``bgc_page``/
``download_bgc``/``download_results_tsv`` handlers are gone — those
surfaces lived under ``/legacy/*`` and were retired with the
``mgnify_bgcs`` app. The remaining views serve the static portal pages
(landing, about, docs) and the React SPA at ``/dashboard/``.
"""

import logging
import os

from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import render
from django.views.generic import TemplateView

log = logging.getLogger(__name__)
numeric_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
log.setLevel(numeric_level)


class DocsView(TemplateView):
    def get(self, request, path="index.html", *args, **kwargs):
        file_path = os.path.join(settings.BASE_DIR, "docs", "_site", path)
        if os.path.exists(file_path):
            return FileResponse(open(file_path, "rb"))
        raise Http404("File not found")


def landing_page(request):
    """Render the landing page."""
    return render(request, "landing_page.html")


def about(request):
    """Render the about page."""
    return render(request, "about.html")


def dashboard_spa(request):
    """Serve the React SPA for the Discovery Platform."""
    return render(request, "dashboard.html", {
        "FORCE_SCRIPT_NAME": settings.FORCE_SCRIPT_NAME,
        "DEBUG": settings.DEBUG,
    })


def custom_404_view(request, exception):
    """Custom 404 error view."""
    return render(request, "404.html", status=404)
