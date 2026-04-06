#!/usr/bin/env python3
"""
Poll Sentient Arena submission status via tRPC API.

Uses saved browser cookies to hit the submissions endpoint directly.
No browser needed — pure HTTP polling.

Usage:
    python3 scripts/poll_submission.py                  # poll every 30s
    python3 scripts/poll_submission.py --interval 10    # poll every 10s
    python3 scripts/poll_submission.py --once            # single check
    python3 scripts/poll_submission.py --output log.jsonl # also save to file
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

STATE_FILE = Path(__file__).resolve().parent / "sentient_storage_state.json"
CHALLENGE_ID = "a9460337-6f91-4837-897a-2754c2fc7ed1"
SUBMISSIONS_URL = (
    "https://arena.sentient.xyz/api/trpc/submissions.getByTeam"
    "?batch=1"
    f"&input=%7B%220%22%3A%7B%22json%22%3A%7B%22challengeId%22%3A%22{CHALLENGE_ID}%22%7D%7D%7D"
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://arena.sentient.xyz/challenges/grounded-reasoning",
}


def load_session() -> requests.Session:
    if not STATE_FILE.exists():
        print(f"ERROR: {STATE_FILE} not found. Run login_and_save_state.py first.", file=sys.stderr)
        sys.exit(1)

    with open(STATE_FILE) as f:
        state = json.load(f)

    session = requests.Session()
    for cookie in state.get("cookies", []):
        session.cookies.set(
            cookie["name"], cookie["value"],
            domain=cookie.get("domain", ""),
            path=cookie.get("path", "/"),
        )
    return session


def fetch_submissions(session: requests.Session) -> list[dict]:
    r = session.get(SUBMISSIONS_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data[0]["result"]["data"]["json"]


def format_submission(s: dict) -> str:
    status = s["status"]
    score = s.get("score") or 0
    total = s.get("totalTasks") or 0
    success = s.get("successful") or 0
    failed = s.get("failed") or 0
    done = success + failed
    pct = s.get("successPercent") or 0
    cost = s.get("avgCostPerTask") or 0
    runtime = s.get("avgRuntimePerTask") or 0
    version = s.get("version", "?")
    harness = s.get("harnessName", "?")

    # Status indicator
    if status == "in_progress":
        indicator = "\033[33m● IN PROGRESS\033[0m"
    elif status == "completed":
        indicator = "\033[32m✓ COMPLETED\033[0m"
    elif status == "failed":
        indicator = "\033[31m✗ FAILED\033[0m"
    else:
        indicator = status

    lines = [
        f"  {indicator}  [{harness} v{version}]",
        f"  Score: {score:.1f}   Success: {pct:.1f}%  ({success}/{total} done, {failed} failed)",
        f"  Avg cost: ${cost:.4f}/task   Avg time: {runtime:.1f}s/task",
    ]

    if status == "in_progress" and total > 0 and done > 0:
        remaining = total - done
        est_minutes = (remaining * runtime) / 60
        lines.append(f"  Progress: {done}/{total} ({done*100//total}%)   ETA: ~{est_minutes:.0f} min remaining")

    return "\n".join(lines)


def poll(session: requests.Session, interval: int, once: bool, output_path: str | None):
    out_f = open(output_path, "a") if output_path else None

    try:
        while True:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            try:
                submissions = fetch_submissions(session)

                in_progress = [s for s in submissions if s["status"] == "in_progress"]

                print(f"\n{'='*60}")
                print(f"  {ts}  ({len(in_progress)} in-progress)")
                print(f"{'='*60}")

                for i, s in enumerate(in_progress):
                    print(format_submission(s))
                    if i < len(in_progress) - 1:
                        print(f"  {'─'*40}")

                # Log to file
                if out_f:
                    for s in submissions:
                        record = {
                            "ts": ts,
                            "id": s["id"],
                            "status": s["status"],
                            "score": s.get("score") or 0,
                            "successPercent": s.get("successPercent") or 0,
                            "successful": s.get("successful") or 0,
                            "failed": s.get("failed") or 0,
                            "totalTasks": s.get("totalTasks") or 0,
                            "avgCostPerTask": s.get("avgCostPerTask") or 0,
                            "avgRuntimePerTask": s.get("avgRuntimePerTask") or 0,
                        }
                        out_f.write(json.dumps(record) + "\n")
                    out_f.flush()

                # Check if any are still in progress
                if not in_progress and not once:
                    print(f"\n  No submissions in progress. Stopping.")
                    break

            except Exception as e:
                print(f"\n  ERROR: {e}", file=sys.stderr)

            if once:
                break

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n\nStopped.")
    finally:
        if out_f:
            out_f.close()


def main():
    parser = argparse.ArgumentParser(description="Poll Sentient Arena submission status")
    parser.add_argument("--interval", type=int, default=30, help="Poll interval in seconds (default: 30)")
    parser.add_argument("--once", action="store_true", help="Single check, then exit")
    parser.add_argument("--output", help="Path to append JSONL log")
    parser.add_argument("--wait-for-new", action="store_true",
                        help="Wait up to 5 min for a new in_progress submission before polling")
    args = parser.parse_args()

    session = load_session()

    if args.wait_for_new and not args.once:
        # Remember the current submission IDs so we can detect a new one
        # or wait for an existing one to flip to in_progress
        print("  Waiting for an in_progress submission (up to 5 min)...")
        sys.stdout.flush()
        deadline = time.time() + 300
        found = False
        while time.time() < deadline:
            try:
                subs = fetch_submissions(session)
                if any(s["status"] == "in_progress" for s in subs):
                    print("  Found in_progress submission. Starting live polling.\n")
                    sys.stdout.flush()
                    found = True
                    break
            except Exception:
                pass
            time.sleep(5)
        if not found:
            print("  No in_progress submission appeared after 5 min. Polling once and exiting.")
            sys.stdout.flush()

    poll(session, args.interval, args.once, args.output)


if __name__ == "__main__":
    main()
