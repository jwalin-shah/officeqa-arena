#!/usr/bin/env python3
"""Pull traces using arena traces --task (which works even when direct API storage fails)."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "results" / "traces" / "b7184ee2"
SUBMISSION_ID = "b7184ee2-2b19-4953-9300-169bf0fa80f1"
SLUG = "grounded-reasoning"
ARENA_BIN = Path.home() / ".arena" / "venv" / "bin" / "arena"


async def get_all_task_ids():
    from arena_cli.client.base import ArenaClient
    from arena_cli.client.trajectories import list_trajectories

    async with ArenaClient() as client:
        all_items = []
        offset = 0
        while True:
            resp = await list_trajectories(client, submission_id=SUBMISSION_ID, slug=SLUG, limit=100, offset=offset)
            all_items.extend(resp.items)
            if len(all_items) >= resp.total or len(resp.items) == 0:
                break
            offset += 100
        return [(item.task_id, item.reward) for item in all_items]


def pull_single_trace(task_id: str) -> str:
    """Pull a single trace using arena CLI and return the raw output."""
    result = subprocess.run(
        [str(ARENA_BIN), "traces", SUBMISSION_ID, "--task", task_id],
        capture_output=True, text=True, timeout=60
    )
    return result.stdout + result.stderr


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Get all task IDs
    print("Listing all tasks...")
    tasks = asyncio.run(get_all_task_ids())
    print(f"Total: {len(tasks)}")

    # Filter already downloaded
    remaining = [(tid, reward) for tid, reward in tasks if not (OUT_DIR / f"{tid}.txt").exists()]
    print(f"Need to download: {len(remaining)} (skipping {len(tasks) - len(remaining)} existing)")

    for idx, (task_id, reward) in enumerate(remaining):
        try:
            output = pull_single_trace(task_id)
            out_path = OUT_DIR / f"{task_id}.txt"
            with open(out_path, "w") as f:
                f.write(output)
            status = "PASS" if reward > 0 else "FAIL"
            lines = len(output.splitlines())
            print(f"  [{idx+1}/{len(remaining)}] {task_id}: {status} ({lines} lines)")
        except Exception as e:
            print(f"  [{idx+1}/{len(remaining)}] {task_id}: ERROR - {e}")

    total = len(list(OUT_DIR.glob("*.txt")))
    print(f"\nDone. {total}/{len(tasks)} traces in {OUT_DIR}/")


if __name__ == "__main__":
    main()
