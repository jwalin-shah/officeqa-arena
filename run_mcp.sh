#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONUNBUFFERED=1
# Default telemetry endpoint if not set by parent
export TELEMETRY_URL="${TELEMETRY_URL:-http://147.182.206.223:8080}"

# === Bootstrap: install system + Python deps (first MCP connect in container) ===
# All output to stderr since stdout is the MCP JSON-RPC channel.
_bootstrap_done="${SCRIPT_DIR}/.bootstrap_done"
if [ ! -f "$_bootstrap_done" ]; then
  {
    # Install zstd (for DB decompression) and pip
    if ! command -v zstd >/dev/null 2>&1; then
      apt-get update -qq && apt-get install -y -qq --no-install-recommends zstd python3-pip || true
    fi
    # Install Python deps
    python3 -c "import msgpack, zstandard" 2>/dev/null || {
      pip3 install --break-system-packages --quiet msgpack zstandard 2>/dev/null || \
        python3 -m pip install --break-system-packages --quiet msgpack zstandard 2>/dev/null || true
    }
    touch "$_bootstrap_done"
  } >/dev/null 2>&1
fi

# === Find or download SQLite DB ===
# Priority: enriched DB first (has canonical_facts + master_ledger),
# then fall back to corpus/subset for local dev.
if [ -z "${OFFICEQA_SQLITE_DB:-}" ]; then
  for candidate in \
    "/app/corpus/officeqa_enriched.sqlite3" \
    "/app/corpus/officeqa_corpus.sqlite3" \
    "${SCRIPT_DIR}/data/officeqa_v3.sqlite3" \
    "${SCRIPT_DIR}/data/officeqa_slim_v2.sqlite3" \
    "${SCRIPT_DIR}/data/officeqa_corpus.sqlite3"
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
  DB_TARGET="/app/corpus/officeqa_enriched.sqlite3"
  DB_URL="http://147.182.206.223:9090/officeqa_v3.sqlite3.zst"
  mkdir -p "$(dirname "$DB_TARGET")" 2>/dev/null || true
  echo "Downloading enriched DB from ${DB_URL}..." >&2
  curl -fsSL "$DB_URL" | zstd -d -o "$DB_TARGET" -f 2>/dev/null
  echo "DB downloaded: $(ls -lh "$DB_TARGET" 2>/dev/null | awk '{print $5}')" >&2
  export OFFICEQA_SQLITE_DB="$DB_TARGET"
fi

if [ -z "${OFFICEQA_SQLITE_DB:-}" ]; then
  echo "FATAL: No SQLite DB found and download failed." >&2
  exit 1
fi

echo "MCP server starting with DB: ${OFFICEQA_SQLITE_DB}" >&2

cd "$SCRIPT_DIR"

exec python3 -m server.mcp_stdio
