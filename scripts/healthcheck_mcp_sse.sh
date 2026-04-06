#!/usr/bin/env bash
# Health check for server.mcp_sse (FastMCP SSE). Default listens on :8081.
# Usage:
#   MCP_SSE_BASE_URL=http://127.0.0.1:8081 ./scripts/healthcheck_mcp_sse.sh
set -euo pipefail
BASE="${MCP_SSE_BASE_URL:-http://127.0.0.1:8081}"
# FastMCP SSE typically exposes GET /sse for the SSE stream
code="$(curl -sS -o /dev/null -w "%{http_code}" --max-time 5 "${BASE%/}/sse" || true)"
if [[ "$code" =~ ^(200|405)$ ]]; then
  echo "ok (HTTP $code)"
  exit 0
fi
echo "unexpected HTTP $code from ${BASE%/}/sse" >&2
exit 1
