Start the development sandbox.

Execute: `sandbox/sandbox.sh up`

This creates an isolated git clone at /tmp/bgc-sandbox/ and starts a full Docker stack (Django, Postgres, Redis, RabbitMQ, Celery) on separate ports so it doesn't conflict with the main dev stack.

After the sandbox is up, confirm:
1. All containers are healthy (`sandbox/sandbox.sh status`)
2. Django is accessible at http://localhost:8100
3. Report the sandbox directory path for future file edits
