"""Integration tests for the ephemeral asset-upload endpoints.

Covers ``POST /assets/upload/``, ``GET /assets/{token}/status/``, and
``DELETE /assets/{token}/``. The Celery ``.delay`` call is patched so the
projection runs synchronously inside the test process — that gives us a
realistic end-to-end through the Redis cache without needing a worker.
"""

from __future__ import annotations

import io
import tarfile
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings


UPLOAD_URL = "/api/dashboard/assets/upload/"

# Disable Django Debug Toolbar interception for the integration tests so the
# JSON responses aren't run through the toolbar's HTML-injection template.
_disable_djdt = override_settings(
    DEBUG_TOOLBAR_CONFIG={"SHOW_TOOLBAR_CALLBACK": lambda _r: False},
    DEBUG=False,
)


def _has_umap_projected_column() -> bool:
    """The dashboard's iBGC roster query SELECTs ``umap_projected``. A pending
    migration on some local dev DBs leaves it unmigrated, which would fail
    these tests through no fault of the asset code under test. Skip in that
    case so the asset behaviour is still exercised by the round-trip /
    count / report tests further down (those don't go through the roster
    SQL path)."""
    from django.db import connection

    try:
        with connection.cursor() as c:
            c.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'discovery_integrated_bgc' "
                "AND column_name = 'umap_projected'"
            )
            return c.fetchone() is not None
    except Exception:  # noqa: BLE001
        return False


_skip_if_unmigrated = pytest.mark.skipif(
    not _has_umap_projected_column(),
    reason="discovery_integrated_bgc.umap_projected column missing — "
    "run `python manage.py migrate discovery` before running these tests.",
)


def _minimal_tarball() -> bytes:
    """Build a tiny valid tarball with one BGC so projection runs end-to-end."""
    members = {
        "assemblies.tsv": (
            b"assembly_accession\torganism_name\tsource\tassembly_type\n"
            b"A1\tFoo bar\tdemo\t2\n"
        ),
        "contigs.tsv": (
            b"assembly_accession\tsequence_sha256\taccession\tlength\n"
            b"A1\tcontig1\tC1\t10000\n"
        ),
        "detectors.tsv": (
            b"name\ttool\tversion\nantiSMASH:1\tantiSMASH\t1.0\n"
        ),
        "bgcs.tsv": (
            b"contig_sha256\tdetector_name\tstart_position\tend_position\n"
            b"contig1\tantiSMASH:1\t0\t1000\n"
        ),
    }
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def api_client():
    return Client()


@pytest.fixture
def synchronous_task():
    """Run ``process_asset_upload_task`` synchronously in-process.

    Patches ``.delay`` so the upload endpoint's ``async_result.id`` is a
    stub, then invokes the underlying task function in the same thread so
    Redis cache writes happen before we poll status.
    """
    import discovery.tasks as tasks_mod

    real_fn = tasks_mod.process_asset_upload_task

    class _StubResult:
        id = "task-sync-id"

    def fake_delay(*args, **kwargs):
        class _Self:
            request = type("R", (), {"id": "task-sync-id"})

        # Bound-task signature: (self, token)
        real_fn.run(*args, **kwargs)
        return _StubResult()

    with patch.object(tasks_mod.process_asset_upload_task, "delay", side_effect=fake_delay):
        yield


@_disable_djdt
@pytest.mark.django_db
def test_upload_rejects_non_gzip(api_client):
    response = api_client.post(
        UPLOAD_URL,
        data={"file": SimpleUploadedFile("upload.tar.gz", b"not a tarball")},
        format="multipart",
    )
    assert response.status_code == 400


@_disable_djdt
@pytest.mark.django_db
def test_upload_rejects_missing_file(api_client):
    response = api_client.post(UPLOAD_URL, data={}, format="multipart")
    assert response.status_code == 400


@_disable_djdt
@pytest.mark.django_db
def test_upload_round_trip(api_client, synchronous_task):
    """POST upload → projection runs synchronously → status SUCCESS →
    DELETE evicts the cache."""
    raw = _minimal_tarball()
    response = api_client.post(
        UPLOAD_URL,
        data={"file": SimpleUploadedFile("upload.tar.gz", raw)},
        format="multipart",
    )
    assert response.status_code == 202, response.content
    body = response.json()
    token = body["token"]
    assert body["task_id"] == "task-sync-id"

    # Status should be SUCCESS — the synchronous task ran during the POST.
    status_resp = api_client.get(f"/api/dashboard/assets/{token}/status/")
    assert status_resp.status_code == 200
    payload = status_resp.json()
    assert payload["state"] == "SUCCESS"
    assert payload["summary"]["n_ibgcs"] >= 1

    # Manifest + ibgc list should be present in the cache.
    assert cache.get(f"asset:{token}:manifest") is not None
    assert cache.get(f"asset:{token}:ibgcs") is not None

    # DELETE wipes them.
    evict = api_client.delete(f"/api/dashboard/assets/{token}/")
    assert evict.status_code == 204
    assert cache.get(f"asset:{token}:ibgcs") is None
    assert cache.get(f"asset:{token}:status") is None


