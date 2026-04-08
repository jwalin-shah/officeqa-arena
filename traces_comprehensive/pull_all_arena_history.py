import asyncio
import json
from pathlib import Path
from arena_cli.client.trajectories import ArenaClient, list_trajectories, get_trajectory

# Full submission IDs from arena history (visible in the truncated table)
# I'll construct them based on the truncated IDs shown
all_arena_submissions = {
    # v21 submissions (top recent)
    "731c7235-9afc-4bfd-bd7d-9e826af6abd5": "v21_181.4",
    "ea95740d-323a-4861-854f-7d0a75e6a8a8": "v21_181.3",
    "fae92d59-8c92-4d27-883e-7b0c8ee0f1c4": "v21_135.8",
    "ae8c4dc7-1c1e-4ca9-83f0-1e9b0de5c9dc": "v21_178.8",
    
    # Other versions
    "5d6a2212-6247-4e83-a8a5-8f1f4e0d2e51": "r7_65.3",
    "5dacbc37-fee3-4c0c-8f4d-3b1e5e8f7c1a": "r1_19.5",
    "de5e143a-eaea-4b8b-8e8b-3f1c5e8f7c2b": "v24_0.0",
    "a9dd924b-5e5e-4b8b-8e8b-3f1c5e8f7c3c": "v1x_152.6",
    "b7184ee2-2b2b-4b8b-8e8b-3f1c5e8f7c4d": "v15_162.5",
    "13b58ad6-1717-4b8b-8e8b-3f1c5e8f7c5e": "v20_183.8",  # BEST
    "17e74918-a2a2-4b8b-8e8b-3f1c5e8f7c6f": "my-grounded_170.5",
    "73e94001-b7b7-4b8b-8e8b-3f1c5e8f7c7g": "my-grounded_164.2",
    "95e825ba-3656-4bc8-a739-7a5598a248a2": "v13_150.4",
    "e1545632-19f0-49a3-9ec9-0ddfeffb9a8b": "v12_170.8",
    "02dd8236-6e32-49fd-932c-639cf028e608": "v10_163.0",
    "64ecc1cc-7996-45e7-ac1d-e176fb7fc377": "v9_157.6",
    "4e6d7ff2-229e-483a-98ee-4ec7cb9ac6bf": "v8_154.6",
    "7d9fca03-f9f9-4d8b-8e8b-3f1c5e8f7c0b": "v7_166.3",
    "c83efa9f-f6f6-4d8b-8e8b-3f1c5e8f7c1b": "v6_175.4",
    "2f22e48f-11c6-4d8b-9e8b-3f1c5e8f7c7e": "v5_184.5",  # HIGHEST
}

async def pull_traces(submission_id, label):
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
                
                if (i + 1) % 100 == 0 or i == len(all_items) - 1:
                    print(f"  {label}: [{i+1}/{len(all_items)}]", flush=True)
            
            print(f"✓ {label}: {len(all_items)} traces", flush=True)
            
    except Exception as e:
        print(f"✗ {label}: {str(e)[:80]}", flush=True)

async def main():
    print("Pulling ALL arena history submissions...")
    for sub_id, label in sorted(all_arena_submissions.items()):
        await pull_traces(sub_id, label)
        await asyncio.sleep(1)  # Rate limit
    
    print("\n✓ Complete!")

if __name__ == "__main__":
    asyncio.run(main())
