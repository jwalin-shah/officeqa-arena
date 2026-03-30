#!/bin/bash
# MCP server launcher for Arena Docker containers.
# Installs Python deps synchronously (stderr only), then starts MCP server.
# All bootstrap output goes to stderr to keep stdout clean for JSON-RPC.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Set SQLite DB path
[ -z "${OFFICEQA_SQLITE_DB:-}" ] && [ -f /app/corpus/officeqa_corpus.sqlite3 ] && export OFFICEQA_SQLITE_DB="/app/corpus/officeqa_corpus.sqlite3"
[ -z "${OFFICEQA_SQLITE_DB:-}" ] && [ -f "${SCRIPT_DIR}/data/officeqa_corpus.sqlite3" ] && export OFFICEQA_SQLITE_DB="${SCRIPT_DIR}/data/officeqa_corpus.sqlite3"

cd "$SCRIPT_DIR"

# Install deps if needed — ALL output to stderr
if ! python3 -c "import mcp" 2>/dev/null; then
  {
    echo "[run_mcp.sh] Installing Python dependencies..."
    if command -v pip3 &>/dev/null; then
      pip3 install --quiet --break-system-packages mcp jinja2 pyyaml
    else
      apt-get update -qq
      apt-get install -y -qq python3-pip
      pip3 install --quiet --break-system-packages mcp jinja2 pyyaml
    fi
    echo "[run_mcp.sh] Dependencies installed successfully"
  } >&2
fi

# Start MCP server — stdout is the JSON-RPC channel
exec python3 -m server.mcp_server
