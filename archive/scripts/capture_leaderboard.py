#!/usr/bin/env python3
"""
Capture the leaderboard tRPC endpoint by navigating to the Leaderboard tab
with Chrome DevTools Protocol (CDP).

Prerequisites:
  pip install websockets

  Launch Chrome with remote debugging:
  /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --remote-debugging-port=9222 \
    --user-data-dir=scripts/chrome_profile

Then navigate to https://arena.sentient.xyz/challenges/grounded-reasoning
and log in if needed.

Usage:
    python3 scripts/capture_leaderboard.py
"""

import asyncio
import json
import sys
import urllib.parse

import requests

# --- Approach 1: Pure requests brute-force with batched tRPC ---

STATE_FILE = "scripts/sentient_storage_state.json"
CHALLENGE_ID = "a9460337-6f91-4837-897a-2754c2fc7ed1"
BASE = "https://arena.sentient.xyz/api/trpc"


def load_session():
    state = json.load(open(STATE_FILE))
    s = requests.Session()
    for c in state.get("cookies", []):
        s.cookies.set(c["name"], c["value"], domain=c.get("domain", ""), path=c.get("path", "/"))
    return s


def try_batched_endpoints(session):
    """Try multi-procedure batched tRPC calls (how Next.js often batches them)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://arena.sentient.xyz/challenges/grounded-reasoning",
    }

    cid = CHALLENGE_ID

    # Exhaustive list of plausible tRPC procedure names
    procedures = [
        # Leaderboard-specific
        "leaderboard.getByChallengeId",
        "leaderboard.getAll",
        "leaderboard.list",
        "leaderboard.fetch",
        # Challenge sub-resources
        "challenges.leaderboard",
        "challenges.getLeaderboard",
        "challenges.rankings",
        "challenges.getParticipants",
        "challenges.getTeams",
        "challenges.getSubmissions",
        "challenges.getResults",
        "challenges.getScores",
        # Submissions variants
        "submissions.getAll",
        "submissions.getByChallengeId",
        "submissions.list",
        "submissions.rankings",
        "submissions.leaderboard",
        "submissions.getTopSubmissions",
        "submissions.getBestByTeam",
        # Teams variants
        "teams.getAll",
        "teams.list",
        "teams.getByChallengeId",
        "teams.leaderboard",
        "teams.rankings",
        "teams.getWithScores",
        # Results
        "results.getByChallenge",
        "results.leaderboard",
        "results.getAll",
        "results.rankings",
        # Rankings
        "rankings.get",
        "rankings.getByChallenge",
        "rankings.getByChallengeId",
        "rankings.list",
    ]

    # Build different input shapes
    input_shapes = [
        {"challengeId": cid},
        {"id": cid},
        {"slug": "grounded-reasoning"},
        {"challengeId": cid, "limit": 100},
        {},
    ]

    print(f"Testing {len(procedures)} procedures x {len(input_shapes)} input shapes...\n")

    hits = []
    for proc in procedures:
        for inp_data in input_shapes:
            inp = json.dumps({"0": {"json": inp_data}})
            url = f"{BASE}/{proc}?batch=1&input={urllib.parse.quote(inp)}"
            try:
                r = session.get(url, headers=headers, timeout=8)
                if r.status_code == 200:
                    body = r.json()
                    result = body[0].get("result", {}).get("data", {}).get("json") if isinstance(body, list) else None
                    if result:
                        print(f"  HIT  {proc} with {inp_data}")
                        print(f"       Type: {type(result).__name__}, ", end="")
                        if isinstance(result, list):
                            print(f"Length: {len(result)}")
                        elif isinstance(result, dict):
                            print(f"Keys: {list(result.keys())[:10]}")
                        else:
                            print(f"Value: {str(result)[:100]}")
                        hits.append((proc, inp_data, result))
                elif r.status_code != 404:
                    print(f"  {r.status_code}  {proc} with {inp_data}")
            except requests.Timeout:
                pass
            except Exception as e:
                pass

    return hits


def main():
    session = load_session()

    print("=" * 70)
    print("  Brute-forcing tRPC endpoints for leaderboard data")
    print("=" * 70)
    print()

    hits = try_batched_endpoints(session)

    if hits:
        print(f"\n{'='*70}")
        print(f"  Found {len(hits)} working endpoints!")
        print(f"{'='*70}\n")

        for proc, inp, data in hits:
            print(f"\n--- {proc} ---")
            print(json.dumps(data, indent=2, default=str)[:5000])

        # Save all hits
        with open("scripts/leaderboard_raw.json", "w") as f:
            json.dump([{"procedure": p, "input": i, "data": d} for p, i, d in hits], f, indent=2, default=str)
        print(f"\nSaved to scripts/leaderboard_raw.json")
    else:
        print("\nNo hits. The endpoint uses a name we haven't tried.")
        print("\nNext steps:")
        print("  1. Open Chrome DevTools Network tab")
        print("  2. Click the 'Leaderboard' tab on the challenge page")
        print("  3. Look for the tRPC request URL in the Network tab")
        print("  4. Share the URL here and I'll build the scraper")


if __name__ == "__main__":
    main()
