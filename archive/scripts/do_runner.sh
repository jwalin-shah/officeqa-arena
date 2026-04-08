#!/usr/bin/env bash
set -euo pipefail

# Spin up / tear down an on-demand DO runner for arena test.
#
# Usage:
#   ./scripts/do_runner.sh up        # create runner, install deps, sync code
#   ./scripts/do_runner.sh down       # destroy runner
#   ./scripts/do_runner.sh ip         # print runner IP (if exists)
#   ./scripts/do_runner.sh test ...   # sync + arena test (passes extra args)
#   ./scripts/do_runner.sh smoke      # sync + arena test (1 task)
#
# Runner is s-2vcpu-4gb ($24/mo = ~$0.036/hr). Create, test, destroy.

RUNNER_NAME="officeqa-runner"
RUNNER_SIZE="${RUNNER_SIZE:-s-4vcpu-8gb}"
RUNNER_IMAGE="${RUNNER_IMAGE:-223007008}"  # officeqa-runner-ready-2026-04-02 snapshot
RUNNER_REGION="sfo3"
DB_URL="http://147.182.206.223:9090/officeqa_slim_v2.sqlite3.zst"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

get_ip() {
  doctl compute droplet list --format "Name,PublicIPv4" --no-header 2>/dev/null \
    | grep "^${RUNNER_NAME}" | awk '{print $2}' | head -1
}

cmd_up() {
  local existing_ip
  existing_ip=$(get_ip)
  if [ -n "$existing_ip" ]; then
    echo "Runner already exists at ${existing_ip}"
    return 0
  fi

  echo "=== Creating runner (${RUNNER_SIZE}) ==="
  local ssh_key_id
  ssh_key_id=$(doctl compute ssh-key list --format ID --no-header | head -1)

  doctl compute droplet create "$RUNNER_NAME" \
    --size "$RUNNER_SIZE" \
    --image "$RUNNER_IMAGE" \
    --region "$RUNNER_REGION" \
    --ssh-keys "$ssh_key_id" \
    --user-data '#!/bin/bash
chage -d $(date +%Y-%m-%d) root
sed -i "s/^PasswordAuthentication.*/PasswordAuthentication no/" /etc/ssh/sshd_config
systemctl restart ssh' \
    --wait \
    --format "ID,Name,PublicIPv4"

  local ip
  ip=$(get_ip)
  echo ""
  echo "=== Waiting for SSH ==="
  for i in $(seq 1 30); do
    if ssh -o StrictHostKeyChecking=no -o ConnectTimeout=3 "root@${ip}" "echo ok" >/dev/null 2>&1; then
      echo "  SSH ready"
      break
    fi
    sleep 2
  done

  echo ""
  echo "=== Installing deps ==="
  ssh "root@${ip}" bash -s <<'SETUP'
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq docker.io python3-pip python3-venv zstd curl >/dev/null 2>&1
systemctl enable --now docker

# Install arena CLI
curl -fsSL --retry 3 --http1.1 https://get.arena.build -o /tmp/install_arena.sh 2>/dev/null \
  || wget -q https://get.arena.build -O /tmp/install_arena.sh 2>/dev/null \
  || true
if [ -f /tmp/install_arena.sh ]; then
  bash /tmp/install_arena.sh || echo "WARN: arena CLI install failed, will use manual test"
fi

echo "Deps installed"
SETUP

  echo ""
  echo "=== Syncing code ==="
  DROPLET_IP="$ip" "$SCRIPT_DIR/arena_droplet.sh" --sync-only

  echo ""
  echo "=== Runner ready at ${ip} ==="
  echo "  Run tests:  DROPLET_IP=${ip} ./scripts/arena_droplet.sh"
  echo "  Destroy:    ./scripts/do_runner.sh down"
}

cmd_down() {
  echo "=== Destroying runner ==="
  doctl compute droplet delete "$RUNNER_NAME" --force 2>/dev/null && echo "Runner destroyed" || echo "No runner found"
}

cmd_ip() {
  local ip
  ip=$(get_ip)
  if [ -n "$ip" ]; then
    echo "$ip"
  else
    echo "No runner found" >&2
    exit 1
  fi
}

cmd_test() {
  local ip
  ip=$(get_ip)
  if [ -z "$ip" ]; then
    echo "No runner found. Run: ./scripts/do_runner.sh up"
    exit 1
  fi
  DROPLET_IP="$ip" "$SCRIPT_DIR/arena_droplet.sh" "$@"
  # arena_droplet.sh already pulls runs; nothing extra needed here
}

case "${1:-help}" in
  up)    cmd_up ;;
  down)  cmd_down ;;
  ip)    cmd_ip ;;
  test)  shift; cmd_test "$@" ;;
  smoke) cmd_test ;;
  help|*)
    echo "Usage: $0 {up|down|ip|test|smoke}"
    echo "  up    — create runner, install deps, sync code"
    echo "  down  — destroy runner"
    echo "  ip    — print runner IP"
    echo "  test  — sync + arena test (extra args passed through)"
    echo "  smoke — sync + arena test (default 5 tasks)"
    ;;
esac
