#!/bin/bash
# MCP server launcher — works from repo root or Arena cloud.
# Detects SQLite DB location automatically.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Set SQLite DB path (auto-detect)
if [ -z "${OFFICEQA_SQLITE_DB:-}" ]; then
  if [ -f /app/corpus/officeqa_corpus.sqlite3 ]; then
    export OFFICEQA_SQLITE_DB="/app/corpus/officeqa_corpus.sqlite3"
  elif [ -f "${SCRIPT_DIR}/data/officeqa_corpus.sqlite3" ]; then
    export OFFICEQA_SQLITE_DB="${SCRIPT_DIR}/data/officeqa_corpus.sqlite3"
  fi
fi

exec python3 -m server.mcp_server
