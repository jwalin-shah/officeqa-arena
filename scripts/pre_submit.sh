#!/usr/bin/env bash
# pre_submit.sh — Pre-submission checklist for officeqa-arena.
#
# Run this before every `arena submit` to catch common issues fast.
# All non-smoke checks complete in <5 seconds.
#
# Usage:
#   ./scripts/pre_submit.sh           # run all checks (no smoke test)
#   ./scripts/pre_submit.sh --smoke   # also run arena test --filter uid0001
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# ── Flags ─────────────────────────────────────────────────────────────
RUN_SMOKE=0
for arg in "$@"; do
  [[ "$arg" == "--smoke" ]] && RUN_SMOKE=1
done

# ── Box-drawing helpers ───────────────────────────────────────────────
BOX_WIDTH=42   # inner width (between ║ and ║)

_pad() {
  # _pad "text" -> text padded to BOX_WIDTH chars
  local text="$1"
  # Strip ANSI codes to measure visible length
  local visible
  visible="$(printf '%s' "$text" | sed 's/\x1b\[[0-9;]*m//g')"
  local len=${#visible}
  local pad=$(( BOX_WIDTH - len ))
  printf '%s%*s' "$text" "$pad" ""
}

_row() {
  printf '║ %s ║\n' "$(_pad "$1")"
}

_header() {
  printf '╔%s╗\n' "$(printf '═%.0s' $(seq 1 $(( BOX_WIDTH + 2 ))))"
  printf '║ %s ║\n' "$(_pad "$1")"
  printf '╠%s╣\n' "$(printf '═%.0s' $(seq 1 $(( BOX_WIDTH + 2 ))))"
}

_footer() {
  printf '╚%s╝\n' "$(printf '═%.0s' $(seq 1 $(( BOX_WIDTH + 2 ))))"
}

# Collect rows to print all at once at the end
ROWS=()
PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

_ok()   { ROWS+=("$(printf '\033[32m✓\033[0m %s' "$1")"); (( PASS_COUNT++ )) || true; }
_fail() { ROWS+=("$(printf '\033[31m✗\033[0m %s' "$1")"); (( FAIL_COUNT++ )) || true; }
_warn() { ROWS+=("$(printf '\033[33m⚠\033[0m %s' "$1")"); (( WARN_COUNT++ )) || true; }
_skip() { ROWS+=("$(printf '\033[90m✗\033[0m %s' "$1")"); }

# ── 1. Git Status ─────────────────────────────────────────────────────
cd "$PROJECT_DIR"

GIT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'unknown')"
GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
GIT_DIRTY="$(git status --porcelain 2>/dev/null)"

if [[ -z "$GIT_DIRTY" ]]; then
  _ok "Git: clean @ ${GIT_SHA} (${GIT_BRANCH})"
else
  DIRTY_COUNT="$(printf '%s\n' "$GIT_DIRTY" | grep -c . || true)"
  _warn "Git: ${DIRTY_COUNT} uncommitted file(s) @ ${GIT_SHA} (${GIT_BRANCH})"
fi

# ── 2. Config Validation ──────────────────────────────────────────────
ARENA_YAML="$PROJECT_DIR/arena.yaml"

_cfg_check() {
  python3 - "$ARENA_YAML" <<'PYEOF'
import sys, json
try:
    import yaml
except ImportError:
    # Fallback: minimal key=value extraction without PyYAML
    # We'll handle this below
    sys.exit(2)

with open(sys.argv[1]) as f:
    cfg = yaml.safe_load(f)

agent = cfg.get('agent', {})
harness = agent.get('harness_name', '')
model   = agent.get('model', '')
env     = agent.get('env', {})
api_key = env.get('OPENROUTER_API_KEY', '') or env.get('LLM_API_KEY', '')
mcp_cmd = ''
transport = ''
url = ''
for srv in agent.get('mcp_servers', []):
    if not transport:
        transport = srv.get('transport', '') or ''
    if srv.get('command'):
        mcp_cmd = srv['command']
        break
    if srv.get('url') and not url:
        url = srv['url']

result = {
    'harness': harness,
    'model':   model,
    'api_key': api_key,
    'mcp_cmd': mcp_cmd,
    'transport': transport,
    'url': url,
}
print(json.dumps(result))
PYEOF
}

CFG_JSON="$(_cfg_check 2>/dev/null)"
CFG_EXIT=$?

