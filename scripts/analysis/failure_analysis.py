#!/usr/bin/env python3
"""Analyze failure patterns to find what causes task failures"""
import json
import re
from pathlib import Path
from collections import defaultdict, Counter

def analyze_failures():
    traces_dir = Path("traces_comprehensive")

    failures = {
        "by_version": defaultdict(list),
        "failure_patterns": Counter(),
        "last_steps": Counter(),
        "error_indicators": Counter(),
    }

    # Analyze failures
    for version_dir in sorted(traces_dir.iterdir()):
        if not version_dir.is_dir() or version_dir.name.startswith('.'):
            continue

        version = version_dir.name
        trace_files = list(version_dir.glob("*.json"))

        for trace_file in trace_files[:50]:  # Sample for speed
            try:
                with open(trace_file) as f:
                    trace = json.load(f)

                reward = trace.get("reward", 1)
                if reward > 0.5:  # Only failures
                    continue

                task_id = trace.get("task_id")
                traj = trace.get("trajectory", {})
                steps = traj.get("steps", [])

                # Look at last step
                if steps:
                    last_step = steps[-1]
                    message = last_step.get("message", "")
                    observation = last_step.get("observation", "")

                    failures["by_version"][version].append({
                        "task_id": task_id,
                        "step_count": len(steps),
                        "last_message": message[:100] if message else None,
                        "has_error": "error" in str(observation).lower(),
                        "has_timeout": "timeout" in str(observation).lower(),
                        "observation_type": type(observation).__name__
                    })

                    # Track patterns
                    if "error" in str(observation).lower():
                        failures["error_indicators"]["error_message"] += 1
                    if "timeout" in str(observation).lower():
                        failures["error_indicators"]["timeout"] += 1
                    if "not found" in str(observation).lower():
                        failures["error_indicators"]["not_found"] += 1

            except Exception as e:
                pass

    return failures

def print_failure_analysis(failures):
    print("\n" + "="*100)
    print("FAILURE PATTERN ANALYSIS")
    print("="*100)

    print("\n❌ Error Indicators (in failed tasks):")
    for indicator, count in failures["error_indicators"].most_common():
        print(f"  {indicator}: {count} occurrences")

    print("\n❌ Sample Failures by Version:")
    for version in sorted(failures["by_version"].keys())[:10]:
        fails = failures["by_version"][version]
        if fails:
            print(f"\n  {version} ({len(fails)} failures sampled):")
            for fail in fails[:3]:
                print(f"    Task {fail['task_id']}: {fail['step_count']} steps")
                print(f"      Error: {fail['has_error']}, Timeout: {fail['has_timeout']}")

    print("\n" + "="*100)

if __name__ == "__main__":
    print("Analyzing failure patterns...")
    failures = analyze_failures()
    print_failure_analysis(failures)

    with open("failure_analysis.json", "w") as f:
        json.dump({
            "error_indicators": dict(failures["error_indicators"]),
        }, f, indent=2)

    print("✓ Failure analysis saved")
