# Rollout Runbook — NRB Dashboard + Embedding Retirement

**Target date:** 2026-05-14
**Source ref:** `dev @ b479900` (15 commits ahead of `origin/dev`, +16 uncommitted files)
**Targets (in order):** `bgc-data-portal-hl-exp` → `bgc-data-portal-hl-prod`

---

## 1. Context

Recent work (since `1c9a99a checkpoint: Report fixes`) replaces the ESM-embedding-based
similarity stack with the **composite-Dice / Leiden** NRB pipeline and ships the new
**NRB-first Discovery dashboard**, including:

- New filter surface (`detector_tools`, `assembly_type`, `chemont_ids`, `bgc_accession`,
  `assembly_ids`, `best_hit_protein_id`, `is_type_strain`, `source_names`)
- Shortlist Report v2 (Redis-only, deterministic token)
- phmmer-based protein sequence search (Celery)
- Hierarchical Leiden clustering + composite-Dice scoring cache

There are **no new PVCs, ConfigMaps, Secrets, or Ingress changes**. PVCs in both
namespaces are reused as-is. The risk vector is **destructive Django migrations**.

---

## 2. Destructive migrations summary

Five new discovery migrations vs. the previously released state. All three of the
non-additive ones are **irreversible without re-vectorising or re-clustering** from
ETL outputs.

| Migration | Op | Notes |
|-----------|-----|-------|
| `0015_discoverystats_and_more` | Additive (`DiscoveryStats` + index swap) | safe |
| `0016_bgcdomain_go_slim` | Additive (`BgcDomain.go_slim`) | safe |
| `0017_pair_based_clustering` | **Destructive** — drops `ClusterAssignment`, `BgcCluster`; removes ~15 legacy fields on `ClusteringRun` (UMAP/HDBSCAN/PCA blobs) | rollback infeasible |
| `0018_domain_clustering` | **Destructive** — drops `ProteinSimilarPair` table; reshapes `ClusteringRun` (adds composite-Dice + Leiden fields, removes pair-floor/dice-threshold) | rollback infeasible |
| `0020_drop_embeddings` | **Destructive** — drops `discovery_bgc_embedding`, `discovery_protein_embedding`, both HNSW indexes, plus `DashboardBgc.nearest_validated_accession` / `nearest_validated_distance` | irreversible without full re-vectorisation |

### About the missing `0019` slot

There is no `0019_*.py` on disk — the on-disk sequence jumps from `0018` to
`0020`. **This is intentional and safe** for two reasons:

1. Django plans migrations by the **dependency graph**, not by numeric order.
   `0020_drop_embeddings` declares `dependencies = [("discovery", "0018_domain_clustering")]`,
   so as long as `0018` is applied, `0020` is queued next regardless of the gap.
2. The author of `0020` explicitly anticipated the gap. From the migration
   docstring: *"The dev team's `makemigrations` may have inserted intermediate
   migrations (e.g. `0019_*`); list this one after them when applying."* The
   pinned dependency is `0018`, so any future-inserted `0019_*` would chain in
   naturally without breaking the deploy.

The one residual risk is a **phantom `0019` row in `django_migrations`** — i.e.
a previous checkpoint deploy applied a `0019_something.py` that has since been
deleted from the branch. Forward migrate still works (Django logs an "unknown"
migration warning and proceeds), but you should detect it before the rollout
so you know what's in your DB. Pre-flight check (run on **both** clusters):

```bash
kubectl exec -n bgc-data-portal-hl-exp deploy/bgc-data-portal-django \
  --context <ebi-context> -- \
  python -c "
from django.db import connection
with connection.cursor() as c:
    c.execute(\"SELECT app, name FROM django_migrations WHERE app='discovery' AND name LIKE '0019%';\")
    rows = c.fetchall()
    print('phantom 0019 rows:', rows or '(none — good)')
"
```

