#!/bin/bash
# Local test harness for v13 — minimal prompt + tools.py accessible.
# Simulates the post-fix arena where tarball files land in /installed-agent/.
# Usage: ./run_local_v13.sh UID0004
#        ./run_local_v13.sh --batch UID0004 UID0005 UID0038 UID0061

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
SAMPLES_DIR="$REPO_ROOT/.arena/samples"
PROMPT_TEMPLATE="$REPO_ROOT/v13/prompts/system.j2"
TOOLS_PY="$REPO_ROOT/v13/tools.py"
MAX_TURNS=25

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

run_task() {
    local TASK_UID="$1"
    local TASK_DIR="$SAMPLES_DIR/officeqa-$(echo "$TASK_UID" | tr '[:upper:]' '[:lower:]')"

    if [ ! -d "$TASK_DIR" ]; then
        echo -e "${RED}Task not found: $TASK_DIR${NC}"
        return 1
    fi

    QUESTION=$(cat "$TASK_DIR/instruction.md")
    EXPECTED=$(python3 -c "
import re, os
solve = os.path.join('$TASK_DIR', 'solution', 'solve.sh')
if os.path.exists(solve):
    with open(solve) as f: text = f.read()
    m = re.search(r'ANSWEREOF\n(.*?)\nANSWEREOF', text, re.DOTALL)
    print(m.group(1).strip() if m else 'UNKNOWN')
else: print('UNKNOWN')
" 2>/dev/null || echo "UNKNOWN")

    echo "=== $TASK_UID ==="
    echo "Q: ${QUESTION:0:100}..."
    echo "Expected: $EXPECTED"

    # Set up /app and /installed-agent
    APP_DIR="/tmp/arena_v13_$TASK_UID"
    rm -rf "$APP_DIR"
    mkdir -p "$APP_DIR/resources"
    mkdir -p /tmp/installed-agent-v13

    # Copy task resource files
    if [ -d "$TASK_DIR/environment/resources" ]; then
        cp -r "$TASK_DIR/environment/resources/"* "$APP_DIR/resources/" 2>/dev/null || true
    elif [ -d "$TASK_DIR/environment" ]; then
        cp -r "$TASK_DIR/environment/"* "$APP_DIR/resources/" 2>/dev/null || true
    fi

    # Copy tools.py to /installed-agent/ (simulates tarball files in container)
    cp "$TOOLS_PY" /tmp/installed-agent-v13/tools.py

    # Symlink /app and /installed-agent
    sudo rm -rf /app 2>/dev/null || true
    sudo ln -sf "$APP_DIR" /app
    sudo rm -rf /installed-agent 2>/dev/null || true
    sudo ln -sf /tmp/installed-agent-v13 /installed-agent

    echo "Resources: $(ls "$APP_DIR/resources/" 2>/dev/null | wc -l | tr -d ' ') files"
    echo "Tools: $(ls /installed-agent/tools.py 2>/dev/null && echo 'OK' || echo 'MISSING')"

    # Render prompt
    PROMPT=$(python3 -c "
from jinja2 import Template
with open('$PROMPT_TEMPLATE') as f:
    tmpl = Template(f.read())
question = open('$TASK_DIR/instruction.md').read().strip()
print(tmpl.render(instruction=question))
")

    # Build goose recipe
    cat > /tmp/arena_v13_recipe.yaml << RECEOF
version: 1.0.0
title: arena-v13-$TASK_UID
description: v13 local test
instructions: "You are given a task and you need to complete it. Act autonomously."
prompt: |
$(echo "$PROMPT" | sed 's/^/  /')
extensions:
  - type: builtin
    name: developer
RECEOF

    export GOOSE_PROVIDER=openrouter
    export GOOSE_MODEL=minimax/minimax-m2.5
    export OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-REDACTED}"
    export GOOSE_DISABLE_KEYRING=true

    rm -f /app/answer.txt

    timeout 300 goose run \
        --recipe /tmp/arena_v13_recipe.yaml \
        --max-turns $MAX_TURNS \
        --output-format stream-json 2>&1 \
        | tee /tmp/arena_v13_${TASK_UID}.log > /dev/null

    # Result
    if [ -f "/app/answer.txt" ]; then
        GOT=$(cat "/app/answer.txt" | tr -d '\n')
        echo "Got:      $GOT"
        echo "Expected: $EXPECTED"
        python3 -c "
got = '''$GOT'''.strip().replace(',','').replace('\$','').replace('%','')
exp = '''$EXPECTED'''.strip().replace(',','').replace('\$','').replace('%','')
try:
    g, e = float(got), float(exp)
    pct = abs(g - e) / abs(e) * 100 if e != 0 else 0
    print(f'  {\"PASS\" if pct <= 1 else \"FAIL\"} (diff: {pct:.2f}%)')
except:
    if got.strip().lower() == exp.strip().lower():
        print('  PASS (exact)')
    else:
        print(f'  FAIL (got={got[:50]} exp={exp[:50]})')
"
    else
        echo "  NO ANSWER"
    fi
    echo ""
}

# Main
if [ "${1:-}" = "--batch" ]; then
    shift
    PASS=0; FAIL=0; NOANS=0; TOTAL=0
    for uid in "$@"; do
        ((TOTAL++))
        run_task "$uid" 2>/dev/null || true
        if [ -f "/app/answer.txt" ]; then
            GOT=$(cat "/app/answer.txt" | tr -d '\n')
            EXPECTED=$(python3 -c "
import re, os
TASK_DIR='$SAMPLES_DIR/officeqa-$(echo "$uid" | tr '[:upper:]' '[:lower:]')'
solve = os.path.join(TASK_DIR, 'solution', 'solve.sh')
if os.path.exists(solve):
    with open(solve) as f: text = f.read()
    m = re.search(r'ANSWEREOF\n(.*?)\nANSWEREOF', text, re.DOTALL)
    print(m.group(1).strip() if m else '')
else: print('')
" 2>/dev/null)
            python3 -c "
got = '''$GOT'''.strip().replace(',','').replace('\$','').replace('%','')
exp = '''$EXPECTED'''.strip().replace(',','').replace('\$','').replace('%','')
try:
    g, e = float(got), float(exp)
    pct = abs(g - e) / abs(e) * 100 if e != 0 else 0
    exit(0 if pct <= 1 else 1)
except: exit(1)
" 2>/dev/null && ((PASS++)) || ((FAIL++))
        else
            ((NOANS++))
        fi
    done
    echo "=== BATCH RESULTS: $PASS pass, $FAIL fail, $NOANS no-answer / $TOTAL total ($(( PASS * 100 / TOTAL ))%) ==="
else
    run_task "${1:?Usage: $0 UID0004 or $0 --batch UID0004 UID0005}"
fi
