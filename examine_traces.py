#!/usr/bin/env python3
"""Examine all local traces comprehensively"""
import json
from pathlib import Path
from collections import defaultdict

def analyze_traces():
    traces_dir = Path("traces_comprehensive")

    stats = {
        "total_dirs": 0,
        "total_traces": 0,
        "by_dir": {},
        "pass_fail": defaultdict(lambda: {"pass": 0, "fail": 0, "unknown": 0}),
        "reward_stats": defaultdict(lambda: {"sum": 0, "count": 0, "min": float('inf'), "max": float('-inf')}),
        "latency_stats": defaultdict(lambda: {"sum": 0, "count": 0}),
    }

    for trace_dir in sorted(traces_dir.iterdir()):
        if not trace_dir.is_dir() or trace_dir.name.startswith('.'):
            continue

        stats["total_dirs"] += 1
        trace_files = list(trace_dir.glob("*.json"))
        stats["total_traces"] += len(trace_files)
        stats["by_dir"][trace_dir.name] = len(trace_files)

        # Analyze traces in this directory
        for trace_file in trace_files:
            try:
                with open(trace_file) as f:
                    trace = json.load(f)

                # Try to extract status and reward
                status = "unknown"
                reward = None
                latency = None

                if isinstance(trace, dict):
                    # Check common fields
                    if "status" in trace:
                        status = trace["status"].upper() if trace["status"] else "unknown"
                    if "reward" in trace:
                        try:
                            reward = float(trace["reward"])
                        except (ValueError, TypeError):
                            pass
                    if "latency" in trace:
                        try:
                            latency = float(trace["latency"])
                        except (ValueError, TypeError):
                            pass

                stats["pass_fail"][trace_dir.name][status if status in ["PASS", "FAIL"] else "unknown"] += 1

                if reward is not None:
                    stats["reward_stats"][trace_dir.name]["sum"] += reward
                    stats["reward_stats"][trace_dir.name]["count"] += 1
                    stats["reward_stats"][trace_dir.name]["min"] = min(stats["reward_stats"][trace_dir.name]["min"], reward)
                    stats["reward_stats"][trace_dir.name]["max"] = max(stats["reward_stats"][trace_dir.name]["max"], reward)

                if latency is not None:
                    stats["latency_stats"][trace_dir.name]["sum"] += latency
                    stats["latency_stats"][trace_dir.name]["count"] += 1

            except Exception as e:
                pass

    return stats

def print_stats(stats):
    print(f"\n{'='*80}")
    print(f"TRACE ANALYSIS - Total: {stats['total_traces']} traces across {stats['total_dirs']} collections")
    print('='*80)

    print(f"\n{'Collection':<30} {'Traces':>8} {'Pass':>8} {'Fail':>8} {'Avg Reward':>12} {'Avg Latency':>14}")
    print('-'*82)

    total_pass = 0
    total_fail = 0

    for dir_name in sorted(stats["by_dir"].keys(), key=lambda x: stats["by_dir"][x], reverse=True):
        count = stats["by_dir"][dir_name]
        pf = stats["pass_fail"][dir_name]
        rs = stats["reward_stats"][dir_name]
        ls = stats["latency_stats"][dir_name]

        pass_count = pf.get("PASS", 0)
        fail_count = pf.get("FAIL", 0)
        total_pass += pass_count
        total_fail += fail_count

        avg_reward = rs["sum"] / rs["count"] if rs["count"] > 0 else 0
        avg_latency = ls["sum"] / ls["count"] if ls["count"] > 0 else 0

        print(f"{dir_name:<30} {count:>8} {pass_count:>8} {fail_count:>8} {avg_reward:>12.2f} {avg_latency:>14.1f}s")

    print('-'*82)
    print(f"{'TOTAL':<30} {stats['total_traces']:>8} {total_pass:>8} {total_fail:>8}")

    # Calculate pass rate
    total = total_pass + total_fail
    if total > 0:
        pass_rate = (total_pass / total) * 100
        print(f"\nOverall Pass Rate: {pass_rate:.1f}% ({total_pass}/{total})")

    print(f"\n{'='*80}")

if __name__ == "__main__":
    stats = analyze_traces()
    print_stats(stats)
