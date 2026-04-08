#!/usr/bin/env python3
"""
Analyze top 10 versions to find patterns, strengths, and complementarity.
"""
import json
import os
from pathlib import Path
from collections import defaultdict
import sys

BASE_DIR = Path("/Users/jwalinshah/projects/officeqa-arena/traces_comprehensive")

# Top versions by score (name -> estimated score from dirname)
TOP_VERSIONS = {
    "v20_183.8": 183.8,
    "v20-1d-183.8": 183.8,
    "best_184": 184,
    "v21-6h-181.4": 181.4,
    "v21-9h-181.3": 181.3,
    "v21-13h-178.8": 178.8,
    "v15-23h": None,  # need to extract
    "v15-oh-21h": None,
}

def load_traces(version_dir):
    """Load all traces from a version directory."""
    traces = {}
    trace_dir = version_dir
    if not trace_dir.exists():
        return traces

    for trace_file in sorted(trace_dir.glob("*.json")):
        try:
            with open(trace_file) as f:
                trace = json.load(f)
                uid = trace.get("uid")
                if uid:
                    traces[uid] = trace
        except:
            pass
    return traces

def extract_question_id(uid):
    """Extract question number from UID."""
    if uid and len(uid) > 10:
        # Format like UID0001, UID0042, etc.
        try:
            return int(uid[3:7])  # UID0001 -> 1
        except:
            pass
    return None

def check_answer(trace):
    """Extract answer from trace."""
    if "steps" in trace:
        for step in reversed(trace["steps"]):
            if "observation" in step and step["observation"]:
                return step["observation"]
    return None

def get_step_count(trace):
    """Get number of steps taken."""
    return len(trace.get("steps", []))

def analyze_version(version_name):
    """Analyze a single version."""
    version_dir = BASE_DIR / version_name
    if not version_dir.exists():
        return None

    traces = load_traces(version_dir)
    if not traces:
        return None

    # Calculate stats
    total = len(traces)

    # Determine passes (need to compare with gold answers)
    passes = 0
    step_counts = []
    answers_by_qid = {}

    for uid, trace in traces.items():
        qid = extract_question_id(uid)
        answer = check_answer(trace)
        step_count = get_step_count(trace)

        step_counts.append(step_count)

        if qid not in answers_by_qid:
            answers_by_qid[qid] = []
        answers_by_qid[qid].append((uid, answer, step_count))

    # Estimate pass rate (we'll refine with gold answers later)
    avg_steps = sum(step_counts) / len(step_counts) if step_counts else 0
    max_steps = max(step_counts) if step_counts else 0
    min_steps = min(step_counts) if step_counts else 0

    return {
        "name": version_name,
        "total_questions": total,
        "avg_steps": round(avg_steps, 1),
        "max_steps": max_steps,
        "min_steps": min_steps,
        "traces": traces,
        "answers_by_qid": answers_by_qid,
    }

def load_gold_answers():
    """Load gold answers from officeqa_full.csv."""
    gold = {}
    csv_path = Path("/Users/jwalinshah/projects/officeqa-arena")
    for csv_file in csv_path.glob("**/officeqa_full.csv"):
        try:
            with open(csv_file) as f:
                for line in f:
                    parts = line.strip().split(",", 1)
                    if len(parts) == 2:
                        qid, answer = parts
                        try:
                            gold[int(qid)] = answer.strip('"')
                        except:
                            pass
        except:
            pass
    return gold

def numeric_similarity(v1, v2, tolerance=0.01):
    """Check if two values are numerically similar."""
    try:
        f1 = float(v1)
        f2 = float(v2)
        return abs(f1 - f2) <= max(abs(f1), abs(f2)) * tolerance
    except:
        return False

def check_answer_correct(v1, v2):
    """Check if answer matches gold (loose numeric tolerance)."""
    if not v1 or not v2:
        return False

    v1_str = str(v1).strip().lower()
    v2_str = str(v2).strip().lower()

    # Exact match
    if v1_str == v2_str:
        return True

    # Numeric similarity
    if numeric_similarity(v1_str, v2_str, tolerance=0.01):
        return True

    return False

