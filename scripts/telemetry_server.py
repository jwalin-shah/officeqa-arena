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
from collections import Counter
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse


LOG_FILE = Path("telemetry_live.jsonl")
TRAJECTORY_FILE = Path("telemetry_trajectories.jsonl")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []

    entries: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _first(values: dict[str, list[str]], key: str, default: str = "") -> str:
    return values.get(key, [default])[0]


def _matches_filters(entry: dict, params: dict[str, list[str]]) -> bool:
    task_id = _first(params, "task_id")
    run_id = _first(params, "run_id")
    source = _first(params, "source")
    event = _first(params, "event")

    if task_id and str(entry.get("task_id", "")) != task_id:
        return False
    if run_id and str(entry.get("run_id", "")) != run_id:
        return False
    if source and str(entry.get("source", "")) != source:
        return False
    if event and str(entry.get("event", "")) != event:
        return False
    return True


def _task_key(entry: dict) -> tuple[str, str, str]:
    return (
        str(entry.get("task_id", "")),
        str(entry.get("run_id", "")),
        str(entry.get("source", "")),
    )


def _aggregate_task_stats(tool_events: list[dict], trajectories: list[dict]) -> list[dict]:
    stats_by_key: dict[tuple[str, str, str], dict] = {}

    def get_or_create(entry: dict) -> dict:
        key = _task_key(entry)
        if key not in stats_by_key:
            task_id, run_id, source = key
            stats_by_key[key] = {
                "task_id": task_id,
                "run_id": run_id,
                "source": source,
                "event_count": 0,
                "tool_call_count": 0,
                "tool_counts": Counter(),
                "tool_error_count": 0,
                "tool_latency_sum_s": 0.0,
                "tool_latency_avg_s": 0.0,
                "tool_latency_max_s": 0.0,
                "started_ts": None,
                "ended_ts": None,
                "started_at": None,
                "ended_at": None,
                "wall_time_s": None,
                "cost_usd": None,
                "prompt_tokens": None,
                "completion_tokens": None,
                "cached_tokens": None,
                "iterations": None,
                "total_steps": None,
                "trajectory_total_tool_calls": None,
                "used_delegate": None,
                "answer_source": None,
                "answer_preview": None,
                "auto_submit_answer": None,
                "fallback_answer": None,
            }
        return stats_by_key[key]

    for event in tool_events:
        stats = get_or_create(event)
        stats["event_count"] += 1

        ts = event.get("ts")
        if isinstance(ts, (int, float)):
            stats["started_ts"] = ts if stats["started_ts"] is None else min(stats["started_ts"], ts)
            stats["ended_ts"] = ts if stats["ended_ts"] is None else max(stats["ended_ts"], ts)

        received = event.get("_received")
        if received:
            stats["started_at"] = stats["started_at"] or received
            stats["ended_at"] = received

        if event.get("event") == "tool_call":
            stats["tool_call_count"] += 1
            tool = str(event.get("tool", "unknown"))
            stats["tool_counts"][tool] += 1
            latency = event.get("latency_s")
            if isinstance(latency, (int, float)):
                stats["tool_latency_sum_s"] += float(latency)
                stats["tool_latency_max_s"] = max(stats["tool_latency_max_s"], float(latency))
            if event.get("is_error"):
                stats["tool_error_count"] += 1
        elif event.get("event") == "auto_submit":
            stats["auto_submit_answer"] = event.get("answer")
        elif event.get("event") == "fallback_answer_write":
            stats["fallback_answer"] = event.get("answer")

    for traj in trajectories:
        stats = get_or_create(traj)
        for key in (
            "cost_usd",
            "prompt_tokens",
            "completion_tokens",
            "cached_tokens",
            "iterations",
            "total_steps",
            "used_delegate",
            "answer_source",
            "answer_preview",
            "wall_time_s",
            "started_at",
            "ended_at",
        ):
            value = traj.get(key)
            if value is not None and value != "":
                stats[key] = value

        if traj.get("harness") and not stats.get("source"):
            stats["source"] = traj["harness"]
        if traj.get("total_tool_calls") is not None:
            stats["trajectory_total_tool_calls"] = traj.get("total_tool_calls")
        if traj.get("tool_counts") and stats["tool_call_count"] == 0:
            stats["tool_counts"].update(traj["tool_counts"])

    results = []
    for stats in stats_by_key.values():
        if stats["wall_time_s"] is None and stats["started_ts"] is not None and stats["ended_ts"] is not None:
            stats["wall_time_s"] = round(float(stats["ended_ts"]) - float(stats["started_ts"]), 3)
        if stats["tool_call_count"] > 0:
            stats["tool_latency_avg_s"] = round(stats["tool_latency_sum_s"] / stats["tool_call_count"], 3)
        stats["tool_latency_sum_s"] = round(stats["tool_latency_sum_s"], 3)
        stats["tool_counts"] = dict(sorted(stats["tool_counts"].items()))
        if stats["trajectory_total_tool_calls"] is None:
            stats["trajectory_total_tool_calls"] = stats["tool_call_count"]
        if stats["cost_usd"] is not None and stats["trajectory_total_tool_calls"]:
            stats["cost_per_tool_call_usd"] = round(
                float(stats["cost_usd"]) / max(int(stats["trajectory_total_tool_calls"]), 1),
                6,
            )
        else:
            stats["cost_per_tool_call_usd"] = None
        results.append(stats)

    results.sort(
        key=lambda item: (
            item["ended_ts"] if item["ended_ts"] is not None else float("-inf"),
            item["task_id"],
            item["run_id"],
        ),
        reverse=True,
    )
    return results


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
        source = payload.get("source", "?")
        tag = f"[{source}:{task_id}]" if task_id else f"[{source}]"

        if event == "tool_call":
            tool = payload.get("tool", "?")
            latency = payload.get("latency_s", 0)
            is_error = payload.get("is_error", False)
            result_len = payload.get("result_len", 0)
            status = "ERR" if is_error else "OK"
            args = payload.get("args", {})
            args_brief = ", ".join(f"{k}={str(v)[:30]}" for k, v in list(args.items())[:3])
            print(f"{tag} {tool:25s} {status:3s} {latency:5.2f}s {result_len:>6d}B  {args_brief}")
        elif event == "auto_submit":
            ans = payload.get("answer", "?")[:60]
            print(f"{tag} AUTO-SUBMIT: {ans}")
        elif event == "fallback_answer_write":
            ans = payload.get("answer", "?")[:60]
            print(f"{tag} FALLBACK-WRITE: {ans}")
        elif event == "mcp_started":
            db = payload.get("db_path", "?")
            print(f"{tag} MCP STARTED db={db}")
        else:
            print(f"{tag} {event}")

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
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        n = 20
        try:
            n = int(_first(params, "n", "20"))
        except ValueError:
            pass

        if parsed.path == "/summary":
            tool_events = [e for e in _read_jsonl(LOG_FILE) if _matches_filters(e, params)]
            trajectories = [e for e in _read_jsonl(TRAJECTORY_FILE) if _matches_filters(e, params)]
            summaries = _aggregate_task_stats(tool_events, trajectories)
            body = {
                "total": len(summaries),
                "showing": min(len(summaries), n),
                "entries": summaries[:n],
            }
        else:
            target = TRAJECTORY_FILE if parsed.path == "/trajectory" else LOG_FILE
            entries = [e for e in _read_jsonl(target) if _matches_filters(e, params)]
            recent = entries[-n:]
            body = {
                "total": len(entries),
                "showing": len(recent),
                "entries": recent,
            }

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

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
