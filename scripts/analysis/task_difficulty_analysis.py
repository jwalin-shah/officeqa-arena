#!/usr/bin/env python3
"""Analyze which tasks are hard vs easy and why"""
import json
from pathlib import Path
from collections import defaultdict

def analyze_task_difficulty():
    traces_dir = Path("traces_comprehensive")

    tasks = defaultdict(lambda: {
        "total": 0, "pass": 0, "fail": 0,
        "versions": set(),
        "versions_passing": set(),
        "versions_failing": set(),
        "avg_steps_pass": [], "avg_steps_fail": []
    })

    # Collect data
    for version_dir in traces_dir.iterdir():
        if not version_dir.is_dir():
            continue

        version = version_dir.name
        trace_files = list(version_dir.glob("*.json"))

        for trace_file in trace_files:
            try:
                with open(trace_file) as f:
                    trace = json.load(f)

                task_id = trace.get("task_id")
                reward = trace.get("reward", 0)
                steps = len(trace.get("trajectory", {}).get("steps", []))

                t_data = tasks[task_id]
                t_data["total"] += 1
                t_data["versions"].add(version)

                if reward > 0.5:
                    t_data["pass"] += 1
                    t_data["versions_passing"].add(version)
                    t_data["avg_steps_pass"].append(steps)
                else:
                    t_data["fail"] += 1
                    t_data["versions_failing"].add(version)
                    t_data["avg_steps_fail"].append(steps)

            except:
                pass

    return tasks

def print_analysis(tasks):
    print("\n" + "="*120)
    print("TASK DIFFICULTY ANALYSIS: Which tasks are hard? Which versions pass them?")
    print("="*120)

    # Sort by pass rate
    sorted_tasks = sorted(tasks.items(), key=lambda x: (x[1]["pass"] / max(1, x[1]["total"]), x[1]["total"]), reverse=True)

    print("\n✅ EASIEST TASKS (passed by most versions):")
    print(f"{'Task':<20} {'Pass Rate':>12} {'Versions':>10} {'Pass/Fail':>10} {'Avg Steps':>12}")
    print("-"*65)

    for task_id, data in sorted_tasks[:15]:
        if data["total"] == 0:
            continue
        rate = (data["pass"] / data["total"]) * 100
        avg_steps = sum(data["avg_steps_pass"]) / len(data["avg_steps_pass"]) if data["avg_steps_pass"] else 0
        print(f"{task_id:<20} {rate:>11.1f}% {data['total']:>10} {data['pass']:>9}/{data['fail']} {avg_steps:>12.1f}")

    print("\n\n❌ HARDEST TASKS (failed by most versions):")
    print(f"{'Task':<20} {'Pass Rate':>12} {'Versions':>10} {'Pass/Fail':>10} {'Avg Steps':>12}")
    print("-"*65)

    for task_id, data in reversed(sorted_tasks[-15:]):
        if data["total"] == 0:
            continue
        rate = (data["pass"] / data["total"]) * 100
        avg_steps_fail = sum(data["avg_steps_fail"]) / len(data["avg_steps_fail"]) if data["avg_steps_fail"] else 0
        print(f"{task_id:<20} {rate:>11.1f}% {data['total']:>10} {data['pass']:>9}/{data['fail']} {avg_steps_fail:>12.1f}")

    # Find universal passes/fails
    print("\n\n🎯 UNIVERSAL OUTCOMES:")
    always_pass = [t for t, d in tasks.items() if d["pass"] > 0 and d["fail"] == 0 and d["total"] > 10]
    always_fail = [t for t, d in tasks.items() if d["fail"] > 0 and d["pass"] == 0 and d["total"] > 10]

    print(f"\nAlways Pass (all {len(always_pass)} versions): {always_pass[:5]}...")
    print(f"Always Fail (all {len(always_fail)} versions): {always_fail[:5]}...")

    print("\n" + "="*120)

if __name__ == "__main__":
    print("Analyzing task difficulty...")
    tasks = analyze_task_difficulty()
    print_analysis(tasks)
