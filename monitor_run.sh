#!/usr/bin/env bash
# Quick status check for the 50-task Goose run

RUN_TAG="pool-20260402T181120Z"

echo "=== GOOSE 50-TASK RUN MONITOR ==="
echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Run:  $RUN_TAG"
echo ""

echo "--- Active Tasks ---"
./scripts/do_runner_pool.sh status 2>&1 | grep -E "^===|bash|python" | head -20

echo ""
echo "--- Results Collected ---"
LANE_FILES=$(find results/runner_pool -name "lane*.jsonl" -type f -newer /tmp/mcp_bundle.tar.gz 2>/dev/null | wc -l)
echo "Lane result files: $LANE_FILES"

echo ""
echo "--- Droplet Progress ---"
ssh -o StrictHostKeyChecking=no root@143.198.48.7 "find /root/officeqa-serve/.runner_pool/$RUN_TAG -name '*.jsonl' -type f 2>/dev/null | wc -l" 2>/dev/null | xargs echo "Runner-01 results:" || echo "Runner-01: connection failed"
ssh -o StrictHostKeyChecking=no root@146.190.36.49 "find /root/officeqa-serve/.runner_pool/$RUN_TAG -name '*.jsonl' -type f 2>/dev/null | wc -l" 2>/dev/null | xargs echo "Runner-02 results:" || echo "Runner-02: connection failed"

echo ""
echo "Estimated completion: 11:50-12:00 UTC (based on 50 tasks, ~1-1.5 min each)"
