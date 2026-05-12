#!/usr/bin/env bash
set -euo pipefail

# Seed the local discovery DB from staged-files tarballs.
#
# For each *.tgz in $STAGED_FILES_DIR (alphabetical order):
#   1. Resolve the django pod fresh (survives reschedules).
#   2. Copy the tarball as a SINGLE file via `kubectl cp` (robust for large
#      payloads — directory-cp shells out per file and is the main failure mode
#      that made the old Makefile recipe trip on the 245 MB mibig archive).
#   3. Extract inside the pod into /tmp/staged_files.
#   4. Run `python manage.py load_discovery_data` — first archive gets
#      --truncate (full reset); subsequent archives are additive.
# Per-archive stderr is tee'd into $LOG_DIR/<name>.log so failures aren't lost.

STAGED_FILES_DIR="${STAGED_FILES_DIR:-../../.SCRATCH/STAGED_FILES_SAMPLES}"
NS="${NS:-bgc-local}"
DEPLOY="${DEPLOY:-deploy/bgc-data-portal-django}"
POD_LABEL="${POD_LABEL:-app=bgc-data-portal-django}"

test -d "$STAGED_FILES_DIR" || {
    echo "ERROR: $STAGED_FILES_DIR not found. Place ETL .tgz archives there." >&2
    exit 1
}
shopt -s nullglob
archives=("$STAGED_FILES_DIR"/*.tgz)
shopt -u nullglob
if [ "${#archives[@]}" -eq 0 ]; then
    echo "ERROR: no *.tgz files in $STAGED_FILES_DIR. Nothing to load." >&2
    exit 1
fi

LOG_DIR=$(mktemp -d -t seed_real_data.XXXXXX)
echo "Per-archive logs -> $LOG_DIR"

truncate_flag="--truncate"
for tgz in "${archives[@]}"; do
    name=$(basename "$tgz")
    log="$LOG_DIR/${name%.tgz}.log"
    echo "==> $name (log: $log)"

    pod=$(kubectl get pod -n "$NS" -l "$POD_LABEL" \
          -o jsonpath='{.items[0].metadata.name}' 2>>"$log")
    test -n "$pod" || {
        echo "ERROR: no django pod in namespace $NS" >&2
        exit 1
    }
    echo "    pod=$pod"

    kubectl exec -n "$NS" "$pod" -- \
        rm -rf /tmp/staged_files /tmp/staged.tgz 2>>"$log"

    echo "    copying tarball to pod ..."
    kubectl cp "$tgz" "$NS/$pod:/tmp/staged.tgz" 2>>"$log"

    echo "    extracting inside pod ..."
    kubectl exec -n "$NS" "$pod" -- bash -c '
        set -e
        mkdir -p /tmp/staged_files
        tar -xzf /tmp/staged.tgz -C /tmp/staged_files
        rm /tmp/staged.tgz
        test -f /tmp/staged_files/assemblies.tsv
    ' 2>>"$log"

    echo "    loading (${truncate_flag:-additive}) ..."
    if ! kubectl exec -n "$NS" "$DEPLOY" -- \
            python manage.py load_discovery_data \
            --data-dir /tmp/staged_files $truncate_flag \
            2>>"$log"; then
        echo "ERROR: load_discovery_data failed for $name" >&2
        echo "---- tail of $log ----" >&2
        tail -50 "$log" >&2
        exit 1
    fi

    kubectl exec -n "$NS" "$pod" -- rm -rf /tmp/staged_files 2>>"$log" || true
    truncate_flag=""
done

echo "All archives loaded."
