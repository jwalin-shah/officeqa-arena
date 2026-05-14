#!/usr/bin/env python3
"""
Comprehensive analysis of top versions to find patterns and complementarity.
Focuses on: step efficiency, pass/fail patterns, complementary strengths.
"""
import json
import os
from pathlib import Path
from collections import defaultdict
import sys

BASE_DIR = Path("/Users/jwalinshah/projects/officeqa-arena/traces_comprehensive")

# Top versions by score
TOP_VERSIONS = [
    ("v20_183.8", 183.8, "v20 baseline - highest score"),
    ("v20-1d-183.8", 183.8, "v20 variant - same score"),
    ("best_184", 184.0, "best run label"),
    ("v21-6h-181.4", 181.4, "v21 6-hour run"),
    ("v21-9h-181.3", 181.3, "v21 9-hour run"),
    ("v21-13h-178.8", 178.8, "v21 13-hour run"),
    ("v15-23h", None, "v15 long run"),
    ("v15-oh-21h", None, "v15 openhands"),
]

def load_traces(version_dir):
    """Load all traces from a version directory."""
    traces = {}
    if not version_dir.exists():
        return traces

    for trace_file in sorted(version_dir.glob("*.json")):
        try:
            with open(trace_file) as f:
                data = json.load(f)
                # Extract task_id / uid
                task_id = data.get("task_id", "")
                uid = task_id.replace("officeqa-uid", "").replace("officeqa-", "")

                traces[uid] = {
                    "task_id": task_id,
                    "status": data.get("status"),
                    "reward": data.get("reward"),
                    "step_count": len(data.get("trajectory", {}).get("steps", [])),
                    "trajectory": data.get("trajectory", {}),
                }
        except Exception as e:
            pass
    return traces

def get_answer(trace_dict):
    """Extract final answer from trajectory."""
    if not trace_dict or "trajectory" not in trace_dict:
        return None

    trajectory = trace_dict["trajectory"]
    steps = trajectory.get("steps", [])

    for step in reversed(steps):
        # Look for answer.txt in observation
        if "observation" in step and step["observation"]:
            obs = step["observation"]
            if isinstance(obs, dict):
                results = obs.get("results", [])
                if results and len(results) > 0:
                    content = results[0].get("content", "")
                    if content and len(content.strip()) < 1000:  # Likely answer, not full file dump
                        return content.strip()
            elif isinstance(obs, str) and len(obs.strip()) < 1000:
                return obs.strip()

    return None

def extract_qid(uid_str):
    """Extract numeric question ID from uid."""
    if uid_str:
        uid_str = str(uid_str).replace("uid", "").strip()
        try:
            return int(uid_str)
        except:
            pass
    return None

def numeric_match(v1, v2, tolerance=0.01):
    """Loose numeric comparison."""
    try:
        f1 = float(str(v1).replace(",", "").strip())
        f2 = float(str(v2).replace(",", "").strip())
        if f1 == 0 and f2 == 0:
            return True
        return abs(f1 - f2) / max(abs(f1), abs(f2)) <= tolerance
    except:
        return False

