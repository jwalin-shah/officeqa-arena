#!/bin/bash
# MCP server launcher with automatic DB download.
# Downloads compressed lean DB from droplet, decompresses, then starts MCP server.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DB_PATH="/app/corpus/officeqa_corpus.sqlite3"
DB_URL="http://134.209.73.238:9090/officeqa_lean_final.sqlite3.zst"

# Download DB if not present
if [ ! -f "$DB_PATH" ]; then
  echo "[run_mcp] Downloading lean DB..." >&2
  python3 -c "
import urllib.request, sys
print('Downloading 581MB...', file=sys.stderr)
urllib.request.urlretrieve('$DB_URL', '/tmp/db.zst')
print('Done', file=sys.stderr)
"
  # Install zstd if needed
  if ! command -v zstd &>/dev/null; then
    apt-get update -qq >/dev/null 2>&1
    apt-get install -y -qq zstd >/dev/null 2>&1
  fi
  echo "[run_mcp] Decompressing..." >&2
  zstd -d /tmp/db.zst -o "$DB_PATH" 2>/dev/null
  rm -f /tmp/db.zst
  echo "[run_mcp] DB ready at $DB_PATH" >&2
fi

export OFFICEQA_SQLITE_DB="$DB_PATH"

# Try our fixed server first, fall back to baked-in
if [ -f "$SCRIPT_DIR/server/mcp_stdio.py" ]; then
  cd "$SCRIPT_DIR"
  exec python3 -m server.mcp_stdio
elif [ -f /opt/officeqa/run_mcp.sh ]; then
  exec bash /opt/officeqa/run_mcp.sh
else
  echo "[run_mcp] ERROR: No MCP server found" >&2
  exit 1
fi
