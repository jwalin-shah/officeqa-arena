import asyncio
import json
import os
import subprocess
from pathlib import Path
from arena_cli.client.trajectories import ArenaClient, list_trajectories, get_trajectory

# All known submission IDs from local files
known_submissions = {
    "02dd8236-6e32-49fd-932c-639cf028e608": "v10",
    "4e6d7ff2-229e-483a-98ee-4ec7cb9ac6bf": "v8", 
    "64ecc1cc-7996-45e7-ac1d-e176fb7fc377": "v9",
    "95e825ba-3656-4bc8-a739-7a5598a248a2": "v13",
    "e1545632-19f0-49a3-9ec9-0ddfeffb9a8b": "v12",
    "0d738df1-6067-4e6e-8450-54f42e1728da": "unknown",
    "1120fcd1-6826-4311-8db3-3762c55615cd": "unknown",
    "121d5f33-f133-4d2b-806d-6f626ef36e44": "unknown",
    "1629ff51-5137-40a5-ba16-bc70528874fc": "unknown",
    "3a1ae778-50c6-4c25-bc12-5f5929e93490": "unknown",
    "3c6c395b-7fe4-43b2-8d61-41c0061a594c": "unknown",
    "40dc21e2-71dc-4293-b25f-758edd663c55": "unknown",
    "56d0a77b-c907-4447-bdb9-65a977a173e6": "unknown",
    "69e7d7ce-4bea-4d4f-b17a-1135562867b8": "unknown",
    "7abc9f0d-fe22-4681-8e6e-5876791a9c82": "unknown",
    "89790f83-ddcd-4f0f-9fb1-4dadd13893f1": "unknown",
    "9f632fb4-5067-40d9-ae3a-20534367eb78": "unknown",
    "c1e2618e-5f9c-4035-ab40-1a924d5798fb": "unknown",
    "cc19566b-0c49-440c-b4b2-10687ac55c74": "unknown",
    "cc403325-6aeb-477b-bb9f-8e4e1014a2e2": "unknown",
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
            output_dir = Path(label)
            output_dir.mkdir(exist_ok=True)
            
            for i, item in enumerate(all_items):
                detail = await get_trajectory(client, item.trajectory_id, slug=slug)
                task_id = item.task_id
                
                # Save as JSON
                output_file = output_dir / f"{task_id}.json"
                with open(output_file, 'w') as f:
                    json.dump(detail.model_dump(mode='json'), f)
                
                print(f"    [{i+1}/{len(all_items)}] Saved {task_id}")
            
            print(f"  ✓ Completed for {label}: {len(all_items)} traces saved to {output_dir}/")
            
    except Exception as e:
        print(f"  ✗ Error for {label}: {e}")

async def main():
    print("Starting comprehensive trace pull...")
    print(f"Total submissions to pull: {len(known_submissions)}")
    
    # Pull traces sequentially to avoid rate limiting
    for sub_id, label in sorted(known_submissions.items()):
        await pull_traces(sub_id, label)
        await asyncio.sleep(1)  # Rate limit
    
    print(f"\n{'='*60}")
    print("Trace pull complete!")
    print('='*60)

if __name__ == "__main__":
    asyncio.run(main())
