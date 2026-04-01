#!/bin/bash
# Poll Arena submission status and append to log
# Usage: bash scripts/poll_submission.sh [submission_id] [interval_seconds]
#
# Polls the Arena dashboard API and logs score/accuracy/cost/time.
# Press Ctrl+C to stop.

set -euo pipefail

SUBMISSION_ID="${1:-69e7d7ce-4bea-4d4f-b17a-1135562867b8}"
INTERVAL="${2:-30}"
LOG_FILE="results/submission_poll_log.csv"
DROPLET="root@209.38.75.192"
ARENA_BIN="/root/.arena/venv/bin/arena"

mkdir -p results

# Create CSV header if file doesn't exist
if [ ! -f "$LOG_FILE" ]; then
  echo "timestamp,score,success_pct,avg_cost,avg_time,est_tasks,projected_final,status" > "$LOG_FILE"
fi

echo "Polling submission $SUBMISSION_ID every ${INTERVAL}s..."
echo "Logging to $LOG_FILE"
echo "Press Ctrl+C to stop."
echo ""

while true; do
  ts=$(date '+%Y-%m-%d %H:%M:%S')

  # Get status from CLI
  status=$(ssh -o ConnectTimeout=5 "$DROPLET" \
    "cd /root/officeqa-arena && $ARENA_BIN status $SUBMISSION_ID 2>&1" 2>/dev/null \
    | grep -oP '(?<=Status:\s{5})\S+' || echo "unknown")

  echo "$ts | Status: $status"

  if [ "$status" = "completed" ]; then
    echo ""
    echo "=== COMPLETED ==="
    ssh "$DROPLET" "cd /root/officeqa-arena && $ARENA_BIN results $SUBMISSION_ID 2>&1"
    echo "$ts,COMPLETED,,,,,$status" >> "$LOG_FILE"
    break
  fi

  sleep "$INTERVAL"
done
