#!/usr/bin/env python3
"""
Poll Sentient Arena leaderboard via tRPC API.

Usage:
    python3 scripts/poll_leaderboard.py                  # single fetch + analysis
    python3 scripts/poll_leaderboard.py --poll 60        # poll every 60s
    python3 scripts/poll_leaderboard.py --output lb.jsonl # append to log
    python3 scripts/poll_leaderboard.py --csv             # output as CSV
    python3 scripts/poll_leaderboard.py --json            # output raw JSON
"""

import argparse
import json
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests

STATE_FILE = Path(__file__).resolve().parent / "sentient_storage_state.json"
CHALLENGE_ID = "a9460337-6f91-4837-897a-2754c2fc7ed1"
LEADERBOARD_URL = (
    "https://arena.sentient.xyz/api/trpc/leaderboard.getByChallengeId"
    "?batch=1"
    "&input=" + urllib.parse.quote(
        json.dumps({"0": {"json": {"challengeId": CHALLENGE_ID}}})
    )
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://arena.sentient.xyz/challenges/grounded-reasoning",
}


def load_session() -> requests.Session:
    if not STATE_FILE.exists():
        print(f"ERROR: {STATE_FILE} not found.", file=sys.stderr)
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


def fetch_leaderboard(session: requests.Session) -> dict:
    r = session.get(LEADERBOARD_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data[0]["result"]["data"]["json"]


def print_table(data: dict):
    entries = data["entries"]
    updated = data.get("updatedAt", "?")

    print(f"\n{'='*130}")
    print(f"  LEADERBOARD  |  {len(entries)} teams  |  Updated: {updated}")
    print(f"{'='*130}")
    print(f"{'#':>3}  {'Team':25s}  {'Score':>7s}  {'Pass':>5s}  {'Fail':>5s}  {'Pct':>6s}  {'Harness':15s}  {'AvgTime':>8s}  {'AvgCost':>8s}  Members")
    print(f"{'-'*130}")

    for e in entries:
        members = ", ".join(m["name"] for m in e.get("members", []))
        total = e["totalTasks"]
        pct = e["successful"] / total * 100 if total > 0 else 0
        print(
            f"{e['rank']:>3}  {e['teamName']:25s}  {e['score']:>7.1f}  "
            f"{e['successful']:>5d}  {e['failed']:>5d}  {pct:>5.1f}%  "
            f"{e['harnessName']:15s}  {e['avgRuntime']:>8s}  {e['avgCost']:>8s}  "
            f"{members}"
        )

    # === Analysis ===
    print(f"\n{'='*130}")
    print("  ANALYSIS")
    print(f"{'='*130}")

    if not entries:
        return

    # Score distribution
    scores = [e["score"] for e in entries]
    top_score = max(scores)
    our_team = next((e for e in entries if "Zero Node" in e["teamName"] or "Jwalin" in ",".join(m["name"] for m in e.get("members", []))), None)

    print(f"\n  Score range: {min(scores):.1f} - {max(scores):.1f}")
    print(f"  Median score: {sorted(scores)[len(scores)//2]:.1f}")

    if our_team:
        gap = top_score - our_team["score"]
        our_pct = our_team["successful"] / our_team["totalTasks"] * 100
        print(f"\n  Our position: #{our_team['rank']} / {len(entries)}")
        print(f"  Our score: {our_team['score']:.1f}  ({our_pct:.1f}% pass rate)")
        print(f"  Gap to #1: {gap:.1f} points")

    # Compare harness types
    harness_groups: dict[str, list] = {}
    for e in entries:
        h = e["harnessName"]
        harness_groups.setdefault(h, []).append(e)

    print(f"\n  By harness:")
    for h, teams in sorted(harness_groups.items()):
        avg_score = sum(e["score"] for e in teams) / len(teams)
        best = max(e["score"] for e in teams)
        print(f"    {h:20s}  {len(teams)} teams  avg={avg_score:.1f}  best={best:.1f}")

    # Top team analysis
    leader = entries[0]
    print(f"\n  #1 ({leader['teamName']}) stats:")
    print(f"    {leader['successful']}/{leader['totalTasks']} passed ({leader['successful']/leader['totalTasks']*100:.1f}%)")
    print(f"    Avg runtime: {leader['avgRuntime']}")
    print(f"    Avg cost: {leader['avgCost']}")
    print(f"    Harness: {leader['harnessName']}")

    # Points per correct answer (score efficiency)
    print(f"\n  Points per correct answer:")
    for e in entries:
        if e["successful"] > 0:
            eff = e["score"] / e["successful"]
            print(f"    #{e['rank']:<3}  {e['teamName']:25s}  {eff:.3f} pts/correct")

    # Unsolved questions estimate
    print(f"\n  Questions answered (of 246):")
    for e in entries:
        attempted = e["successful"] + e["failed"]
        if attempted > 0:
            print(f"    #{e['rank']:<3}  {e['teamName']:25s}  {attempted}/246 attempted  ({e['successful']} correct)")


def print_csv(data: dict):
    entries = data["entries"]
    print("rank,team,score,successful,failed,total,success_pct,harness,avg_runtime,avg_cost,members")
    for e in entries:
        members = "|".join(m["name"] for m in e.get("members", []))
        pct = e["successful"] / e["totalTasks"] * 100 if e["totalTasks"] > 0 else 0
        print(
            f"{e['rank']},{e['teamName']},{e['score']:.2f},"
            f"{e['successful']},{e['failed']},{e['totalTasks']},{pct:.1f},"
            f"{e['harnessName']},{e['avgRuntime']},{e['avgCost']},\"{members}\""
        )


def main():
    parser = argparse.ArgumentParser(description="Fetch Sentient Arena leaderboard")
    parser.add_argument("--poll", type=int, help="Poll interval in seconds (continuous mode)")
    parser.add_argument("--output", help="Append JSONL log to file")
    parser.add_argument("--csv", action="store_true", help="Output as CSV")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    session = load_session()

    while True:
        try:
            data = fetch_leaderboard(session)

            if args.json:
                print(json.dumps(data, indent=2, default=str))
            elif args.csv:
                print_csv(data)
            else:
                print_table(data)

            if args.output:
                ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                with open(args.output, "a") as f:
                    f.write(json.dumps({"ts": ts, **data}, default=str) + "\n")

        except Exception as e:
            print(f"\n  ERROR: {e}", file=sys.stderr)

        if not args.poll:
            break

        time.sleep(args.poll)


if __name__ == "__main__":
    main()
