#!/usr/bin/env python3
"""Pull telemetry from the droplet telemetry server.

Usage:
    python3 scripts/pull_telemetry.py                      # last 50 tool events
    python3 scripts/pull_telemetry.py --trajectories       # trajectory summaries
    python3 scripts/pull_telemetry.py --live                # poll every 5s
    python3 scripts/pull_telemetry.py --task-id UID0030    # filter by task
    python3 scripts/pull_telemetry.py --dump out.jsonl     # save to file

Env vars:
    TELEMETRY_HOST — override default (default: 64.23.196.53:8080)
"""
import argparse
import json
import time
import urllib.request

DEFAULT_HOST = "147.182.206.223:8080"


def fetch(host: str, endpoint: str = "/", n: int = 50) -> list[dict]:
    url = f"http://{host}{endpoint}?n={n}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        entries = data.get("entries", [])
        parsed = []
        for e in entries:
            if isinstance(e, str):
                try:
                    parsed.append(json.loads(e))
                except json.JSONDecodeError:
                    continue
            else:
                parsed.append(e)
        return parsed
    except Exception as ex:
        print(f"Error fetching from {url}: {ex}")
        return []


def fmt_tool_event(entry: dict) -> str:
    event = entry.get("event", "?")
    tool = entry.get("tool", "")
    task = entry.get("task_id", "")
    latency = entry.get("latency_s", "")
    is_err = entry.get("is_error", False)

    err_flag = " ERR" if is_err else ""
    lat_str = f" {latency:.2f}s" if isinstance(latency, (int, float)) else ""
    task_str = f"[{task}] " if task else ""

    if event == "tool_call":
        args = entry.get("args", {})
        args_str = ", ".join(f"{k}={str(v)[:30]}" for k, v in list(args.items())[:3])
        return f"{task_str}{tool:25s}{lat_str}{err_flag}  {args_str}"
    elif event in ("auto_submit", "fallback_answer_write"):
        ans = entry.get("answer", "?")[:60]
        return f"{task_str}{event.upper()}: {ans}"
    elif event == "mcp_started":
        return f"{task_str}MCP STARTED db={entry.get('db_path', '?')}"
    else:
        return f"{task_str}{event}"


def fmt_trajectory(entry: dict) -> str:
    task = entry.get("task_id", "?")
    iters = entry.get("iterations", "?")
    cost = entry.get("cost_usd", 0)
    tools = entry.get("tool_counts", {})
    answer = entry.get("answer_preview", "")[:60]
    src = entry.get("answer_source", "?")
    delegate = " [DELEGATED]" if entry.get("used_delegate") else ""

    tools_str = " ".join(f"{k}={v}" for k, v in sorted(tools.items()))
    lines = [
        f"{'='*60}",
        f"[{task}] iters={iters} cost=${cost:.4f} src={src}{delegate}",
        f"  tools: {tools_str}",
        f"  answer: {answer}",
        f"{'='*60}",
    ]
    return "\n".join(lines)


def main():
    import os
    parser = argparse.ArgumentParser(description="Pull telemetry from droplet")
    parser.add_argument("--trajectories", action="store_true", help="Show trajectory summaries")
    parser.add_argument("--live", action="store_true", help="Poll every 5s")
    parser.add_argument("--task-id", help="Filter by task ID")
    parser.add_argument("--dump", help="Save raw JSONL to file")
    parser.add_argument("-n", type=int, default=50, help="Number of entries")
    parser.add_argument("--host", default=os.environ.get("TELEMETRY_HOST", DEFAULT_HOST))
    args = parser.parse_args()

    endpoint = "/trajectory" if args.trajectories else "/"
    fmt_fn = fmt_trajectory if args.trajectories else fmt_tool_event
    dump_f = open(args.dump, "a") if args.dump else None
    seen_count = 0

    try:
        while True:
            entries = fetch(args.host, endpoint, args.n)

            # Skip already-seen entries on subsequent polls
            new_entries = entries[seen_count:] if seen_count < len(entries) else []
            if not new_entries and not args.live:
                # First fetch — show all
                new_entries = entries

            for entry in new_entries:
                if args.task_id and entry.get("task_id", "") != args.task_id:
                    continue
                print(fmt_fn(entry))
                if dump_f:
                    dump_f.write(json.dumps(entry) + "\n")
                    dump_f.flush()

            seen_count = len(entries)

            if not args.live:
                break
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        if dump_f:
            dump_f.close()


if __name__ == "__main__":
    main()