if [[ $CFG_EXIT -eq 0 && -n "$CFG_JSON" ]]; then
  HARNESS="$(printf '%s' "$CFG_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['harness'])")"
  MODEL="$(printf '%s' "$CFG_JSON"   | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['model'])")"
  API_KEY="$(printf '%s' "$CFG_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['api_key'])")"
  MCP_CMD="$(printf '%s' "$CFG_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['mcp_cmd'])")"
  MCP_TRANSPORT="$(printf '%s' "$CFG_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['transport'])")"
  MCP_URL="$(printf '%s' "$CFG_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['url'])")"

  CONFIG_OK=1
  CONFIG_ISSUES=""

  # Harness check
  if [[ "$HARNESS" == "openhands-sdk" || "$HARNESS" == "goose" ]]; then
    :
  else
    CONFIG_OK=0
    CONFIG_ISSUES+=" harness='${HARNESS}' (expected openhands-sdk or goose);"
  fi

  # Model check
  if [[ -z "$MODEL" ]]; then
    CONFIG_OK=0
    CONFIG_ISSUES+=" model not set;"
  fi

  # MCP wiring check: accept either stdio command or remote URL transport
  if [[ -n "$MCP_CMD" ]]; then
    :
  elif [[ -n "$MCP_TRANSPORT" && -n "$MCP_URL" ]]; then
    :
  else
    CONFIG_OK=0
    CONFIG_ISSUES+=" MCP server missing command/url transport wiring;"
  fi

  # Shorten model name for display (strip openrouter/ prefix)
  MODEL_SHORT="${MODEL#openrouter/}"
  # Take last segment after last /
  MODEL_LABEL="${MODEL_SHORT##*/}"

  if [[ $CONFIG_OK -eq 1 ]]; then
    if [[ -n "$MCP_CMD" ]]; then
      _ok "Config: ${HARNESS} + ${MODEL_LABEL} (stdio MCP)"
    else
      _ok "Config: ${HARNESS} + ${MODEL_LABEL} (${MCP_TRANSPORT} MCP)"
    fi
  else
    _fail "Config:${CONFIG_ISSUES}"
  fi
else
  _fail "Config: failed to parse arena.yaml"
  API_KEY=""
  MCP_CMD=""
  HARNESS=""
  MODEL=""
  MODEL_LABEL=""
fi

# ── 3. API Key Check ──────────────────────────────────────────────────
if [[ -z "${API_KEY:-}" ]]; then
  _fail "API Key: not found in arena.yaml"
else
  KEY_PREFIX="${API_KEY:0:12}"

  OR_RESP="$(curl -sf --max-time 5 \
    -H "Authorization: Bearer ${API_KEY}" \
    "https://openrouter.ai/api/v1/auth/key" 2>/dev/null || echo "")"

  if [[ -z "$OR_RESP" ]]; then
    _warn "API Key: ${KEY_PREFIX}... (could not reach OpenRouter)"
  else
    OR_VALID="$(printf '%s' "$OR_RESP" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    data = d.get('data', {})
    remaining = data.get('limit_remaining', None)
    if remaining is None:
        print('invalid')
    else:
        print(f'{remaining:.2f}')
except Exception:
    print('invalid')
" 2>/dev/null)"

    if [[ "$OR_VALID" == "invalid" ]]; then
      _fail "API Key: ${KEY_PREFIX}... INVALID"
    else
      REMAINING="$OR_VALID"
      # Warn if below $10
      LOW_BAL="$(python3 -c "print('yes' if float('${REMAINING}') < 10 else 'no')" 2>/dev/null || echo 'no')"
      if [[ "$LOW_BAL" == "yes" ]]; then
        _warn "API Key: valid (\$${REMAINING} remaining — LOW)"
      else
        _ok "API Key: valid (\$${REMAINING} remaining)"
      fi
    fi
  fi
fi

# ── 4. MCP Server Quick Test ──────────────────────────────────────────
# We test using the local Python module directly (not the arena container path).
# Find a local DB to test with (slim fallback, skip if none found).

LOCAL_DB=""
for candidate in \
  "$PROJECT_DIR/data/officeqa_enriched.sqlite3" \
  "$PROJECT_DIR/data/officeqa_slim_v2.sqlite3" \
  "$PROJECT_DIR/data/officeqa_corpus.sqlite3"; do
  if [[ -f "$candidate" ]]; then
    LOCAL_DB="$candidate"
    break
  fi
done

if [[ -z "$LOCAL_DB" ]]; then
  _warn "MCP Server: no local DB (skipping)"
else
  MCP_RESULT="$(OFFICEQA_SQLITE_DB="$LOCAL_DB" PYTHONUNBUFFERED=1 \
    python3 - <<'PYEOF' 2>/dev/null
import json, os, subprocess, sys
from pathlib import Path

root = Path(__file__).resolve().parents[0] if '__file__' in dir() else Path('.')
# This script is run with python3 - so __file__ is not set; use cwd approach
import os
root = Path(os.environ.get('PWD', '.')).resolve()

proc = subprocess.Popen(
    [sys.executable, '-m', 'server.mcp_stdio'],
    cwd=str(root),
    env=os.environ.copy(),
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)

def rpc(msg):
    proc.stdin.write(json.dumps(msg) + '\n')
    proc.stdin.flush()
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError('no response')
    return json.loads(line)

try:
    rpc({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}})
    proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized', 'params': {}}) + '\n')
    proc.stdin.flush()
    resp = rpc({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}})
    tools = resp.get('result', {}).get('tools', [])
    print(f'OK:{len(tools)}')
except Exception as e:
    print(f'FAIL:{e}')
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
PYEOF
  )"

  if [[ "$MCP_RESULT" == OK:* ]]; then
    TOOL_COUNT="${MCP_RESULT#OK:}"
    _ok "MCP Server: ${TOOL_COUNT} tools registered"
  else
    ERR="${MCP_RESULT#FAIL:}"
    _fail "MCP Server: FAILED (${ERR:-unknown error})"
  fi
