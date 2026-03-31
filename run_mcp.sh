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

# Auto-download lean DB if not found anywhere
if [ -z "${OFFICEQA_SQLITE_DB:-}" ]; then
  DB_TARGET="/app/corpus/officeqa_corpus.sqlite3"
  DB_URL="http://64.23.196.53:9090/officeqa_slim_v2.sqlite3.zst"
  mkdir -p "$(dirname "$DB_TARGET")"
  curl -fsSL "$DB_URL" 2>/dev/null | zstd -d -o "$DB_TARGET" -f 2>/dev/null
  export OFFICEQA_SQLITE_DB="$DB_TARGET"
fi

if [ -z "${OFFICEQA_SQLITE_DB:-}" ]; then
  exit 1
fi

cd "$SCRIPT_DIR"

# Ensure blob deps are installed (required for slim_v2 DB which uses cell_blobs)
# ALL output must go to /dev/null — stderr is the MCP protocol channel
python3 -c "import msgpack, zstandard" 2>/dev/null || {
  pip install --quiet msgpack zstandard >/dev/null 2>&1 || pip3 install --quiet msgpack zstandard >/dev/null 2>&1 || true
}

# slim_v2 DB has col_label_lookup and row_label_lookup pre-built — no index build needed

exec python3 -m server.mcp_stdio
