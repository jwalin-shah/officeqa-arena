#!/bin/bash
# Local test harness that replicates arena submit environment exactly.
# Usage: ./run_local_v7.sh UID0001
#        ./run_local_v7.sh UID0001 --dry-run  (just set up, don't run goose)

set -euo pipefail

TASK_UID="${1:?Usage: $0 UID0001}"
DRY_RUN="${2:-}"

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
CORPUS_DIR="$REPO_ROOT/corpus"
JSONS_DIR="/tmp/officeqa_jsons"
PAGES_DIR="/tmp/officeqa_reingest/officeqa_repo/treasury_bulletins_parsed/transformed_page_level"
CSV_PATH="/tmp/officeqa_full.csv"
PROMPT_TEMPLATE="$REPO_ROOT/submit-goose/prompts/system.j2"
SKILLS_DIR="$REPO_ROOT/submit-goose/skills"

# Look up question, answer, source files
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
            print(r['source_files'])
            break
")
SOURCE_DOCS=$(python3 -c "
import csv
with open('$CSV_PATH') as f:
    for r in csv.DictReader(f):
        if r['uid'].upper() == '${TASK_UID}'.upper():
            print(r['source_docs'])
            break
")

echo "=== $TASK_UID ==="
echo "Question: ${QUESTION:0:100}..."
echo "Expected: $ANSWER"
echo "Sources: $SOURCE_FILES"

# Set up /app equivalent
APP_DIR="/tmp/arena_local_$TASK_UID"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/resources" "$APP_DIR/corpus"

# Symlink corpus
ln -sf "$CORPUS_DIR"/* "$APP_DIR/corpus/" 2>/dev/null || cp "$CORPUS_DIR"/* "$APP_DIR/corpus/"

# Create manifest.json
python3 << MANIFEST_PY
import json, csv
with open('$CSV_PATH') as f:
    for r in csv.DictReader(f):
        if r['uid'].upper() == '${TASK_UID}'.upper():
            source_files = [s.strip() for s in r['source_files'].split('\n') if s.strip()]
            manifest = {
                'uid': r['uid'],
                'source_files': source_files,
                'source_docs': [],
                'files': {}
            }
            with open('$APP_DIR/resources/manifest.json', 'w') as out:
                json.dump(manifest, out, indent=2)
            # Also write source files list for bash to use
            with open('/tmp/arena_sources_${TASK_UID}.txt', 'w') as out:
                out.write('\n'.join(source_files))
            break
MANIFEST_PY

# Copy oracle files to resources
for src_file in $(cat /tmp/arena_sources_${TASK_UID}.txt); do
    base="${src_file%.txt}"
    
    # Copy full TXT
    if [ -f "$CORPUS_DIR/$src_file" ]; then
        cp "$CORPUS_DIR/$src_file" "$APP_DIR/resources/"
        echo "  Copied: $src_file"
    fi
    
    # Copy JSON
    if [ -f "$JSONS_DIR/${base}.json" ]; then
        cp "$JSONS_DIR/${base}.json" "$APP_DIR/resources/"
        echo "  Copied: ${base}.json"
    fi
    
    # Copy ONLY the specific page files (from source_docs URLs)
    # Extract page numbers for this source file from CSV
    PAGE_NUMS=$(python3 -c "
import csv, re
with open('$CSV_PATH') as f:
    for r in csv.DictReader(f):
        if r['uid'].upper() == '${TASK_UID}'.upper():
            docs = r.get('source_docs', '')
            # Match pages to source files in order
            pages = re.findall(r'page=(\d+)', docs)
            files = [s.strip() for s in r['source_files'].split('\n') if s.strip()]
            # Find index of current file
            try:
                idx = files.index('$src_file')
                if idx < len(pages):
                    print(pages[idx])
            except: pass
            break
")
    if [ -n "$PAGE_NUMS" ]; then
        for page_num in $PAGE_NUMS; do
            page_src="$PAGES_DIR/${base}_${page_num}.txt"
            if [ -f "$page_src" ]; then
                cp "$page_src" "$APP_DIR/resources/${base}_page_${page_num}.txt"
                echo "  Page: ${base}_page_${page_num}.txt"
            fi
        done
    else
        echo "  (no specific page identified)"
    fi
done

echo ""
echo "Resources:"
ls "$APP_DIR/resources/"

# Set up skills
mkdir -p ~/.agents/skills
rm -rf ~/.agents/skills/cpi-reference ~/.agents/skills/computation-patterns ~/.agents/skills/fiscal-calendar
cp -r "$SKILLS_DIR/cpi-reference" ~/.agents/skills/ 2>/dev/null || true
cp -r "$SKILLS_DIR/computation-patterns" ~/.agents/skills/ 2>/dev/null || true
cp -r "$SKILLS_DIR/fiscal-calendar" ~/.agents/skills/ 2>/dev/null || true
echo "Skills: $(ls ~/.agents/skills/)"

if [ "$DRY_RUN" = "--dry-run" ]; then
    echo "=== DRY RUN - not running goose ==="
    exit 0
fi

# Build recipe (replicating what Harbor does)
RENDERED_PROMPT=$(python3 -c "
import re
with open('$PROMPT_TEMPLATE') as f:
    template = f.read()
instruction = '''$QUESTION

## Available Resources

You have access to the full U.S. Treasury Bulletin corpus at \`/app/corpus/\`. This directory contains 697 parsed Treasury Bulletin text files (Markdown with tables), one per monthly bulletin issue.

**Corpus location:** \`/app/corpus/\`
**File naming convention:** \`treasury_bulletin_YYYY_MM.txt\` (e.g., \`treasury_bulletin_1941_01.txt\`)
**File listing:** \`/app/corpus/index.txt\`

You must search through these files to find the relevant information to answer the question.

## Output

Write your final answer to \`/app/answer.txt\`. Numerical answers should be precise (scoring uses 1% tolerance).'''

rendered = template.replace('{{ instruction }}', instruction)
# Replace /app paths with local paths
rendered = rendered.replace('/app/resources/', '$APP_DIR/resources/')
rendered = rendered.replace('/app/corpus/', '$APP_DIR/corpus/')
rendered = rendered.replace('/app/answer.txt', '$APP_DIR/answer.txt')
print(rendered)
")

cat > /tmp/arena_recipe_$TASK_UID.yaml << RECEOF
version: 1.0.0
title: arena-local-$TASK_UID
description: Local arena test
instructions: "You are given a task and you need to complete it. Act autonomously."
prompt: |
$(echo "$RENDERED_PROMPT" | sed 's/^/  /')
extensions:
  - type: builtin
    name: developer
  - type: platform
    name: summon
  - type: platform
    name: todo
RECEOF

echo ""
echo "=== Running goose ==="
export GOOSE_PROVIDER=openrouter
export GOOSE_MODEL=minimax/minimax-m2.5
export OPENROUTER_API_KEY=REDACTED
export GOOSE_DISABLE_KEYRING=true

timeout 300 goose run --recipe /tmp/arena_recipe_$TASK_UID.yaml --output-format stream-json 2>&1 | tee /tmp/arena_goose_$TASK_UID.log | grep -E "toolRequest|toolResponse" | head -50

echo ""
echo "=== RESULT ==="
if [ -f "$APP_DIR/answer.txt" ]; then
    GOT=$(cat "$APP_DIR/answer.txt")
    echo "Got:      $GOT"
    echo "Expected: $ANSWER"
else
    echo "NO ANSWER WRITTEN"
    echo "Expected: $ANSWER"
fi
