#!/usr/bin/env bash
set -euo pipefail

# Local arena test that works around the openhands-sdk harness limitation:
# `arena test` doesn't copy project files to /installed-agent/ in the container.
# `arena submit` does (the platform extracts the tarball there).
#
# This script monkey-patches the setup to also upload our project files,
# then calls `arena test` normally.
#
# Usage:
#   ./scripts/arena_test_local.sh              # smoke test (1 task)
#   ./scripts/arena_test_local.sh --all        # all sample tasks
#   ./scripts/arena_test_local.sh -n 5         # 5 tasks

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# ── Export API key ──────────────────────────────────────────────────
if [ -z "${LLM_API_KEY:-}" ]; then
  LLM_API_KEY=$(python3 -c "
import yaml
with open('arena.yaml') as f:
    cfg = yaml.safe_load(f)
key = cfg.get('agent',{}).get('env',{}).get('LLM_API_KEY','')
if not key:
    key = cfg.get('agent',{}).get('env',{}).get('OPENROUTER_API_KEY','')
print(key)
" 2>/dev/null || echo "")
fi

if [ -z "$LLM_API_KEY" ]; then
  echo "ERROR: No LLM_API_KEY found"
  exit 1
fi

export LLM_API_KEY
export OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-$LLM_API_KEY}"

# ── Check Docker ────────────────────────────────────────────────────
if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker is not running. Start Colima: colima start --memory 4 --disk 20"
  exit 1
fi

echo "=== Pre-flight ==="
echo "  API key: ${LLM_API_KEY:0:12}..."
echo "  Docker: $(docker info --format '{{.ServerVersion}}' 2>/dev/null)"
echo ""

# ── Apply monkey-patch and run arena test ────────────────────────────
ARENA_PYTHON="${HOME}/.arena/venv/bin/python3"
if [ ! -f "$ARENA_PYTHON" ]; then
  echo "ERROR: Arena venv not found at ${ARENA_PYTHON}"
  exit 1
fi

export PROJECT_DIR="$PROJECT_DIR"

echo "=== Running arena test (with project file upload) ==="
"$ARENA_PYTHON" -c "
import sys, os
from arena_sdk.harness.openhands_sdk import OpenHandsSDKAgent
from pathlib import Path

_original_setup = OpenHandsSDKAgent.setup
PROJECT_DIR = Path(os.environ.get('PROJECT_DIR', '.')).resolve()

UPLOAD_ITEMS = [
    ('server', True),
    ('run_mcp.sh', False),
    ('install.sh', False),
    ('prompts', True),
    ('data/reference', True),
]

async def patched_setup(self, environment):
    await _original_setup(self, environment)
    for item_name, is_dir in UPLOAD_ITEMS:
        local_path = PROJECT_DIR / item_name
        if not local_path.exists():
            continue
        container_path = f'/installed-agent/{item_name}'
        if is_dir:
            await environment.exec(command=f'mkdir -p {container_path}')
            await environment.upload_dir(str(local_path), container_path)
        else:
            await environment.upload_file(str(local_path), container_path)
    await environment.exec(command='chmod +x /installed-agent/run_mcp.sh /installed-agent/install.sh 2>/dev/null || true')
    result = await environment.exec(
        command='bash /installed-agent/install.sh',
        env={'DEBIAN_FRONTEND': 'noninteractive'},
    )
    if result.return_code != 0:
        print(f'WARNING: install.sh exit {result.return_code}', file=sys.stderr)

OpenHandsSDKAgent.setup = patched_setup

# Now run arena CLI normally
sys.argv = ['arena', 'test'] + sys.argv[1:]
from arena_cli.main import app
app()
" "$@"
