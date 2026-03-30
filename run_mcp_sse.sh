#!/usr/bin/env bash
# Launch the OfficeQA Arena MCP SSE server.
#
# Runs on port 8081 by default, alongside the existing baked-in server on 8080.
# Connects to the 11GB SQLite DB on the droplet.
#
# Usage:
#   ./run_mcp_sse.sh                    # defaults: 0.0.0.0:8081
#   ./run_mcp_sse.sh --port 9090        # custom port
#   OFFICEQA_SQLITE_DB=/path/to/db.sqlite3 ./run_mcp_sse.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Default DB path on the droplet
export OFFICEQA_SQLITE_DB="${OFFICEQA_SQLITE_DB:-/app/corpus/officeqa_corpus.sqlite3}"

# Ensure dependencies are available
if ! python3 -c "import mcp" 2>/dev/null; then
    echo "[run_mcp_sse] Installing mcp package..."
    pip3 install --quiet mcp 2>/dev/null || pip3 install --quiet --break-system-packages mcp
fi

echo "[run_mcp_sse] DB: ${OFFICEQA_SQLITE_DB}"
echo "[run_mcp_sse] Starting SSE server..."

exec python3 -m server.mcp_sse "$@"
