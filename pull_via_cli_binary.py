#!/usr/bin/env python3
import subprocess
import json
from pathlib import Path

ARENA_CLI = "/Users/jwalinshah/.arena/bin/arena"

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

def pull_traces(submission_id, label):
    """Pull traces using arena CLI binary"""
    print(f"\n{'='*60}")
    print(f"Pulling traces for {label}")
    print('='*60)

    try:
        output_dir = Path("traces_comprehensive") / label
        output_dir.mkdir(parents=True, exist_ok=True)

        # Try to list trajectories using arena CLI
        cmd = [
            ARENA_CLI, "trajectories", "list",
            "--submission-id", submission_id,
            "--slug", "grounded-reasoning",
            "--format", "json"
        ]

        print(f"  Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            print(f"  ✗ CLI error: {result.stderr[:200]}")
            return 0

        try:
            data = json.loads(result.stdout)
            items = data.get("items", [])
            print(f"  ✓ Found {len(items)} trajectories")

            # Save each trajectory
            for i, item in enumerate(items):
                task_id = item.get("task_id", f"trace_{i}")
                output_file = output_dir / f"{task_id}.json"
                with open(output_file, 'w') as f:
                    json.dump(item, f)

                if (i + 1) % 50 == 0 or i == len(items) - 1:
                    print(f"    [{i+1}/{len(items)}] Saved")

            return len(items)
        except json.JSONDecodeError:
            print(f"  ✗ Invalid JSON response")
            return 0

    except subprocess.TimeoutExpired:
        print(f"  ✗ Command timeout")
        return 0
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return 0

def main():
    print("Starting trace pull using arena CLI binary...")
    print(f"Total submissions: {len(submissions)}")

    total = 0
    for sub_id, label in sorted(submissions.items()):
        count = pull_traces(sub_id, label)
        total += count

    print(f"\n{'='*60}")
    print(f"Complete! Total traces: {total}")
    print('='*60)

if __name__ == "__main__":
    main()
