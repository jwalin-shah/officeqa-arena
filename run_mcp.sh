#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONUNBUFFERED=1

# === Bootstrap: install deps if missing (runs once in arena container) ===
python3 -c "import msgpack, zstandard" 2>/dev/null || {
  # Install pip if needed, then deps — all output to /dev/null (stderr is MCP channel)
  apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq python3-pip zstd >/dev/null 2>&1 || true
  pip3 install --break-system-packages --quiet msgpack zstandard >/dev/null 2>&1 || \
    python3 -m pip install --break-system-packages --quiet msgpack zstandard >/dev/null 2>&1 || true
}

# === Find or download SQLite DB ===
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

# Auto-download enriched DB if not found anywhere
if [ -z "${OFFICEQA_SQLITE_DB:-}" ]; then
  DB_TARGET="/app/corpus/officeqa_corpus.sqlite3"
  DB_URL="http://209.38.75.192:9090/officeqa_slim_v2.sqlite3.zst"
  mkdir -p "$(dirname "$DB_TARGET")" 2>/dev/null || true
  # Download with zstd decompression — all output to /dev/null
  curl -fsSL "$DB_URL" 2>/dev/null | zstd -d -o "$DB_TARGET" -f 2>/dev/null
  export OFFICEQA_SQLITE_DB="$DB_TARGET"
fi

if [ -z "${OFFICEQA_SQLITE_DB:-}" ]; then
  exit 1
fi

cd "$SCRIPT_DIR"

exec python3 -m server.mcp_stdio
