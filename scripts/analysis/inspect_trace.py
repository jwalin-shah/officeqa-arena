#!/usr/bin/env python3
import json
from pathlib import Path

# Find one sample trace
traces_dir = Path("traces_comprehensive")
trace_file = None
for d in traces_dir.iterdir():
    traces = list(d.glob("*.json"))
    if traces:
        trace_file = traces[0]
        break

if trace_file:
    with open(trace_file) as f:
        t = json.load(f)

    print(f"File: {trace_file}")
    print(f"Task: {t.get('task_id')}")
    print(f"Reward: {t.get('reward')}")
    print(f"Status: {t.get('status')}")
    print(f"\nTop-level keys: {list(t.keys())}")

    if "trajectory" in t:
        traj = t["trajectory"]
        print(f"\nTrajectory field type: {type(traj).__name__}")

        if isinstance(traj, dict):
            print(f"Trajectory keys: {list(traj.keys())}")

            # Show first few fields
            for k in list(traj.keys())[:5]:
                v = traj[k]
                if isinstance(v, str):
                    preview = v[:100] + "..." if len(v) > 100 else v
                    print(f"\n  {k} (str): {preview}")
                elif isinstance(v, list):
                    print(f"\n  {k} (list, {len(v)} items)")
                    if v and isinstance(v[0], dict):
                        print(f"    First item keys: {list(v[0].keys())[:5]}")
                elif isinstance(v, dict):
                    print(f"\n  {k} (dict, {len(v)} keys): {list(v.keys())[:5]}")
                else:
                    print(f"\n  {k} ({type(v).__name__}): {v}")

        elif isinstance(traj, list):
            print(f"Trajectory is list with {len(traj)} items")
            if traj and isinstance(traj[0], dict):
                print(f"  First item keys: {list(traj[0].keys())}")
