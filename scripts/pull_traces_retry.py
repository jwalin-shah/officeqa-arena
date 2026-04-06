#!/usr/bin/env python3
"""Pull traces in batches of 100 with retries."""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "nomcp" / "results" / "traces" / "v10.0.0_180"

SUBMISSION_ID = "02dd8236-6e32-49fd-932c-639cf028e608"


async def main():
    from arena_cli.client.base import ArenaClient
    from arena_cli.client.trajectories import get_trajectory, list_trajectories

    slug = "grounded-reasoning"

    async with ArenaClient() as client:
        # Get all trajectory items
        all_items = []
        offset = 0
        while True:
            resp = await list_trajectories(
                client, submission_id=SUBMISSION_ID,
                slug=slug, limit=100, offset=offset
            )
            all_items.extend(resp.items)
            print(f"Listed {len(all_items)}/{resp.total}")
            if len(all_items) >= resp.total or len(resp.items) == 0:
                break
            offset += 100

        passed = sum(1 for i in all_items if i.reward > 0)
        print(f"Total: {len(all_items)}, Passed: {passed}, Failed: {len(all_items)-passed}")

        OUT_DIR.mkdir(parents=True, exist_ok=True)

        # Filter to ones we haven't downloaded yet
        remaining = [
            item for item in all_items
            if not (OUT_DIR / f"{item.task_id}.json").exists()
        ]
        print(f"Need to download: {len(remaining)} (skipping {len(all_items)-len(remaining)} existing)")

        # Process in batches of 100
        batch_size = 100
        for batch_start in range(0, len(remaining), batch_size):
            batch = remaining[batch_start:batch_start + batch_size]
            print(f"\n--- Batch {batch_start//batch_size + 1} ({len(batch)} items) ---")

            for idx, item in enumerate(batch):
                task_id = item.task_id
                out_path = OUT_DIR / f"{task_id}.json"
                for attempt in range(3):
                    try:
                        detail = await get_trajectory(client, item.trajectory_id, slug=slug)
                        traj_dict = detail.model_dump(mode="json")
                        with open(out_path, "w") as f:
                            json.dump(traj_dict, f)
                        status = "PASS" if item.reward > 0 else "FAIL"
                        print(f"  [{batch_start+idx+1}/{len(remaining)}] {task_id}: {status}")
                        break
                    except Exception as e:
                        if attempt < 2:
                            await asyncio.sleep(1)
                        else:
                            print(f"  [{batch_start+idx+1}/{len(remaining)}] {task_id}: ERROR - {e}")

        total_downloaded = len(list(OUT_DIR.glob("*.json")))
        print(f"\nDone. {total_downloaded} traces in {OUT_DIR}/")


if __name__ == "__main__":
    asyncio.run(main())
