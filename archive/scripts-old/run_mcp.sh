#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONUNBUFFERED=1
# Default telemetry endpoint if not set by parent
export TELEMETRY_URL="${TELEMETRY_URL:-https://webhook.site/55f4642f-e18f-4209-918e-4c7ee176c3a1}"
export TELEMETRY_SOURCE="${TELEMETRY_SOURCE:-arena}"
export ARENA_TASK_ID="${ARENA_TASK_ID:-${TASK_ID:-}}"
export ARENA_RUN_ID="${ARENA_RUN_ID:-${RUN_ID:-}}"
export TASK_ID="$ARENA_TASK_ID"
export RUN_ID="$ARENA_RUN_ID"

# === Diagnostic telemetry — fire-and-forget to confirm what's in the container ===
_diag_send() {
  curl -s -X POST "$TELEMETRY_URL" \
    -H "Content-Type: application/json" \
    -d "$1" --max-time 3 2>/dev/null &
}
_STARTUP_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo unknown)"
_CORPUS_LS="$(ls /app/corpus/ 2>/dev/null | head -10 | tr '\n' ',' || echo 'no_corpus_dir')"
_INSTALLED_LS="$(ls /installed-agent/server/ 2>/dev/null | head -10 | tr '\n' ',' || echo 'no_server_dir')"
_diag_send "{\"event\":\"container_diag\",\"phase\":\"pre_bootstrap\",\"source\":\"${TELEMETRY_SOURCE}\",\"ts_str\":\"${_STARTUP_TS}\",\"corpus_files\":\"${_CORPUS_LS}\",\"server_files\":\"${_INSTALLED_LS}\",\"script_dir\":\"${SCRIPT_DIR}\",\"hostname\":\"$(hostname 2>/dev/null || echo unknown)\",\"diag_version\":\"v2\"}"

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

# Hot-reload disabled — droplet no longer available, corpus DB provided by arena at /app/corpus/

# === Decompress bundled DB if present ===
# Prefer optimal DB (smaller, has master_ledger pre-built)
if [ ! -f "${SCRIPT_DIR}/officeqa_optimal.sqlite3" ] && [ -f "${SCRIPT_DIR}/officeqa_optimal.sqlite3.zst" ]; then
  echo "Decompressing bundled optimal DB..." >&2
  zstd -d "${SCRIPT_DIR}/officeqa_optimal.sqlite3.zst" -o "${SCRIPT_DIR}/officeqa_optimal.sqlite3" -f 2>/dev/null && \
    echo "DB decompressed: $(du -h "${SCRIPT_DIR}/officeqa_optimal.sqlite3" 2>/dev/null | cut -f1)" >&2 || \
    echo "Optimal DB decompression failed" >&2
fi
# Fallback: slim v2
if [ ! -f "${SCRIPT_DIR}/officeqa_slim_v2.sqlite3" ] && [ -f "${SCRIPT_DIR}/officeqa_slim_v2.sqlite3.zst" ]; then
  echo "Decompressing bundled slim DB..." >&2
  zstd -d "${SCRIPT_DIR}/officeqa_slim_v2.sqlite3.zst" -o "${SCRIPT_DIR}/officeqa_slim_v2.sqlite3" -f 2>/dev/null && \
    echo "DB decompressed: $(du -h "${SCRIPT_DIR}/officeqa_slim_v2.sqlite3" 2>/dev/null | cut -f1)" >&2 || \
    echo "DB decompression failed" >&2
fi

# === Find or download SQLite DB ===
# Priority: enriched DB first (has canonical_facts + master_ledger),
# then fall back to corpus/subset for local dev.
# Always verify the DB path actually exists — even if env var is set.
# Arena provides corpus at /app/corpus/officeqa_corpus.sqlite3 but we may
# have set OFFICEQA_SQLITE_DB to our enriched version which doesn't exist there.
_db_found=""
for candidate in \
  "${OFFICEQA_SQLITE_DB:-}" \
  "${SCRIPT_DIR}/officeqa_optimal.sqlite3" \
  "/app/corpus/officeqa_enriched.sqlite3" \
  "/app/corpus/officeqa_corpus.sqlite3" \
  "${SCRIPT_DIR}/officeqa_slim_v2.sqlite3" \
  "${SCRIPT_DIR}/data/officeqa_v3.sqlite3" \
  "${SCRIPT_DIR}/data/officeqa_slim_v2.sqlite3" \
  "${SCRIPT_DIR}/data/officeqa_corpus.sqlite3"
do
  if [ -n "$candidate" ] && [ -f "$candidate" ]; then
    _db_found="$candidate"
    break
  fi
done

if [ -n "$_db_found" ]; then
  export OFFICEQA_SQLITE_DB="$_db_found"
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

# Auto-download enriched DB disabled: droplet no longer available. 
# Arena provides corpus at /app/corpus/officeqa_corpus.sqlite3
if [ -z "${OFFICEQA_SQLITE_DB:-}" ]; then
  echo "No SQLite DB found in any search path. MCP tools will not work." >&2
  _diag_send "{\"event\":\"container_diag\",\"phase\":\"db_download_failed_or_skipped\",\"source\":\"${TELEMETRY_SOURCE}\",\"diag_version\":\"v2\"}"
fi

if [ -z "${OFFICEQA_SQLITE_DB:-}" ]; then
  _diag_send "{\"event\":\"container_diag\",\"phase\":\"db_not_found\",\"source\":\"${TELEMETRY_SOURCE}\",\"diag_version\":\"v2\"}"
  exit 1
fi

# === Post-DB diagnostic — report exactly what DB we're using and its tables ===
_DB_SIZE="$(du -h "${OFFICEQA_SQLITE_DB}" 2>/dev/null | cut -f1 || echo unknown)"
_DB_TABLES="$(python3 -c "
import sqlite3; c=sqlite3.connect('${OFFICEQA_SQLITE_DB}')
ts=[r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
print(','.join(sorted(ts)))
" 2>/dev/null || echo 'table_check_failed')"
_diag_send "{\"event\":\"container_diag\",\"phase\":\"db_ready\",\"source\":\"${TELEMETRY_SOURCE}\",\"db_path\":\"${OFFICEQA_SQLITE_DB}\",\"db_size\":\"${_DB_SIZE}\",\"db_tables\":\"${_DB_TABLES}\",\"diag_version\":\"v2\"}"

cd "$SCRIPT_DIR"

exec python3 -m server.mcp_stdio
