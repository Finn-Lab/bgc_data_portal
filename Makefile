.PHONY: cluster-create cluster-delete create-local-namespace create-local-secrets \
        dev deploy-local delete-local deploy-dev deploy-prod \
        test-unit test-integration test-e2e logs shell db-shell validate-secrets \
        clear-cache-redis clear-cache-celery clear-cache-django clear-cache \
        workspace-enter workspace-login workspace-claude workspace-sync-in workspace-sync-out \
        workspace-patch workspace-apply-patch workspace-set-api-key workspace-restart

ENV_FILE := deployments/k8s-local/.env.local

# ── Secrets validation ─────────────────────────────────────────────────────────
REQUIRED_VARS := DJANGO_SECRET_KEY DATABASE_URL POSTGRES_USER POSTGRES_PASSWORD \
                 POSTGRES_DB CELERY_BROKER_URL CELERY_RESULT_BACKEND DJANGO_CACHE_BACKEND

validate-secrets:
	@test -f $(ENV_FILE) || \
	  (echo "ERROR: $(ENV_FILE) not found." && \
	   echo "  Run: cp $(ENV_FILE).example $(ENV_FILE)" && exit 1)
	@for var in $(REQUIRED_VARS); do \
	    grep -q "^$$var=" $(ENV_FILE) || \
	      (echo "ERROR: $$var is missing in $(ENV_FILE)" && exit 1); \
	done
	@echo "Secrets OK"

# ── Cluster lifecycle ──────────────────────────────────────────────────────────
cluster-create:
	kind create cluster --config deployments/k8s-local/kind-cluster.yaml

cluster-delete:
	kind delete cluster --name bgc-local

# ── Secrets ───────────────────────────────────────────────────────────────────
create-local-namespace:
	kubectl apply -f deployments/k8s-local/manifests/00-namespace.yaml

create-local-secrets: validate-secrets create-local-namespace
	kubectl create secret generic bgc-data-portal-secret \
	  --from-env-file=$(ENV_FILE) -n bgc-local \
	  --dry-run=client -o yaml | kubectl apply -f -

# ── Local dev loop ────────────────────────────────────────────────────────────
dev:
	skaffold dev -p local

deploy-local: create-local-secrets
	skaffold run -p local

delete-local:
	skaffold delete -p local

# ── Remote deploy (requires KUBE_CONTEXT env var) ─────────────────────────────
deploy-dev:
	skaffold run -p dev --kube-context $(KUBE_CONTEXT)

deploy-prod:
	skaffold run -p prod --kube-context $(KUBE_CONTEXT)

# ── Tests ─────────────────────────────────────────────────────────────────────
test-unit:
	kubectl exec -n bgc-local deploy/bgc-data-portal-django -- pytest tests/unit/ -q

test-integration:
	kubectl exec -n bgc-local deploy/bgc-data-portal-django -- pytest tests/integration/ -q

test-e2e:
	pytest django/tests/e2e/playwright --e2e-base-url http://localhost:8080 -q

# ── Observability ─────────────────────────────────────────────────────────────
logs-django:
	kubectl logs -f -n bgc-local deploy/bgc-data-portal-django

logs-celery:
	kubectl logs -f -n bgc-local deploy/bgc-data-portal-celery

shell:
	kubectl exec -it -n bgc-local deploy/bgc-data-portal-django -- bash

db-shell:
	kubectl exec -it -n bgc-local statefulset/postgres -- psql -U bgc_dp_pg_user mgnify_bgcs

# ── Cache management ───────────────────────────────────────────────────────────
clear-cache-redis:
	@echo "Flushing Redis..."
	kubectl exec -n bgc-local deploy/redis -- redis-cli FLUSHALL

clear-cache-celery:
	@echo "Purging Celery task queues..."
	kubectl exec -n bgc-local deploy/bgc-data-portal-celery -- celery -A bgc_data_portal purge -f

clear-cache-django:
	@echo "Clearing Django cache..."
	kubectl exec -n bgc-local deploy/bgc-data-portal-django -- python manage.py shell -c "from django.core.cache import cache; cache.clear()"

clear-cache: clear-cache-redis clear-cache-celery clear-cache-django

# ── Workspace (Claude Code in isolated pod) ──────────────────────────────────
workspace-enter:
	./scripts/workspace.sh enter

workspace-login:
	./scripts/workspace.sh login

workspace-claude:
	./scripts/workspace.sh claude

workspace-sync-in:
	./scripts/workspace.sh sync-in

workspace-sync-out:
	./scripts/workspace.sh sync-out

workspace-patch:
	./scripts/workspace.sh patch

workspace-apply-patch:
	./scripts/workspace.sh apply-patch

workspace-set-api-key:
	./scripts/workspace.sh set-api-key

workspace-restart:
	./scripts/workspace.sh restart