@_disable_djdt
@pytest.mark.django_db
def test_status_unknown_token(api_client):
    response = api_client.get("/api/dashboard/assets/does-not-exist/status/")
    assert response.status_code == 200
    assert response.json()["state"] == "UNKNOWN"


@_disable_djdt
@_skip_if_unmigrated
@pytest.mark.django_db
def test_roster_injects_asset_rows(api_client, synchronous_task):
    """An asset_token on /ibgcs/roster/ surfaces the cached asset iBGCs at
    the top of page 1 with ``is_asset=True``."""
    raw = _minimal_tarball()
    upload = api_client.post(
        UPLOAD_URL,
        data={"file": SimpleUploadedFile("upload.tar.gz", raw)},
        format="multipart",
    )
    token = upload.json()["token"]

    response = api_client.get(
        f"/api/dashboard/ibgcs/roster/?asset_token={token}"
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["items"], "expected at least one asset row in the roster"
    first = body["items"][0]
    assert first["is_asset"] is True
    assert first["id"] < 0
    assert body["pagination"]["total_count"] >= 1


@_disable_djdt
@pytest.mark.django_db
def test_count_includes_asset_rows(api_client, synchronous_task):
    raw = _minimal_tarball()
    upload = api_client.post(
        UPLOAD_URL,
        data={"file": SimpleUploadedFile("upload.tar.gz", raw)},
        format="multipart",
    )
    token = upload.json()["token"]

    response = api_client.get(
        f"/api/dashboard/ibgcs/count/?asset_token={token}"
    )
    assert response.status_code == 200
    assert response.json()["exact_count"] >= 1


@_disable_djdt
@_skip_if_unmigrated
@pytest.mark.django_db
def test_report_snapshot_accepts_asset_id(api_client, synchronous_task):
    """Asset iBGCs can be shortlisted into the Report endpoint."""
    import json

    raw = _minimal_tarball()
    upload = api_client.post(
        UPLOAD_URL,
        data={"file": SimpleUploadedFile("upload.tar.gz", raw)},
        format="multipart",
    )
    token = upload.json()["token"]
    roster = api_client.get(
        f"/api/dashboard/ibgcs/roster/?asset_token={token}"
    ).json()
    neg_id = roster["items"][0]["id"]

    # No asset_token → 400.
    resp_no_token = api_client.post(
        "/api/dashboard/report/snapshot/",
        data=json.dumps({"ibgc_ids": [neg_id]}),
        content_type="application/json",
    )
    assert resp_no_token.status_code == 400

    # With asset_token → snapshot succeeds with n_ibgcs=1.
    resp = api_client.post(
        "/api/dashboard/report/snapshot/",
        data=json.dumps({"ibgc_ids": [neg_id], "asset_token": token}),
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["n_ibgcs"] == 1

    # GET the snapshot and confirm the asset row is in ibgc_rows.
    report = api_client.get(f"/api/dashboard/report/{body['token']}/").json()
    assert any(r["id"] == neg_id for r in report["ibgc_rows"])


@_disable_djdt
@_skip_if_unmigrated
@pytest.mark.django_db
def test_ibgc_detail_resolves_asset_via_negative_id(api_client, synchronous_task):
    raw = _minimal_tarball()
    upload = api_client.post(
        UPLOAD_URL,
        data={"file": SimpleUploadedFile("upload.tar.gz", raw)},
        format="multipart",
    )
    token = upload.json()["token"]
    roster = api_client.get(
        f"/api/dashboard/ibgcs/roster/?asset_token={token}"
    ).json()
    neg_id = roster["items"][0]["id"]

    # Without the token header → 404.
    no_header = api_client.get(f"/api/dashboard/ibgcs/{neg_id}/")
    assert no_header.status_code == 404

    # With the token header → asset payload.
    with_header = api_client.get(
        f"/api/dashboard/ibgcs/{neg_id}/", HTTP_X_ASSET_TOKEN=token
    )
    assert with_header.status_code == 200
    body = with_header.json()
    assert body["id"] == neg_id
    assert body["label"].startswith("iBGC-A")
