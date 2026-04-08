#!/usr/bin/env python3
"""Comprehensive analysis of all 8,265 traces"""
import json
import re
from pathlib import Path
from collections import defaultdict, Counter
from statistics import mean, median, stdev

def analyze_all_traces():
    traces_dir = Path("traces_comprehensive")

    analysis = {
        "versions": defaultdict(lambda: {
            "total": 0, "pass": 0, "fail": 0, "pass_rate": 0,
            "step_counts": [], "step_avg": 0,
            "models_used": Counter(),
            "tools_used": Counter(),
            "failure_reasons": Counter(),
            "reasoning_lengths": [],
            "task_ids": set()
        }),
        "tasks": defaultdict(lambda: {"pass": 0, "fail": 0, "versions": []}),
        "patterns": {
            "step_count_correlation": {},
            "model_correlation": {},
            "tool_correlation": {}
        }
    }

    # Analyze each trace
    for version_dir in sorted(traces_dir.iterdir()):
        if not version_dir.is_dir() or version_dir.name.startswith('.'):
            continue

        version = version_dir.name
        trace_files = list(version_dir.glob("*.json"))

        for trace_file in trace_files:
            try:
                with open(trace_file) as f:
                    trace = json.load(f)

                task_id = trace.get("task_id", "unknown")
                reward = trace.get("reward", 0)
                traj = trace.get("trajectory", {})

                # Update version stats
                v_data = analysis["versions"][version]
                v_data["total"] += 1
                v_data["task_ids"].add(task_id)

                if reward > 0.5:
                    v_data["pass"] += 1
                else:
                    v_data["fail"] += 1

                # Extract data
                agent = traj.get("agent", {})
                model = agent.get("model_name", "unknown")
                v_data["models_used"][model] += 1

                steps = traj.get("steps", [])
                v_data["step_counts"].append(len(steps))

                # Analyze steps for tools and reasoning
                for step in steps:
                    if step.get("tool_calls"):
                        for tool_call in step["tool_calls"]:
                            tool_name = tool_call.get("name", "unknown")
                            v_data["tools_used"][tool_name] += 1

                    reasoning = step.get("reasoning_content", "")
                    if reasoning:
                        v_data["reasoning_lengths"].append(len(reasoning))

                # Track task performance
                t_data = analysis["tasks"][task_id]
                t_data["versions"].append(version)
                if reward > 0.5:
                    t_data["pass"] += 1
                else:
                    t_data["fail"] += 1

            except Exception as e:
                pass

        # Calculate averages for this version
        v_data = analysis["versions"][version]
        if v_data["step_counts"]:
            v_data["step_avg"] = mean(v_data["step_counts"])
        if v_data["total"] > 0:
            v_data["pass_rate"] = v_data["pass"] / v_data["total"] * 100

    return analysis

def print_analysis(analysis):
    print("\n" + "="*120)
    print("COMPREHENSIVE TRACE ANALYSIS: 8,265 TRACES ACROSS 62 VERSIONS")
    print("="*120)

    # Version rankings
    print("\n📊 VERSION RANKINGS BY PASS RATE:")
    print(f"{'Version':<35} {'Total':>6} {'Pass':>6} {'Fail':>6} {'Rate':>8} {'Avg Steps':>10} {'Top Model':>30}")
    print("-"*130)

    sorted_versions = sorted(
        analysis["versions"].items(),
        key=lambda x: x[1]["pass_rate"],
        reverse=True
    )

    for version, data in sorted_versions[:20]:
        if data["total"] == 0:
            continue

        top_model = data["models_used"].most_common(1)[0][0] if data["models_used"] else "unknown"
        step_avg = data.get("step_avg", 0) or 0
        print(f"{version:<35} {data['total']:>6} {data['pass']:>6} {data['fail']:>6} {data['pass_rate']:>7.1f}% {step_avg:>10.1f} {str(top_model)[:30]:>30}")

    # Task difficulty analysis
    print("\n\n🎯 TASK DIFFICULTY ANALYSIS (% of versions that pass each task):")
    print(f"{'Task ID':<20} {'Versions Passed':>20} {'Versions Tested':>20} {'Difficulty':>15}")
    print("-"*75)

    task_difficulty = sorted(
        analysis["tasks"].items(),
        key=lambda x: (x[1]["pass"] / max(1, x[1]["pass"] + x[1]["fail"]), -len(x[1]["versions"])),
        reverse=True
    )

    hardest = task_difficulty[-10:]
    easiest = task_difficulty[:10]

    for task_id, data in easiest:
        total = data["pass"] + data["fail"]
        if total > 0:
            rate = (data["pass"] / total) * 100
            print(f"{task_id:<20} {data['pass']:>20} {total:>20} {rate:>14.1f}%")

    print("\n... [middle tasks] ...\n")

    for task_id, data in reversed(hardest):
        total = data["pass"] + data["fail"]
        if total > 0:
            rate = (data["pass"] / total) * 100
            print(f"{task_id:<20} {data['pass']:>20} {total:>20} {rate:>14.1f}%")

    # Tool usage analysis
    print("\n\n🔧 TOOL USAGE PATTERNS:")
    all_tools = Counter()
    for version_data in analysis["versions"].values():
        all_tools.update(version_data["tools_used"])

    if all_tools:
        print("Top tools used:")
        for tool, count in all_tools.most_common(10):
            print(f"  {tool}: {count} calls")
    else:
        print("  No tools detected in traces (MCP/tool_calls may not be captured)")

    # Step count correlation
    print("\n\n📈 STEP COUNT PATTERNS:")
    step_ranges = defaultdict(lambda: {"pass": 0, "fail": 0})

    for version, data in analysis["versions"].items():
        if data["step_counts"]:
            avg_steps = data["step_avg"]
            step_range = f"{int(avg_steps//5)*5}-{int(avg_steps//5)*5+5}"
            if data["pass"] > 0:
                step_ranges[step_range]["pass"] += data["pass"]
            if data["fail"] > 0:
                step_ranges[step_range]["fail"] += data["fail"]

    print("Pass rate by average step count:")
    for step_range in sorted(step_ranges.keys(), key=lambda x: int(x.split('-')[0])):
        data = step_ranges[step_range]
        total = data["pass"] + data["fail"]
        if total > 0:
            rate = (data["pass"] / total) * 100
            print(f"  {step_range} steps: {rate:.1f}% pass ({data['pass']}/{total})")

    print("\n" + "="*120)

if __name__ == "__main__":
    print("Analyzing all traces...")
    analysis = analyze_all_traces()
    print_analysis(analysis)

    # Save analysis for agent review
    with open("trace_analysis_results.json", "w") as f:
        # Convert for JSON serialization
        export = {}
        for v_name, v_data in analysis["versions"].items():
            export[v_name] = {
                "total": v_data["total"],
                "pass": v_data["pass"],
                "fail": v_data["fail"],
                "pass_rate": v_data["pass_rate"],
                "step_avg": v_data["step_avg"],
                "top_model": dict(v_data["models_used"].most_common(3)),
                "top_tools": dict(v_data["tools_used"].most_common(5))
            }
        json.dump(export, f, indent=2)

    print("\n✓ Analysis saved to trace_analysis_results.json")