- **`(none — good)`** → proceed normally; `0020` applies cleanly after `0018`.
- **Any rows returned** → a previous checkpoint left a phantom `0019`. The
  forward migrate **still works** (the row is just inert), but flag it in the
  rollout log. Do **not** try to "fix" it by inserting a fake `0019` file —
  that would risk dependency resolution against `0020`. Leave the row in
  place; it will be cleaned up if/when a future `makemigrations` legitimately
  produces a `0019`.

Sanity-check after `migrate` runs that `0020_drop_embeddings` is the last
applied row:

```bash
kubectl exec -n bgc-data-portal-hl-exp deploy/bgc-data-portal-django \
  --context <ebi-context> -- python manage.py showmigrations discovery | tail -10
```

There are **no `mgnify_bgcs/` migrations new in this set**. The `Assembly.is_type_strain`
field referenced by the new API was added by `mgnify_bgcs/0019` long ago and is
already on both clusters.

### Migration execution model

Both manifests run migrations **inline in the Django pod startup command**:
```
cd /app && python manage.py migrate && python manage.py collectstatic --noinput && gunicorn ...
```
There is **no separate Job and no init container** for `migrate`. The rolling-update
will simply not flip Ready until migrate succeeds — but a failed migrate will
crashloop the new pod indefinitely while the old pod stays live. **You must verify
the migration completes (`kubectl logs … django`) before considering the rollout
done.**

---

## 3. Storage and infra

**No changes required.** PVCs (in both namespaces) are unchanged from the previous
release:

| PVC | Size | Mount | Notes |
|-----|------|-------|-------|
| `bgc-static-volume-claim` (prod) / `bgc-static-volume-claim-v2` (exp) | 2 Gi | `/app/staticfiles` | regenerated by `collectstatic` on every start |
| `bgc-ingest-packages-claim` | 5 Gi | `/data/packages` | ingest payloads |
| `bgc-hf-cache-claim` | 10 Gi | `/data/protein_search` | phmmer FASTA + `.ssi` (already populated since the previous phmmer rollout) |

`CLUSTERING_ARTIFACTS_DIR` defaults to `BASE_DIR/data/clustering_artifacts` inside
the pod (writable layer, **not a PVC**) — the composite-Dice scoring cache is
rebuilt by the next `run_bgc_clustering --apply` run, so this is fine but **a pod
restart loses the cache** until you re-run clustering.

No new Secret keys are required. The existing `bgc-data-portal-secret` covers all
new code paths.

---

## 4. Pre-flight (do this once, before touching either cluster)

```bash
cd services/bgc_data_portal
git status                         # 16 dirty files — commit or stash them first
git log origin/dev..HEAD --oneline # confirm 15 commits to push
git push origin dev                # optional — only needed if relying on CI to build :dev
```

1. **Commit or stash** the 16 uncommitted files (mix of `api.py`, `api_schemas.py`,
   `tasks.py`, `services/report.py`, and frontend). Whether you build through CI
   or via `make deploy-dev`, both use the checked-in tree; unstaged changes won't
   ship.
2. **Image build path — pick one:**
   - *Local build (recommended for this rollout):* skip the push and let
     `make deploy-dev` / `make deploy-prod` build the images themselves (see
     §7 and §8). This is the simplest path and gives you bit-for-bit control
     over what's deployed.
   - *CI build:* push `dev` to GitHub; `.github/workflows/release.yml` rebuilds
     `quay.io/microbiome-informatics/bgc_dp_web_site:dev` (and the worker) on
     every push to `dev`. Skip `make deploy-dev`'s build step by running
     `kubectl apply -f deployments/k8s-dev/ebi-wp-k8s-hl.yaml` directly once
     CI is green. **Note:** the CI prod path needs ` release ` (with surrounding
     spaces) in the commit message on `main` — for this rollout we rely on
     `make deploy-prod` instead, so that path is not needed.
