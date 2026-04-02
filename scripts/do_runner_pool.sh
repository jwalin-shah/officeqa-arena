#!/usr/bin/env bash
set -euo pipefail

# Create and use a pool of large DigitalOcean runners for Arena.
#
# Default topology:
#   2 droplets x 4 concurrent lanes each = 8 concurrent single-task runs
#
# Usage:
#   ./scripts/do_runner_pool.sh up
#   ./scripts/do_runner_pool.sh ips
#   ./scripts/do_runner_pool.sh sync
#   ./scripts/do_runner_pool.sh run --all
#   ./scripts/do_runner_pool.sh run --filter 'uid00*' -n 8
#   ./scripts/do_runner_pool.sh run --uids 'UID0001,UID0002,UID0201'
#   ./scripts/do_runner_pool.sh run --uids 'UID0001,UID0002' --cases data/officeqa_full.csv
#   ./scripts/do_runner_pool.sh status
#   ./scripts/do_runner_pool.sh down
#
# Default image is the DO runner snapshot:
#   223007008 = officeqa-runner-ready-2026-04-02

RUNNER_PREFIX="${RUNNER_PREFIX:-officeqa-big-runner}"
RUNNER_COUNT="${RUNNER_COUNT:-2}"
LANES_PER_RUNNER="${LANES_PER_RUNNER:-4}"
RUNNER_SIZE="${RUNNER_SIZE:-s-8vcpu-16gb}"
RUNNER_IMAGE="${RUNNER_IMAGE:-223007008}"
RUNNER_REGION="${RUNNER_REGION:-sfo3}"
DROPLET_USER="${DROPLET_USER:-root}"
DROPLET_DIR="${DROPLET_DIR:-/root/officeqa-serve}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOCAL_POOL_DIR="${PROJECT_DIR}/results/runner_pool"

runner_name() {
  local idx="$1"
  printf "%s-%02d" "$RUNNER_PREFIX" "$idx"
}

runner_ip() {
  local name="$1"
  doctl compute droplet list --format "Name,PublicIPv4" --no-header 2>/dev/null \
    | awk -v name="$name" '$1 == name { print $2; exit }'
}

