#!/bin/bash
# Pre-build the search index before the agent starts.
# This saves 1-2 tool calls and ensures the index is ready.
set -e
export CORPUS_DIR="/app/corpus"
export INDEX_PATH="/tmp/table_index.jsonl"
export KEYWORD_INDEX_PATH="/tmp/keyword_index.txt"
python3 /installed-agent/build_index.py 2>/dev/null || true
echo "Index ready."
