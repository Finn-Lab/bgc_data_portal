# CLAUDE.md — BGC Data Portal

Django 5 web portal and REST API for Biosynthetic Gene Clusters (BGCs) in MGnify.

## Common Commands

### Local dev (Docker Compose)

```bash
docker compose up --build                          # Start full stack
docker compose exec django pytest -q               # Run all tests
docker compose exec django pytest tests/unit/test_foo.py -q          # Single file
docker compose exec django pytest tests/unit/test_foo.py::test_name -q  # Single test

# E2E (run outside the container; needs `playwright install chromium` once):
pytest tests/e2e/playwright/specs/test_bgc_journey.py -q \
    --e2e-base-url http://localhost:8000              # legacy /mgnify_bgcs surface
pytest tests/e2e/playwright/specs/test_v2_discovery_journey.py -q \
    --e2e-v2-base-url http://localhost:8000           # v2 NRB-first dashboard
```

### Code quality

```bash
ruff check . --fix      # Lint
black django/           # Format
pre-commit run --all-files
```

### Management commands

```bash
docker compose exec django python manage.py migrate
docker compose exec django python manage.py collectstatic
docker compose exec django python manage.py build_non_redundant_bgcs

# Clustering is an HPC handoff in prod (CLUSTERING_HPC_MODE=True):
#   1. export signature matrices, ship to HPC, run `bgc-cluster run`
docker compose exec django python manage.py export_clustering_inputs --run-tag <tag>
#   2. (HPC) sbatch deployments/cronjobs/slurm/bgc_clustering_cpu.sh in.tgz out.tgz
#   3. import the result tarball back into the DB
docker compose exec django python manage.py import_clustering_results /data/clustering_artifacts/imports/<tag>.tgz
#   rollback: restore per-NRB columns from a previous run's snapshot
docker compose exec django python manage.py set_active_clustering_run --sha <previous_sha>

# Dev-only (CLUSTERING_HPC_MODE unset): in-portal clustering still works.
docker compose exec django python manage.py run_bgc_clustering --apply
docker compose exec django python manage.py reclassify_bgcs --run <pk>
docker compose exec django python manage.py recompute_all_scores
docker compose exec django python manage.py update_discovery_stats
```


## Architecture

```
django/
  bgc_data_portal/        # Project settings, root URLs, template views
  discovery/              # v2 Discovery app (NRB-first)
    models.py             # ORM models (NonRedundantBGC, DashboardBgc, ClusteringRun, …)
    api.py                # Django Ninja REST API (OpenAPI at /api/docs)
    api_schemas.py        # Pydantic schemas for API I/O
    tasks.py              # Celery async tasks
    cache_utils.py        # Redis caching helpers
    services/             # Business logic layer
      clustering/         # Domain+adjacency Dice → KNN → hierarchical Leiden
        pipeline.py       # Orchestrator (persists per-run scoring cache)
        nrb_scoring.py    # NRB novelty + domain_novelty + partial projection
        reclassify.py     # KNN reclassification of non-primary DashboardBgcs
        metrics.py        # Sørensen–Dice similarity
        bgc_similarity.py # Composite weighted-mean Dice
        knn_graph.py      # Union top-k KNN graph
        leiden.py         # Hierarchical CPM Leiden
        layout.py         # UMAP (precomputed_knn) → DRL fallback
        adjacency.py      # Adjacency-pair matrix builder
        membership.py     # NRB × domain binary matrix builder
        non_redundant.py  # NonRedundantBGC table builder
      protein_search/     # phmmer-based sequence search
      report.py           # Shortlist Report payload builder
      stats.py            # Aggregations for BGC/Assembly stats panels
      ingestion/          # Stream-based NDJSON package ingestion
  mgnify_bgcs/            # Legacy app (pre-v2; being retired by P1.4b)
  tests/
    unit/
    integration/
    e2e/playwright/
```

## Key Patterns

**NRB-first** — In v2 the dashboard surfaces ``NonRedundantBGC`` rows (each consolidates one or more source ``DashboardBgc`` predictions). Old BGC-level endpoints (`/bgcs/{id}/`) still exist for drill-down but the primary unit everywhere is the NRB. `NonRedundantBGC.umap_projected = True` marks coords averaged from top-K primary neighbours (partials reclassified via KNN); `False` means the row was directly clustered.

**Composite-Dice similarity** — Replaces the retired ESM embedding HNSW. Per `ClusteringRun`, ``run_clustering_pipeline`` builds the NRB×NRB composite-Dice matrix (`w_d · Dice(domains) + w_a · Dice(adjacency-pairs)`) and persists it under `<CLUSTERING_ARTIFACTS_DIR>/<sha[:12]>/scoring_cache/`. The cache feeds NRB novelty scoring and the `/query/similar-nrb/` endpoint.

**NRB scoring** — `novelty_score = 1 − max(sim to validated NRB)` and `domain_novelty = |domains unique within leaf GCF| / |domains|` (NULL for singleton GCFs / NRBs without source-vocab domains). Computed inline by the pipeline (primary NRBs) and by `project_partial_nrbs` (partials, after reclassify).

**Async search** — POST to a search endpoint returns HTTP 202 with a `task_id`; poll the job-status endpoint for results. All search tasks run through Celery (RabbitMQ broker, Redis result backend). Sequence search uses pyhmmer's phmmer.

**Shortlist Report** — Stateless. `POST /report/snapshot/` accepts ≤100 NRB ids and returns a deterministic `sha256(sorted ids)[:32]` token after materialising the payload in Redis (`report:{token}` with 24h TTL). `GET /report/{token}/` serves the cached payload. No DB table; reload-safe within the TTL window.

**Ingestion** — stream-based NDJSON packages; all writes are idempotent upserts keyed on stable identifiers.

**API docs** — Swagger UI at `/api/docs`, ReDoc at `/api/redoc`.

## Stack

| Component | Technology |
|-----------|-----------|
| Web framework | Django 5 + Django Ninja |
| Database | PostgreSQL (pgvector kept for legacy embeddings until P1.4b drops them) |
| Cache / result backend | Redis |
| Task broker | RabbitMQ |
| Async workers | Celery |
| Production server | Gunicorn |
| Local dev | Docker Compose / Kind |

## Kubernetes Workspace (Claude Code in an isolated pod)

An isolated workspace pod in the Kind cluster where `claude --dangerously-skip-permissions` can run safely. All edits, shell commands, and git ops happen inside the pod.

```bash
# First time (Max account): log in via OAuth
make workspace-login              # follow the URL to authenticate

# Enter Claude Code directly
make workspace-claude

# Or enter a shell first
make workspace-enter

# After Claude makes changes, extract them as a patch:
make workspace-patch           # Creates workspace.patch on host
make workspace-apply-patch     # Applies the patch to host repo

# Refresh workspace with latest host code:
make workspace-sync-in
```