wait_for_ssh() {
  local ip="$1"
  for _ in $(seq 1 45); do
    if ssh -o StrictHostKeyChecking=no -o ConnectTimeout=3 "${DROPLET_USER}@${ip}" "echo ok" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

install_remote_deps() {
  local ip="$1"
  ssh -o StrictHostKeyChecking=no "${DROPLET_USER}@${ip}" bash -s <<'SETUP'
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq docker.io python3-pip python3-venv zstd curl rsync >/dev/null 2>&1
systemctl enable --now docker

curl -fsSL --retry 3 --http1.1 https://get.arena.build -o /tmp/install_arena.sh 2>/dev/null \
  || wget -q https://get.arena.build -O /tmp/install_arena.sh 2>/dev/null \
  || true
if [ -f /tmp/install_arena.sh ]; then
  bash /tmp/install_arena.sh >/dev/null 2>&1 || echo "WARN: arena CLI install failed"
fi
SETUP
}

sync_runner() {
  local ip="$1"
  DROPLET_IP="$ip" "${SCRIPT_DIR}/arena_droplet.sh" --sync-only >/dev/null
}

extract_api_key() {
  python3 - <<'PY'
import yaml
with open("arena.yaml") as f:
    cfg = yaml.safe_load(f)
env = cfg.get("agent", {}).get("env", {})
print(env.get("LLM_API_KEY") or env.get("OPENROUTER_API_KEY") or "")
PY
}

select_tasks() {
  python3 - "$@" <<'PY'
import argparse
import csv
import fnmatch
from pathlib import Path

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--all", action="store_true")
parser.add_argument("--smoke", action="store_true")
parser.add_argument("--filter", default="*")
parser.add_argument("--n", "-n", type=int)
parser.add_argument("--uids", default="")
parser.add_argument("--cases", default="data/officeqa_full.csv")
args, _ = parser.parse_known_args()

tasks = []
if args.uids:
    csv_path = Path(args.cases)
    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = {row["uid"].strip().upper(): row for row in csv.DictReader(f)}
    for raw_uid in args.uids.split(","):
        uid = raw_uid.strip().upper()
        if not uid:
            continue
        if uid not in rows:
            raise SystemExit(f"UID not found in CSV: {uid}")
        tasks.append(uid.lower())
else:
    sample_root = Path(".arena/samples")
    for path in sorted(sample_root.glob("officeqa-*")):
        if not path.is_dir():
            continue
        uid = path.name.removeprefix("officeqa-")
        if fnmatch.fnmatch(uid, args.filter):
            tasks.append(uid)

if args.smoke:
    tasks = tasks[:1]
elif args.n:
    tasks = tasks[:args.n]

for task in tasks:
    print(task)
PY
}

ensure_generated_tasks() {
  local cases="$1"
  local uids="$2"
  [ -n "$uids" ] || return 0
  python3 "${SCRIPT_DIR}/generate_arena_samples.py" \
    --cases "$cases" \
    --uids "$uids" \
    --overwrite >/dev/null
}

cmd_up() {
  local ssh_key_id
  ssh_key_id="$(doctl compute ssh-key list --format ID --no-header | head -1)"
  if [ -z "$ssh_key_id" ]; then
    echo "No DigitalOcean SSH key found in doctl."
    exit 1
  fi

  for idx in $(seq 1 "$RUNNER_COUNT"); do
    local name ip
    name="$(runner_name "$idx")"
    ip="$(runner_ip "$name")"
    if [ -n "$ip" ]; then
      echo "${name} already exists at ${ip}"
      continue
    fi

    echo "=== Creating ${name} (${RUNNER_SIZE}) ==="
    doctl compute droplet create "$name" \
      --size "$RUNNER_SIZE" \
      --image "$RUNNER_IMAGE" \
      --region "$RUNNER_REGION" \
      --ssh-keys "$ssh_key_id" \
      --wait \
      --format "ID,Name,PublicIPv4"

    ip="$(runner_ip "$name")"
    echo "Waiting for SSH on ${name} (${ip})..."
    wait_for_ssh "$ip"
    install_remote_deps "$ip"
    sync_runner "$ip"
  done
}

cmd_ips() {
  for idx in $(seq 1 "$RUNNER_COUNT"); do
    local name ip
    name="$(runner_name "$idx")"
    ip="$(runner_ip "$name")"
    printf "%-24s %s\n" "$name" "${ip:-MISSING}"
  done
}

cmd_sync() {
  for idx in $(seq 1 "$RUNNER_COUNT"); do
    local name ip
    name="$(runner_name "$idx")"
    ip="$(runner_ip "$name")"
    if [ -z "$ip" ]; then
      echo "${name} is missing. Run '$0 up' first."
      exit 1
    fi
    echo "Syncing ${name} (${ip})..."
    sync_runner "$ip"
  done
}

cmd_status() {
  for idx in $(seq 1 "$RUNNER_COUNT"); do
    local name ip
    name="$(runner_name "$idx")"
    ip="$(runner_ip "$name")"
    if [ -z "$ip" ]; then
      echo "${name}: missing"
      continue
    fi
    echo "=== ${name} (${ip}) ==="
    ssh -o StrictHostKeyChecking=no "${DROPLET_USER}@${ip}" \
      "pgrep -af 'scripts/arena_test.sh|python -m arena_cli.main test|/opt/arena-venv/bin/arena test' || true"
  done
}

cmd_down() {
  for idx in $(seq 1 "$RUNNER_COUNT"); do
    local name
    name="$(runner_name "$idx")"
    echo "Destroying ${name}..."
    doctl compute droplet delete "$name" --force >/dev/null 2>&1 || true
  done
}

cmd_run() {
  local api_key run_label total_lanes cases_arg uids_arg
  api_key="${OPENROUTER_API_KEY:-${LLM_API_KEY:-$(extract_api_key)}}"
  if [ -z "$api_key" ]; then
    echo "No API key found in env or arena.yaml."
    exit 1
  fi

  cases_arg="data/officeqa_full.csv"
  uids_arg=""
  local prev=""
  for arg in "$@"; do
    if [ "$prev" = "--cases" ]; then
      cases_arg="$arg"
      prev=""
      continue
    fi
    if [ "$prev" = "--uids" ]; then
      uids_arg="$arg"
      prev=""
      continue
    fi
    case "$arg" in
      --cases|--uids)
        prev="$arg"
        ;;
      *)
        prev=""
        ;;
    esac
  done

  ensure_generated_tasks "$cases_arg" "$uids_arg"

  mapfile -t tasks < <(select_tasks "$@")
  if [ "${#tasks[@]}" -eq 0 ]; then
    echo "No tasks matched."
    exit 1
  fi

  run_label="${RUN_LABEL:-pool-$(date -u +%Y%m%dT%H%M%SZ)}"
  total_lanes=$((RUNNER_COUNT * LANES_PER_RUNNER))
  mkdir -p "${LOCAL_POOL_DIR}/${run_label}"

  declare -a shards
  for ((i=0; i<total_lanes; i++)); do
    shards[$i]=""
  done
  for idx in "${!tasks[@]}"; do
    local lane_idx=$((idx % total_lanes))
    shards[$lane_idx]+="${tasks[$idx]}"$'\n'
  done

  cmd_sync

  declare -a ssh_pids
  for runner_idx in $(seq 1 "$RUNNER_COUNT"); do
    local name ip runner_root
    name="$(runner_name "$runner_idx")"
    ip="$(runner_ip "$name")"
    if [ -z "$ip" ]; then
      echo "${name} is missing. Run '$0 up' first."
      exit 1
    fi

    runner_root="${DROPLET_DIR}/.runner_pool/${run_label}"
    ssh -o StrictHostKeyChecking=no "${DROPLET_USER}@${ip}" \
      "mkdir -p '${runner_root}/manifests' '${runner_root}/logs' '${runner_root}/results'"

    for lane in $(seq 1 "$LANES_PER_RUNNER"); do
      local global_idx=$(((runner_idx - 1) * LANES_PER_RUNNER + (lane - 1)))
      printf "%s" "${shards[$global_idx]}" | ssh -o StrictHostKeyChecking=no "${DROPLET_USER}@${ip}" \
        "cat > '${runner_root}/manifests/lane${lane}.txt'"
    done

    ssh -o StrictHostKeyChecking=no "${DROPLET_USER}@${ip}" "bash -s" <<EOF &
