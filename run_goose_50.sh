#!/usr/bin/env bash
# Run Goose on 50 tasks: the original 19 + 31 more
# Tests improvements: status fields, grep capping, abort rules

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Original 19 from oom-fix run
ORIGINAL_19="uid0001,uid0007,uid0011,uid0014,uid0021,uid0022,uid0027,uid0028,uid0034,uid0053,uid0114,uid0118,uid0153,uid0161,uid0165,uid0179,uid0188,uid0208,uid0216"

# Add 31 more to make 50 total
# Pick a mix of easy and hard from remaining 227
ADDITIONAL_31="uid0002,uid0003,uid0004,uid0005,uid0006,uid0008,uid0009,uid0010,uid0012,uid0013,uid0015,uid0016,uid0017,uid0018,uid0019,uid0020,uid0023,uid0024,uid0025,uid0026,uid0029,uid0030,uid0031,uid0032,uid0033,uid0035,uid0036,uid0037,uid0038,uid0039,uid0040"

ALL_50="${ORIGINAL_19},${ADDITIONAL_31}"

echo "============================================"
echo "Running Goose on 50 tasks"
echo "============================================"
echo ""
echo "Original 19 (from oom-fix):"
echo "  - 7 passed, 12 failed"
echo ""
echo "Adding 31 more (mix of easy/harder)"
echo ""
echo "Expected improvements:"
echo "  - Status fields detect MCP failures faster"
echo "  - Grep capped at 10 lines (no 100k token explosions)"
echo "  - Abort after 2 failed attempts instead of looping"
echo ""

cd "$SCRIPT_DIR"

RUN_TAG="pool-$(date +%Y%m%dT%H%M%SZ)-goose-50-v2"

echo "Starting run with tag: $RUN_TAG"
echo ""

./scripts/do_runner_pool.sh run \
  --uids "$ALL_50" \
  --cases data/officeqa_full.csv \
  --tag "$RUN_TAG" \
  2>&1 | tee goose_50_run.log

echo ""
echo "============================================"
echo "Run complete!"
echo "============================================"
echo ""
echo "Results in: results/runner_pool/$RUN_TAG/"
echo ""
echo "Summary:"
python3 scripts/pull_telemetry.py --summary 2>&1 | head -80
