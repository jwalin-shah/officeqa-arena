import asyncio
import json
from pathlib import Path
from arena_cli.client.trajectories import ArenaClient, list_trajectories, get_trajectory

# Try these UUIDs based on arena history (may not be exact)
recent_submissions = {
    "731c7235-9afc-4bfd-bd7d-9e826af6abd5": "v21_1",
    "ea95740d-323a-4861-854f-7d0a75e6a8a8": "v21_2",
}

async def pull_traces(submission_id, label):
    try:
        async with ArenaClient() as client:
            slug = 'grounded-reasoning'
            resp = await list_trajectories(client, submission_id=submission_id, slug=slug, limit=10, offset=0)
            print(f"✓ {label}: {resp.total} trajectories")
            return True
    except Exception as e:
        print(f"✗ {label}: {str(e)[:80]}")
        return False

async def main():
    for sub_id, label in recent_submissions.items():
        await pull_traces(sub_id, label)

asyncio.run(main())
