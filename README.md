# MGnify Biosynthetic Gene Clusters (BGCs) Portal

MGnify BGCs is a web portal for exploring predicted biosynthetic gene clusters (BGCs) across MGnify metagenomic datasets. It harmonises outputs from multiple detection tools (e.g., antiSMASH, GECCO, SanntiS) and provides both an interactive UI and a programmatic API for search, download, and analysis.

The portal is developed by EMBL-EBI’s MGnify team as part of the EUREMAP project. See the About page content in `django/docs/about.qmd` for background, scope, and references.


## Features

- Explore BGCs and associated contigs/assemblies and metadata in a unified interface
- Multiple search modes:
	- Keyword search across metadata
	- Advanced faceted search (class, assembly/contig, domain filters, completeness, detectors)
	- Sequence-based search (nucleotide/protein; HMMER/cosine similarity; region vs CDS set)
	- Chemical structure search using SMILES
- Download a single BGC in GBK/FNA/FAA/JSON
- Export search results as TSV
- REST-like API powered by Django Ninja (`/api`)
- Asynchronous background processing using Celery (RabbitMQ broker, Redis result cache)


## Running tests

Unit/integration tests (pytest):

```bash
docker compose exec django pytest -q
```

End-to-end (Playwright) tests can target a running instance (see `pytest.ini`):

```bash
# Example (against dev site):
E2E_BASE_URL=https://bgc-portal-dev.mgnify.org pytest tests/e2e/playwright -q

# Or specify base URL via CLI option:
pytest tests/e2e/playwright -q --e2e-base-url http://localhost:8000
```

## Stack and architecture

- Django 5, Django Ninja (API), Django REST Framework (throttling)
- Celery workers (RabbitMQ broker, Redis result backend)
- PostgreSQL with pgvector extension (see `db/init/init_vector.sql`)
- Static files: collected by Django; served by NGINX in Kubernetes; WhiteNoise available
- Optional analytics via Matomo

Main services (local via Docker Compose):
- Postgres (pgvector)
- Redis
- RabbitMQ
- Django web app
- Celery worker


## Repository layout (high level)

- `django/` — Django project and app code, Dockerfile, requirements
- `django/bgc_data_portal/` — project settings, URLs, templates
- `django/mgnify_bgcs/` — app (API, models, tasks, utilities)
- `db/` — database Dockerfile and init scripts (pgvector)
- `deployments/` — Kubernetes manifests (dev/prod)
- `docs/` — Quarto site (compiled under `docs/_site/`) and content
- `tests/` — unit/integration/e2e test scaffolding
- `docker-compose.yml` — local development stack



## Quick start (Docker Compose)

1) Create a `.env` file at the repo root with the required environment variables. Minimal example for local use:

```
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=True

# Database (Compose uses service name `db`)
POSTGRES_USER=bgc_dp_pg_user
POSTGRES_PASSWORD=dummy_password
POSTGRES_DB=mgnify_bgcs
DATABASE_URL=postgres://bgc_dp_pg_user:dummy_password@db:5432/mgnify_bgcs

# Messaging + caching
CELERY_BROKER_URL=amqp://bgc_dp_user:dummy_password@rabbitmq:5672//
CELERY_RESULT_BACKEND=redis://redis:6379/1
DJANGO_CACHE_BACKEND=redis://redis:6379/0

# RabbitMQ defaults (for container init)
RABBITMQ_DEFAULT_USER=bgc_dp_user
RABBITMQ_DEFAULT_PASS=dummy_password

# Optional analytics and host settings for local dev
ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://localhost:8000
```

2) Start the stack:

```bash
docker compose up --build
```

This will:
- Build the Django image from `django/Dockerfile`
- Start Redis, Postgres (with `pgvector` enabled via `db/init/init_vector.sql`), RabbitMQ
- Run Django migrations and start the dev server on http://localhost:8000
- Start a Celery worker

Notes
- Compose mounts `./django` into the app container for rapid iteration.
- The app uses `/data/packages` for package ingestion and `/data/huggingface` as a cache; see volumes in `docker-compose.yml`.


