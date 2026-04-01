#!/usr/bin/env bash
set -euo pipefail

# Arena test wrapper — exports env vars that the openhands-sdk harness
# reads from os.environ BEFORE extra_env gets merged.
#
# Usage:
#   ./scripts/arena_test.sh                     # run 5 sample tasks
#   ./scripts/arena_test.sh --task uid0004      # run one task
#   ./scripts/arena_test.sh --all               # run all 20 sample tasks

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# ── Extract API key from arena.yaml ─────────────────────────────────
# The openhands-sdk harness checks os.environ for LLM_API_KEY before
# the arena.yaml env block gets merged. We must export it here.
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

# ── Check Docker/Colima ─────────────────────────────────────────────
if ! docker info >/dev/null 2>&1; then
  echo "WARNING: Docker is not running."
  echo "  Start Colima:  colima start --memory 4 --disk 20"
  echo "  Or run on droplet: ./scripts/arena_droplet.sh"
  exit 1
fi

# ── DB contract check ───────────────────────────────────────────────
echo "=== Pre-flight checks ==="
echo "  LLM_API_KEY: ${LLM_API_KEY:0:12}..."
echo "  Harness: openhands-sdk"
echo "  Docker: $(docker info --format '{{.ServerVersion}}' 2>/dev/null || echo 'unknown')"
echo ""

# ── Run arena test ──────────────────────────────────────────────────
echo "=== Running arena test ==="
arena test "$@"
