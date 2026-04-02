#!/usr/bin/env bash
# Run OOM-fix variant on the same 19 tasks to validate improvements
# These are the tasks from pool-20260402T165000Z-oom-fix run

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The 19 tasks from previous OOM-fix run
TASK_UIDS="uid0001,uid0007,uid0011,uid0014,uid0021,uid0022,uid0027,uid0028,uid0034,uid0053,uid0114,uid0118,uid0153,uid0161,uid0165,uid0179,uid0188,uid0208,uid0216"

echo "Running OOM-fix variant on 19 tasks..."
echo "Tasks: $TASK_UIDS"
echo ""

cd "$SCRIPT_DIR"

# Run with the same tags as before for comparison
./scripts/do_runner_pool.sh run \
  --filter "officeqa-$(echo $TASK_UIDS | tr ',' '|')" \
  --tag "pool-$(date +%Y%m%dT%H%M%SZ)-oom-fix-v2" \
  2>&1 | tee pool_run_oom_fix_v2.log

echo ""
echo "Run complete. Check results in:"
echo "  results/runner_pool/"
echo ""
echo "Compare with baseline:"
python3 scripts/pull_telemetry.py --summary 2>&1 | tail -40
