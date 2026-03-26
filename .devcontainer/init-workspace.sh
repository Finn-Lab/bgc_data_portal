#!/usr/bin/env bash
set -euo pipefail

echo "=== BGC Data Portal: Dev Container initialization ==="

# ── Git safe directory (volume-mounted repos need this) ──────────────────
git config --global --add safe.directory /workspace

# ── Run migrations ───────────────────────────────────────────────────────
echo "Running Django migrations..."
cd /workspace/django
python manage.py migrate --noinput

# ── Collect static files ────────────────────────────────────────────────
echo "Collecting static files..."
python manage.py collectstatic --noinput 2>/dev/null || true

# ── Install pre-commit hooks ────────────────────────────────────────────
cd /workspace
if [ -f .pre-commit-config.yaml ]; then
    echo "Installing pre-commit hooks..."
    pre-commit install 2>/dev/null || true
fi

# ── Verify Claude Code ──────────────────────────────────────────────────
if command -v claude &>/dev/null; then
    echo "Claude Code: $(claude --version 2>/dev/null || echo 'installed')"
else
    echo "WARNING: Claude Code CLI not found — the devcontainer feature may still be installing."
fi

echo ""
echo "=== Dev container ready ==="
echo "  Django:  cd /workspace/django && python manage.py runserver 0.0.0.0:8000"
echo "  Tests:   cd /workspace/django && pytest tests/unit/ -q"
echo "  Claude:  claude --dangerously-skip-permissions"
echo ""
