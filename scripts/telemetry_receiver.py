#!/usr/bin/env python3
"""Tiny telemetry receiver — stdlib only, no deps.

Listens on 0.0.0.0:8080, appends JSON payloads to telemetry.jsonl.
Run: python3 telemetry_receiver.py
"""
import json
import sys
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

LOG_FILE = Path(__file__).parent / "telemetry.jsonl"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return

        payload["_received"] = datetime.now(timezone.utc).isoformat()
        line = json.dumps(payload, default=str)

        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")

        # Print to stdout for live tailing
        print(line, flush=True)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def do_GET(self):
        """Return last N entries for quick browser check."""
        lines = []
        if LOG_FILE.exists():
            lines = LOG_FILE.read_text().strip().split("\n")[-50:]
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"entries": len(lines), "recent": lines[-10:]}).encode())

    def log_message(self, format, *args):
        # Suppress default access logs
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"Telemetry receiver listening on :{port}, logging to {LOG_FILE}")
    server.serve_forever()
