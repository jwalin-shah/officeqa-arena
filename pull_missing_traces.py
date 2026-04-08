#!/usr/bin/env python3
import asyncio
import json
import os
from pathlib import Path
from arena_cli.client.trajectories import ArenaClient, list_trajectories, get_trajectory

# All recent submission IDs from the submissions table
# These are the ones that don't appear to have local traces yet
recent_submissions = {
    "b65d00b6-d09e-4fff-9c8d-ad9cece44746": "v21-submission-2h",
    "731c7235-9a64-4a87-ab41-d6b997e4fe5b": "v21-6h-181.4",
    "ea95740d-32ba-4aa1-84f4-21fddcdb9e08": "v21-9h-181.3",
    "fae92d59-8c20-453e-8d5f-dc9c060d9e69": "v21-10h-135.8",
    "ae8c4dc7-1c4d-4cba-a69e-48845839ab74": "v21-13h-178.8",
    "5d6a2212-62d0-4cea-bfea-0a0dc4486157": "r7-15h",
    "5dacbc37-fe87-4615-ba61-08ef3d56013c": "r1-17h",
    "de5e143a-ea2b-444b-b770-699807fc1d25": "v24-18h",
    "a9dd924b-5e28-4b22-8c3e-5542c6bc5cdd": "v15-oh-21h",
    "b7184ee2-2b19-4953-9300-169bf0fa80f1": "v15-23h",
    "13b58ad6-1767-46e6-be25-e3f1108023a0": "v20-1d-183.8",
    "17e74918-a2e7-4249-a3b0-d8ad02e01754": "my-agent-1d",
    "73e94001-b769-4759-9e25-a4df586ba442": "my-agent-1d-2",
    "c83efa9f-f64f-4be8-90b9-d31821026a36": "page-first-2d",
    "2f22e48f-115e-49bb-a9ed-ec38397e331d": "mcp-v5-2d",
}

async def pull_traces(submission_id, label):
    print(f"\n{'='*60}")
    print(f"Pulling traces for {label} ({submission_id})")
    print('='*60)

    try:
        async with ArenaClient() as client:
            slug = 'grounded-reasoning'

            # List trajectories
            all_items = []
            offset = 0
            while True:
                resp = await list_trajectories(
                    client,
                    submission_id=submission_id,
                    slug=slug,
                    limit=100,
                    offset=offset
                )
                all_items.extend(resp.items)
                print(f"  Fetched {len(resp.items)} trajectories (offset {offset}, total available: {resp.total})")
                if len(all_items) >= resp.total or not resp.items:
                    break
                offset += 100

            print(f"  Total trajectories: {len(all_items)}")

            # Download each trace
            output_dir = Path("traces_comprehensive") / label
            output_dir.mkdir(parents=True, exist_ok=True)

            for i, item in enumerate(all_items):
                detail = await get_trajectory(client, item.trajectory_id, slug=slug)
                task_id = item.task_id

                # Save as JSON
                output_file = output_dir / f"{task_id}.json"
                with open(output_file, 'w') as f:
                    json.dump(detail.model_dump(mode='json'), f)

                print(f"    [{i+1}/{len(all_items)}] Saved {task_id}")

            print(f"  ✓ Completed for {label}: {len(all_items)} traces saved to {output_dir}/")
            return len(all_items)

    except Exception as e:
        print(f"  ✗ Error for {label}: {e}")
        return 0

async def main():
    print("Starting trace pull for recent submissions...")
    print(f"Total submissions to pull: {len(recent_submissions)}")

    total_traces = 0

    # Pull traces sequentially to avoid rate limiting
    for sub_id, label in sorted(recent_submissions.items()):
        count = await pull_traces(sub_id, label)
        total_traces += count
        await asyncio.sleep(1)  # Rate limit

    print(f"\n{'='*60}")
    print(f"Trace pull complete! Total traces: {total_traces}")
    print('='*60)

if __name__ == "__main__":
    asyncio.run(main())
