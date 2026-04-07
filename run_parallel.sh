#!/bin/bash
# Parallel test runner — runs N goose tasks concurrently on one machine
# Usage:
#   ./run_parallel.sh 5 UID0001 UID0003 UID0004 ...     # 5 parallel workers
#   GOOSE_MODEL=deepseek/deepseek-chat-v3-0324 ./run_parallel.sh 3 UID0001 UID0003
#
# Each task gets its own /tmp/arena_slot_N directory to avoid conflicts.
# Results written to /tmp/parallel_results.log

set -uo pipefail

WORKERS="${1:?Usage: $0 <num_workers> UID0001 UID0002 ...}"
shift
UIDS=("$@")

if [ ${#UIDS[@]} -eq 0 ]; then
    echo "No UIDs specified"
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
RESULTS_LOG="/tmp/parallel_results_$(date +%s).log"
MODEL="${GOOSE_MODEL:-minimax/minimax-m2.5}"

echo "=== Parallel Runner ===" | tee "$RESULTS_LOG"
echo "Workers: $WORKERS | Tasks: ${#UIDS[@]} | Model: $MODEL" | tee -a "$RESULTS_LOG"
echo "Started: $(date)" | tee -a "$RESULTS_LOG"
echo "" | tee -a "$RESULTS_LOG"

# Create a FIFO job queue
QUEUE_DIR=$(mktemp -d)
FIFO="$QUEUE_DIR/fifo"
mkfifo "$FIFO"

# Semaphore: prefill with N tokens
exec 3<>"$FIFO"
for ((i=0; i<WORKERS; i++)); do
    echo "token" >&3
done

PASS=0; FAIL=0; NOANS=0; TOTAL=${#UIDS[@]}
LOCK_FILE="$QUEUE_DIR/lock"

run_single() {
    local TASK_UID="$1"
    local SLOT="$2"
    local SLOT_DIR="/tmp/arena_slot_${SLOT}"
    local AGENT_DIR="/tmp/arena_agent_${SLOT}"
    local TRACE_DIR="${TRACE_DIR:-/tmp/traces_${MODEL//\//_}}"
    mkdir -p "$TRACE_DIR"
    local LOG="$TRACE_DIR/${TASK_UID}.log"

    # Isolate this task
    rm -rf "$SLOT_DIR" "$AGENT_DIR"
    mkdir -p "$SLOT_DIR/resources" "$SLOT_DIR/corpus" "$AGENT_DIR/v14/server"

    # Copy agent scripts
    cp "$REPO_ROOT/v14/solve_v14.py" "$AGENT_DIR/solve_v14.py"
    cp "$REPO_ROOT/v14/tools.py" "$AGENT_DIR/tools.py"
    cp "$REPO_ROOT/v14/server/mcp_stdio.py" "$AGENT_DIR/v14/server/mcp_stdio.py"

    # Read task from CSV
    local CSV_PATH="${CSV_PATH:-/tmp/officeqa_full.csv}"
    local PAGES_DIR="${PAGES_DIR:-/tmp/officeqa_reingest/officeqa_repo/treasury_bulletins_parsed/transformed_page_level}"
    local CORPUS_DIR="${CORPUS_SRC:-$REPO_ROOT/corpus}"

    local TASK_ENV="/tmp/arena_env_${SLOT}.sh"
    python3 << SETUP_PYTHON
import csv, os, re, shutil
csv_path = '$CSV_PATH'
task_uid = '$TASK_UID'
corpus_dir = '$CORPUS_DIR'
pages_dir = '$PAGES_DIR'
slot_dir = '$SLOT_DIR'
env_file = '$TASK_ENV'
with open(csv_path) as f:
    for r in csv.DictReader(f):
        if r['uid'].upper() != task_uid.upper():
            continue
        # Write question and expected to env file (base64 to avoid shell escaping)
        import base64
        q_b64 = base64.b64encode(r['question'].encode()).decode()
        e_b64 = base64.b64encode(r['answer'].encode()).decode()
        with open(env_file, 'w') as ef:
            ef.write(f'QUESTION_B64={q_b64}\n')
            ef.write(f'EXPECTED_B64={e_b64}\n')
        source_files = [s.strip() for s in r['source_files'].split('\n') if s.strip()]
        source_docs = r.get('source_docs', '')
        pages = re.findall(r'page=(\d+)', source_docs)
        for idx, src_file in enumerate(source_files):
            base = src_file.replace('.txt', '')
            src = os.path.join(corpus_dir, src_file)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(slot_dir, 'resources'))
            if idx < len(pages):
                page_src = os.path.join(pages_dir, f'{base}_{pages[idx]}.txt')
                if os.path.exists(page_src):
                    shutil.copy2(page_src, os.path.join(slot_dir, 'resources', f'{base}_page_{pages[idx]}.txt'))
        break
SETUP_PYTHON

    if [ ! -f "$TASK_ENV" ]; then
        echo "[$TASK_UID] NOT FOUND" >> "$RESULTS_LOG"
        return 1
    fi
    source "$TASK_ENV"
    QUESTION=$(echo "$QUESTION_B64" | base64 -d)
    EXPECTED=$(echo "$EXPECTED_B64" | base64 -d)

    # Symlink corpus
    if [ -d "$CORPUS_DIR" ] && [ "$(ls -A "$CORPUS_DIR" 2>/dev/null)" ]; then
        ln -sf "$CORPUS_DIR"/* "$SLOT_DIR/corpus/" 2>/dev/null || true
    fi

    # Full corpus mode: symlink ALL corpus files into /resources/ too
    if [ "${FULL_CORPUS:-0}" = "1" ] && [ -d "$CORPUS_DIR" ]; then
        ln -sf "$CORPUS_DIR"/* "$SLOT_DIR/resources/" 2>/dev/null || true
    fi

    # Render prompt
    local PROMPT_TEMPLATE="$REPO_ROOT/v14/prompts/system.j2"
    local RENDERED_PROMPT
    RENDERED_PROMPT=$(python3 -c "
tmpl = open('$PROMPT_TEMPLATE').read()
question = '''$QUESTION

## Available Resources
**Corpus location:** \`$SLOT_DIR/corpus/\`
**File naming convention:** \`treasury_bulletin_YYYY_MM.txt\`

## Output
Write your final answer to \`$SLOT_DIR/answer.txt\`. Numerical answers should be precise (scoring uses 1%% tolerance).'''

rendered = tmpl.replace('{{ instruction }}', question).replace('{{instruction}}', question)
rendered = rendered.replace('/app/', '$SLOT_DIR/')
rendered = rendered.replace('/installed-agent/', '$AGENT_DIR/')
print(rendered)
" 2>/dev/null)

    # Build recipe
    local RECIPE="/tmp/arena_recipe_${TASK_UID}.yaml"
    cat > "$RECIPE" << RECEOF
version: 1.0.0
title: arena-${TASK_UID}
description: parallel test
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
      - $AGENT_DIR/v14/server/mcp_stdio.py
    env:
      RESOURCES_DIR: "$SLOT_DIR/resources"
      CORPUS_DIR: "$SLOT_DIR/corpus"
RECEOF

    # Run goose — support openrouter or openai-compatible (Dedalus)
    export GOOSE_PROVIDER="${GOOSE_PROVIDER:-openrouter}"
    export GOOSE_MODEL="$MODEL"
    export OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-}"
    export GOOSE_DISABLE_KEYRING=true
    export GOOSE_MAX_TURNS=40
    export GOOSE_TEMPERATURE=0.0
    export GOOSE_CONTEXT_LIMIT=128000
    # For Dedalus/OpenAI-compatible providers
    if [ -n "${OPENAI_API_BASE:-}" ]; then
        export OPENAI_API_BASE
    fi
    if [ -n "${OPENAI_API_KEY:-}" ]; then
        export OPENAI_API_KEY
    fi

    timeout 300 goose run --recipe "$RECIPE" --output-format stream-json > "$LOG" 2>&1

    # Evaluate — check slot dir first, then /app/answer.txt as fallback
    local RESULT="NO_ANSWER"
    local GOT=""
    local ANS_FILE=""
    if [ -f "$SLOT_DIR/answer.txt" ] && [ -s "$SLOT_DIR/answer.txt" ]; then
        ANS_FILE="$SLOT_DIR/answer.txt"
    elif [ -f "/app/answer.txt" ] && [ -s "/app/answer.txt" ]; then
        ANS_FILE="/app/answer.txt"
    fi
    if [ -n "$ANS_FILE" ]; then
        GOT=$(cat "$ANS_FILE")
        local GOT_B64=$(echo "$GOT" | base64)
        RESULT=$(python3 -c "
import base64
got = base64.b64decode('$GOT_B64').decode().strip().replace(',','').replace('\$','').replace('%','')
exp = base64.b64decode('$EXPECTED_B64').decode().strip().replace(',','').replace('\$','').replace('%','')
try:
    g, e = float(got), float(exp)
    if e == 0:
        pct = 0 if g == 0 else 100
    else:
        pct = abs(g - e) / abs(e) * 100
    print('PASS' if pct <= 1 else 'FAIL')
except:
    print('FAIL' if got.strip() != exp.strip() else 'PASS')
" 2>/dev/null || echo "FAIL")
    fi

    echo "[$TASK_UID] $RESULT (got=${GOT:-none}, expected=$EXPECTED)" | tee -a "$RESULTS_LOG"

    # Cleanup
    rm -rf "$SLOT_DIR" "$AGENT_DIR" "$RECIPE"
}

# Launch tasks with semaphore
SLOT=0
for TASK_UID in "${UIDS[@]}"; do
    # Wait for a semaphore token
    read -r _ <&3
    SLOT=$((SLOT+1))
    (
        run_single "$TASK_UID" "$SLOT"
        # Return token
        echo "token" >&3
    ) &
done

# Wait for all background jobs
wait

echo "" | tee -a "$RESULTS_LOG"
echo "============================================" | tee -a "$RESULTS_LOG"
# Count results
P=$(grep -c 'PASS' "$RESULTS_LOG" 2>/dev/null || echo 0)
F=$(grep -c 'FAIL' "$RESULTS_LOG" 2>/dev/null || echo 0)
N=$(grep -c 'NO_ANSWER' "$RESULTS_LOG" 2>/dev/null || echo 0)
echo "FINAL: $P pass / $F fail / $N no_answer out of $TOTAL" | tee -a "$RESULTS_LOG"
echo "DONE $(date -u +%Y-%m-%dT%H:%M:%SZ) model=$MODEL workers=$WORKERS" | tee -a "$RESULTS_LOG"
echo "Full log: $RESULTS_LOG"

# Cleanup semaphore
exec 3>&-
rm -rf "$QUEUE_DIR"
