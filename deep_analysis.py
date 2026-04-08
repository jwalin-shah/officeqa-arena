#!/usr/bin/env python3
"""Deep analysis of trace content"""
import json
from pathlib import Path
from collections import defaultdict, Counter

def analyze_trace_content():
    traces_dir = Path("traces_comprehensive")

    analysis = {
        "by_version": defaultdict(lambda: {
            "total": 0,
            "sample_keys": set(),
            "has_tools": 0,
            "has_intermediate": 0,
            "has_answer": 0,
            "has_steps": 0,
            "reward_dist": Counter(),
            "task_samples": []
        })
    }

    for trace_dir in sorted(traces_dir.iterdir()):
        if not trace_dir.is_dir() or trace_dir.name.startswith('.'):
            continue

        version = trace_dir.name
        trace_files = list(trace_dir.glob("*.json"))

        for trace_file in trace_files[:5]:  # Sample 5 traces per version
            try:
                with open(trace_file) as f:
                    trace = json.load(f)

                if not isinstance(trace, dict):
                    continue

                version_data = analysis["by_version"][version]
                version_data["total"] = len(trace_files)

                # Track top-level keys
                version_data["sample_keys"].update(trace.keys())

                # Look for common trace structures
                if "tool_calls" in trace or "tools" in trace or "action" in trace:
                    version_data["has_tools"] += 1
                if "intermediate" in trace or "steps" in trace:
                    version_data["has_intermediate"] += 1
                if "answer" in trace or "final_answer" in trace or "result" in trace:
                    version_data["has_answer"] += 1
                if "steps" in trace or "actions" in trace:
                    version_data["has_steps"] += 1

                # Track reward
                if "reward" in trace:
                    try:
                        r = float(trace["reward"])
                        version_data["reward_dist"][round(r, 2)] += 1
                    except:
                        pass

            except Exception as e:
                pass

    return analysis

def print_analysis(analysis):
    print(f"\n{'='*100}")
    print("DEEP TRACE CONTENT ANALYSIS")
    print('='*100)

    for version in sorted(analysis["by_version"].keys()):
        data = analysis["by_version"][version]
        if data["total"] == 0:
            continue

        print(f"\n{version} ({data['total']} traces)")
        print(f"  Keys: {sorted(list(data['sample_keys'])[:5])}")
        print(f"  Has tools: {data['has_tools']}, intermediate: {data['has_intermediate']}, answer: {data['has_answer']}, steps: {data['has_steps']}")

        if data["reward_dist"]:
            rewards = sorted(data["reward_dist"].items())
            print(f"  Reward distribution: {dict(rewards[:5])}")

if __name__ == "__main__":
    analysis = analyze_trace_content()
    print_analysis(analysis)

    # Also show trace structure example
    print(f"\n{'='*100}")
    print("SAMPLE TRACE STRUCTURE")
    print('='*100)

    for trace_dir in sorted(Path("traces_comprehensive").iterdir()):
        if not trace_dir.is_dir():
            continue

        traces = list(trace_dir.glob("*.json"))
        if traces:
            with open(traces[0]) as f:
                sample = json.load(f)

            print(f"\n{trace_dir.name}:")
            if isinstance(sample, dict):
                print(f"  Top-level keys: {list(sample.keys())[:10]}")
                print(f"  Sample data:")
                for key in list(sample.keys())[:3]:
                    val = sample[key]
                    if isinstance(val, (str, int, float, bool)):
                        print(f"    {key}: {str(val)[:80]}")
                    elif isinstance(val, (list, dict)):
                        print(f"    {key}: {type(val).__name__} with {len(val)} items")
            break
