#!/usr/bin/env python3
"""Pull traces directly from Arena API without arena-cli"""
import asyncio
import json
import os
from pathlib import Path
from typing import Optional

try:
    import httpx
except ImportError:
    print("Installing httpx...")
    os.system("python3 -m pip install --user httpx -q")
    import httpx

# Recent submission IDs from the table
submissions = {
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

# Try to get auth token from environment
AUTH_TOKEN = os.getenv("ANTHROPIC_API_KEY") or os.getenv("ARENA_API_KEY")

async def pull_traces(client: httpx.AsyncClient, submission_id: str, label: str):
    """Pull traces for a submission"""
    print(f"\n{'='*60}")
    print(f"Pulling traces for {label}")
    print('='*60)

    try:
        slug = "grounded-reasoning"
        base_url = "https://api.anthropic.com"

        # Try to list trajectories
        headers = {}
        if AUTH_TOKEN:
            headers["Authorization"] = f"Bearer {AUTH_TOKEN}"

        all_traces = []
        offset = 0

        while True:
            # Try different API endpoints
            for endpoint in [
                f"{base_url}/v1/submissions/{submission_id}/trajectories",
                f"https://grounded-reasoning-api.anthropic.com/trajectories",
            ]:
                try:
                    resp = await client.get(
                        endpoint,
                        params={"submission_id": submission_id, "limit": 100, "offset": offset},
                        headers=headers,
                        timeout=30
                    )

                    if resp.status_code == 200:
                        data = resp.json()
                        items = data.get("items", [])
                        all_traces.extend(items)
                        print(f"  Fetched {len(items)} traces (offset {offset})")

                        if len(items) < 100 or offset > 1000:
                            break
                        offset += 100
                        break
                except Exception as e:
                    continue
            else:
                break

        if all_traces:
            output_dir = Path("traces_comprehensive") / label
            output_dir.mkdir(parents=True, exist_ok=True)

            for item in all_traces:
                task_id = item.get("task_id", "unknown")
                with open(output_dir / f"{task_id}.json", "w") as f:
                    json.dump(item, f)

            print(f"✓ Saved {len(all_traces)} traces to {output_dir}/")
            return len(all_traces)
        else:
            print(f"✗ No traces found or API unreachable")
            return 0

    except Exception as e:
        print(f"✗ Error: {e}")
        return 0

async def main():
    print("Pulling traces from recent submissions...")

    async with httpx.AsyncClient() as client:
        total = 0
        for sub_id, label in sorted(submissions.items()):
            count = await pull_traces(client, sub_id, label)
            total += count
            await asyncio.sleep(2)

    print(f"\n{'='*60}")
    print(f"Total traces pulled: {total}")
    print('='*60)

if __name__ == "__main__":
    asyncio.run(main())
