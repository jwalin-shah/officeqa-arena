#!/bin/bash
set -euo pipefail
# Run a single question through goose + MiniMax + MCP server locally.
# Replicates the arena environment as closely as possible.
#
# Usage:
#   ./run_local.sh UID0001
#   ./run_local.sh UID0001 --dry-run   # Just set up resources, don't run goose
#
# Requirements:
#   - goose CLI installed
#   - OPENROUTER_API_KEY set (or uses the one from arena.yaml)
#   - /tmp/officeqa_jsons/ has parsed JSONs
#   - corpus/ has raw TXT files
#   - /tmp/officeqa_full.csv has questions + answers

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
CORPUS_DIR="$REPO_ROOT/corpus"
JSONS_DIR="/tmp/officeqa_jsons"
CSV_PATH="/tmp/officeqa_full.csv"
MCP_SERVER="$SCRIPT_DIR/mcp_server.py"

TASK_UID="${1:?Usage: $0 UID0001}"
DRY_RUN="${2:-}"

# ── Look up the question ──────────────────────────────────────────────
QUESTION=$(python3 -c "
import csv
with open('$CSV_PATH') as f:
    for r in csv.DictReader(f):
        if r['uid'].upper() == '${TASK_UID}'.upper():
            print(r['question'])
            break
")

ANSWER=$(python3 -c "
import csv
with open('$CSV_PATH') as f:
    for r in csv.DictReader(f):
        if r['uid'].upper() == '${TASK_UID}'.upper():
            print(r['answer'])
            break
")

SOURCE_FILES=$(python3 -c "
import csv
with open('$CSV_PATH') as f:
    for r in csv.DictReader(f):
        if r['uid'].upper() == '${TASK_UID}'.upper():
            for f in r['source_files'].strip().split('\n'):
                if f.strip():
                    print(f.strip())
            break
")

if [ -z "$QUESTION" ]; then
    echo "ERROR: UID $TASK_UID not found in $CSV_PATH"
    exit 1
fi

echo "=========================================="
echo "Question: $TASK_UID"
echo "=========================================="
echo "$QUESTION"
echo ""
echo "Ground truth: $ANSWER"
echo "Source files: $SOURCE_FILES"
echo ""

# ── Set up temp resources directory ───────────────────────────────────
WORK_DIR=$(mktemp -d)
RES_DIR="$WORK_DIR/resources"
ANSWER_FILE="$WORK_DIR/answer.txt"
mkdir -p "$RES_DIR"

echo "Work dir: $WORK_DIR"
echo "Resources dir: $RES_DIR"

# Copy resource files (TXT + JSON)
while IFS= read -r src_file; do
    [ -z "$src_file" ] && continue
    base="${src_file%.txt}"

    # Raw TXT
    if [ -f "$CORPUS_DIR/$src_file" ]; then
        cp "$CORPUS_DIR/$src_file" "$RES_DIR/"
        echo "  Copied: $src_file"
    fi

    # Parsed JSON
    json_file="${base}.json"
    if [ -f "$JSONS_DIR/$json_file" ]; then
        cp "$JSONS_DIR/$json_file" "$RES_DIR/"
        echo "  Copied: $json_file"
    fi
done <<< "$SOURCE_FILES"

# Create manifest.json
python3 -c "
import json
manifest = {'task_id': '${TASK_UID}'.lower(), 'question': '''${QUESTION}'''}
with open('$RES_DIR/manifest.json', 'w') as f:
    json.dump(manifest, f)
"
echo "  Created: manifest.json"
echo ""
echo "Resources:"
ls -la "$RES_DIR/"
echo ""

if [ "$DRY_RUN" = "--dry-run" ]; then
    echo "DRY RUN — resources set up at $RES_DIR"
    echo "To test MCP server manually:"
    echo "  RESOURCES_DIR=$RES_DIR python3 $MCP_SERVER"
    exit 0
fi

# ── Build the full prompt (render system.j2 + question) ──────────────
SYSTEM_PROMPT=$(python3 -c "
import re
with open('$SCRIPT_DIR/prompts/system.j2') as f:
    template = f.read()
# Replace {{ instruction }} with the question
prompt = template.replace('{{ instruction }}', '''$QUESTION''')
print(prompt)
")

# ── Set up goose config for this run ──────────────────────────────────
# Use OpenRouter API key from arena.yaml or environment
OPENROUTER_KEY="${OPENROUTER_API_KEY:-REDACTED}"

# Create a temporary goose profile config
GOOSE_CONFIG="$WORK_DIR/goose_config.yaml"
cat > "$GOOSE_CONFIG" << YAML
extensions:
  officeqa:
    enabled: true
    type: stdio
    cmd: python3
    args:
      - "$MCP_SERVER"
    env:
      RESOURCES_DIR: "$RES_DIR"
  developer:
    enabled: true
    type: platform
    name: developer
    description: Write and edit files, and execute shell commands
    display_name: Developer
    bundled: true
    available_tools: []
  todo:
    enabled: true
    type: platform
    name: todo
    display_name: Todo
    bundled: true
    available_tools: []
YAML

echo "Goose config: $GOOSE_CONFIG"
echo ""
echo "Starting goose with MiniMax M2.5..."
echo "=========================================="

# ── Run goose ─────────────────────────────────────────────────────────
export OPENROUTER_API_KEY="$OPENROUTER_KEY"

cd "$WORK_DIR"

# Use --no-profile to avoid loading user's default extensions
# Use --provider openrouter --model minimax/minimax-m2.5 to match arena config
# Use --with-extension to add our MCP server
# submit_answer writes to /app/answer.txt by default, but we're not in a container
# so we also check WORK_DIR for the answer

goose run \
    --no-profile \
    --with-builtin developer \
    --with-extension "RESOURCES_DIR=$RES_DIR ANSWER_PATH=$ANSWER_FILE python3 $MCP_SERVER" \
    --provider openrouter \
    --model minimax/minimax-m2.5 \
    --text "$SYSTEM_PROMPT" \
    2>&1 | tee "$WORK_DIR/goose_output.log"

echo ""
echo "=========================================="
echo "RESULTS for $TASK_UID"
echo "=========================================="

# Check for answer (try ANSWER_PATH first, then fallbacks)
PREDICTED=""
if [ -f "$ANSWER_FILE" ]; then
    PREDICTED=$(cat "$ANSWER_FILE")
elif [ -f "$WORK_DIR/answer.txt" ]; then
    PREDICTED=$(cat "$WORK_DIR/answer.txt")
elif [ -f "/app/answer.txt" ]; then
    PREDICTED=$(cat "/app/answer.txt")
fi

if [ -n "$PREDICTED" ]; then
    echo "Predicted: $PREDICTED"
    echo "Expected:  $ANSWER"

    # Score
    python3 -c "
import re
def parse_num(s):
    s = str(s).strip().replace(',','').replace('\$','').replace('%','')
    m = re.match(r'^\(([0-9.]+)\)\$', s)
    if m: s = '-' + m.group(1)
    try: return float(s)
    except: return None

pred = parse_num('$PREDICTED')
gt = parse_num('$ANSWER')
if pred is not None and gt is not None:
    if gt == 0:
        score = 1.0 if abs(pred) < 0.01 else 0.0
    else:
        rel = abs(pred - gt) / abs(gt)
        score = 1.0 if rel <= 0.01 else 0.0
    print(f'Score: {score} (rel_error={abs(pred-gt)/max(abs(gt),1e-9):.4f})')
else:
    print('Score: could not parse numeric values')
"
else
    echo "NO ANSWER FILE FOUND"
    echo "Checked: $ANSWER_FILE, $WORK_DIR/answer.txt, /app/answer.txt"
    echo "Files in work dir:"
    ls -la "$WORK_DIR/"
fi

echo ""
echo "Full output: $WORK_DIR/goose_output.log"
echo "Work dir: $WORK_DIR"
