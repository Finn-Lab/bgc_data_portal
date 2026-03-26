#!/usr/bin/env bash
set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
SANDBOX_DIR="${BGC_SANDBOX_DIR:-$HOME/.bgc-sandbox}"
PROJECT_NAME="bgc-sandbox"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Helpers ──────────────────────────────────────────────────────────────────
compose() {
    docker compose -p "$PROJECT_NAME" -f "$SANDBOX_DIR/docker-compose.sandbox.yml" "$@"
}

info()  { echo "▸ $*"; }
error() { echo "✗ $*" >&2; exit 1; }

ensure_sandbox() {
    [[ -d "$SANDBOX_DIR" ]] || error "Sandbox not found at $SANDBOX_DIR. Run '$0 up' first."
}

# ── Commands ─────────────────────────────────────────────────────────────────

cmd_up() {
    local branch=""

    # Parse --branch flag
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --branch) branch="$2"; shift 2 ;;
            *) error "Unknown option: $1" ;;
        esac
    done

    # Default to current branch
    if [[ -z "$branch" ]]; then
        branch="$(git -C "$REPO_ROOT" branch --show-current 2>/dev/null || echo "main")"
    fi

    # Clone if sandbox doesn't exist
    if [[ ! -d "$SANDBOX_DIR/.git" ]]; then
        local remote_url
        remote_url="$(git -C "$REPO_ROOT" remote get-url origin)"
        info "Cloning $remote_url (branch: $branch) → $SANDBOX_DIR"
        git clone --depth=1 --branch "$branch" "$remote_url" "$SANDBOX_DIR" 2>/dev/null || {
            info "Branch '$branch' not on remote, cloning default branch and creating it locally"
            git clone --depth=1 "$remote_url" "$SANDBOX_DIR"
            git -C "$SANDBOX_DIR" checkout -b "$branch"
        }
    else
        info "Sandbox already exists at $SANDBOX_DIR"
    fi

    # Copy sandbox configs and any files from the working tree that may not be on the remote
    info "Syncing sandbox configuration files"
    cp "$SCRIPT_DIR/docker-compose.sandbox.yml" "$SANDBOX_DIR/docker-compose.sandbox.yml"
    cp "$SCRIPT_DIR/.env.sandbox" "$SANDBOX_DIR/.env.sandbox"

    # Sync the entire working tree into the clone (overwrite with local state)
    # This ensures dev Dockerfiles, local changes, etc. are available in the sandbox
    info "Syncing working tree into sandbox"
    rsync -a --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
        --exclude='node_modules' --exclude='.venv' --exclude='venv' \
        "$REPO_ROOT/" "$SANDBOX_DIR/"

    # Start the stack
    info "Starting Docker stack (project: $PROJECT_NAME)"
    compose up --build -d

    # Wait for Django to be ready (migrations run as part of the command)
    info "Waiting for Django to be ready..."
    for i in $(seq 1 60); do
        if compose exec -T django python -c "import django; django.setup()" 2>/dev/null; then
            break
        fi
        sleep 2
    done

    echo ""
    info "Sandbox is ready!"
    info "  Directory:  $SANDBOX_DIR"
    info "  Django:     http://localhost:8100"
    info "  Redis:      localhost:6479"
    echo ""
    info "Claude Code: edit files in $SANDBOX_DIR/django/"
    info "Run tests:   $0 test [unit|integration|PATH]"
}

cmd_down() {
    ensure_sandbox
    info "Stopping sandbox containers (keeping volumes and clone)"
    compose down
}

cmd_destroy() {
    info "Destroying sandbox completely"
    if [[ -f "$SANDBOX_DIR/docker-compose.sandbox.yml" ]]; then
        compose down -v --remove-orphans 2>/dev/null || true
    fi
    if [[ -d "$SANDBOX_DIR" ]]; then
        rm -rf "$SANDBOX_DIR"
        info "Removed $SANDBOX_DIR"
    fi
    info "Sandbox destroyed"
}

cmd_test() {
    ensure_sandbox
    local target="${1:-unit}"

    case "$target" in
        unit)        target="tests/unit/" ;;
        integration) target="tests/integration/" ;;
        # Otherwise treat as a literal path (e.g. tests/unit/test_foo.py::test_bar)
    esac

    info "Running pytest $target"
    compose exec -T django pytest "$target" -q
}

cmd_lint() {
    ensure_sandbox
    info "Running ruff check"
    (cd "$SANDBOX_DIR" && ruff check django/ --fix 2>/dev/null || true)
    info "Running black check"
    (cd "$SANDBOX_DIR" && black --check django/ 2>/dev/null || true)
}

cmd_status() {
    if [[ ! -d "$SANDBOX_DIR" ]]; then
        info "No sandbox found at $SANDBOX_DIR"
        return
    fi
    compose ps
}

cmd_logs() {
    ensure_sandbox
    local service="${1:-django}"
    compose logs -f "$service"
}

cmd_shell() {
    ensure_sandbox
    compose exec django bash
}

# ── Entrypoint ───────────────────────────────────────────────────────────────
usage() {
    cat <<EOF
Usage: $(basename "$0") <command> [options]

Commands:
  up [--branch NAME]       Create sandbox clone and start Docker stack
  down                     Stop containers (keep volumes + clone)
  destroy                  Remove everything (containers, volumes, clone)
  test [unit|integration|PATH]  Run pytest in sandbox container
  lint                     Run ruff + black on sandbox code
  status                   Show container status
  logs [django|celery]     Tail container logs
  shell                    Open bash in Django container

Environment:
  BGC_SANDBOX_DIR          Override sandbox location (default: /tmp/bgc-sandbox)
EOF
}

case "${1:-}" in
    up)      shift; cmd_up "$@" ;;
    down)    cmd_down ;;
    destroy) cmd_destroy ;;
    test)    shift; cmd_test "$@" ;;
    lint)    cmd_lint ;;
    status)  cmd_status ;;
    logs)    shift; cmd_logs "$@" ;;
    shell)   cmd_shell ;;
    -h|--help|help) usage ;;
    "") usage; exit 1 ;;
    *) error "Unknown command: $1. Run '$0 --help' for usage." ;;
esac
