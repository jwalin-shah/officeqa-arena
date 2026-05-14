import asyncio
import json
from pathlib import Path
from arena_cli.client.trajectories import ArenaClient, list_trajectories, get_trajectory

# From arena history, the 3 most recent COMPLETED submissions
latest_submissions = [
    ("731c7235-9afc-4bfd-bd7d-9e826af6abd5", "v21_181.377_latest"),  # 4h ago, 181.377
    ("ea95740d-323a-4861-854f-7d0a75e6a8a8", "v21_181.254_2ndlatest"),  # 7h ago, 181.254
    ("fae92d59-8c92-4d27-883e-7b0c8ee0f1c4", "v21_135.796_failed"),     # 8h ago, 135.796 (failed)
]

async def pull_submission(submission_id, label):
    print(f"\n{'='*60}")
    print(f"Pulling: {label}")
    print(f"ID: {submission_id}")
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
                print(f"  Fetched batch: {len(resp.items)} items (total: {len(all_items)}/{resp.total})")
                if len(all_items) >= resp.total or not resp.items:
                    break
                offset += 100
            
            if not all_items:
                print(f"  ⚠ No trajectories found")
                return 0
            
            print(f"  Total trajectories available: {len(all_items)}")
            
            # Download each trace
            output_dir = Path("traces_comprehensive") / label
            output_dir.mkdir(parents=True, exist_ok=True)
            
            for i, item in enumerate(all_items):
                detail = await get_trajectory(client, item.trajectory_id, slug=slug)
                task_id = item.task_id
                
                output_file = output_dir / f"{task_id}.json"
                with open(output_file, 'w') as f:
                    json.dump(detail.model_dump(mode='json'), f)
                
                if (i + 1) % 50 == 0 or i == len(all_items) - 1:
                    print(f"    [{i+1}/{len(all_items)}] ✓")
            
            print(f"  ✓ Saved {len(all_items)} traces")
            return len(all_items)
            
    except Exception as e:
        error_msg = str(e)
        if "Submission not found" in error_msg:
            print(f"  ✗ Submission not found (UUID may be incorrect)")
        else:
            print(f"  ✗ Error: {error_msg[:100]}")
        return 0

async def main():
    print("\n" + "="*60)
    print("PULLING LATEST 3 COMPLETED SUBMISSIONS FROM ARENA")
    print("="*60)
    
    results = {}
    for sub_id, label in latest_submissions:
        count = await pull_submission(sub_id, label)
        results[label] = count
        await asyncio.sleep(2)  # Rate limit
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    for label, count in results.items():
        status = "✓" if count > 0 else "✗"
        print(f"{status} {label:40s} : {count:4d} traces")
    
    total = sum(results.values())
    print(f"\nTotal traces pulled: {total}")

if __name__ == "__main__":
    asyncio.run(main())
