#!/usr/bin/env bash
# Launch live monitors on the droplet after you've submitted.
#
# Usage:
#   arena submit                                    # submit first (as usual)
#   bash scripts/submit_and_monitor.sh              # start monitoring
#   bash scripts/submit_and_monitor.sh --stop       # kill running monitors
#   bash scripts/submit_and_monitor.sh --leaderboard # tail leaderboard instead
#
# Submission poller waits up to 5 min for a new in_progress submission,
# then polls every 2s. Auto-stops (and kills leaderboard poller) when done.
# Ctrl-C detaches the tail — monitors keep running on the droplet.
set -euo pipefail

DROPLET="root@147.182.206.223"
REMOTE_DIR="/root/monitors"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUB_LOG="/root/monitors/submission_live.jsonl"
LB_LOG="/root/monitors/leaderboard_live.jsonl"

stop_monitors() {
    echo "==> Stopping monitors on droplet..."
    ssh "$DROPLET" "pkill -f 'poll_submission.py' 2>/dev/null; pkill -f 'poll_leaderboard.py' 2>/dev/null; echo 'Stopped.'"
}

deploy_if_needed() {
    if ! ssh "$DROPLET" "test -f $REMOTE_DIR/poll_submission.py" 2>/dev/null; then
        echo "==> First run — deploying monitor scripts..."
        bash "$SCRIPT_DIR/deploy_monitors.sh"
    else
        # Re-sync scripts + cookies
        scp -q \
          "$SCRIPT_DIR/poll_submission.py" \
          "$SCRIPT_DIR/poll_leaderboard.py" \
          "$SCRIPT_DIR/sentient_storage_state.json" \
          "$DROPLET:$REMOTE_DIR/" 2>/dev/null || true
    fi
}

start_monitors() {
    echo "==> Starting monitors on droplet..."

    # Kill any existing monitors first
    ssh "$DROPLET" "pkill -f 'poll_submission.py' 2>/dev/null; pkill -f 'poll_leaderboard.py' 2>/dev/null; true"

    # Wrapper script on the droplet: runs submission poller, then kills leaderboard poller when done
    ssh "$DROPLET" "cat > $REMOTE_DIR/run_monitors.sh" <<'REMOTE_EOF'
#!/usr/bin/env bash
cd /root/monitors

# Start leaderboard poller in background
python3 poll_leaderboard.py --poll 600 --output /root/monitors/leaderboard_live.jsonl > /root/poll_leaderboard.log 2>&1 &
LB_PID=$!

# Run submission poller (blocks until no in_progress submissions)
python3 poll_submission.py --interval 2 --wait-for-new --output /root/monitors/submission_live.jsonl

echo ""
echo "==> Submission complete. Stopping leaderboard poller."

# Kill leaderboard poller
kill $LB_PID 2>/dev/null || true

# One final leaderboard fetch
echo ""
echo "==> Final leaderboard:"
python3 poll_leaderboard.py 2>&1 | head -40

echo ""
echo "==> All monitors stopped."
REMOTE_EOF

    ssh "$DROPLET" "chmod +x $REMOTE_DIR/run_monitors.sh"

    # Launch the combined monitor script via nohup
    ssh "$DROPLET" "nohup bash $REMOTE_DIR/run_monitors.sh > /root/poll_submission.log 2>&1 &"

    echo "==> Monitors running. Tailing live output (Ctrl-C to detach)..."
    echo ""
}

# --- Main ---

case "${1:-}" in
    --stop)
        stop_monitors
        exit 0
        ;;
    --leaderboard)
        deploy_if_needed
        ssh "$DROPLET" "tail -f /root/poll_leaderboard.log"
        exit 0
        ;;
esac

# Default: deploy + start monitors + tail
deploy_if_needed
start_monitors
ssh "$DROPLET" "tail -f /root/poll_submission.log"
