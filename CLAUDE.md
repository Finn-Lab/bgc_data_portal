# CLAUDE.md — BGC Data Portal

Django 5 web portal and REST API for Biosynthetic Gene Clusters (BGCs) in MGnify.

## Common Commands

### Local dev (Docker Compose)

```bash
docker compose up --build                          # Start full stack
docker compose exec django pytest -q               # Run all tests
docker compose exec django pytest tests/unit/test_foo.py -q          # Single file
docker compose exec django pytest tests/unit/test_foo.py::test_name -q  # Single test
pytest tests/e2e/playwright -q --e2e-base-url http://localhost:8000  # E2E tests (run outside container)
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
docker compose exec django python manage.py calculate_aggregated_bgcs
docker compose exec django python manage.py update_current_stats
docker compose exec django python manage.py backfill_protein_embeddings
```

## Architecture

```
django/
  bgc_data_portal/        # Project settings, root URLs, template views
  mgnify_bgcs/            # Main app
    models.py             # ORM models (Bgc, GCF, Genome, …)
    api.py                # Django Ninja REST API (OpenAPI at /api/docs)
    api_schemas.py        # Pydantic schemas for API I/O
    tasks.py              # Celery async tasks
    searches.py           # Search orchestration
    filters.py            # Query filters
    cache_utils.py        # Redis caching helpers
    services/             # Business logic layer
      ingestion/          # Stream-based NDJSON package ingestion
      annotation/         # Annotation helpers
      search/             # Search utilities
      umap/               # UMAP dimensionality reduction
  tests/
    unit/
    integration/
    e2e/playwright/
```

## Key Patterns

**Async search** — POST to a search endpoint returns HTTP 202 with a `task_id`; poll the job-status endpoint for results. All search tasks run through Celery (RabbitMQ broker, Redis result backend).

**Vector similarity search** — `Bgc.embedding` is a 960-dim pgvector column with an HNSW index (cosine distance). Similarity queries use `<=>` operator via `pgvector`.

**Ingestion** — stream-based NDJSON packages; all writes are idempotent upserts keyed on stable identifiers.

**API docs** — Swagger UI at `/api/docs`, ReDoc at `/api/redoc`.

## Stack

| Component | Technology |
|-----------|-----------|
| Web framework | Django 5 + Django Ninja |
| Database | PostgreSQL + pgvector |
| Cache / result backend | Redis |
| Task broker | RabbitMQ |
| Async workers | Celery |
| Production server | Gunicorn |
| Local dev | Docker Compose |

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
