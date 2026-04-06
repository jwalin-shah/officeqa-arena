#!/bin/bash
# Local test harness for v12 — anti-spiral prompt, no MCP, no skills.
# Usage: ./run_local_v12.sh UID0001

set -euo pipefail

TASK_UID="${1:?Usage: $0 UID0001}"

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
SAMPLES_DIR="$REPO_ROOT/../final/.arena/samples"
TASK_DIR="$SAMPLES_DIR/officeqa-$(echo "$TASK_UID" | tr '[:upper:]' '[:lower:]')"

if [ ! -d "$TASK_DIR" ]; then
    echo "ERROR: Task not found at $TASK_DIR"
    exit 1
fi

# Read question from instruction.md
QUESTION=$(cat "$TASK_DIR/instruction.md")
EXPECTED=$(python3 -c "
import re
with open('$TASK_DIR/solution/solve.sh') as f:
    text = f.read()
m = re.search(r'ANSWEREOF\n(.*?)\nANSWEREOF', text, re.DOTALL)
print(m.group(1).strip() if m else 'UNKNOWN')
")

echo "=== $TASK_UID (v12-antispiral) ==="
echo "Question: ${QUESTION:0:120}..."
echo "Expected: $EXPECTED"

# Set up /app to match arena environment
APP_DIR="/tmp/arena_v12_$TASK_UID"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/resources"

# Copy task environment (resource files)
if [ -d "$TASK_DIR/environment" ]; then
    cp -r "$TASK_DIR/environment/"* "$APP_DIR/resources/" 2>/dev/null || true
fi

# Symlink /app -> our test dir
sudo rm -rf /app 2>/dev/null || true
sudo ln -sf "$APP_DIR" /app

echo "Resources: $(ls "$APP_DIR/resources/" | head -10)"

# Render prompt with jinja2
PROMPT=$(python3 -c "
from jinja2 import Template
import sys
with open('$REPO_ROOT/prompts/system_v12.j2') as f:
    tmpl = Template(f.read())
question = open('$TASK_DIR/instruction.md').read().strip()
print(tmpl.render(instruction=question))
")

# Build goose recipe — no MCP, matches v9 arena config
cat > /tmp/arena_v12_recipe_$TASK_UID.yaml << RECEOF
version: 1.0.0
title: arena-v12-$TASK_UID
description: v12 local test
instructions: "You are given a task and you need to complete it. Act autonomously."
prompt: |
$(echo "$PROMPT" | sed 's/^/  /')
extensions:
  - type: builtin
    name: developer
RECEOF

echo ""
echo "=== Running goose (v12-antispiral) ==="
export GOOSE_PROVIDER=openrouter
export GOOSE_MODEL=minimax/minimax-m2.5
export OPENROUTER_API_KEY=REDACTED
export GOOSE_DISABLE_KEYRING=true

timeout 300 goose run --recipe /tmp/arena_v12_recipe_$TASK_UID.yaml --max-turns 25 --output-format stream-json 2>&1 \
    | tee /tmp/arena_v12_${TASK_UID}.log \
    | grep -E "toolRequest|toolResponse|text" | tail -20

echo ""
echo "=== RESULT (v12-antispiral) ==="
if [ -f "/app/answer.txt" ]; then
    GOT=$(cat "/app/answer.txt")
    echo "Got:      $GOT"
    echo "Expected: $EXPECTED"
    python3 -c "
got = '$GOT'.strip().replace(',','').replace('\$','').replace('%','')
exp = '$EXPECTED'.strip().replace(',','').replace('\$','').replace('%','')
try:
    g, e = float(got), float(exp)
    pct = abs(g - e) / abs(e) * 100 if e != 0 else 0
    print(f'Diff: {pct:.2f}%  {\"PASS\" if pct <= 1 else \"FAIL\"} (1% tolerance)')
except:
    print(f'Cannot compare numerically: got={got} exp={exp}')
"
else
    echo "NO ANSWER WRITTEN"
    echo "Expected: $EXPECTED"
fi