## Environment variables

Key variables read by the app (see `django/bgc_data_portal/settings.py`):

- `DJANGO_SECRET_KEY` — Django secret key (required)
- `DJANGO_DEBUG` — Enable debug mode in development (`True`/`False`)
- `ALLOWED_HOSTS` — Comma-separated allowed hosts; required in non-debug
- `CSRF_TRUSTED_ORIGINS`, `CORS_TRUSTED_ORIGINS` — Optional origins lists
- `DJANGO_FORCE_SCRIPT_NAME` — Set when the app is hosted under a path prefix (used in prod)
- `DATABASE_URL` — Postgres connection URL
- `CELERY_BROKER_URL` — RabbitMQ broker URL
- `CELERY_RESULT_BACKEND` — Redis URL for Celery results
- `DJANGO_CACHE_BACKEND` — Redis URL for Django cache
- `MATOMO_URL`, `MATOMO_SITE_ID` — Optional analytics config
- `ADMIN_API_TOKEN`, `PROJECT_USER_TOKEN` — Bearer tokens for admin/project-scoped API endpoints




## Documentation

Content is authored with Quarto under `docs/` and `django/docs/`. The compiled site is in `docs/_site/`. To update:

1) Edit or add `.qmd` content (e.g., `django/docs/about.qmd`)
2) Render the site with Quarto
3) Keep `bgc_data_portal/templates/about.html` in sync with the rendered `about.html` for consistent in-app About content


## Deployment notes (Kubernetes)

Reference manifests:
- Dev: `deployments/k8s-dev/ebi-wp-k8s-hl.yaml`
- Prod: `deployments/k8s-prod/ebi-wp-k8s-hl.yaml`

Key components defined in the manifests:

- Proxy `ConfigMap` (proxies, `ALLOWED_HOSTS`, optional CSRF/CORS, Matomo in prod)
- Secret `bgc-data-portal-secret` with application env (DB, broker, cache, tokens)
- PostgreSQL (StatefulSet) with `pgvector` and persistent volume claim
- Redis (Deployment + Service)
- RabbitMQ (Deployment + Service)
- Django web app (Deployment + Service)
	- Dev runs `runserver`; Prod runs `gunicorn`
	- Prod sets `DJANGO_FORCE_SCRIPT_NAME=/finn-srv/mgnify-bgcs` for hosting under a path prefix
	- PVCs for static files and data packages; optional HuggingFace cache
- Celery worker (Deployment)
- Static NGINX (serves `/static/*` with correct MIME types)

Operational tips:
- Ensure `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` match the public host
- Set `DJANGO_DEBUG=False` in production
- Run `collectstatic` as part of the image build (already in `django/Dockerfile`) or via a Job, and ensure the static PVC is mounted where NGINX expects it
- Database readiness/liveness probes are present; adjust resources and PVC sizes as needed

## API quick start

- Base path: `/api`
- OpenAPI/Docs (Django Ninja): typically available at `/api/docs` in development
- Selected endpoints (see `django/mgnify_bgcs/api.py`):
	- `POST /api/search/keyword` — keyword search (async)
	- `POST /api/search/advanced` — advanced faceted search (async)
	- `POST /api/search/sequence` — sequence-based search (async)
	- `POST /api/search/chemical` — SMILES search (async)
	- `GET /api/download/bgc` — download a single BGC (gbk/fna/faa/json)
	- `GET /api/download/results-tsv` — download results for a task as TSV

Authentication
- Administrative DB-operation endpoints under `/api/db_op/*` require `Authorization: Bearer <ADMIN_API_TOKEN>`
- Ingestion endpoint `/api/upload/ingest_bgc` requires `Authorization: Bearer <PROJECT_USER_TOKEN>`


## Funding

This portal is part of the EUREMAP project, funded by the European Union under HORIZON-INFRA-2023-DEV-01-04 (Grant No. 101131663).


## License

Apache License 2.0. See LICENSE file in the repository root for details.