set -euo pipefail
cd "${DROPLET_DIR}"

runner_name="${name}"
runner_root="${runner_root}"
run_label="${run_label}"
api_key='${api_key}'

openrouter_usage() {
  curl -s -H "Authorization: Bearer \$api_key" "https://openrouter.ai/api/v1/auth/key" \
    | python3 -c "import sys, json; d=json.load(sys.stdin).get('data', {}); print(f\"{float(d.get('usage', 0)):.6f}\")" 2>/dev/null || echo "0"
}

write_result_row() {
  python3 - "\$@" <<'PY'
import json
import sys

uid, runner, lane, started_at, finished_at, before, after, exit_code, tag = sys.argv[1:]
before_f = float(before)
after_f = float(after)
row = {
    "task_id": uid,
    "runner": runner,
    "lane": int(lane),
    "started_at": started_at,
    "finished_at": finished_at,
    "elapsed_s": round(float(finished_at) - float(started_at), 2),
    "openrouter_usage_before": before_f,
    "openrouter_usage_after": after_f,
    "cost_usd": round(after_f - before_f, 6),
    "exit_code": int(exit_code),
    "tag": tag,
}
print(json.dumps(row))
PY
}

run_lane() {
  local lane="\$1"
  local manifest="\${runner_root}/manifests/lane\${lane}.txt"
  local lane_log="\${runner_root}/logs/lane\${lane}.log"
  local lane_results="\${runner_root}/results/lane\${lane}.jsonl"

  [ -s "\$manifest" ] || return 0

  (
    while IFS= read -r uid || [ -n "\$uid" ]; do
      [ -n "\$uid" ] || continue
      local started_at finished_at before after exit_code tag run_id source
      started_at="\$(python3 -c 'import time; print(time.time())')"
      before="\$(openrouter_usage)"
      tag="\${run_label}-\${runner_name}-lane\${lane}-\${uid}"
      run_id="\${run_label}:\${runner_name}:lane\${lane}:\${uid}"
      source="\${runner_name}:lane\${lane}"

      set +e
      TASK_ID="\$uid" \
      ARENA_TASK_ID="\$uid" \
      RUN_ID="\$run_id" \
      ARENA_RUN_ID="\$run_id" \
      TELEMETRY_SOURCE="\$source" \
      LLM_API_KEY="\$api_key" \
      OPENROUTER_API_KEY="\$api_key" \
      ./scripts/arena_test.sh --filter "\$uid" --tag "\$tag"
      exit_code=\$?
      set -e

      after="\$(openrouter_usage)"
      finished_at="\$(python3 -c 'import time; print(time.time())')"
      write_result_row "\$uid" "\$runner_name" "\$lane" "\$started_at" "\$finished_at" "\$before" "\$after" "\$exit_code" "\$tag" >> "\$lane_results"
    done < "\$manifest"
  ) > "\$lane_log" 2>&1 &

  echo \$!
}

