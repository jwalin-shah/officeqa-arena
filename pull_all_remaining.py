#!/usr/bin/env python3
"""Aggressively pull traces from ALL submissions"""
import asyncio
import json
from pathlib import Path
from arena_cli.client.trajectories import ArenaClient, list_trajectories, get_trajectory

# ALL submissions from the table (not yet pulled or incomplete)
all_submissions = {
    # Already got good ones, but retry for completeness
    "13b58ad6-1767-46e6-be25-e3f1108023a0": "v20-1d-183.8",

    # Other recent ones from the table
    "17e74918-a2e7-4249-a3b0-d8ad02e01754": "my-agent-v0.2-1d-170.5",
    "73e94001-b769-4759-9e25-a4df586ba442": "my-agent-v0.2-1d-164.2",
    "95e825ba-3656-4bc8-a739-7a5598a248a2": "v13-1d-150.4",
    "e1545632-19f0-49a3-9ec9-0ddfeffb9a8b": "v12-1d-170.8",
    "02dd8236-6e32-49fd-932c-639cf028e608": "v10-1d-163",
    "64ecc1cc-7996-45e7-ac1d-e176fb7fc377": "v9-2d-157.6",
    "4e6d7ff2-229e-483a-98ee-4ec7cb9ac6bf": "v8-2d-154.6",
    "7d9fca03-f947-4750-9d17-93902cf6a09c": "v7-2d-166.3",
    "c83efa9f-f64f-4be8-90b9-d31821026a36": "page-first-2d-175.4",
    "2f22e48f-115e-49bb-a9ed-ec38397e331d": "mcp-v5-2d-184.5",
    "ceb59271-6459-4061-838d-13da3e3703e4": "submit-v6-2d-157.2",
    "ceddcd6f-ecdc-4b55-88a3-833646afd64e": "submit-v5-2d-170.5",
    "339e7378-cca2-4276-9101-6c759871febc": "final-v2-3d-170.9",
    "f4cea075-7773-4c41-a2b0-d1569ed334d7": "final-v1-3d-175.5",
    "1dc17be5-fdf1-4958-ba4c-ffa2126a8df5": "mcp-v4-3d-162.4",
    "607acb7c-fec5-4629-890d-326d859c40ac": "mcp-v4-3d-179.4",
    "01c0b0a9-fa0a-4e59-a092-07b54d97dc15": "submit-v4-3d-150.5",
    "9e482be0-8c8a-45a0-958a-01d0c6814639": "nomcp-v3-3d-174.2",
    "14461e0c-181e-4983-ab9a-2a8ff34bd6e4": "nomcp-v2-4d-174",
    "56d0a77b-c907-4447-bdb9-65a977a173e6": "nomcp-v2-4d-175.6",
    "3c6c395b-7fe4-43b2-8d61-41c0061a594c": "nomcp-v2-4d-172.3",
    "cc403325-6aeb-477b-bb9f-8e4e1014a2e2": "nomcp-v2-4d-179.3",
    "c1e2618e-5f9c-4035-ab40-1a924d5798fb": "nomcp-v2-5d-170.9",
    "1629ff51-5137-40a5-ba16-bc70528874fc": "arena-v1-5d-179.2",
    "1120fcd1-6826-4311-8db3-3762c55615cd": "arena-v1-5d-168.5",
    "9f632fb4-5067-40d9-ae3a-20534367eb78": "arena-v1-5d-174.6",
    "7abc9f0d-fe22-4681-8e6e-5876791a9c82": "arena-v1-6d-180.4",
    "0b44a6a1-efe8-4dd4-baf3-f0784270d557": "my-agent-v0.1-6d-78.75",
    "40dc21e2-71dc-4293-b25f-758edd663c55": "arena-v0.9-6d-167.2",
    "0d738df1-6067-4e6e-8450-54f42e1728da": "arena-v0.8-6d-148.9",
    "3a1ae778-50c6-4c25-bc12-5f5929e93490": "arena-v0.7-failed",
    "89790f83-ddcd-4f0f-9fb1-4dadd13893f1": "arena-v0.7-failed-2",
    "69e7d7ce-4bea-4d4f-b17a-1135562867b8": "arena-v0.7-2d-143.3",
    "121d5f33-f133-4d2b-806d-6f626ef36e44": "arena-v0.6-30d-144.3",
    "cc19566b-0c49-440c-b4b2-10687ac55c74": "arena-v0.6-30d-151.8",
}

async def pull_traces(submission_id, label):
    """Pull traces for a submission"""
    output_dir = Path("traces_comprehensive") / label
    output_dir.mkdir(parents=True, exist_ok=True)

    # Skip if already has traces
    existing = list(output_dir.glob("*.json"))
    if len(existing) >= 200:
        print(f"✓ {label}: already {len(existing)} traces")
        return len(existing)

    try:
        async with ArenaClient() as client:
            slug = 'grounded-reasoning'
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

                if len(all_items) >= resp.total or not resp.items:
                    break
                offset += 100

            # Download each trace
            for i, item in enumerate(all_items):
                detail = await get_trajectory(client, item.trajectory_id, slug=slug)
                task_id = item.task_id
                output_file = output_dir / f"{task_id}.json"

                with open(output_file, 'w') as f:
                    json.dump(detail.model_dump(mode='json'), f)

            print(f"✓ {label}: {len(all_items)} traces")
            return len(all_items)

    except Exception as e:
        print(f"✗ {label}: {str(e)[:60]}")
        return 0

async def main():
    print(f"Pulling traces from {len(all_submissions)} submissions (aggressive mode)...\n")

    # Run pulls with moderate parallelism (3-4 concurrent to avoid overwhelming API)
    semaphore = asyncio.Semaphore(3)

    async def pull_with_semaphore(sub_id, label):
        async with semaphore:
            return await pull_traces(sub_id, label)

    tasks = [pull_with_semaphore(sub_id, label) for sub_id, label in all_submissions.items()]
    results = await asyncio.gather(*tasks)

    total = sum(results)
    print(f"\n{'='*60}")
    print(f"Complete! Pulled {total} traces total")
    print(f"{'='*60}")

if __name__ == "__main__":
    asyncio.run(main())
