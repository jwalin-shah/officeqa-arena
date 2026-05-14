import asyncio
import json
from arena_cli.client.trajectories import ArenaClient

async def main():
    async with ArenaClient() as client:
        # Try to use client methods to get submissions
        # The list_trajectories function can help us identify submissions
        
        # These are the truncated IDs from the table - we need to find the full ones
        truncated_patterns = [
            ("731c7235-9a", "v21_181.4"),
            ("ea95740d-32", "v21_181.3"),
            ("fae92d59-8c", "v21_135.8"),
            ("ae8c4dc7-1c", "v21_178.8"),
            ("13b58ad6-17", "v20_183.8"),
            ("2f22e48f-11", "v5_184.5"),
            ("7d9fca03-f9", "v7_166.3"),
            ("c83efa9f-f6", "v6_175.4"),
            ("b7184ee2-2b", "v15_162.5"),
            ("a9dd924b-5e", "v1x_152.6"),
            ("de5e143a-ea", "v24_0.0"),
            ("5dacbc37-fe", "r1_19.5"),
            ("5d6a2212-62", "r7_65.3"),
        ]
        
        # Try each truncated pattern and see if we can complete it
        for truncated, label in truncated_patterns:
            # The pattern is 8-4 hex, we need to find valid continuations
            # Since we don't know the full UUID, let's try a different approach
            
            # Check if arena has any submission listing endpoint
            try:
                # Try posting to get submission details
                resp = await client.post("/submissions/search", json={
                    "limit": 1,
                    "offset": 0,
                })
                print(f"Found endpoint! {resp}")
            except Exception as e:
                pass
        
        print("Need different approach - arena API doesn't expose submissions list")

asyncio.run(main())
