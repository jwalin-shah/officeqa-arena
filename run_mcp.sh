#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONUNBUFFERED=1
# Default telemetry endpoint if not set by parent
export TELEMETRY_URL="${TELEMETRY_URL:-http://147.182.206.223:8080}"
export TELEMETRY_SOURCE="${TELEMETRY_SOURCE:-arena}"
export ARENA_TASK_ID="${ARENA_TASK_ID:-${TASK_ID:-}}"
export ARENA_RUN_ID="${ARENA_RUN_ID:-${RUN_ID:-}}"
export TASK_ID="$ARENA_TASK_ID"
export RUN_ID="$ARENA_RUN_ID"

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

# === Hot-reload MCP bundle from DDB ===
# Pull the latest server/, prompts/, and dependencies from central DDB
# This ensures containers always use the latest guardrails and code changes
_bundle_url="http://147.182.206.223:9090/mcp_bundle.tar.gz"
_ua="officeqa-mcp/1.0 (source=${TELEMETRY_SOURCE:-unknown}; task=${ARENA_TASK_ID:-none})"
if curl -fsSL --max-time 30 -A "$_ua" "$_bundle_url" -o /tmp/mcp_bundle.tar.gz 2>/dev/null; then
  # Verify and extract bundle to SCRIPT_DIR, overwriting stale code
  if tar -tzf /tmp/mcp_bundle.tar.gz >/dev/null 2>&1; then
    tar -xzf /tmp/mcp_bundle.tar.gz -C "$SCRIPT_DIR" --strip-components=0 2>/dev/null || true
    rm -f /tmp/mcp_bundle.tar.gz
  fi
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
  "/app/corpus/officeqa_enriched.sqlite3" \
  "/app/corpus/officeqa_corpus.sqlite3" \
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

# Auto-download enriched DB if not found anywhere
if [ -z "${OFFICEQA_SQLITE_DB:-}" ]; then
  DB_TARGET="/app/corpus/officeqa_enriched.sqlite3"
  DB_URL="http://147.182.206.223:9090/officeqa_v3.sqlite3.zst"
  mkdir -p "$(dirname "$DB_TARGET")" 2>/dev/null || true
  curl -fsSL "$DB_URL" | zstd -d -o "$DB_TARGET" -f 2>/dev/null
  export OFFICEQA_SQLITE_DB="$DB_TARGET"
fi

if [ -z "${OFFICEQA_SQLITE_DB:-}" ]; then
  exit 1
fi

# Silence: Goose treats any early stderr as extension failure

cd "$SCRIPT_DIR"

exec python3 -m server.mcp_stdio
