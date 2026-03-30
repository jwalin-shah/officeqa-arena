#!/bin/bash
# MCP server launcher — uses zero-dependency stdio implementation.
# No pip install needed. Starts instantly.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Set SQLite DB path (auto-detect)
[ -z "${OFFICEQA_SQLITE_DB:-}" ] && [ -f /app/corpus/officeqa_corpus.sqlite3 ] && export OFFICEQA_SQLITE_DB="/app/corpus/officeqa_corpus.sqlite3"
[ -z "${OFFICEQA_SQLITE_DB:-}" ] && [ -f "${SCRIPT_DIR}/data/officeqa_corpus.sqlite3" ] && export OFFICEQA_SQLITE_DB="${SCRIPT_DIR}/data/officeqa_corpus.sqlite3"

cd "$SCRIPT_DIR"
exec python3 -m server.mcp_stdio
