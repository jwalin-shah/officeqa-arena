#!/bin/bash
# A/B test: Run the SAME 20 tasks with two different PROMPTS.
# Same MCP server (143.244.177.156), same model, same turns — only prompt differs.
#
# Version A: Old grep-based prompt (lists MCP tools but workflow is grep/sed)
# Version B: Excited-expert prompt (MCP-first workflow, situational framing)
#
# Usage:
#   export OPENROUTER_API_KEY=...
#   ./deploy/daytona/ab-test.sh
#
# To run locally instead of Daytona:
#   cd /path/to/final-A && arena test --filter 'officeqa-{uid0007,uid0030,...}'
#   cd /path/to/final-B && arena test --filter 'officeqa-{uid0007,uid0030,...}'

set -e

SNAPSHOT_NAME="officeqa-arena-runner"
OPENROUTER_API_KEY="${OPENROUTER_API_KEY:?Must set OPENROUTER_API_KEY}"
ARENA_TOKEN=$(awk -F' = ' '/token/{print $2}' ~/.arena/credentials 2>/dev/null | head -1)
GH_TOKEN=$(gh auth token 2>/dev/null)

# 20-task test subset: mix of easy/medium/hard, includes the uid0007 failure
# Picked to cover: simple lookups, multi-year, percent change, geometric mean, CY/FY
TEST_UIDS="uid0004,uid0007,uid0013,uid0030,uid0042,uid0055,uid0067,uid0082,uid0100,uid0118,uid0127,uid0136,uid0154,uid0172,uid0190,uid0208,uid0226,uid0235,uid0244,uid0246"

# ─── Version A: Old server (lite MCP, grep-based prompt) ───────────────
setup_version_a() {
  local NAME="ab-test-version-a"

  echo "=== [A] Creating sandbox ==="
  daytona create --snapshot "$SNAPSHOT_NAME" --name "$NAME" 2>&1 | grep -v "^time=\|level=warning"

  echo "=== [A] Credentials ==="
  daytona exec "$NAME" -- bash -c "echo '[default]' > /root/.arena/credentials && echo 'token = ${ARENA_TOKEN}' >> /root/.arena/credentials" 2>&1 | grep -v "^time=\|level=warning"

  echo "=== [A] Cloning project ==="
  daytona exec "$NAME" -- bash -c "cd /workspace && git clone https://${GH_TOKEN}@github.com/jwalin-shah/officeqa-final final" 2>&1 | grep -v "^time=\|level=warning"

  echo "=== [A] Switching to OLD prompt (grep-based, same MCP server) ==="
  daytona exec "$NAME" -- bash -c "
    cd /workspace/final

    # Same MCP server — only change the prompt
    cat > prompts/system.j2 << 'PROMPT_EOF'
RULES:
1. NEVER use curl, wget, or internet access. All data is in /app/resources/ and /app/corpus/.
2. NEVER import numpy, scipy, pandas, sklearn, requests. Use only Python stdlib.
3. ALWAYS write answer: echo -n \"VALUE\" > /app/answer.txt
4. A wrong answer beats no answer — write your best guess early, then refine.
5. If the question refers to a chart/graph/figure/visual — immediately write \"0\" > /app/answer.txt and STOP.

You are a Treasury Data Analyst. Answer the question using local files only.

MCP TOOLS (use these — do not do arithmetic manually):
- search_corpus(query, bulletin?, limit?) — search across all bulletins
- get_table(bulletin, keyword, row_filter?) — structured table
- find_values(query, year?, month?) — one-shot lookup
- compute_expression: ALL math. Supports: sum, mean, stdev, geometric_mean, cagr, linreg, median, pct_change(old,new).
- get_cpi_index: CPI-U lookup.
- get_fiscal_year_bounds: Fiscal year start/end dates.
- verify_answer(answer, question_type?) — sanity check

WORKFLOW:
1. cat /app/resources/manifest.json — find source bulletin filenames.
2. grep -n -i \"keyword\" /app/corpus/treasury_bulletin_YYYY_MM.txt | head -30
3. sed -n 'START,ENDp' /app/corpus/treasury_bulletin_YYYY_MM.txt
4. Read rows carefully. Match row label and column header.
5. Use compute_expression for any calculation.
6. echo -n \"VALUE\" > /app/answer.txt

FORMAT: Plain number only. No units, no symbols. Examples: \"2602\"  \"1608.80\"  \"44463\"

{{ instruction }}
PROMPT_EOF
  " 2>&1 | grep -v "^time=\|level=warning"

  echo "=== [A] Running ${TEST_UIDS} ==="
  daytona exec "$NAME" -- bash -c "
    export ARENA_NO_AUTO_UPDATE=1
    export PATH=/root/.arena/bin:\$PATH
    export OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
    cd /workspace/final
    arena test --filter 'officeqa-{${TEST_UIDS}}' 2>&1
  " 2>&1 | tee /tmp/ab-test-A.log

  echo "=== [A] Complete ==="
}

# ─── Version B: New corpus server (full MCP, excited-expert prompt) ────
setup_version_b() {
  local NAME="ab-test-version-b"

  echo "=== [B] Creating sandbox ==="
  daytona create --snapshot "$SNAPSHOT_NAME" --name "$NAME" 2>&1 | grep -v "^time=\|level=warning"

  echo "=== [B] Credentials ==="
  daytona exec "$NAME" -- bash -c "echo '[default]' > /root/.arena/credentials && echo 'token = ${ARENA_TOKEN}' >> /root/.arena/credentials" 2>&1 | grep -v "^time=\|level=warning"

  echo "=== [B] Cloning project (already has new config) ==="
  daytona exec "$NAME" -- bash -c "cd /workspace && git clone https://${GH_TOKEN}@github.com/jwalin-shah/officeqa-final final" 2>&1 | grep -v "^time=\|level=warning"

  echo "=== [B] Running ${TEST_UIDS} ==="
  daytona exec "$NAME" -- bash -c "
    export ARENA_NO_AUTO_UPDATE=1
    export PATH=/root/.arena/bin:\$PATH
    export OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
    cd /workspace/final
    arena test --filter 'officeqa-{${TEST_UIDS}}' 2>&1
  " 2>&1 | tee /tmp/ab-test-B.log

  echo "=== [B] Complete ==="
}

# ─── Run both in parallel ──────────────────────────────────────────────
echo "Starting A/B test with ${TEST_UIDS}"
echo "  Version A: Grep-first prompt (same MCP server, same turns)"
echo "  Version B: MCP-first excited-expert prompt (same MCP server, same turns)"
echo ""

setup_version_a &
PID_A=$!

setup_version_b &
PID_B=$!

wait $PID_A
wait $PID_B

echo ""
echo "========================================="
echo "A/B Test Complete"
echo "========================================="
echo "Version A log: /tmp/ab-test-A.log"
echo "Version B log: /tmp/ab-test-B.log"
echo ""
echo "Compare results:"
echo "  grep 'Score:' /tmp/ab-test-A.log /tmp/ab-test-B.log"
echo "  grep 'PASS\|FAIL' /tmp/ab-test-A.log | sort"
echo "  grep 'PASS\|FAIL' /tmp/ab-test-B.log | sort"
