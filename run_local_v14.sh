#!/bin/bash
# Local test harness for v14 — mentor/intern + MCP backup
# Replicates arena environment: /app/resources, /app/corpus, /installed-agent/
#
# Usage:
#   ./run_local_v14.sh UID0004                    # single task
#   ./run_local_v14.sh UID0004 --dry-run          # set up only, run solve_v14.py
#   ./run_local_v14.sh --batch UID0004 UID0005    # batch mode
#   ./run_local_v14.sh --batch-file v14/test_uids.txt

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
V14_DIR="$REPO_ROOT/v14"
PROMPT_TEMPLATE="$V14_DIR/prompts/system.j2"
SOLVE_SCRIPT="$V14_DIR/solve_v14.py"
TOOLS_PY="$V14_DIR/tools.py"
MCP_SERVER="$V14_DIR/server/mcp_stdio.py"

# Configurable paths (override via env)
CSV_PATH="${CSV_PATH:-/tmp/officeqa_full.csv}"
CORPUS_DIR="${CORPUS_SRC:-$REPO_ROOT/corpus}"
PAGES_DIR="${PAGES_DIR:-/tmp/officeqa_reingest/officeqa_repo/treasury_bulletins_parsed/transformed_page_level}"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

# Load env
source "$REPO_ROOT/.env" 2>/dev/null || true

# Read a field from CSV by UID
read_csv_field() {
    local uid="$1" field="$2"
    python3 -c "
import csv
with open('$CSV_PATH') as f:
    for r in csv.DictReader(f):
        if r['uid'].upper() == '${uid}'.upper():
            print(r.get('$field', ''))
            break
"
}