3. **Pre-flight checks (local):**
   ```bash
   ruff check django/
   docker compose exec django pytest tests/unit -q     # smoke
   ```
4. **Login to the registry** so skaffold's push step works:
   ```bash
   docker login quay.io
   ```

---

## 5. Database safety (DO THIS BEFORE EXP)

Even though `bgc-data-portal-hl-exp` is "experimental", capture a snapshot —
re-seeding takes time. **Prod backup is mandatory.**

```bash
# EXP — quick logical dump from the postgres pod
kubectl exec -n bgc-data-portal-hl-exp statefulset/postgres \
  --context <ebi-context> -- \
  pg_dump -U bgc_dp_pg_user -Fc mgnify_bgcs \
  > backups/exp-pre-rollout-$(date +%Y%m%d).dump

# PROD — same shape, but also confirm a recent EBI HL volume snapshot exists.
kubectl exec -n bgc-data-portal-hl-prod statefulset/postgres \
  --context <prod-context> -- \
  pg_dump -U bgc_dp_pg_user -Fc mgnify_bgcs \
  > backups/prod-pre-rollout-$(date +%Y%m%d).dump
```

You don't need to dump the embedding tables specifically — they are not used by
any live code path any more — but the `pg_dump` captures them anyway in case you
ever want to rebuild similarity search the old way.

---

## 6. Verify the current migration state of each cluster

Before rolling out, confirm which of `0015–0020` are already applied so you know
which will fire on the new pod's `manage.py migrate`.

```bash
# EXP
kubectl exec -n bgc-data-portal-hl-exp deploy/bgc-data-portal-django \
  --context <ebi-context> -- python manage.py showmigrations discovery | tail -25

# PROD
kubectl exec -n bgc-data-portal-hl-prod deploy/bgc-data-portal-django \
  --context <prod-context> -- python manage.py showmigrations discovery | tail -25
```

Note the highest applied migration. If anything **above `0014`** is already
applied on prod, audit the gap before continuing — production should not have
seen the new ones yet.

---

## 7. Rollout to **experimental** (`bgc-data-portal-hl-exp`)

```bash
# Image is already built (step 4.2). Apply manifests.
KUBE_CONTEXT=<ebi-context> make deploy-dev
```

### Watch migration progress

```bash
kubectl logs -f -n bgc-data-portal-hl-exp deploy/bgc-data-portal-django \
  --context <ebi-context>
```

Expect to see, in order:
- `Applying discovery.0015_discoverystats_and_more… OK`
- `Applying discovery.0016_bgcdomain_go_slim… OK`
- `Applying discovery.0017_pair_based_clustering… OK`
- `Applying discovery.0018_domain_clustering… OK`
- `Applying discovery.0020_drop_embeddings… OK`
- `collectstatic` writing files
- gunicorn boot line

If `migrate` fails: roll the deployment back to the previous SHA before
`Skaffold` finalises the rollout (`kubectl rollout undo deploy/bgc-data-portal-django`).

### Post-migrate housekeeping (one-time, on exp)

```bash
# 1. The scoring cache and Redis cache reference the OLD schema. Flush both.
kubectl exec -n bgc-data-portal-hl-exp deploy/redis --context <ebi-context> -- \
  redis-cli FLUSHALL

kubectl exec -n bgc-data-portal-hl-exp deploy/bgc-data-portal-celery \
  --context <ebi-context> -- \
  celery -A bgc_data_portal purge -f

# 2. Re-run clustering so NRB rows / scoring cache / Leiden hierarchy exist.
kubectl exec -n bgc-data-portal-hl-exp deploy/bgc-data-portal-django \
  --context <ebi-context> -- \
  python manage.py run_bgc_clustering --apply

# 3. Refresh stats panels.
kubectl exec -n bgc-data-portal-hl-exp deploy/bgc-data-portal-django \
  --context <ebi-context> -- \
  python manage.py update_discovery_stats
```

