## nice to have
-Area	Hardening Step
Auth	Swap the single bearer token for JWT validation against your IdP (Auth0/OIDC).
Queue back-pressure	Apply Celery acks_late + task_time_limit; put HAProxy/NGINX in front of FastAPI with request-size limits.
Replayability / audit	Persist the raw payload object before enqueueing (e.g. S3 + record key in DB) so you can re-ingest with exact bytes later.
Schema evolution	Version the Pydantic schema (v1, v2) and route tasks by version header.
Observability	Push Celery metrics to Prometheus, traces to OpenTelemetry, and expose a /metrics endpoint.

- request bgc-data-portal-secret changes
