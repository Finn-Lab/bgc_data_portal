# Local Dev Setup (kind + Skaffold)

This runbook gets you a production-faithful local environment using
[kind](https://kind.sigs.k8s.io/) (Kubernetes in Docker) and
[Skaffold](https://skaffold.dev/). The dev image omits ML packages
(torch, esm, etc.) so first builds complete in ~3 min instead of ~20 min.

## Prerequisites

Install via Homebrew (macOS / Linux):

```bash
brew install kind kubectl skaffold make
# Docker Desktop or OrbStack must be running
```

Verify:

```bash
kind version      # >= 0.23
kubectl version   # >= 1.29
skaffold version  # >= 2.13
```

## First-time Setup

```bash
# 1. Create the kind cluster (exposes port 8080 on localhost)
make cluster-create

# 2. Copy secrets template and fill in values
#    The defaults work out-of-the-box for local dev
cp deployments/k8s-local/.env.local.example deployments/k8s-local/.env.local

# 3. Build dev image, create secrets, and deploy all services
make deploy-local

# make create-local-secrets
```

The first `make deploy-local` pulls base images and installs Python packages.
Subsequent runs use the Docker layer cache and are much faster.

## Active Development (hot-reload)

```bash
make dev
```

Skaffold watches for file changes and syncs `*.py`, `*.html`, `*.css`, `*.js`
directly into the running pod — no image rebuild needed. Django `runserver`
auto-reloads on `.py` changes. Celery restarts automatically via `watchmedo`.

## Accessing the App

| URL | Description |
|-----|-------------|
| `http://localhost:8080` | Django portal |
| `http://localhost:8080/api/docs` | Swagger UI |
| `http://localhost:8080/api/redoc` | ReDoc |
| `http://localhost:15672` | RabbitMQ management UI (guest / guest) |

> Port 8080 is mapped from container port 30080 via kind's `extraPortMappings`.

## Running Tests

```bash
# Unit tests (fast, no external services)
make test-unit

# Integration tests (requires running cluster)
make test-integration

# E2E Playwright tests (run outside cluster)
make test-e2e
```

## Useful Commands

```bash
make logs       # Tail Django logs
make shell      # bash shell inside Django pod
make db-shell   # psql inside postgres StatefulSet
```

## Teardown

```bash
make delete-local    # Remove Skaffold-managed resources
make cluster-delete  # Delete the kind cluster entirely
```

## Disk Hygiene

The Colima VM has a fixed disk allocation (default 100 GB). Image rebuilds and
the Docker build cache grow silently and will eventually starve the cluster —
when this happens postgres `initdb` fails with "No space left on device" and
rabbitmq's Erlang cookie file gets truncated, both presenting as
CrashLoopBackOff.

```bash
make tidy            # clean-images + docker builder prune (run when nagged)
make clean-images    # prune dangling images on host + Kind containerd
make nuke            # last resort: delete cluster + prune --volumes (wipes db)
```

`make dev` runs a preflight that warns when reclaimable Docker space crosses
`DISK_RECLAIMABLE_WARN_GB` (default 10 GB) and pauses 5 s — Ctrl-C to abort
and run `make tidy` first. It also waits for any in-progress namespace
termination before re-applying, so back-to-back `make dev` invocations no
longer hit the "namespace is being terminated" race.

### Clean Slate (Danger Zone)

To wipe all resources from the kind cluster without deleting the cluster itself
(preserves the kind node and avoids a slow re-pull of base images):

```bash
# --- DANGER: deletes all Skaffold-managed workloads and services ---
# kubectl delete all --all -n bgc-local

# --- DANGER: destroys all persistent data (Postgres volume, etc.) ---
# kubectl delete pvc --all -n bgc-local
```

After running these, redeploy:

```bash
make deploy-local
```

Then seed:

```bash
make shell
# with real data
make seed-real-data
# or, use synth data
python manage.py seed_data --manifest medium
```

If you want to destroy the cluster entirely (slower but fully clean):

```bash
make cluster-delete && make cluster-create && make deploy-local
```

## Seeding the Database with Synthetic Data

The portal ships with a manifest-driven factory layer that generates realistic synthetic
BGC data without needing a real ETL run. Use it to get a working dataset into your KIND
cluster immediately after `make deploy-local`.

### Seed the local KIND database

```bash
# Open a shell inside the running Django pod
make shell

# Seed with the small manifest (~24 BGCs — fast, good for feature dev)
python manage.py seed_data

# Seed with the medium manifest (~1 000 BGCs — good for UI / pagination work)
python manage.py seed_data --manifest medium

# Update the stats to display on website
python manage.py calculate_aggregated_bgcs
python manage.py update_current_stats

# Wipe everything and re-seed from scratch
python manage.py seed_data --clear --manifest small
```

The command prints a summary on completion:

```
Seed complete — summary:
  Studies:    2
  Assemblies: 4
  Contigs:    4
  BGCs:       12
  Proteins:   24
  Domains:    24
```

### Manifest files

Manifests live in `django/tests/factories/manifests/`.
Edit a manifest to change dataset shape without touching Python code:

| Key | Effect |
|-----|--------|
| `studies` | Number of Study objects |
| `assemblies_per_study` | Assemblies per study |
| `contigs_per_assembly` | Contigs per assembly |
| `bgcs_per_contig` | BGC regions per contig |
| `cds_per_bgc` | CDS (proteins) per BGC |
| `pfam_domains_per_protein` | Pfam domain hits per protein |
| `bgc_classes` | List of BGC class names to create |
| `detectors` | List of detector tool names to create |

Skaffold syncs `*.py` and `*.yaml` files into the pod automatically, so you can edit a
manifest locally and re-run `seed_data` without rebuilding the image.

You can also point to a custom manifest by absolute path inside the pod:

```bash
python manage.py seed_data --manifest /app/path/to/my.yaml
```

## Loading Real Precomputed Data

As an alternative to the synthetic seeders above, you can load real
precomputed data (the output of the ETL pipeline) into the local KIND
database. Use this when you want to exercise the portal against realistic
accessions, taxonomies, embeddings, etc., without re-running the ETL.

The data must be staged on the host as one or more `*.tgz` archives in
`../../.SCRATCH/STAGED_FILES_SAMPLES/` (i.e. `.SCRATCH/STAGED_FILES_SAMPLES/`
at the repository root). Each archive contains the TSV files consumed by
`load_discovery_data`.

```bash
make seed-real-data
```

What it does, in order:

1. Verifies that `../../.SCRATCH/STAGED_FILES_SAMPLES/` exists on the host
   and contains at least one `*.tgz` file. If not, the target aborts with a
   clear error **without touching the database**.
2. Resolves the running django pod.
3. For each `*.tgz` (in lexical order), in series:
   1. Extracts it to a host `mktemp -d`.
   2. Locates the directory containing `assemblies.tsv` (root, or one
      level down — anything deeper is rejected with an error).
   3. `kubectl cp`s that directory to `/tmp/staged_files` inside the pod.
   4. Runs `python manage.py load_discovery_data --data-dir /tmp/staged_files [--truncate]`.
      `--truncate` is passed **only on the first archive**; subsequent
      archives load additively.
   5. Cleans up `/tmp/staged_files` in the pod and the host tempdir
      (even if the loader fails).

End state of the DB = union of every archive's contents.

> **WARNING — destructive.** The first archive is loaded with `--truncate`,
> which wipes every discovery table. Do not run this against a database
> whose contents you care about. It is intended for the local KIND cluster
> only.

### Prerequisites

- The KIND cluster must be running (`make dev` or `make deploy-local`).
- `../../.SCRATCH/STAGED_FILES_SAMPLES/` must exist at the repository root
  and contain at least one ETL `*.tgz` archive. **If the directory is
  missing or contains no `*.tgz` files, the make target will exit non-zero
  and do nothing** — it will not silently truncate your DB or load an
  empty dataset.

### Expected archive layout

Each `*.tgz` must, after extraction, expose `assemblies.tsv` either at the
archive root or inside a single top-level directory. The full set of
required and optional TSV files (and their column contracts) is documented
in `django/discovery/services/ingestion/loader.py`. At a minimum each
archive must include:

- `detectors.tsv`
- `assemblies.tsv`
- `contigs.tsv`
- `bgcs.tsv`

Optional (loaded when present): `cds.tsv`, `cds_sequences.tsv`,
`contig_sequences.tsv`, `domains.tsv`, `embeddings_bgc.tsv`,
`embeddings_protein.tsv`, `natural_products.tsv`,
`np_chemont_classes.tsv`.

### Running with different options

`make seed-real-data` is a thin wrapper around the Django command. If you
want to skip the truncate (e.g. extend an existing dataset), skip the
in-pipeline stats step, or load a single archive on demand, invoke the
command directly inside the pod after copying the TSVs in yourself:

```bash
make shell
python manage.py load_discovery_data --data-dir /tmp/staged_files            # no truncate
python manage.py load_discovery_data --data-dir /tmp/staged_files --skip-stats
```

## Running Tests

### Unit tests (no DB required)

```bash
make shell
pytest tests/unit/ -q
```

### Integration tests (hits the KIND DB)

Integration tests use the same factory layer to build real DB rows.
The `small_dataset` fixture is session-scoped and runs once per pytest session.

```bash
make shell
pytest tests/integration/ -q --tb=short
```

Example test using the built-in fixtures:

```python
# tests/integration/test_example.py

def test_bgc_accession_format(bgc):
    # `bgc` fixture creates one BGC with the full relational chain
    assert bgc.accession.startswith("MGYB")
    assert bgc.contig.assembly.study.accession.startswith("ERP")

def test_small_dataset_counts(small_dataset):
    # session-scoped: built once and reused across all integration tests
    assert small_dataset["bgcs"] == 12

# Ad-hoc inline setup:
from tests.factories import BgcFactory, CdsFactory, ProteinFactory

def test_cds_relationship(db):
    bgc = BgcFactory()
    p = ProteinFactory()
    CdsFactory(contig=bgc.contig, protein=p)
    assert bgc.contig.cds.count() == 1
```

### E2E / Playwright tests

E2E tests run **outside** the cluster and talk to `http://localhost:8080`.
Seed the DB with the medium manifest first so there is enough data to exercise
pagination and search:

```bash
# In a separate terminal — seed while the cluster is running
make shell
python manage.py seed_data --manifest medium
exit

# Then run Playwright from your host machine
pytest tests/e2e/playwright -q --e2e-base-url http://localhost:8080
```

## Protein Search Index (phmmer)

The Discovery Dashboard "Protein Sequence" search runs `phmmer` against an
on-disk reference FASTA plus a `VERSION` stamp at
`$PROTEIN_SEARCH_INDEX_DIR` (default `/data/protein_search`). In the KIND
cluster this path is an `emptyDir` mounted only on the Celery pod, so the
index lives in the worker.

**You only need to build it once per fresh deploy.** After that, every
`load_discovery_data` run (manual or via `make seed-real-data`) automatically
enqueues an index update at the end. There's nothing to wire on subsequent
deploys — re-rolling Skaffold preserves the index unless the celery pod is
recreated (an emptyDir is destroyed when the pod is, which is why
`make seed-real-data` automatically rebuilds it).

### One-time bootstrap after `make deploy-local` / `make dev`

```bash
make build-protein-index     # = manage.py build_protein_search_index --rebuild on celery pod
```

### Steady state

| Action | Effect on the index |
|---|---|
| `python manage.py load_discovery_data --data-dir X` | Append-only update auto-enqueued at end |
| `python manage.py load_discovery_data --data-dir X --truncate` | Full rebuild auto-enqueued at end |
| `make seed-real-data` | Truncate + rebuild on first archive; subsequent archives append |
| `python manage.py load_discovery_data ... --skip-protein-index` | Skip the auto-update (e.g. while loading multi-archive batches) |
| Celery pod recreated (e.g. `kubectl delete pod`) | Index gone — rerun `make build-protein-index` |

The worker compares `VERSION` against its loaded copy on every query and
reloads the DB lazily, so updates become visible without a worker restart.

### Manual operations

```bash
make build-protein-index     # full rebuild from scratch
make update-protein-index    # append-only (skips already-indexed sha256s)
```

## Notes on Heavy Management Commands

`Dockerfile.dev` omits the heavier science packages (biopython, pyrodigal,
pyhmmer, rdkit, umap-learn). Management commands that need them must be
run using the full worker image:

```bash
docker run --rm -it \
  --env-file deployments/k8s-local/.env.local \
  quay.io/microbiome-informatics/bgc_dp_web_site_worker:latest \
  python manage.py build_protein_search_index --rebuild
```
