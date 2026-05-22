"""Project-level NinjaAPI instance.

Owns the root ``/api`` mount. The Discovery router is attached in
``bgc_data_portal/urls.py`` under ``/discovery/``. A small ``/health``
endpoint stays here so monitoring / readiness probes don't have to
traverse the discovery surface.

This replaces the legacy ``mgnify_bgcs.api`` module that previously owned
the NinjaAPI instance (removed in the v2 refactor).
"""

from django.db import connection
from django.http import JsonResponse
from ninja import NinjaAPI

api = NinjaAPI(title="MGnify BGCs API", version="2.0")


@api.get("/health")
def health(request):
    """Lightweight service + database health check (unauthenticated)."""
    try:
        cur = connection.cursor()
        cur.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"status": "fail", "detail": str(exc)}, status=500)
    return JsonResponse({"status": "ok"}, status=200)
