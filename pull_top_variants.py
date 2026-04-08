import asyncio
import json
from pathlib import Path
from arena_cli.client.trajectories import ArenaClient, list_trajectories, get_trajectory

# Top and variant submissions
target_submissions = {
    # Top v21 submissions
    "731c7235-9afc-4bfd-bd7d-9e826af6abd5": "v21_top1",  # 181.377
    "ea95740d-323a-4861-854f-7d0a75e6a8a8": "v21_top2",  # 181.254
    # Best overall (v20)
    "13b58ad6-1717-4b8b-8e8b-3f1c5e8f7c5e": "v20_best",  # 183.845
    # Second best (v5)
    "2f22e48f-11c6-4d8b-9e8b-3f1c5e8f7c7e": "v5_high",  # 184.454
    # Variants mentioned
    "de5e143a-eaea-4b8b-8e8b-3f1c5e8f7c2b": "v24_opencode",  # 0.0 (opencode test)
    # Other high performers
    "c83efa9f-f6f6-4d8b-8e8b-3f1c5e8f7c1b": "v6_goose",  # 175.446
    "7d9fca03-f9f9-4d8b-8e8b-3f1c5e8f7c0b": "v7_goose",  # 166.277
}

async def pull_traces(submission_id, label):
    print(f"\nPulling {label}...", flush=True)
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
                print(f"  Fetched {len(resp.items)} trajectories (total: {resp.total})", flush=True)
                if len(all_items) >= resp.total or not resp.items:
                    break
                offset += 100
            
            # Download each trace
            output_dir = Path("traces_comprehensive") / label
            output_dir.mkdir(parents=True, exist_ok=True)
            
            for i, item in enumerate(all_items):
                detail = await get_trajectory(client, item.trajectory_id, slug=slug)
                task_id = item.task_id
                
                output_file = output_dir / f"{task_id}.json"
                with open(output_file, 'w') as f:
                    json.dump(detail.model_dump(mode='json'), f)
                
                if (i + 1) % 50 == 0:
                    print(f"    [{i+1}/{len(all_items)}] Saved", flush=True)
            
            print(f"  ✓ {label}: {len(all_items)} traces saved", flush=True)
            
    except Exception as e:
        print(f"  ✗ {label}: {e}", flush=True)

async def main():
    print("Pulling top submissions and variants...")
    for sub_id, label in target_submissions.items():
        await pull_traces(sub_id, label)
        await asyncio.sleep(2)  # Rate limit
    
    print("\n✓ All top/variant submissions pulled!")

if __name__ == "__main__":
    asyncio.run(main())
