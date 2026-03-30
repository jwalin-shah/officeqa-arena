#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONUNBUFFERED=1

if [ -z "${OFFICEQA_SQLITE_DB:-}" ]; then
  for candidate in \
    "/app/corpus/officeqa_corpus.sqlite3" \
    "/app/corpus/officeqa_subset.sqlite3" \
    "${SCRIPT_DIR}/data/officeqa_corpus.sqlite3" \
    "${SCRIPT_DIR}/data/officeqa_subset.sqlite3"
  do
    if [ -f "$candidate" ]; then
      export OFFICEQA_SQLITE_DB="$candidate"
      break
    fi
  done
fi

if [ -z "${OFFICEQA_SQLITE_DB:-}" ]; then
  found="$(
    {
      find /app/corpus -maxdepth 1 -type f -name '*.sqlite3' 2>/dev/null || true
      find "${SCRIPT_DIR}/data" -maxdepth 1 -type f -name '*.sqlite3' 2>/dev/null || true
    } | head -n 1
  )"
  if [ -n "${found:-}" ]; then
    export OFFICEQA_SQLITE_DB="$found"
  fi
fi

if [ -z "${OFFICEQA_SQLITE_DB:-}" ]; then
  echo "No SQLite DB found. Set OFFICEQA_SQLITE_DB explicitly." >&2
  exit 1
fi

cd "$SCRIPT_DIR"
exec python3 -m server.mcp_stdio
