#!/bin/bash
# Local test harness for r12 (v22-hybrid) — pre-built tools at /installed-agent/, verify skill
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
R12_DIR="$REPO_ROOT/r12/submit"
PROMPT_TEMPLATE="$R12_DIR/prompt.j2"

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

    # Set up /app/resources (task-specific oracle files)
    APP_BASE="/tmp/arena_app_$TASK_UID"
    rm -rf "$APP_BASE/resources" "$APP_BASE/answer.txt" 2>/dev/null || true
    mkdir -p "$APP_BASE/resources"

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
        source_files = [s.strip() for s in r['source_files'].split('\n') if s.strip()]
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

    # Set up /installed-agent/ with r12 tools (no DB — model greps raw files)
    AGENT_BASE="/tmp/arena_agent_$TASK_UID"
    rm -rf "$AGENT_BASE" 2>/dev/null || true
    mkdir -p "$AGENT_BASE/skills"
    cp "$R12_DIR/cpi.py" "$AGENT_BASE/cpi.py"
    cp -r "$R12_DIR/skills/verify" "$AGENT_BASE/skills/verify" 2>/dev/null || true

    # Register verify skill for goose
    mkdir -p ~/.config/goose/skills 2>/dev/null || true
    rm -f ~/.config/goose/skills/verify 2>/dev/null || true
    ln -sf "$AGENT_BASE/skills/verify" ~/.config/goose/skills/verify 2>/dev/null || true

    echo "Resources:"
    ls "$APP_BASE/resources/"

    # Render prompt — replace paths for local testing
    local RENDERED_PROMPT
    RENDERED_PROMPT=$(python3 -c "
tmpl = open('$PROMPT_TEMPLATE').read()
question = '''$QUESTION'''
rendered = tmpl.replace('{{ instruction }}', question).replace('{{instruction}}', question)
rendered = rendered.replace('/installed-agent/', '$AGENT_BASE/')
rendered = rendered.replace('/app/', '$APP_BASE/')
print(rendered)
" 2>/dev/null)

    rm -f "$APP_BASE/answer.txt"

    # Build goose recipe — developer + summon for verify skill
    local RECIPE="/tmp/arena_recipe_r12_$TASK_UID.yaml"
    cat > "$RECIPE" << RECEOF
version: 1.0.0
title: arena-r12-$TASK_UID
description: r12 v22-hybrid with verify skill (combines v20 reliability + v21 efficiency)
instructions: "You are given a task and you need to complete it. Act autonomously."
prompt: |
$(echo "$RENDERED_PROMPT" | sed 's/^/  /')
extensions:
  - type: builtin
    name: developer
  - type: builtin
    name: summon
RECEOF

    echo "Running goose (r12, max ${GOOSE_MAX_TURNS:-30} turns)..."
    export GOOSE_PROVIDER="${GOOSE_PROVIDER:-openrouter}"
    export GOOSE_MODEL="${GOOSE_MODEL:-minimax/minimax-m2.5}"
    export OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"
    export GOOSE_DISABLE_KEYRING=true
    export GOOSE_MAX_TURNS="${GOOSE_MAX_TURNS:-30}"
    export GOOSE_TEMPERATURE=0.0
    export GOOSE_CONTEXT_LIMIT=128000
    export RES_DIR="$APP_BASE/resources"

    timeout 480 goose run --recipe "$RECIPE" --output-format stream-json 2>&1 \
        | tee "/tmp/arena_goose_r12_$TASK_UID.log" \
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

# Main
if [ "${1:-}" = "--parallel" ]; then
    shift
    PARALLEL=${PARALLEL:-5}
    RESULTS_DIR="/tmp/arena_parallel_r12_$$"
    mkdir -p "$RESULTS_DIR"
    TOTAL=$#
    echo "Running $TOTAL tasks with parallelism=$PARALLEL"

    RUNNING=0
    for uid in "$@"; do
        (
            rc=0
            run_task "$uid" > "$RESULTS_DIR/$uid.log" 2>&1 || rc=$?
            echo $rc > "$RESULTS_DIR/$uid.rc"
        ) &
        RUNNING=$((RUNNING + 1))
        if [ "$RUNNING" -ge "$PARALLEL" ]; then
            wait -n 2>/dev/null || wait
            RUNNING=$((RUNNING - 1))
        fi
    done
    wait

    PASS=0; FAIL=0
    for uid in "$@"; do
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
    echo "=== BATCH SUMMARY ==="
    echo -e "Pass: ${GREEN}$PASS${NC} / $TOTAL ($(( PASS * 100 / TOTAL ))%)"
    echo -e "Fail: ${RED}$FAIL${NC}"
    echo "Full logs: $RESULTS_DIR/"

elif [ "${1:-}" = "--batch" ]; then
    shift
    PASS=0; FAIL=0; TOTAL=0
    for uid in "$@"; do
        TOTAL=$((TOTAL + 1))
        echo ""
        echo "============ Task $TOTAL: $uid ============"
        if run_task "$uid"; then
            PASS=$((PASS + 1))
        else
            FAIL=$((FAIL + 1))
        fi
    done
    echo ""
    echo "=== BATCH SUMMARY ==="
    echo -e "Pass: ${GREEN}$PASS${NC} / $TOTAL ($(( PASS * 100 / TOTAL ))%)"
    echo -e "Fail: ${RED}$FAIL${NC}"
else
    run_task "${1:-UID0001}"
fi
