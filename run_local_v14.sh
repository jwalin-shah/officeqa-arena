#!/bin/bash
# Local test harness for v14 — mentor/intern + MCP backup
# Usage:
#   ./run_local_v14.sh UID0004                    # single task
#   ./run_local_v14.sh --batch UID0004 UID0005    # batch mode
#   ./run_local_v14.sh --batch-file flaky_38.txt  # from file

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
SAMPLES_DIR="$REPO_ROOT/.arena/samples"
V14_DIR="$REPO_ROOT/v14"
PROMPT_TEMPLATE="$V14_DIR/prompts/system.j2"
SOLVE_SCRIPT="$V14_DIR/solve_v14.py"
TOOLS_PY="$V14_DIR/tools.py"
MCP_SERVER="$V14_DIR/server/mcp_stdio.py"
MAX_TURNS=25

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

# Load env
source "$REPO_ROOT/.env" 2>/dev/null || true

run_task() {
    local TASK_UID="$1"
    local TASK_DIR="$SAMPLES_DIR/officeqa-$(echo "$TASK_UID" | tr '[:upper:]' '[:lower:]')"

    if [ ! -d "$TASK_DIR" ]; then
        echo -e "${RED}Task not found: $TASK_DIR${NC}"
        return 1
    fi

    # Read question and expected answer
    QUESTION=$(cat "$TASK_DIR/instruction.md")
    EXPECTED=$(python3 -c "
import json, os
meta_file = os.path.join('$TASK_DIR', 'metadata.json')
if os.path.exists(meta_file):
    with open(meta_file) as f:
        data = json.load(f)
    print(data.get('expected_answer', data.get('answer', '')))
else:
    ans_file = os.path.join('$TASK_DIR', 'answer.txt')
    if os.path.exists(ans_file):
        print(open(ans_file).read().strip())
    else:
        print('')
" 2>/dev/null)

    echo "Question: ${QUESTION:0:100}..."
    echo "Expected: $EXPECTED"

    # Set up resources directory (simulate oracle pages)
    RESOURCES_DIR="$TASK_DIR/resources"
    if [ ! -d "$RESOURCES_DIR" ]; then
        RESOURCES_DIR="$TASK_DIR"
    fi

    # Render prompt template
    RENDERED_PROMPT=$(python3 -c "
import sys
tmpl = open('$PROMPT_TEMPLATE').read()
question = '''$QUESTION'''
rendered = tmpl.replace('{{ instruction }}', question).replace('{{instruction}}', question)
print(rendered)
" 2>/dev/null)

    # Clean up previous answer
    rm -f /app/answer.txt 2>/dev/null || true
    mkdir -p /app 2>/dev/null || true

    # Set environment
    export CORPUS_DIR="$TASK_DIR"
    export ANSWER_PATH="/app/answer.txt"

    # Copy scripts to /installed-agent/ (simulate arena)
    mkdir -p /installed-agent/v14/server 2>/dev/null || true
    cp "$SOLVE_SCRIPT" /installed-agent/v14/ 2>/dev/null || true
    cp "$TOOLS_PY" /installed-agent/ 2>/dev/null || true
    cp "$MCP_SERVER" /installed-agent/v14/server/ 2>/dev/null || true

    # Symlink resources
    ln -sf "$RESOURCES_DIR" /app/resources 2>/dev/null || true
    ln -sf "$TASK_DIR" /app/corpus 2>/dev/null || true

    # Run with goose headless
    echo "Running goose..."
    timeout 300 goose run --model openrouter/minimax/minimax-m2.5 \
        --max-turns "$MAX_TURNS" \
        --prompt "$RENDERED_PROMPT" \
        2>&1 | tail -20

    # Check answer
    if [ -f /app/answer.txt ]; then
        GOT=$(cat /app/answer.txt)
        echo -e "Answer: $GOT"

        RESULT=$(python3 -c "
got = '''$GOT'''.strip().replace(',','').replace('\$','').replace('%','')
exp = '''$EXPECTED'''.strip().replace(',','').replace('\$','').replace('%','')
try:
    g, e = float(got), float(exp)
    if e == 0:
        print('PASS' if g == 0 else 'FAIL')
    else:
        pct = abs(g - e) / abs(e) * 100
        print('PASS' if pct <= 1 else 'FAIL')
except:
    print('FAIL')
" 2>/dev/null || echo "FAIL")

        if [ "$RESULT" = "PASS" ]; then
            echo -e "${GREEN}PASS${NC}"
            return 0
        else
            echo -e "${RED}FAIL${NC} (got: $GOT, expected: $EXPECTED)"
            return 1
        fi
    else
        echo -e "${YELLOW}NO ANSWER${NC}"
        return 1
    fi
}

# Main
if [ "${1:-}" = "--batch" ]; then
    shift
    PASS=0; FAIL=0; NOANS=0; TOTAL=0
    for UID in "$@"; do
        echo ""
        echo "============================================"
        echo "Task: $UID"
        TOTAL=$((TOTAL+1))
        if run_task "$UID"; then
            PASS=$((PASS+1))
        else
            if [ -f /app/answer.txt ] && [ -s /app/answer.txt ]; then
                FAIL=$((FAIL+1))
            else
                NOANS=$((NOANS+1))
            fi
        fi
        echo "TALLY: $PASS pass / $FAIL fail / $NOANS noans / $TOTAL total"
    done
    echo ""
    echo "============================================"
    echo "FINAL: $PASS/$TOTAL pass ($(( PASS * 100 / TOTAL ))%)"
elif [ "${1:-}" = "--batch-file" ]; then
    shift
    FILE="$1"
    UIDS=$(cat "$FILE" | grep -v '^#' | grep -v '^$')
    # Re-invoke with --batch
    exec "$0" --batch $UIDS
else
    run_task "${1:?Usage: $0 UID0004}"
fi
