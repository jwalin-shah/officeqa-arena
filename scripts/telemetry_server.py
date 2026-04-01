#!/usr/bin/env python3
"""Simple HTTP server to receive telemetry from arena MCP containers.

Run on your droplet:
    python3 scripts/telemetry_server.py --port 8080

Then set in arena.yaml:
    TELEMETRY_URL: "http://134.209.73.238:8080/telemetry"

Each tool call from the arena container will POST a JSON payload here.
Logs to telemetry_live.jsonl for real-time monitoring.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path


LOG_FILE = Path("telemetry_live.jsonl")


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

        # Add server-side timestamp
        payload["received_at"] = datetime.now(timezone.utc).isoformat()

        # Log to file
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(payload) + "\n")

        # Print summary to stdout for live monitoring
        event = payload.get("event", "?")
        task_id = payload.get("task_id", "?")
        if event == "tool_call":
            tool = payload.get("tool", "?")
            latency = payload.get("latency_s", 0)
            is_error = payload.get("is_error", False)
            result_len = payload.get("result_len", 0)
            status = "ERR" if is_error else "OK"
            print(f"[{task_id}] {tool:30s} {status} {latency:.2f}s {result_len}B")
        elif event == "mcp_started":
            db = payload.get("db_path", "?")
            print(f"[{task_id}] MCP STARTED db={db}")
        else:
            print(f"[{task_id}] {event}")

        sys.stdout.flush()

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, format, *args):
        pass  # suppress default HTTP logging


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--log", default="telemetry_live.jsonl")
    args = parser.parse_args()

    global LOG_FILE
    LOG_FILE = Path(args.log)

    server = HTTPServer(("0.0.0.0", args.port), TelemetryHandler)
    print(f"Telemetry server listening on port {args.port}")
    print(f"Logging to {LOG_FILE}")
    print(f"Set TELEMETRY_URL=http://<your-ip>:{args.port}/telemetry in arena.yaml")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
