# k8s-dev Deployment

Deploy the BGC Data Portal to the EBI HL Kubernetes cluster (experimental namespace).

## Prerequisites

- Access to `quay.io/microbiome-informatics` — log in with `docker login quay.io`
- `kubeconfig` for the EBI HL cluster (ask the team for access)
- `skaffold` >= 2.13 and `kubectl` >= 1.29

## Secrets

`bgc-data-portal-secret` must exist in the namespace before any pods can start —
it provides credentials for PostgreSQL, RabbitMQ, Django, and Celery.

```bash
# Copy the dev secrets template and fill in every ${...} placeholder
cp deployments/k8s-dev/secrets-template.yaml /tmp/bgc-dev-secret.yaml
# Edit /tmp/bgc-dev-secret.yaml, then apply and remove
kubectl apply -f /tmp/bgc-dev-secret.yaml --context <your-ebi-kube-context>
rm /tmp/bgc-dev-secret.yaml
```

> `kubectl delete all` does **not** delete Secrets, so the secret survives a normal
> wipe. Only re-apply it when rotating credentials or after a full namespace deletion.

## Deploying

```bash
# Build Dockerfile.dev image, push to quay.io, and apply k8s-dev manifests
# kubectl config get-contexts
KUBE_CONTEXT=<your-ebi-kube-context> make deploy-dev
```

This runs `skaffold run -p dev` which:
1. Builds `quay.io/microbiome-informatics/bgc_dp_web_site` from `django/Dockerfile.dev`
2. Pushes the image to quay.io (tagged with the git commit SHA)
3. Applies `deployments/k8s-dev/ebi-wp-k8s-hl.yaml` to namespace `bgc-data-portal-hl-exp`

## CI-Triggered Builds

Every push to `main` that modifies `django/` triggers the
`.github/workflows/release.yml` pipeline, which:
- Builds and pushes the image automatically
- Tags it with the short git SHA

No manual push is needed for routine development — CI handles it.

## Viewing Logs

```bash
kubectl logs -f -n bgc-data-portal-hl-exp deploy/bgc-data-portal-django \
  --context <your-ebi-kube-context>
```

## Seeding the Dev Database

The `seed_data` management command populates the dev database with synthetic BGC data
without requiring a full ETL run.

```bash
# Exec into the running Django pod
kubectl exec -it -n bgc-data-portal-hl-exp deploy/bgc-data-portal-django \
  --context <your-ebi-kube-context> -- bash

# Inside the pod:
python manage.py seed_data                    # ~24 BGCs (small manifest)
python manage.py seed_data --manifest medium  # ~1 000 BGCs
python manage.py seed_data --clear --manifest medium  # wipe and re-seed
```

Use `medium` after a fresh deploy so search, pagination, and the UMAP scatter all have
enough data to exercise meaningfully.

## Clean Slate (Danger Zone)

To wipe all resources in the dev namespace and redeploy from scratch, run the commands
below **in order**. This permanently destroys the database and all persistent volumes —
there is no undo.

```bash
# --- DANGER: deletes all workloads and services ---
# kubectl delete all --all -n bgc-data-portal-hl-exp --context <your-ebi-kube-context>

# --- DANGER: destroys all data (Postgres, static files, packages, HF cache) ---
# kubectl delete pvc --all -n bgc-data-portal-hl-exp --context <your-ebi-kube-context>
```

After running these, recreate the secret (see [Secrets](#secrets)) if needed, then:

```bash
KUBE_CONTEXT=<your-ebi-kube-context> make deploy-dev
```

Then seed the fresh database:

```bash
kubectl exec -it -n bgc-data-portal-hl-exp deploy/bgc-data-portal-django \
  --context <your-ebi-kube-context> -- python manage.py seed_data --manifest medium
```

## Running Tests Against Dev

```bash
# Unit tests (no DB required — safe to run in any environment)
kubectl exec -n bgc-data-portal-hl-exp deploy/bgc-data-portal-django \
  --context <your-ebi-kube-context> -- pytest tests/unit/ -q

# Integration tests (read/write the dev DB — seed first)
kubectl exec -n bgc-data-portal-hl-exp deploy/bgc-data-portal-django \
  --context <your-ebi-kube-context> -- pytest tests/integration/ -q --tb=short
```

> **Note:** Integration tests write to the dev database. Run them only on the dev
> namespace — never against prod.

## Post-Deploy Verification

```bash
# Check the API docs endpoint responds
curl -I https://bgc-portal-dev.mgnify.org/api/docs

# Run unit tests inside the running pod
kubectl exec -n bgc-data-portal-hl-exp deploy/bgc-data-portal-django \
  --context <your-ebi-kube-context> -- pytest tests/unit/ -q
```

## Ingress

The dev environment is accessible at: `https://bgc-portal-dev.mgnify.org`

(Hostname and TLS are configured in `deployments/k8s-dev/ebi-wp-k8s-hl.yaml`.)
