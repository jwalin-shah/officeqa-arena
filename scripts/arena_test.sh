#!/usr/bin/env bash
set -euo pipefail

# Arena test wrapper — exports env vars and tracks OpenRouter cost.
#
# Usage:
#   ./scripts/arena_test.sh                          # run sample tasks (default 4 concurrent)
#   ./scripts/arena_test.sh --filter 'uid0199'       # run one task
#   ./scripts/arena_test.sh --all                    # run all sample tasks
#   ./scripts/arena_test.sh --all -j8                # run all with 8 concurrent

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# ── Parse our flags (strip -j from arena args) ───────────────────────
CONCURRENCY=""
ARENA_ARGS=()
for arg in "$@"; do
  if [[ "$arg" =~ ^-j([0-9]+)$ ]]; then
    CONCURRENCY="${BASH_REMATCH[1]}"
  else
    ARENA_ARGS+=("$arg")
  fi
done

# ── Extract API key from arena.yaml ─────────────────────────────────
if [ -z "${LLM_API_KEY:-}" ]; then
  LLM_API_KEY=$(python3 -c "
import yaml, sys
with open('arena.yaml') as f:
    cfg = yaml.safe_load(f)
key = cfg.get('agent',{}).get('env',{}).get('LLM_API_KEY','')
if not key:
    key = cfg.get('agent',{}).get('env',{}).get('OPENROUTER_API_KEY','')
print(key)
" 2>/dev/null || echo "")
fi

if [ -z "${LLM_API_KEY:-}" ]; then
  echo "ERROR: No LLM_API_KEY found in arena.yaml or environment"
  exit 1
fi

export LLM_API_KEY
export OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-$LLM_API_KEY}"

# ── OpenRouter usage tracking ─────────────────────────────────────────
_or_usage() {
  curl -s -H "Authorization: Bearer $OPENROUTER_API_KEY" \
    "https://openrouter.ai/api/v1/auth/key" \
    | python3 -c "import sys,json; d=json.load(sys.stdin)['data']; print(f\"{d['usage']:.6f}\")" 2>/dev/null || echo "0"
}

_or_remaining() {
  curl -s -H "Authorization: Bearer $OPENROUTER_API_KEY" \
    "https://openrouter.ai/api/v1/auth/key" \
    | python3 -c "import sys,json; d=json.load(sys.stdin)['data']; print(f\"{d['limit_remaining']:.4f}\")" 2>/dev/null || echo "?"
}

# ── Check Docker ──────────────────────────────────────────────────────
if command -v docker >/dev/null 2>&1 && ! docker info >/dev/null 2>&1; then
  echo "WARNING: Docker is not running."
  echo "  Start Colima:  colima start --memory 4 --disk 20"
  exit 1
fi

# ── Patch concurrency if requested ────────────────────────────────────
if [ -n "$CONCURRENCY" ]; then
  echo "Patching n_concurrent_trials to $CONCURRENCY..."
  python3 -c "
import importlib, harbor.models.job.config as c
# Monkey-patch default before arena reads it
c.OrchestratorConfig.model_fields['n_concurrent_trials'].default = $CONCURRENCY
" 2>/dev/null || true
  # Fallback: patch the actual source file
  ORCH_CFG="$(python3 -c 'import harbor.models.job.config as c; print(c.__file__)')"
  if [ -f "$ORCH_CFG" ]; then
    sed -i "s/n_concurrent_trials: int = [0-9]*/n_concurrent_trials: int = $CONCURRENCY/" "$ORCH_CFG"
    echo "  Patched $ORCH_CFG"
  fi
fi

# ── Pre-flight ────────────────────────────────────────────────────────
echo "=== Pre-flight ==="
echo "  API key: ${OPENROUTER_API_KEY:0:12}..."
echo "  Concurrency: ${CONCURRENCY:-4 (default)}"
BEFORE=$(_or_usage)
echo "  OpenRouter usage: \$${BEFORE}"
echo "  Remaining: \$$(_or_remaining)"
echo ""

# ── Run arena test ────────────────────────────────────────────────────
echo "=== Running arena test ==="
ARENA_BIN="${ARENA_BIN:-arena}"
command -v "$ARENA_BIN" >/dev/null 2>&1 || ARENA_BIN="/opt/arena-venv/bin/arena"

"$ARENA_BIN" test "${ARENA_ARGS[@]}"
EXIT_CODE=$?

# ── Post-run cost report ──────────────────────────────────────────────
echo ""
echo "=== OpenRouter cost report ==="
AFTER=$(_or_usage)
COST=$(python3 -c "print(f'\${float(\"$AFTER\") - float(\"$BEFORE\"):.4f}')")
N_TASKS=$(echo "${ARENA_ARGS[@]}" | grep -c 'all' && echo 20 || echo 1)
echo "  Run cost: ${COST}"
echo "  Total usage: \$${AFTER}"
echo "  Remaining: \$$(_or_remaining)"

exit $EXIT_CODE
