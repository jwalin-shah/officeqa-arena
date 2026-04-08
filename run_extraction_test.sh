#!/bin/bash
# Ensure goose is in PATH (non-interactive SSH doesn't load .bashrc)
export PATH="${HOME}/.local/bin:${PATH}"
# Load API keys only if not already set
[ -z "$OPENROUTER_API_KEY" ] && [ -f ~/.bashrc ] && eval "$(grep OPENROUTER_API_KEY ~/.bashrc 2>/dev/null)"
# Run extraction A/B test across R1/R2/R3 variants
# Usage: bash run_extraction_test.sh r1|r2|r3 [--parallel N] [UID...]
#
# R1: t.py table parser tool
# R2: prompt-only python3 extraction guidance
# R3: build_db.py + q.py SQL approach
set -euo pipefail

VARIANT="${1:?Usage: $0 r1|r2|r3 [--parallel N] [UID...]}"
shift

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
VARIANT_DIR="$REPO_ROOT/$VARIANT"
PROMPT_TEMPLATE="$VARIANT_DIR/prompt.j2"

if [ ! -f "$PROMPT_TEMPLATE" ]; then
    echo "ERROR: $PROMPT_TEMPLATE not found"
    exit 1
fi

CSV_PATH="${CSV_PATH:-/tmp/officeqa_full.csv}"
CORPUS_DIR="${CORPUS_SRC:-$REPO_ROOT/corpus}"
PAGES_DIR="${PAGES_DIR:-/tmp/officeqa_reingest/officeqa_repo/treasury_bulletins_parsed/transformed_page_level}"

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; NC='\033[0m'

source "$REPO_ROOT/.env" 2>/dev/null || true

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

    APP_BASE="/tmp/arena_app_${VARIANT}_$TASK_UID"
    rm -rf "$APP_BASE/resources" "$APP_BASE/answer.txt" 2>/dev/null || true
    mkdir -p "$APP_BASE/resources"

    # Copy oracle files
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
            src = os.path.join(corpus_dir, src_file)
            if os.path.exists(src):
                shutil.copy2(src, '$APP_BASE/resources/')
                print(f'  Copied: {src_file}')
            if idx < len(pages):
                page_src = os.path.join(pages_dir, f'{base}_{pages[idx]}.txt')
                if os.path.exists(page_src):
                    dest = f'$APP_BASE/resources/{base}_page_{pages[idx]}.txt'
                    shutil.copy2(page_src, dest)
                    print(f'  Page: {base}_page_{pages[idx]}.txt')
        break
SETUP_PY

    # Drop variant-specific tools
    if [ "$VARIANT" = "r1" ]; then
        cp "$VARIANT_DIR/t.py" "$APP_BASE/resources/t.py"
    elif [ "$VARIANT" = "r3" ]; then
        cp "$VARIANT_DIR/build_db.py" "$APP_BASE/resources/build_db.py"
        cp "$VARIANT_DIR/q.py" "$APP_BASE/resources/q.py"
    elif [ "$VARIANT" = "r6" ]; then
        cp "$VARIANT_DIR/q.py" "$APP_BASE/resources/q.py"
        # Pre-build SQLite DB so MiniMax doesn't waste turns
        RES_DIR="$APP_BASE/resources" python3 "$APP_BASE/resources/q.py" preview > /dev/null 2>&1
        echo "  Pre-built DB at $APP_BASE/resources/data.db"
    fi

    # Drop cpi.py if it exists
    if [ -f "$REPO_ROOT/v24/cpi.py" ]; then
        cp "$REPO_ROOT/v24/cpi.py" "$APP_BASE/resources/cpi.py"
    fi

    echo "Resources:"
    ls "$APP_BASE/resources/"

    # Render prompt
    local RENDERED_PROMPT
    RENDERED_PROMPT=$(python3 -c "
tmpl = open('$PROMPT_TEMPLATE').read()
question = '''$QUESTION'''
rendered = tmpl.replace('{{ instruction }}', question).replace('{{instruction}}', question)
rendered = rendered.replace('/app/', '$APP_BASE/')
print(rendered)
" 2>/dev/null)

    rm -f "$APP_BASE/answer.txt"

    # Build goose recipe
    local RECIPE="/tmp/arena_recipe_${VARIANT}_$TASK_UID.yaml"
    cat > "$RECIPE" << RECEOF
version: 1.0.0
title: arena-${VARIANT}-$TASK_UID
description: ${VARIANT} extraction test
instructions: "You are given a task and you need to complete it. Act autonomously."
prompt: |
$(echo "$RENDERED_PROMPT" | sed 's/^/  /')
extensions:
  - type: builtin
    name: developer
RECEOF

    echo "Running goose ($VARIANT, max ${GOOSE_MAX_TURNS:-40} turns)..."
    export GOOSE_PROVIDER="${GOOSE_PROVIDER:-openrouter}"
    export GOOSE_MODEL="${GOOSE_MODEL:-minimax/minimax-m2.5}"
    export OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"
    export GOOSE_DISABLE_KEYRING=true
    export GOOSE_MAX_TURNS="${GOOSE_MAX_TURNS:-40}"
    export GOOSE_TEMPERATURE=0.0
    export GOOSE_CONTEXT_LIMIT=128000

    timeout 300 goose run --recipe "$RECIPE" --output-format stream-json 2>&1 \
        | tee "/tmp/arena_goose_${VARIANT}_$TASK_UID.log" \
        | grep -E "toolRequest|toolResponse|text" | tail -30

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

# Parse args
PARALLEL_COUNT=0
UIDS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --parallel)
            PARALLEL_COUNT="${2:-5}"
            shift 2
            ;;
        *)
            UIDS+=("$1")
            shift
            ;;
    esac
