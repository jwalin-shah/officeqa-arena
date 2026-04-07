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
    mkdir -p "$SLOT_DIR/resources" "$SLOT_DIR/corpus" "$AGENT_DIR/v15/server"

    # Copy v15 tools (CLI + MCP server)
    cp "$REPO_ROOT/v15/tools.py" "$SLOT_DIR/resources/tools.py"
    cp "$REPO_ROOT/v15/server/mcp_stdio.py" "$AGENT_DIR/v15/server/mcp_stdio.py"

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
        # Pre-build SQLite index so search is fast from the start
        python3 "$SLOT_DIR/resources/tools.py" index --dir "$SLOT_DIR/corpus" 2>/dev/null
    fi

    # Render prompt
    local PROMPT_TEMPLATE="${PROMPT_PATH:-$REPO_ROOT/v15/prompts/system.j2}"
    local RENDERED_PROMPT
    RENDERED_PROMPT=$(python3 -c "
import base64
tmpl = open('$PROMPT_TEMPLATE').read()
question = base64.b64decode('$QUESTION_B64').decode()
instruction = question + '''

## Output
Write your final answer to $SLOT_DIR/answer.txt
'''
rendered = tmpl.replace('{{ instruction }}', instruction).replace('{{instruction}}', instruction)
rendered = rendered.replace('/app/resources/', '$SLOT_DIR/resources/')
rendered = rendered.replace('/app/corpus/', '$SLOT_DIR/corpus/')
rendered = rendered.replace('/app/answer.txt', '$SLOT_DIR/answer.txt')
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
  - type: builtin
    name: summon
    config:
      skills_dir: $HOME/.config/goose/skills
RECEOF

    # Copy skills into goose skills directory for summon to find
    if [ -d "$REPO_ROOT/v15/skills" ]; then
        local SKILLS_DIR="$HOME/.config/goose/skills"
        mkdir -p "$SKILLS_DIR"
        cp -r "$REPO_ROOT/v15/skills/"* "$SKILLS_DIR/" 2>/dev/null || true
    fi

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

    timeout ${TASK_TIMEOUT:-600} goose run --recipe "$RECIPE" --output-format stream-json > "$LOG" 2>&1

    # Evaluate — only read from this task's slot dir (no global fallback)
    local RESULT="NO_ANSWER"
    local GOT=""
    local ANS_FILE=""
    if [ -f "$SLOT_DIR/answer.txt" ] && [ -s "$SLOT_DIR/answer.txt" ]; then
        ANS_FILE="$SLOT_DIR/answer.txt"
    fi
    if [ -n "$ANS_FILE" ]; then
        GOT=$(cat "$ANS_FILE")
        local GOT_B64=$(echo "$GOT" | base64)
        RESULT=$(python3 "$REPO_ROOT/score.py" "$GOT_B64" "$EXPECTED_B64" 2>/dev/null || echo "FAIL")
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
