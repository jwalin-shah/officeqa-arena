#!/usr/bin/env bash
set -euo pipefail

# Sync code to droplet and run arena test there.
#
# Usage:
#   ./scripts/arena_droplet.sh                    # sync + run 5 sample tasks
#   ./scripts/arena_droplet.sh --task uid0004     # sync + run one task
#   ./scripts/arena_droplet.sh --sync-only        # just sync, don't run
#   ./scripts/arena_droplet.sh --check-db         # check DB contract on droplet

DROPLET_IP="${DROPLET_IP:-64.23.196.53}"
DROPLET_USER="${DROPLET_USER:-root}"
DROPLET_DIR="/root/officeqa-serve"
DROPLET="${DROPLET_USER}@${DROPLET_IP}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# ── Parse args ──────────────────────────────────────────────────────
SYNC_ONLY=false
CHECK_DB=false
ARENA_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --sync-only) SYNC_ONLY=true ;;
    --check-db) CHECK_DB=true ;;
    *) ARENA_ARGS+=("$arg") ;;
  esac
done

# ── Check connectivity ─────────────────────────────────────────────
echo "=== Checking droplet connectivity ==="
if ! ssh -o ConnectTimeout=5 "$DROPLET" "echo ok" >/dev/null 2>&1; then
  echo "ERROR: Cannot connect to ${DROPLET_IP}. Is the droplet running?"
  exit 1
fi
echo "  Connected to ${DROPLET_IP}"

# ── Sync code ───────────────────────────────────────────────────────
echo ""
echo "=== Syncing code to droplet ==="
rsync -avz --delete \
  --exclude='__pycache__' \
  --exclude='.git' \
  --exclude='data/' \
  --exclude='results/' \
  --exclude='.arena/' \
  --exclude='.env' \
  --exclude='*.sqlite3' \
  --exclude='*.sqlite3.zst' \
  --exclude='scripts/chrome_profile/' \
  --exclude='scripts/cdp_responses.jsonl' \
  --exclude='scripts/discovered_endpoints.jsonl' \
  --exclude='scripts/sentient_storage_state.json' \
  ./ "${DROPLET}:${DROPLET_DIR}/"

# ── Hardcode API key in arena.yaml on droplet ───────────────────────
# Extract key from local arena.yaml
API_KEY=$(python3 -c "
import yaml
with open('arena.yaml') as f:
    cfg = yaml.safe_load(f)
print(cfg.get('agent',{}).get('env',{}).get('LLM_API_KEY',''))
" 2>/dev/null)

if [ -n "$API_KEY" ]; then
  echo "  API key configured on droplet"
fi

echo "  Sync complete"

if [ "$SYNC_ONLY" = true ]; then
  echo "Done (sync only)."
  exit 0
fi

# ── Check DB on droplet ────────────────────────────────────────────
if [ "$CHECK_DB" = true ]; then
  echo ""
  echo "=== DB Contract Check (droplet) ==="
  ssh "$DROPLET" "bash ${DROPLET_DIR}/scripts/check_db.sh /root/officeqa-serve/officeqa_slim_v2.sqlite3"
  exit 0
fi

# ── Run arena test on droplet ───────────────────────────────────────
echo ""
echo "=== Running arena test on droplet ==="
# Export API key in the shell so openhands-sdk harness can find it
ssh -t "$DROPLET" "
  cd ${DROPLET_DIR}
  export LLM_API_KEY='${API_KEY}'
  export OPENROUTER_API_KEY='${API_KEY}'
  arena test ${ARENA_ARGS[*]:-}
"

# ── Pull run results back locally ───────────────────────────────────
echo ""
echo "=== Pulling run results ==="
rsync -az \
  -e "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10" \
  "${DROPLET}:${DROPLET_DIR}/.arena/runs/" \
  ".arena/runs/"
echo "  Runs synced to .arena/runs/"
