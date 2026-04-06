#!/bin/bash
set -euo pipefail
TASK_UID="${1:?Usage: $0 UID0004 [prompt_file]}"
PROMPT_FILE="${2:-/home/daytona/officeqa-arena/prompts/system_v12.j2}"
TASK_UID_UPPER=$(echo "$TASK_UID" | tr '[:lower:]' '[:upper:]')

TASK_DIR="/tmp/task_${TASK_UID_UPPER}"
rm -rf "$TASK_DIR"
mkdir -p "$TASK_DIR"

for batch in /home/daytona/final/batch_*.tar.gz; do
    if tar tzf "$batch" 2>/dev/null | grep -q "^${TASK_UID_UPPER}/"; then
        tar xzf "$batch" -C "$TASK_DIR" "${TASK_UID_UPPER}/"
        break
    fi
done

if [ ! -f "$TASK_DIR/${TASK_UID_UPPER}/question.txt" ]; then
    echo "ERROR: Task $TASK_UID_UPPER not found"
    exit 1
fi

QUESTION=$(cat "$TASK_DIR/${TASK_UID_UPPER}/question.txt")
EXPECTED=$(cat "$TASK_DIR/${TASK_UID_UPPER}/answer.txt" 2>/dev/null || echo "UNKNOWN")

echo "=== $TASK_UID_UPPER ==="
echo "Q: ${QUESTION:0:120}..."
echo "Expected: $EXPECTED"

rm -rf /app/resources /app/answer.txt
mkdir -p /app/resources
cp "$TASK_DIR/${TASK_UID_UPPER}/resources/"* /app/resources/

# Render prompt - append question to template (replace {{ instruction }} or just append)
PROMPT=$(python3 -c "
t = open('$PROMPT_FILE').read()
q = open('$TASK_DIR/${TASK_UID_UPPER}/question.txt').read().strip()
if '{{ instruction }}' in t or '{{instruction}}' in t:
    print(t.replace('{{ instruction }}', q).replace('{{instruction}}', q))
else:
    print(t + '\n' + q)
")

cat > /tmp/recipe.yaml << RECEOF
version: 1.0.0
title: test
description: test
instructions: "You are given a task and you need to complete it. Act autonomously."
prompt: |
$(echo "$PROMPT" | sed 's/^/  /')
extensions:
  - type: builtin
    name: developer
RECEOF

export GOOSE_PROVIDER=openrouter
export GOOSE_MODEL=minimax/minimax-m2.5
export OPENROUTER_API_KEY=REDACTED
export GOOSE_DISABLE_KEYRING=true

timeout 300 goose run --recipe /tmp/recipe.yaml --max-turns 25 2>&1 | tail -5

echo ""
if [ -f "/app/answer.txt" ]; then
    GOT=$(cat "/app/answer.txt")
    echo "Got: $GOT"
    echo "Expected: $EXPECTED"
    python3 << PYEOF
got = '''$GOT'''.strip().replace(',','').replace('\$','').replace('%','')
exp = '''$EXPECTED'''.strip().replace(',','').replace('\$','').replace('%','')
try:
    g, e = float(got), float(exp)
    pct = abs(g - e) / abs(e) * 100 if e != 0 else 0
    print(f'VERDICT: {"PASS" if pct <= 1 else "FAIL"} (diff={pct:.2f}%)')
except:
    print(f'VERDICT: FAIL (non-numeric got={got} exp={exp})')
PYEOF
else
    echo "VERDICT: NO_ANSWER"
    echo "Expected: $EXPECTED"
fi
