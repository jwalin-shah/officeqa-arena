#!/usr/bin/env python3
"""Pull traces with aggressive retries — both API and CLI approaches."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "results" / "traces" / "b7184ee2"
SUBMISSION_ID = "b7184ee2-2b19-4953-9300-169bf0fa80f1"
SLUG = "grounded-reasoning"
MAX_ROUNDS = 20
DELAY_BETWEEN_ROUNDS = 5
ARENA_BIN = str(Path.home() / ".arena" / "venv" / "bin" / "arena")


async def main():
    from arena_cli.client.base import ArenaClient
    from arena_cli.client.trajectories import get_trajectory, list_trajectories

    async with ArenaClient() as client:
        # Get all trajectory items
        all_items = []
        offset = 0
        while True:
            resp = await list_trajectories(
                client, submission_id=SUBMISSION_ID,
                slug=SLUG, limit=100, offset=offset
            )
            all_items.extend(resp.items)
            print(f"Listed {len(all_items)}/{resp.total}")
            if len(all_items) >= resp.total or len(resp.items) == 0:
                break
            offset += 100

        passed = sum(1 for i in all_items if i.reward > 0)
        print(f"Total: {len(all_items)}, Passed: {passed}, Failed: {len(all_items)-passed}")
        OUT_DIR.mkdir(parents=True, exist_ok=True)

        for round_num in range(1, MAX_ROUNDS + 1):
            # Check what we still need (json format = API pull)
            still_missing = [
                item for item in all_items
                if not (OUT_DIR / f"{item.task_id}.json").exists()
            ]
            if not still_missing:
                print(f"\nAll {len(all_items)} traces downloaded!")
                break

            print(f"\n=== Round {round_num}/{MAX_ROUNDS} — {len(still_missing)} missing ===")

            got = 0
            errors = 0
            for idx, item in enumerate(still_missing):
                task_id = item.task_id
                out_path = OUT_DIR / f"{task_id}.json"
                try:
                    detail = await get_trajectory(client, item.trajectory_id, slug=SLUG)
                    traj_dict = detail.model_dump(mode="json")
                    with open(out_path, "w") as f:
                        json.dump(traj_dict, f)
                    status = "PASS" if item.reward > 0 else "FAIL"
                    got += 1
                    print(f"  [{idx+1}/{len(still_missing)}] {task_id}: {status} (NEW)")
                except Exception as e:
                    errors += 1
                    if idx < 5 or idx % 25 == 0:
                        print(f"  [{idx+1}/{len(still_missing)}] {task_id}: {e}")

            downloaded = len(list(OUT_DIR.glob("*.json")))
            print(f"  Round {round_num}: got {got} new, {errors} errors, {downloaded}/{len(all_items)} total")

            if got == 0 and round_num >= 3:
                # Also try CLI --task for the stubborn ones
                print(f"  Trying CLI fallback for {min(10, len(still_missing))} traces...")
                still_missing2 = [
                    item for item in all_items
                    if not (OUT_DIR / f"{item.task_id}.json").exists()
                ]
                for item in still_missing2[:10]:
                    task_id = item.task_id
                    try:
                        result = subprocess.run(
                            [ARENA_BIN, "traces", SUBMISSION_ID, "--task", task_id],
                            capture_output=True, text=True, timeout=60
                        )
                        output = result.stdout
                        if len(output.splitlines()) > 5:
                            # Save as txt since it's CLI format
                            txt_path = OUT_DIR / f"{task_id}.txt"
                            with open(txt_path, "w") as f:
                                f.write(output)
                            print(f"    CLI got {task_id}")
                    except Exception as e:
                        pass

            if errors > 0 and round_num < MAX_ROUNDS:
                print(f"  Waiting {DELAY_BETWEEN_ROUNDS}s...")
                await asyncio.sleep(DELAY_BETWEEN_ROUNDS)

        total_json = len(list(OUT_DIR.glob("*.json")))
        total_txt_only = len([
            f for f in OUT_DIR.glob("*.txt")
            if not (OUT_DIR / f"{f.stem}.json").exists() and sum(1 for _ in open(f)) > 2
        ])
        print(f"\nDone. {total_json} JSON + {total_txt_only} TXT-only = {total_json + total_txt_only} unique traces")


if __name__ == "__main__":
    asyncio.run(main())
