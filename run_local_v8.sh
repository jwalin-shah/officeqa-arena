#!/bin/bash
# Local test harness for v8 — base64 MCP, lean prompt, no skills.
# Usage: ./run_local_v8.sh UID0001 [prompt_variant]
#   prompt_variant: "lean" (default) or "guided" for A/B testing
#
# Runs goose locally with the same MCP server and prompt as arena submit.

set -euo pipefail

TASK_UID="${1:?Usage: $0 UID0001 [lean|guided]}"
PROMPT_VARIANT="${2:-lean}"

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
SAMPLES_DIR="$REPO_ROOT/../final/.arena/samples"
TASK_DIR="$SAMPLES_DIR/officeqa-$(echo "$TASK_UID" | tr '[:upper:]' '[:lower:]')"

if [ ! -d "$TASK_DIR" ]; then
    echo "ERROR: Task not found at $TASK_DIR"
    exit 1
fi

# Read question from instruction.md
QUESTION=$(cat "$TASK_DIR/instruction.md")
EXPECTED=$(cat "$TASK_DIR/solution/solve.sh" | grep -A1 "ANSWEREOF" | head -1 | sed "s/cat.*//;s/echo.*//;/^$/d" || true)
# Better: extract between ANSWEREOF markers
EXPECTED=$(sed -n '/^cat.*ANSWEREOF/,/^ANSWEREOF/{/ANSWEREOF/d;p}' "$TASK_DIR/solution/solve.sh")

echo "=== $TASK_UID ($PROMPT_VARIANT) ==="
echo "Question: ${QUESTION:0:120}..."
echo "Expected: $EXPECTED"

# Set up /app to match arena environment
APP_DIR="/tmp/arena_v8_$TASK_UID"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/resources"

# Copy task environment (resource files)
if [ -d "$TASK_DIR/environment" ]; then
    cp -r "$TASK_DIR/environment/"* "$APP_DIR/resources/" 2>/dev/null || true
fi

# Symlink /app -> our test dir so prompts using /app/ paths work
sudo rm -rf /app 2>/dev/null || true
sudo ln -sf "$APP_DIR" /app

echo "Resources: $(ls "$APP_DIR/resources/" | head -10)"
echo "/app -> $APP_DIR"

# Decode the MCP server from arena.yaml base64
python3 -c "
import base64, re, yaml
with open('$REPO_ROOT/arena.yaml') as f:
    config = yaml.safe_load(f)
args = config['agent']['mcp_servers'][0]['args']
# The base64 is in the bash -c command
cmd = args[1]
b64 = re.search(r\"echo '([A-Za-z0-9+/=]+)'\", cmd).group(1)
code = base64.b64decode(b64).decode()
with open('/tmp/_mcp_v8.py', 'w') as out:
    out.write(code)
print('MCP server decoded OK')
"

# Build prompt based on variant
if [ "$PROMPT_VARIANT" = "guided" ]; then
    PROMPT="You are a U.S. Treasury data analyst answering questions from government financial documents.

Your data is in /app/resources/ — start with *_page_*.txt files, fall back to .txt or .json.

You have MCP tools available — use them instead of curl or python3 -c:
- get_cpi(year) — CPI-U annual average 1913-2024. NEVER curl BLS/FRED.
- compute(expr, vars) — pct_change, stdev, mean, cagr, median, sum, min, max.
- fiscal_year_bounds(fiscal_year) — FY start/end dates.

Key rules: \"(123)\" means negative. Check units \"(in millions)\" vs \"(in thousands)\". FY pre-1977=Jul-Jun, post-1977=Oct-Sep. Bulletin year ≠ data year. Match EXACT row labels. Report percentages as 15.3 not 0.153. Wrong answer > no answer.

$QUESTION

Save your final answer to /app/answer.txt"
else
    # Lean prompt — matches what we submitted as v8
    PROMPT="You have MCP tools available:
- get_cpi(year) — CPI-U annual average 1913-2024
- compute(expr, vars) — pct_change, stdev, mean, cagr, median, sum, min, max
- fiscal_year_bounds(fiscal_year) — FY start/end dates

$QUESTION

Save your final answer to /app/answer.txt"
fi

# Build goose recipe with MCP extension
cat > /tmp/arena_v8_recipe_$TASK_UID.yaml << RECEOF
version: 1.0.0
title: arena-v8-$TASK_UID
description: v8 local test
instructions: "You are given a task and you need to complete it. Act autonomously."
prompt: |
$(echo "$PROMPT" | sed 's/^/  /')
extensions:
  - type: builtin
    name: developer
  - type: stdio
    name: officeqa
    cmd: python3
    args:
      - /tmp/_mcp_v8.py
RECEOF

echo ""
echo "=== Running goose ($PROMPT_VARIANT) ==="
export GOOSE_PROVIDER=openrouter
export GOOSE_MODEL=minimax/minimax-m2.5
export OPENROUTER_API_KEY=REDACTED
export GOOSE_DISABLE_KEYRING=true

timeout 300 goose run --recipe /tmp/arena_v8_recipe_$TASK_UID.yaml --output-format stream-json 2>&1 \
    | tee /tmp/arena_v8_${TASK_UID}_${PROMPT_VARIANT}.log \
    | grep -E "toolRequest|toolResponse|text" | tail -20

echo ""
echo "=== RESULT ($PROMPT_VARIANT) ==="
if [ -f "/app/answer.txt" ]; then
    GOT=$(cat "/app/answer.txt")
    echo "Got:      $GOT"
    echo "Expected: $EXPECTED"
    # Simple numeric comparison
    python3 -c "
got = '$GOT'.strip().replace(',','').replace('$','').replace('%','')
exp = '$EXPECTED'.strip().replace(',','').replace('$','').replace('%','')
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
