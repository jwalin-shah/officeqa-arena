#!/usr/bin/env python3
"""Telemetry receiver for OfficeQA Arena runs.

Receives two kinds of data:
  1. MCP tool-call events (POST /) — from server/mcp_stdio.py in the container
  2. Trajectory summaries (POST /trajectory) — from arena_harness.py post-run

Run on the droplet:
    nohup python3 scripts/telemetry_server.py --port 8080 \
        --log /root/telemetry_live.jsonl > /root/telemetry.log 2>&1 &

Then set in arena.yaml:
    TELEMETRY_URL: "http://64.23.196.53:8080"

Monitor live:
    ssh root@64.23.196.53 "tail -f /root/telemetry_live.jsonl"
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path


LOG_FILE = Path("telemetry_live.jsonl")
TRAJECTORY_FILE = Path("telemetry_trajectories.jsonl")


class TelemetryHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return

        payload["_received"] = datetime.now(timezone.utc).isoformat()

        if self.path == "/trajectory":
            self._handle_trajectory(payload)
        else:
            self._handle_tool_event(payload)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def _handle_tool_event(self, payload):
        """MCP tool-call event from the container."""
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(payload) + "\n")

        event = payload.get("event", "?")
        task_id = payload.get("task_id", "?")

        if event == "tool_call":
            tool = payload.get("tool", "?")
            latency = payload.get("latency_s", 0)
            is_error = payload.get("is_error", False)
            result_len = payload.get("result_len", 0)
            status = "ERR" if is_error else "OK"
            args = payload.get("args", {})
            args_brief = ", ".join(f"{k}={str(v)[:30]}" for k, v in list(args.items())[:3])
            print(f"[{task_id}] {tool:25s} {status:3s} {latency:5.2f}s {result_len:>6d}B  {args_brief}")
        elif event == "auto_submit":
            ans = payload.get("answer", "?")[:60]
            print(f"[{task_id}] AUTO-SUBMIT: {ans}")
        elif event == "fallback_answer_write":
            ans = payload.get("answer", "?")[:60]
            print(f"[{task_id}] FALLBACK-WRITE: {ans}")
        elif event == "mcp_started":
            db = payload.get("db_path", "?")
            print(f"[{task_id}] MCP STARTED db={db}")
        else:
            print(f"[{task_id}] {event}")

        sys.stdout.flush()

    def _handle_trajectory(self, payload):
        """Trajectory summary from arena_harness.py post-run."""
        with open(TRAJECTORY_FILE, "a") as f:
            f.write(json.dumps(payload) + "\n")

        task = payload.get("task_id", "?")
        iters = payload.get("iterations", "?")
        cost = payload.get("cost_usd", 0)
        tools_used = payload.get("tool_counts", {})
        answer = payload.get("answer_preview", "")[:60]
        answer_src = payload.get("answer_source", "?")

        tools_str = " ".join(f"{k}={v}" for k, v in sorted(tools_used.items()))
        print(f"\n{'='*70}")
        print(f"TRAJECTORY [{task}] iters={iters} cost=${cost:.4f} src={answer_src}")
        print(f"  tools: {tools_str}")
        print(f"  answer: {answer}")
        print(f"{'='*70}\n")
        sys.stdout.flush()

    def do_GET(self):
        """Return recent entries for quick checks."""
        path_base = self.path.split("?")[0]
        if path_base == "/trajectory":
            target = TRAJECTORY_FILE
        else:
            target = LOG_FILE

        lines = []
        if target.exists():
            lines = target.read_text().strip().split("\n")

        # Parse query params for ?n=X
        n = 20
        if "?" in self.path:
            for param in self.path.split("?")[1].split("&"):
                if param.startswith("n="):
                    try:
                        n = int(param[2:])
                    except ValueError:
                        pass

        recent = lines[-n:]

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "total": len(lines),
            "showing": len(recent),
            "entries": recent,
        }).encode())

    def log_message(self, format, *args):
        pass  # suppress default HTTP logging


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--log", default="telemetry_live.jsonl")
    parser.add_argument("--trajectories", default="telemetry_trajectories.jsonl")
    args = parser.parse_args()

    global LOG_FILE, TRAJECTORY_FILE
    LOG_FILE = Path(args.log)
    TRAJECTORY_FILE = Path(args.trajectories)

    server = HTTPServer(("0.0.0.0", args.port), TelemetryHandler)
    print(f"Telemetry server listening on port {args.port}")
    print(f"  Tool events:  {LOG_FILE}")
    print(f"  Trajectories: {TRAJECTORY_FILE}")
    print(f"  Set TELEMETRY_URL=http://<your-ip>:{args.port} in arena.yaml")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