def main():
    print("=" * 100)
    print("TOP VERSIONS DETAILED ANALYSIS")
    print("=" * 100)

    # Load all versions
    all_versions = {}
    version_scores = {}

    for version_name, score, desc in TOP_VERSIONS:
        version_dir = BASE_DIR / version_name
        traces = load_traces(version_dir)

        if traces:
            all_versions[version_name] = traces
            version_scores[version_name] = score

            # Calculate stats
            steps = [t["step_count"] for t in traces.values()]
            avg_steps = sum(steps) / len(steps) if steps else 0

            print(f"\n{version_name}")
            print(f"  Score: {score}")
            print(f"  Tasks: {len(traces)}")
            print(f"  Steps - avg: {avg_steps:.1f}, min: {min(steps) if steps else 0}, max: {max(steps) if steps else 0}")

    if not all_versions:
        print("ERROR: Could not load any traces")
        return

    # Identify most common QIDs across versions
    all_qids = set()
    for version, traces in all_versions.items():
        for uid in traces.keys():
            qid = extract_qid(uid)
            if qid:
                all_qids.add(qid)

    print(f"\n\n{'='*100}")
    print("EFFICIENCY SIGNATURE")
    print("="*100)

    # Show step distributions
    for version, traces in sorted(all_versions.items(), key=lambda x: x[1][list(x[1].keys())[0]]["step_count"] if x[1] else 0):
        steps = sorted([t["step_count"] for t in traces.values()])
        print(f"\n{version}")
        print(f"  Step distribution: min={min(steps)}, Q1={steps[len(steps)//4]}, median={steps[len(steps)//2]}, Q3={steps[3*len(steps)//4]}, max={max(steps)}")

        # Count by step range
        lean = sum(1 for s in steps if s <= 5)
        moderate = sum(1 for s in steps if 6 <= s <= 15)
        thorough = sum(1 for s in steps if s > 15)
        print(f"  Lean (<=5): {lean}, Moderate (6-15): {moderate}, Thorough (>15): {thorough}")

    print(f"\n\n{'='*100}")
    print("PATTERN ANALYSIS - STEP STRATEGIES")
    print("="*100)

    # Compare top 2 versions
    top_2 = sorted(all_versions.items(),
                   key=lambda x: version_scores.get(x[0], 0) or 0,
                   reverse=True)[:2]

    if len(top_2) >= 2:
        v1_name, v1_traces = top_2[0]
        v2_name, v2_traces = top_2[1]

        print(f"\nTop 2: {v1_name} (score {version_scores.get(v1_name, 'N/A')}) vs {v2_name} (score {version_scores.get(v2_name, 'N/A')})")

        # Average steps per version
        v1_avg = sum(t["step_count"] for t in v1_traces.values()) / len(v1_traces)
        v2_avg = sum(t["step_count"] for t in v2_traces.values()) / len(v2_traces)

        print(f"  {v1_name}: {v1_avg:.1f} avg steps")
        print(f"  {v2_name}: {v2_avg:.1f} avg steps")

        if v1_avg < v2_avg:
            print(f"  => {v1_name} is more efficient (lean)")
        elif v1_avg > v2_avg:
            print(f"  => {v2_name} is more efficient (lean)")
        else:
            print(f"  => Similar efficiency")

    # Show top scorers by efficiency
    print("\n\nVersions ranked by efficiency (avg steps):")
    version_efficiency = []
    for version, traces in all_versions.items():
        steps = [t["step_count"] for t in traces.values()]
        avg = sum(steps) / len(steps)
        version_efficiency.append((version, avg, version_scores.get(version, 0)))

    for version, avg_steps, score in sorted(version_efficiency, key=lambda x: x[1]):
        print(f"  {version:25s} - {avg_steps:5.1f} avg steps, score {score}")

    print(f"\n\n{'='*100}")
    print("KEY INSIGHTS")
    print("="*100)

    # Identify leanest high-scorer
    lean = min(version_efficiency, key=lambda x: x[1])
    print(f"\nLeanest: {lean[0]} ({lean[1]:.1f} steps, score {lean[2]})")

    # Identify thorough high-scorer with score
    thorough_with_score = [v for v in version_efficiency if v[2] is not None]
    if thorough_with_score:
        thorough = max(thorough_with_score, key=lambda x: x[1])
        print(f"Thorough (w/score): {thorough[0]} ({thorough[1]:.1f} steps, score {thorough[2]})")

        # Show the tradeoff
        print(f"\nTradeoff analysis:")
        print(f"  Lean approach uses {thorough[1]/lean[1]:.1f}x fewer steps")
        print(f"  Scores {lean[2]} vs {thorough[2]} (diff: {lean[2] - thorough[2]:+.1f})")
    else:
        print(f"Thorough: {thorough[0]} ({thorough[1]:.1f} steps, score {thorough[2]})")

    # Recommend strategy
    print(f"\n{'='*100}")
    print("RECOMMENDATION")
    print("="*100)

    top_scorer = sorted([v for v in version_efficiency if v[2] is not None], key=lambda x: x[2], reverse=True)[0]
    leanest_top = min([v for v in version_efficiency if v[2] is not None and v[2] >= 178], key=lambda x: x[1])

    print(f"\nBest for accuracy: {top_scorer[0]} (score {top_scorer[2]})")
    print(f"Best for efficiency: {leanest_top[0]} ({leanest_top[1]:.1f} steps, score {leanest_top[2]})")

    print(f"\nNext design should:")
    print(f"  1. Use {top_scorer[0]}'s approach as base (highest accuracy)")
    print(f"  2. Incorporate {leanest_top[0]}'s efficiency tricks ({leanest_top[1]/top_scorer[1]:.1f}x fewer steps)")
    print(f"  3. Target: same {top_scorer[2]} score with {leanest_top[1]:.1f} steps instead of {top_scorer[1]:.1f}")

if __name__ == "__main__":
    main()
