#!/usr/bin/env python3
"""Pull telemetry from webhook.site and display it.

Usage:
    python3 scripts/pull_telemetry.py                  # last 50 events
    python3 scripts/pull_telemetry.py --live            # poll every 5s
    python3 scripts/pull_telemetry.py --task-id X       # filter by task
    python3 scripts/pull_telemetry.py --dump out.jsonl  # save to file
"""
import argparse
import json
import time
import urllib.request

TOKEN = "0518b046-560c-46a2-ac27-f2b4698ed4ea"
API = f"https://webhook.site/token/{TOKEN}/requests"


def fetch(per_page=50, page=1):
    url = f"{API}?sorting=newest&per_page={per_page}&page={page}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def parse_entry(raw):
    try:
        return json.loads(raw.get("content", "{}"))
    except json.JSONDecodeError:
        return {}


def fmt(entry, ts):
    event = entry.get("event", "?")
    tool = entry.get("tool", "")
    task = entry.get("task_id", "")
    latency = entry.get("latency_s", "")
    is_err = entry.get("is_error", False)
    args_str = json.dumps(entry.get("args", {}))
    if len(args_str) > 80:
        args_str = args_str[:77] + "..."

    err_flag = " ERR" if is_err else ""
    lat_str = f" {latency}s" if latency else ""
    task_str = f" [{task}]" if task else ""
    return f"{ts}{task_str} {event}: {tool}{lat_str}{err_flag} {args_str}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Poll every 5s")
    parser.add_argument("--task-id", help="Filter by task ID")
    parser.add_argument("--dump", help="Save raw JSONL to file")
    parser.add_argument("-n", type=int, default=50, help="Number of entries")
    args = parser.parse_args()

    seen = set()
    dump_f = open(args.dump, "a") if args.dump else None

    try:
        while True:
            data = fetch(per_page=args.n)
            entries = data.get("data", [])
            new_entries = []
            for raw in reversed(entries):
                rid = raw["uuid"]
                if rid in seen:
                    continue
                seen.add(rid)
                entry = parse_entry(raw)
                if args.task_id and entry.get("task_id") != args.task_id:
                    continue
                new_entries.append((entry, raw.get("created_at", "")))
                if dump_f:
                    dump_f.write(json.dumps(entry) + "\n")
                    dump_f.flush()

            for entry, ts in new_entries:
                print(fmt(entry, ts))

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
