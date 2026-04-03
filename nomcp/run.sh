#!/usr/bin/env bash
# OfficeQA Arena — Standalone runner (no Docker, no Arena CLI)
#
# Usage:
#   # Set your API key
#   export OPENROUTER_API_KEY="sk-or-v1-..."
#
#   # Run smoke test (3 tasks)
#   ./nomcp/run.sh --smoke --corpus /path/to/corpus
#
#   # Run specific UIDs
#   ./nomcp/run.sh --corpus /path/to/corpus --uids UID0001,UID0002,UID0003
#
#   # Run all 246 with 4 concurrent
#   ./nomcp/run.sh --corpus /path/to/corpus --concurrency 4
#
#   # Run all 246 sequentially
#   ./nomcp/run.sh --corpus /path/to/corpus

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# ── Parse flags ──────────────────────────────────────────────────────
ARGS=()
SMOKE=false
for arg in "$@"; do
    if [[ "$arg" == "--smoke" ]]; then
        SMOKE=true
    else
        ARGS+=("$arg")
    fi
done

# ── Validate API key ─────────────────────────────────────────────────
if [ -z "${OPENROUTER_API_KEY:-}" ]; then
    # Try to load from .env
    if [ -f "$PROJECT_DIR/.env" ]; then
        export $(grep -v '^#' "$PROJECT_DIR/.env" | xargs)
    fi
fi

if [ -z "${OPENROUTER_API_KEY:-}" ]; then
    echo "ERROR: Set OPENROUTER_API_KEY environment variable"
    echo "  export OPENROUTER_API_KEY='sk-or-v1-...'"
    exit 1
fi

# ── Check remaining balance ──────────────────────────────────────────
echo "Checking OpenRouter balance..."
BALANCE=$(curl -s -H "Authorization: Bearer $OPENROUTER_API_KEY" \
    "https://openrouter.ai/api/v1/auth/key" \
    | python3 -c "import sys,json; d=json.load(sys.stdin).get('data',{}); print(f\"Usage: \${d.get('usage',0):.4f} / Limit: \${d.get('limit',0):.2f} / Remaining: \${d.get('limit_remaining','?')}\")" 2>/dev/null || echo "Could not check balance")
echo "  $BALANCE"
echo ""

# ── Smoke test mode ──────────────────────────────────────────────────
if $SMOKE; then
    echo "Running smoke test (3 tasks: UID0001, UID0002, UID0007)..."
    exec python3 "$SCRIPT_DIR/run_all.py" \
        --cases "$PROJECT_DIR/data/officeqa_full.csv" \
        --uids "UID0001,UID0002,UID0007" \
        "${ARGS[@]}"
fi

# ── Full run ─────────────────────────────────────────────────────────
echo "Starting OfficeQA runner..."
exec python3 "$SCRIPT_DIR/run_all.py" \
    --cases "$PROJECT_DIR/data/officeqa_full.csv" \
    "${ARGS[@]}"