def main():
    print("=" * 80)
    print("TOP VERSIONS ANALYSIS")
    print("=" * 80)

    # Load all versions
    versions = {}
    for version_name in sorted(TOP_VERSIONS.keys()):
        result = analyze_version(version_name)
        if result:
            versions[version_name] = result
            score = TOP_VERSIONS.get(version_name)
            print(f"\n{version_name} (score ~{score})")
            print(f"  Questions: {result['total_questions']}")
            print(f"  Avg steps: {result['avg_steps']} (min={result['min_steps']}, max={result['max_steps']})")

    # Load gold answers
    gold = load_gold_answers()
    print(f"\nLoaded {len(gold)} gold answers")

    if not gold:
        print("WARNING: Could not load gold answers, using step count as proxy")
        # Analyze without gold
        print("\n" + "=" * 80)
        print("EFFICIENCY ANALYSIS (step count as proxy)")
        print("=" * 80)

        for version_name, data in sorted(versions.items()):
            print(f"\n{version_name}:")
            print(f"  Avg steps: {data['avg_steps']}")
            print(f"  Total questions: {data['total_questions']}")

        # Show specialization candidates
        print("\n" + "=" * 80)
        print("COMPLEMENTARITY ANALYSIS")
        print("=" * 80)

        # Compare step patterns
        if len(versions) >= 2:
            version_list = sorted(versions.items(), key=lambda x: x[1]['avg_steps'])

            print("\nBy efficiency (step count):")
            for i, (name, data) in enumerate(version_list, 1):
                print(f"  {i}. {name}: {data['avg_steps']} avg steps")

            print("\nKey insight: Lean vs. thorough")
            lean = version_list[0]
            thorough = version_list[-1]
            print(f"  Leanest: {lean[0]} ({lean[1]['avg_steps']} steps)")
            print(f"  Thorough: {thorough[0]} ({thorough[1]['avg_steps']} steps)")
    else:
        # Detailed analysis with gold answers
        print("\n" + "=" * 80)
        print("ACCURACY ANALYSIS")
        print("=" * 80)

        version_stats = {}

        for version_name, data in versions.items():
            correct = 0
            wrong = 0
            no_answer = 0

            for uid, trace in data['traces'].items():
                qid = extract_question_id(uid)
                if qid and qid in gold:
                    answer = check_answer(trace)
                    if answer:
                        if check_answer_correct(answer, gold[qid]):
                            correct += 1
                        else:
                            wrong += 1
                    else:
                        no_answer += 1

            total = correct + wrong + no_answer
            if total > 0:
                pass_rate = 100 * correct / total
                version_stats[version_name] = {
                    "correct": correct,
                    "wrong": wrong,
                    "no_answer": no_answer,
                    "total": total,
                    "pass_rate": pass_rate,
                    "avg_steps": data['avg_steps'],
                }

        # Print results sorted by pass rate
        print("\nResults by accuracy:")
        for version_name, stats in sorted(version_stats.items(), key=lambda x: x[1]['pass_rate'], reverse=True):
            print(f"\n{version_name}:")
            print(f"  Pass rate: {stats['pass_rate']:.1f}% ({stats['correct']}/{stats['total']})")
            print(f"  Correct: {stats['correct']}, Wrong: {stats['wrong']}, No answer: {stats['no_answer']}")
            print(f"  Avg steps: {stats['avg_steps']}")

        # Specialization analysis
        print("\n" + "=" * 80)
        print("SPECIALIZATION ANALYSIS")
        print("=" * 80)

        # Find questions where versions differ
        all_qids = set()
        version_answers = {}

        for version_name, data in versions.items():
            version_answers[version_name] = {}
            for uid, trace in data['traces'].items():
                qid = extract_question_id(uid)
                if qid:
                    all_qids.add(qid)
                    answer = check_answer(trace)
                    step_count = get_step_count(trace)
                    version_answers[version_name][qid] = {
                        "answer": answer,
                        "steps": step_count,
                        "correct": check_answer_correct(answer, gold.get(qid, "")) if qid in gold else None,
                    }

        # Find complementary strengths
        top_versions_sorted = sorted(
            [(v, version_stats[v]['pass_rate']) for v in version_stats],
            key=lambda x: x[1],
            reverse=True
        )[:3]

        if len(top_versions_sorted) >= 2:
            print(f"\nTop 3 versions by accuracy:")
            for name, pass_rate in top_versions_sorted:
                print(f"  {name}: {pass_rate:.1f}%")

            # Find where top 2 differ
            v1_name, _ = top_versions_sorted[0]
            v2_name, _ = top_versions_sorted[1]

            v1_only_correct = []
            v2_only_correct = []
            both_correct = []
            both_wrong = []

            for qid in all_qids:
                if qid in gold:
                    v1_correct = version_answers.get(v1_name, {}).get(qid, {}).get("correct", False)
                    v2_correct = version_answers.get(v2_name, {}).get(qid, {}).get("correct", False)

                    if v1_correct and not v2_correct:
                        v1_only_correct.append((qid, version_answers[v1_name][qid]['steps']))
                    elif v2_correct and not v1_correct:
                        v2_only_correct.append((qid, version_answers[v2_name][qid]['steps']))
                    elif v1_correct and v2_correct:
                        both_correct.append(qid)
                    else:
                        both_wrong.append(qid)

            print(f"\nComparison: {v1_name} vs {v2_name}")
            print(f"  Both correct: {len(both_correct)}")
            print(f"  {v1_name} only: {len(v1_only_correct)} (using {[s for _, s in v1_only_correct]} steps)")
            print(f"  {v2_name} only: {len(v2_only_correct)} (using {[s for _, s in v2_only_correct]} steps)")
            print(f"  Both wrong: {len(both_wrong)}")

            if v1_only_correct:
                print(f"\n  Sample {v1_name} exclusive wins: {[q for q, _ in v1_only_correct[:3]]}")
            if v2_only_correct:
                print(f"  Sample {v2_name} exclusive wins: {[q for q, _ in v2_only_correct[:3]]}")

if __name__ == "__main__":
    main()
