#!/usr/bin/env python3
"""
Test the reasoning prompt on actual tasks.
Shows the agent's thinking process.
"""

import sys
import os
from pathlib import Path

# Add repo to path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

def test_reasoning():
    """Run a few tasks with reasoning enabled."""
    import subprocess
    import json
    
    # Test 5 tasks with different complexity levels
    test_tasks = [
        "uid0001",  # Easy: single value (budget receipts)
        "uid0008",  # Easy: simple metric
        "uid0043",  # Easy: trust fund
        "uid0045",  # Easy: country claim
        "uid0044",  # Hard: weekly capital flow
    ]
    
    print("\n" + "="*80)
    print("TESTING AGENT REASONING ON 5 TASKS")
    print("="*80)
    
    for uid in test_tasks:
        print(f"\n📝 Testing: {uid}")
        print("-" * 80)
        
        # Run with test harness
        cmd = [
            "python3", "test_local_harness.py",
            "--question-ids", uid,
            "--max-turns", "15"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        # Show output (will include reasoning from enhanced prompt)
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr[:500])
        
        print("-" * 80)
    
    print("\n" + "="*80)
    print("REASONING TEST COMPLETE")
    print("="*80)
    print("\nLook for <thinking> and <evaluation> blocks in the output above.")
    print("These show the agent's reasoning for each tool call.")

if __name__ == "__main__":
    # Check for API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set")
        print("Set it with: export ANTHROPIC_API_KEY=$(cat ~/.anthropic/api_key)")
        sys.exit(1)
    
    test_reasoning()