> Skip step 2 if `showmigrations` already reported `0018_domain_clustering` as
> applied on exp — clustering will already have been run there.

### Verify exp

```bash
# 1. Smoke API
curl -I https://bgc-portal-dev.mgnify.org/api/docs

# 2. Unit tests inside the pod
kubectl exec -n bgc-data-portal-hl-exp deploy/bgc-data-portal-django \
  --context <ebi-context> -- pytest tests/unit/ -q

# 3. Hit the dashboard manually and confirm:
#    - NRB roster loads with the new is_type_strain badge
#    - TopFiltersStrip exposes the new chips (detector tools, ChemOnt, etc.)
#    - Shortlist report generation works end-to-end
#    - Protein sequence search returns NRB hits with best_hit_protein_id
```

Leave exp running for **at least one business day** before promoting. If anything
regresses, you can iterate on `dev` and re-push without touching prod.

---

## 8. Rollout to **production** (`bgc-data-portal-hl-prod`)

### Build/deploy mechanism — use `make deploy-prod`

`make deploy-prod` is the canonical entry point. The target runs:

```
skaffold run -p prod --kube-context $(KUBE_CONTEXT)
```

The `prod` profile in `skaffold.yaml` is **self-contained**:

1. Builds `quay.io/microbiome-informatics/bgc_dp_web_site` from `django/Dockerfile`
   (the *full* image — collectstatic, prod requirements, no dev tooling) on
   `linux/amd64`.
2. Builds `quay.io/microbiome-informatics/bgc_dp_web_site_worker` from
   `django/Dockerfile.worker`.
3. Pushes both with the `:latest` tag (`local.push: true`).
4. Deletes the lingering `bgc-integration-tests` / `bgc-e2e-tests` Helm-hook
   Jobs in the namespace (pre-deploy hook in skaffold.yaml).
5. `kubectl apply -f deployments/k8s-prod/ebi-wp-k8s-hl.yaml` into
   `bgc-data-portal-hl-prod`.

Crucially, **no `release portal` (or any other) commit message is required**.
The previous prod runbook documented the CI path
(`.github/workflows/release.yml` builds on `main` when a commit contains
` release `) — that's an *alternative* path useful when you don't want to
build locally, but `make deploy-prod` bypasses it entirely. For this
rollout, **use `make deploy-prod`** so the image you tested on exp is the
exact build you ship to prod (modulo Dockerfile vs Dockerfile.dev — see
caveat below).

> **Caveat (Dockerfile.dev vs Dockerfile):** exp runs the `Dockerfile.dev`
> image (`:dev`); prod runs the full `Dockerfile` image (`:latest`). The
> Python code is identical, but the *images* are different (different base
> deps, different layering). The exp soak validates code paths, not the prod
> image itself. After `make deploy-prod`, watch logs for any prod-image-only
> import or runtime errors.

> **Tag pinning:** `deployments/k8s-prod/ebi-wp-k8s-hl.yaml` pins `:latest`
> (a TODO in the manifest already calls this out). If you want
> bit-for-bit reproducibility, before running `make deploy-prod` edit the
> two `:latest` references to a SHA tag and tag the image manually before
> pushing. For a routine rollout, leaving `:latest` and relying on
> `imagePullPolicy: Always` is fine.

### Pre-flight

- Prod backup taken (step 5). ✅
- Exp has soaked without regressions. ✅
- Phantom-`0019` check run on prod (step 2). ✅
- `docker login quay.io` succeeded so skaffold's push step won't fail at
  the end of a long build.
- Announce the maintenance window — the rolling restart will pause Django
  briefly while migrate runs, and the clustering re-run (~minutes) blocks
  the Celery worker.

### Deploy

```bash
KUBE_CONTEXT=<prod-context> make deploy-prod
```

This is the one and only command. Skaffold will print build progress for
both images, push them to quay, then stream `kubectl apply` output. The
rolling update starts as soon as `apply` returns.

### Watch migration progress

