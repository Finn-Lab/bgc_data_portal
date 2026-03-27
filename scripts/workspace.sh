#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="bgc-local"
DEPLOY="workspace"
POD_LABEL="app=workspace"
APP_DIR="/app"

usage() {
    cat <<EOF
Usage: $0 <command>

Commands:
  enter           Open a shell in the workspace pod
  login           Authenticate Claude Code interactively (run once per pod lifetime)
  claude          Start Claude Code (--dangerously-skip-permissions) in the pod
  sync-in         Copy current django/ source into the running workspace pod
  sync-out        Copy workspace /app back to host django/
  patch           Generate a git patch inside the pod and copy it to host
  apply-patch     Apply a workspace patch to the host repo
  set-api-key     Create/update the workspace-secret with ANTHROPIC_API_KEY (pay-per-use)
  logs            Follow workspace pod logs
  restart         Restart the workspace pod
EOF
}

get_pod() {
    kubectl get pod -n "$NAMESPACE" -l "$POD_LABEL" \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null
}

case "${1:-}" in
  enter)
    kubectl exec -it -n "$NAMESPACE" "deploy/$DEPLOY" -- bash
    ;;

  login)
    echo "Logging in to Claude Code (Max account)..."
    echo "This opens an OAuth flow — follow the URL printed in the terminal."
    kubectl exec -it -n "$NAMESPACE" "deploy/$DEPLOY" -- claude login
    echo "Done. You can now run: $0 claude"
    ;;

  claude)
    kubectl exec -it -n "$NAMESPACE" "deploy/$DEPLOY" -- claude --dangerously-skip-permissions
    ;;

  sync-in)
    POD=$(get_pod)
    echo "Copying django/ -> $POD:$APP_DIR ..."
    kubectl cp django/ "$NAMESPACE/$POD:$APP_DIR"
    echo "Resetting workspace git baseline..."
    kubectl exec -n "$NAMESPACE" "$POD" -- bash -c \
      'cd /app && git add -A && git reset --hard HEAD'
    echo "Done. Files synced into workspace."
    ;;

  sync-out)
    POD=$(get_pod)
    echo "Copying $POD:$APP_DIR -> django/ ..."
    kubectl cp "$NAMESPACE/$POD:$APP_DIR" django/
    echo "Done. Files synced to host."
    ;;

  patch)
    POD=$(get_pod)
    echo "Generating git patch inside workspace..."
    kubectl exec -n "$NAMESPACE" "$POD" -- bash -c \
      'cd /app && git add -A && git diff --cached -- . ":!node_modules" ":!*/node_modules" ":!__pycache__" ":!*.pyc" ":!.venv" > /tmp/workspace.patch'
    kubectl cp "$NAMESPACE/$POD:/tmp/workspace.patch" ./workspace.patch
    LINES=$(wc -l < workspace.patch)
    if [ "$LINES" -eq 0 ]; then
      echo "No changes detected in workspace."
      rm -f workspace.patch
    else
      echo "Patch saved to ./workspace.patch ($LINES lines)"
      echo "Apply with: make workspace-apply-patch"
      # Reset baseline so next patch only contains new changes
      echo "Resetting workspace git baseline..."
      kubectl exec -n "$NAMESPACE" "$POD" -- bash -c \
        'cd /app && git add -A && git commit -m "baseline after patch extraction"'
    fi
    ;;

  apply-patch)
    if [[ ! -f workspace.patch ]]; then
      echo "ERROR: workspace.patch not found. Run '$0 patch' first."
      exit 1
    fi
    git apply --directory=django workspace.patch
    echo "Patch applied to host repo."
    ;;

  set-api-key)
    read -rsp "ANTHROPIC_API_KEY: " key
    echo
    kubectl create secret generic workspace-secret \
      --from-literal="ANTHROPIC_API_KEY=$key" \
      -n "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
    echo "Secret created. Restart workspace to pick it up: $0 restart"
    ;;

  logs)
    kubectl logs -f -n "$NAMESPACE" "deploy/$DEPLOY"
    ;;

  restart)
    kubectl rollout restart -n "$NAMESPACE" "deploy/$DEPLOY"
    echo "Workspace restarting..."
    kubectl rollout status -n "$NAMESPACE" "deploy/$DEPLOY" --timeout=120s
    ;;

  *)
    usage
    exit 1
    ;;
esac
