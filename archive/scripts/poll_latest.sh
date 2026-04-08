#!/usr/bin/env bash
# Poll the most recent submission until it completes.
# Usage: ./scripts/poll_latest.sh [submission_id]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ARENA="$HOME/.arena/bin/arena"

SUB_ID="${1:-607acb7c-fec5-4629-890d-326d859c40ac}"

while true; do
    OUTPUT=$($ARENA status "$SUB_ID" 2>&1) || true
    clear
    echo "=== $(date '+%H:%M:%S') === Submission: $SUB_ID ==="
    echo "$OUTPUT"

    # Break if completed or failed
    if echo "$OUTPUT" | grep -qiE '(completed|failed)'; then
        echo ""
        echo "Done! Pulling results..."
        $ARENA results "$SUB_ID" 2>&1 || true
        break
    fi

    sleep 30
done