declare -a pids=()
for lane in \$(seq 1 "${LANES_PER_RUNNER}"); do
  pid="\$(run_lane "\$lane" || true)"
  if [ -n "\$pid" ]; then
    pids+=("\$pid")
  fi
done

for pid in "\${pids[@]}"; do
  wait "\$pid"
done
EOF
    ssh_pids+=("$!")
  done

  for pid in "${ssh_pids[@]}"; do
    wait "$pid"
  done

  for runner_idx in $(seq 1 "$RUNNER_COUNT"); do
    local name ip local_root
    name="$(runner_name "$runner_idx")"
    ip="$(runner_ip "$name")"
    local_root="${LOCAL_POOL_DIR}/${run_label}/${name}"
    mkdir -p "$local_root"
    rsync -az -e "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10" \
      "${DROPLET_USER}@${ip}:${DROPLET_DIR}/.runner_pool/${run_label}/" \
      "${local_root}/"
    rsync -az -e "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10" \
      "${DROPLET_USER}@${ip}:${DROPLET_DIR}/.arena/runs/" \
      ".arena/runs/" >/dev/null 2>&1 || true
  done

  echo "Run complete. Results: ${LOCAL_POOL_DIR}/${run_label}"
}

case "${1:-help}" in
  up)
    cmd_up
    ;;
  ips)
    cmd_ips
    ;;
  sync)
    cmd_sync
    ;;
  run)
    shift
    cmd_run "$@"
    ;;
  status)
    cmd_status
    ;;
  down)
    cmd_down
    ;;
  help|*)
    echo "Usage: $0 {up|ips|sync|run|status|down}"
    echo "  up      Create ${RUNNER_COUNT} runners, install deps, sync code"
    echo "  ips     Show runner IPs"
    echo "  sync    Sync code to all runners"
    echo "  run     Fan tasks out across all lanes (pass arena test flags)"
    echo "          Extra selectors: --uids 'UID0001,UID0002' [--cases data/officeqa_full.csv]"
    echo "  status  Show active arena processes on each runner"
    echo "  down    Destroy all runners in the pool"
    ;;
esac
