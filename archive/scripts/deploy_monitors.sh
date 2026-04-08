#!/usr/bin/env bash
# Deploy polling scripts + session cookies to the droplet.
# Usage: bash scripts/deploy_monitors.sh
set -euo pipefail

DROPLET="root@147.182.206.223"
REMOTE_DIR="/root/monitors"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Deploying monitor scripts to ${DROPLET}:${REMOTE_DIR}"

ssh "$DROPLET" "mkdir -p $REMOTE_DIR"

scp -q \
  "$SCRIPT_DIR/poll_submission.py" \
  "$SCRIPT_DIR/poll_leaderboard.py" \
  "$SCRIPT_DIR/sentient_storage_state.json" \
  "$DROPLET:$REMOTE_DIR/"

# Install requests if needed
ssh "$DROPLET" "pip3 install -q requests 2>/dev/null || python3 -m pip install -q requests 2>/dev/null || true"

echo "==> Deployed. Scripts at ${DROPLET}:${REMOTE_DIR}/"
