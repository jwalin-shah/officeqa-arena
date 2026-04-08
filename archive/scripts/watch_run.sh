#!/usr/bin/env bash
# Watch a running arena test in real-time via telemetry.
#
# Usage:
#   ./scripts/watch_run.sh                  # poll every 10s
#   ./scripts/watch_run.sh --once           # single check
#   ./scripts/watch_run.sh --interval 5     # poll every 5s
#   ./scripts/watch_run.sh --droplet IP     # also try SSH status

set -euo pipefail

TELEMETRY_URL="${TELEMETRY_URL:-http://147.182.206.223:8080}"
INTERVAL=10
ONCE=false
DROPLET_IP=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --once) ONCE=true; shift ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    --droplet) DROPLET_IP="$2"; shift 2 ;;
    *) shift ;;
  esac
done

check_status() {
  local now=$(date '+%H:%M:%S')

  echo "═══════════════════════════════════════════════════"
  echo "  Run Monitor — $now"
  echo "═══════════════════════════════════════════════════"

  # Get recent telemetry events
  local response
  response=$(curl -s "${TELEMETRY_URL}/?n=50" 2>/dev/null) || { echo "  Telemetry server unreachable"; return; }

  python3 - "$response" <<'PY'
import sys, json, datetime

try:
    data = json.loads(sys.argv[1])
except:
    print("  Could not parse telemetry response")
    sys.exit(0)

entries = data.get("entries", [])
total = data.get("total", 0)

# Parse entries
events = []
for e in entries:
    try:
        ev = json.loads(e) if isinstance(e, str) else e
        events.append(ev)
    except:
        pass

if not events:
    print("  No events yet")
    sys.exit(0)

# Time range
timestamps = [e.get("ts", 0) for e in events if e.get("ts")]
if timestamps:
    first = datetime.datetime.fromtimestamp(min(timestamps))
    last = datetime.datetime.fromtimestamp(max(timestamps))
    age_s = (datetime.datetime.now() - last).total_seconds()
    print(f"  Total events: {total}")
    print(f"  Latest event: {last.strftime('%H:%M:%S')} ({int(age_s)}s ago)")
    if age_s > 300:
        print(f"  ⚠ No events in {int(age_s/60)} min — run may be idle or finished")
    print()

# Count by event type
tool_counts = {}
task_ids = set()
submits = 0
errors = 0
mcp_starts = 0

for ev in events:
    tool = ev.get("tool", ev.get("event", "?"))
    if tool in tool_counts:
        tool_counts[tool] += 1
    else:
        tool_counts[tool] = 1

    tid = ev.get("task_id", "")
    if tid:
        task_ids.add(tid)
    if tool == "submit_answer":
        submits += 1
    if ev.get("is_error"):
        errors += 1
    if ev.get("event") == "mcp_started":
        mcp_starts += 1

print(f"  Active tasks seen: {len(task_ids) if task_ids else 'unknown'}")
print(f"  MCP starts: {mcp_starts}")
print(f"  Submissions: {submits}")
print(f"  Errors: {errors}")
print()

# Recent tool calls (last 10)
recent = events[-10:]
print("  Recent activity:")
for ev in recent:
    ts = ev.get("ts", 0)
    t = datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S") if ts else "??:??:??"
    tool = ev.get("tool", ev.get("event", "?"))
    err = " ✗" if ev.get("is_error") else ""
    src = ev.get("source", "")
    tid = ev.get("task_id", "")[:12]
    lat = ev.get("latency_s", "")
    lat_str = f" ({lat:.1f}s)" if isinstance(lat, (int, float)) and lat > 0 else ""
    print(f"    {t} {tool}{lat_str}{err}  {tid}")
PY

  # Try SSH if droplet specified
  if [ -n "$DROPLET_IP" ]; then
    echo ""
    echo "  Droplet ($DROPLET_IP):"
    ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 "root@${DROPLET_IP}" \
      "docker ps --format '  {{.Names}}: {{.Status}}' 2>/dev/null | head -5; echo '  Arena processes:'; pgrep -c -f arena 2>/dev/null || echo '  0'" 2>/dev/null \
      || echo "    SSH unreachable (droplet under load)"
  fi

  echo ""
}

if [ "$ONCE" = true ]; then
  check_status
else
  echo "Watching run (Ctrl-C to stop, polling every ${INTERVAL}s)..."
  echo ""
  while true; do
    check_status
    sleep "$INTERVAL"
  done
fi