run_task() {
    local TASK_UID="$1"
    local DRY_RUN="${2:-}"

    # Read task from CSV
    local QUESTION EXPECTED SOURCE_FILES SOURCE_DOCS
    QUESTION=$(read_csv_field "$TASK_UID" question)
    EXPECTED=$(read_csv_field "$TASK_UID" answer)
    SOURCE_FILES=$(read_csv_field "$TASK_UID" source_files)
    SOURCE_DOCS=$(read_csv_field "$TASK_UID" source_docs)

    if [ -z "$QUESTION" ]; then
        echo -e "${RED}UID not found in CSV: $TASK_UID${NC}"
        return 1
    fi

    echo "Question: ${QUESTION:0:120}..."
    echo "Expected: $EXPECTED"

    # Use /app if writable (root on Daytona/DO), else /tmp/arena_app
    if mkdir -p /app/resources 2>/dev/null; then
        APP_BASE="/app"
    else
        APP_BASE="/tmp/arena_app_$TASK_UID"
    fi
    AGENT_BASE="${INSTALLED_AGENT:-/installed-agent}"
    if ! mkdir -p "$AGENT_BASE/v14/server" 2>/dev/null; then
        AGENT_BASE="/tmp/arena_agent"
    fi

    rm -rf "$APP_BASE/resources" "$APP_BASE/answer.txt" 2>/dev/null || true
    mkdir -p "$APP_BASE/resources" "$APP_BASE/corpus" "$AGENT_BASE/v14/server"

    # Install agent scripts
    cp "$SOLVE_SCRIPT" "$AGENT_BASE/solve_v14.py"
    cp "$TOOLS_PY" "$AGENT_BASE/tools.py"
    cp "$MCP_SERVER" "$AGENT_BASE/v14/server/mcp_stdio.py"

    # Symlink corpus
    if [ -d "$CORPUS_DIR" ] && [ "$(ls -A "$CORPUS_DIR" 2>/dev/null)" ]; then
        ln -sf "$CORPUS_DIR"/* "$APP_BASE/corpus/" 2>/dev/null || true
    fi

    # Copy oracle files (source TXT + page-level extracts)
    python3 << SETUP_PY
import csv, os, re, shutil
csv_path = "$CSV_PATH"
task_uid = "$TASK_UID"
corpus_dir = "$CORPUS_DIR"
pages_dir = "$PAGES_DIR"
with open(csv_path) as f:
    for r in csv.DictReader(f):
        if r['uid'].upper() != task_uid.upper():
            continue
        source_files = [s.strip() for s in r['source_files'].split('\\n') if s.strip()]
        source_docs = r.get('source_docs', '')
        pages = re.findall(r'page=(\d+)', source_docs)
        for idx, src_file in enumerate(source_files):
            base = src_file.replace('.txt', '')
            # Full TXT
            src = os.path.join(corpus_dir, src_file)
            if os.path.exists(src):
                shutil.copy2(src, '$APP_BASE/resources/')
                print(f'  Copied: {src_file}')
            # Oracle page extract
            if idx < len(pages):
                page_src = os.path.join(pages_dir, f'{base}_{pages[idx]}.txt')
                if os.path.exists(page_src):
                    dest = f'$APP_BASE/resources/{base}_page_{pages[idx]}.txt'
                    shutil.copy2(page_src, dest)
                    print(f'  Page: {base}_page_{pages[idx]}.txt')
                else:
                    print(f'  MISSING page: {page_src}')
        break
SETUP_PY

    echo "Resources:"
    ls "$APP_BASE/resources/"

    if [ "$DRY_RUN" = "--dry-run" ]; then
        echo "=== DRY RUN — running solve_v14.py directly ==="
        RESOURCES_DIR="$APP_BASE/resources" CORPUS_DIR="$APP_BASE/corpus" ANSWER_PATH="$APP_BASE/answer.txt" \
            python3 "$SOLVE_SCRIPT" "$QUESTION" 2>&1
        return 0
    fi

    # Render prompt
    local RENDERED_PROMPT
    RENDERED_PROMPT=$(python3 -c "
tmpl = open('$PROMPT_TEMPLATE').read()
question = '''$QUESTION

## Available Resources

You have access to the full U.S. Treasury Bulletin corpus at \`/app/corpus/\`.

**Corpus location:** \`/app/corpus/\`
**File naming convention:** \`treasury_bulletin_YYYY_MM.txt\`

You must search through these files to find the relevant information to answer the question.

## Output

Write your final answer to \`$APP_BASE/answer.txt\`. Numerical answers should be precise (scoring uses 1%% tolerance).'''

rendered = tmpl.replace('{{ instruction }}', question).replace('{{instruction}}', question)
# Remap paths for local execution
rendered = rendered.replace('/app/', '$APP_BASE/')
rendered = rendered.replace('/installed-agent/', '$AGENT_BASE/')
print(rendered)
" 2>/dev/null)

    # Clean previous answer
    rm -f "$APP_BASE/answer.txt"

    # Build goose recipe with MCP
    local RECIPE="/tmp/arena_recipe_v14_$TASK_UID.yaml"
    cat > "$RECIPE" << RECEOF
version: 1.0.0
title: arena-v14-$TASK_UID
description: v14 mentor/intern test
instructions: "You are given a task and you need to complete it. Act autonomously."
prompt: |
$(echo "$RENDERED_PROMPT" | sed 's/^/  /')
extensions:
  - type: builtin
    name: developer
  - type: stdio
    name: officeqa
    cmd: python3
    args:
      - $AGENT_BASE/v14/server/mcp_stdio.py
    env:
      RESOURCES_DIR: "$APP_BASE/resources"
      CORPUS_DIR: "$APP_BASE/corpus"
RECEOF

    # Run goose
    echo "Running goose (v14, max 15 turns)..."
    export GOOSE_PROVIDER=openrouter
    export GOOSE_MODEL=minimax/minimax-m2.5
    export OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"
    export GOOSE_DISABLE_KEYRING=true
    export GOOSE_MAX_TURNS=15
    export GOOSE_TEMPERATURE=0.0
    export GOOSE_CONTEXT_LIMIT=128000

    timeout 300 goose run --recipe "$RECIPE" --output-format stream-json 2>&1 \
        | tee "/tmp/arena_goose_v14_$TASK_UID.log" \
        | grep -E "toolRequest|toolResponse|text" | tail -30

    # Check answer
    echo ""
    echo "=== RESULT ==="
    if [ -f "$APP_BASE/answer.txt" ] && [ -s "$APP_BASE/answer.txt" ]; then
        local GOT
        GOT=$(cat "$APP_BASE/answer.txt")
        echo "Got:      $GOT"
        echo "Expected: $EXPECTED"

        local RESULT
        RESULT=$(python3 -c "
got = '''$GOT'''.strip().replace(',','').replace('\$','').replace('%','')
exp = '''$EXPECTED'''.strip().replace(',','').replace('\$','').replace('%','')
try:
    g, e = float(got), float(exp)
    if e == 0:
        pct = 0 if g == 0 else 100
    else:
        pct = abs(g - e) / abs(e) * 100
    status = 'PASS' if pct <= 1 else 'FAIL'
    print(f'{status} ({pct:.2f}%%)')
except:
    print('FAIL (non-numeric)')
" 2>/dev/null || echo "FAIL")

        if [[ "$RESULT" == PASS* ]]; then
            echo -e "${GREEN}${RESULT}${NC}"
            return 0
        else
            echo -e "${RED}${RESULT}${NC}"
            return 1
        fi
    else
        echo -e "${YELLOW}NO ANSWER WRITTEN${NC}"
        echo "Expected: $EXPECTED"
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
            FAIL=$((FAIL+1))
        fi
        echo "TALLY: $PASS pass / $FAIL fail / $NOANS noans / $TOTAL total"
    done
    echo ""
    echo "============================================"
    echo "FINAL: $PASS/$TOTAL pass ($(( PASS * 100 / TOTAL ))%)"
elif [ "${1:-}" = "--batch-file" ]; then
    shift
    FILE="$1"
    UIDS=$(grep -v '^#' "$FILE" | grep -v '^$' | xargs)
    exec "$0" --batch $UIDS
else
    run_task "${1:?Usage: $0 UID0004 [--dry-run]}" "${2:-}"
fi