fi

# ── 5. Prompt File Hashes ─────────────────────────────────────────────
SYSTEM_J2="$PROJECT_DIR/prompts/system.j2"
GOOSE_MD="$PROJECT_DIR/prompts/goose_instructions.md"
ARENA_YAML_FILE="$PROJECT_DIR/arena.yaml"

_md5() {
  local f="$1"
  if [[ ! -f "$f" ]]; then
    echo "missing"
    return
  fi
  if command -v md5sum &>/dev/null; then
    md5sum "$f" | awk '{print $1}'
  else
    md5 -q "$f"
  fi
}

SYS_HASH="$(_md5 "$SYSTEM_J2")"
GOOSE_HASH="$(_md5 "$GOOSE_MD")"
YAML_HASH="$(_md5 "$ARENA_YAML_FILE")"

# Try to find last submission metadata for comparison
LAST_META=""
LAST_META_FILE=""
for d in "$PROJECT_DIR/results"/*; do
  candidate="$d/metadata.json"
  if [[ -f "$candidate" ]]; then
    # Keep the most-recently modified one
    if [[ -z "$LAST_META_FILE" || "$candidate" -nt "$LAST_META_FILE" ]]; then
      LAST_META_FILE="$candidate"
    fi
  fi
done
if [[ -n "$LAST_META_FILE" ]]; then
  LAST_META="$(cat "$LAST_META_FILE" 2>/dev/null || echo '')"
fi

_hash_row() {
  local label="$1" hash="$2" meta_key="$3"
  local short="${hash:0:8}"
  local changed_note=""
  if [[ -n "$LAST_META" && -n "$meta_key" ]]; then
    PREV_HASH="$(printf '%s' "$LAST_META" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('${meta_key}', ''))
except Exception:
    print('')
" 2>/dev/null || echo '')"
    if [[ -n "$PREV_HASH" && "$PREV_HASH" != "$hash" ]]; then
      changed_note=" (changed)"
    fi
  fi
  if [[ "$hash" == "missing" ]]; then
    _warn "${label}: MISSING"
  else
    _ok "${label}: ${short}${changed_note}"
  fi
}

_hash_row "system.j2   " "$SYS_HASH"   "system_j2_md5"
_hash_row "goose_inst  " "$GOOSE_HASH" "goose_md_md5"
_hash_row "arena.yaml  " "$YAML_HASH"  "arena_yaml_md5"

# ── 6. Smoke Test ─────────────────────────────────────────────────────
if [[ $RUN_SMOKE -eq 1 ]]; then
  ARENA_BIN="${ARENA_BIN:-arena}"
  command -v "$ARENA_BIN" &>/dev/null || ARENA_BIN="/opt/arena-venv/bin/arena"

  if ! command -v "$ARENA_BIN" &>/dev/null; then
    _fail "Smoke test: arena binary not found"
  else
    # Track OpenRouter cost before
    _or_remaining() {
      curl -sf --max-time 5 \
        -H "Authorization: Bearer ${API_KEY}" \
        "https://openrouter.ai/api/v1/auth/key" \
        | python3 -c "import sys,json; d=json.load(sys.stdin)['data']; print(f\"{d['usage']:.6f}\")" 2>/dev/null || echo "0"
    }
    BEFORE_USAGE="$(_or_remaining)"

    SMOKE_OUT="$("$ARENA_BIN" test --filter uid0001 2>&1)"
    SMOKE_EXIT=$?

    AFTER_USAGE="$(_or_remaining)"
    SMOKE_COST="$(python3 -c "
try:
    cost = float('${AFTER_USAGE}') - float('${BEFORE_USAGE}')
    print(f'\${cost:.4f}')
except Exception:
    print('?')
" 2>/dev/null)"

    if [[ $SMOKE_EXIT -eq 0 ]]; then
      _ok "Smoke test: PASS (cost ${SMOKE_COST})"
    else
      _fail "Smoke test: FAIL (cost ${SMOKE_COST})"
    fi
  fi
else
  _skip "Smoke test: SKIPPED (use --smoke)"
fi

# ── 7. Submission Quota Reminder ──────────────────────────────────────
_warn "Reminder: 3 submissions/day limit"

# ── Print the box ─────────────────────────────────────────────────────
echo ""
_header "    Pre-Submission Checklist      "
for row in "${ROWS[@]}"; do
  _row "$row"
done
_footer
echo ""

# ── Summary line ──────────────────────────────────────────────────────
printf "  "
if [[ $FAIL_COUNT -gt 0 ]]; then
  printf '\033[31m%d failed\033[0m  ' "$FAIL_COUNT"
fi
if [[ $WARN_COUNT -gt 0 ]]; then
  printf '\033[33m%d warning(s)\033[0m  ' "$WARN_COUNT"
fi
printf '\033[32m%d passed\033[0m\n' "$PASS_COUNT"
echo ""

if [[ $FAIL_COUNT -gt 0 ]]; then
  echo "  Fix failures before submitting."
  exit 1
fi