```bash
kubectl logs -f -n bgc-data-portal-hl-prod deploy/bgc-data-portal-django \
  --context <prod-context>
```

Same expected sequence as exp. **Do not proceed until you see gunicorn boot.**

### Post-migrate housekeeping (prod)

```bash
# 1. Flush stale caches (response payloads include new fields).
kubectl exec -n bgc-data-portal-hl-prod deploy/redis --context <prod-context> -- \
  redis-cli FLUSHALL

kubectl exec -n bgc-data-portal-hl-prod deploy/bgc-data-portal-celery \
  --context <prod-context> -- \
  celery -A bgc_data_portal purge -f

# 2. Re-run clustering so NRBs are populated with composite-Dice / Leiden
#    output. Required because 0017 dropped the legacy cluster tables.
kubectl exec -n bgc-data-portal-hl-prod deploy/bgc-data-portal-django \
  --context <prod-context> -- \
  python manage.py run_bgc_clustering --apply

# 3. Refresh dashboard stats panels.
kubectl exec -n bgc-data-portal-hl-prod deploy/bgc-data-portal-django \
  --context <prod-context> -- \
  python manage.py update_discovery_stats

# 4. Protein index — only needed if /data/protein_search is empty (it
#    should NOT be on prod after the previous phmmer rollout). Verify with:
kubectl exec -n bgc-data-portal-hl-prod deploy/bgc-data-portal-celery \
  --context <prod-context> -- ls -lh /data/protein_search

# If empty:
# kubectl exec -n bgc-data-portal-hl-prod deploy/bgc-data-portal-celery \
#   --context <prod-context> -- python manage.py build_protein_search_index --rebuild
```

### Verify prod

```bash
# 1. Smoke API
curl -I https://www.ebi.ac.uk/finn-srv/mgnify-bgcs/api/docs

# 2. Unit tests (DB-free, safe in prod)
kubectl exec -n bgc-data-portal-hl-prod deploy/bgc-data-portal-django \
  --context <prod-context> -- pytest tests/unit/ -q

# 3. UI walkthrough on https://www.ebi.ac.uk/finn-srv/mgnify-bgcs:
#    - dashboard loads, NRB roster paginates
#    - new filters return the expected counts
#    - report download works
#    - protein sequence search returns results
```

---

## 9. Rollback

> Forward-only beyond `0017`. Once `0017/0018/0020` apply, **the embedding tables
> and pair tables no longer exist**.

- **Code-only regression (e.g. a frontend bug):** re-tag the previous
  `bgc_dp_web_site` image as `:latest` on quay or pin a SHA in the manifest and
  `kubectl apply` + `kubectl rollout restart deployment/bgc-data-portal-django`.
- **Migration regression discovered before going to prod:** restore the EXP DB
  from the dump in step 5; redeploy with the previous image. Production is
  untouched.
- **Migration regression after prod deploy:** restore the prod DB from the dump
  in step 5; redeploy the previous image. Re-vectorising / re-clustering from
  ETL is required to rebuild the dropped tables — this is hours, not minutes.
  Prefer fixing forward.

---

## 10. Known caveats and follow-ups

- `CLUSTERING_ARTIFACTS_DIR` is in the pod's writable layer; **a pod restart wipes
  the scoring cache** until the next `run_bgc_clustering --apply`. Consider
  promoting this to a small PVC in a follow-up.
- `:latest` is still pinned in `deployments/k8s-prod/ebi-wp-k8s-hl.yaml` — pin to
  the released SHA for true reproducibility.
- The dashboard introduces `best_hit_protein_id` plumbing that depends on the
  phmmer index existing in `/data/protein_search`. The PVC carries over from the
  previous release, but verify the directory is non-empty before declaring done.
- The discovery report endpoint returns a deterministic Redis-keyed token with a
  24h TTL — users who held a tab open across the cache flush in step 7/9 will
  need to regenerate their shortlist.