done

# Default test UIDs if none specified: mix of always-fail and flaky extraction tasks
if [ ${#UIDS[@]} -eq 0 ]; then
    UIDS=(
        # Always-fail (extraction errors) — 10 tasks
        UID0012 UID0032 UID0062 UID0077 UID0018
        UID0041 UID0074 UID0096 UID0113 UID0135
        # Flaky (sometimes extraction works) — 10 tasks
        UID0004 UID0038 UID0050 UID0052 UID0021
        UID0026 UID0046 UID0005 UID0020 UID0011
    )
fi

if [ "$PARALLEL_COUNT" -gt 0 ]; then
    RESULTS_DIR="/tmp/arena_${VARIANT}_parallel_$$"
    mkdir -p "$RESULTS_DIR"
    TOTAL=${#UIDS[@]}
    echo "=== $VARIANT: Running $TOTAL tasks with parallelism=$PARALLEL_COUNT ==="

    RUNNING=0
    for uid in "${UIDS[@]}"; do
        (
            rc=0
            run_task "$uid" > "$RESULTS_DIR/$uid.log" 2>&1 || rc=$?
            echo $rc > "$RESULTS_DIR/$uid.rc"
        ) &
        RUNNING=$((RUNNING + 1))
        if [ "$RUNNING" -ge "$PARALLEL_COUNT" ]; then
            wait -n 2>/dev/null || wait
            RUNNING=$((RUNNING - 1))
        fi
    done
    wait

    PASS=0; FAIL=0
    for uid in "${UIDS[@]}"; do
        RC=$(cat "$RESULTS_DIR/$uid.rc" 2>/dev/null || echo 1)
        echo ""
        echo "============ $uid ============"
        grep -E "^(Question:|Expected:|Got:|PASS|FAIL|NO ANSWER)" "$RESULTS_DIR/$uid.log" 2>/dev/null || tail -5 "$RESULTS_DIR/$uid.log"
        if [ "$RC" = "0" ]; then
            PASS=$((PASS + 1))
        else
            FAIL=$((FAIL + 1))
        fi
    done
    echo ""
    echo "=== $VARIANT BATCH SUMMARY ==="
    echo -e "Pass: ${GREEN}$PASS${NC} / $TOTAL ($(( PASS * 100 / TOTAL ))%)"
    echo -e "Fail: ${RED}$FAIL${NC}"
    echo "Full logs: $RESULTS_DIR/"
else
    # Sequential
    PASS=0; FAIL=0; TOTAL=0
    for uid in "${UIDS[@]}"; do
        TOTAL=$((TOTAL + 1))
        echo ""
        echo "============ Task $TOTAL: $uid ($VARIANT) ============"
        if run_task "$uid"; then
            PASS=$((PASS + 1))
        else
            FAIL=$((FAIL + 1))
        fi
    done
    echo ""
    echo "=== $VARIANT BATCH SUMMARY ==="
    echo -e "Pass: ${GREEN}$PASS${NC} / $TOTAL ($(( PASS * 100 / TOTAL ))%)"
    echo -e "Fail: ${RED}$FAIL${NC}"
fi
