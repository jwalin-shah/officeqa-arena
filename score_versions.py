#!/usr/bin/env python3
"""
Score all versions correctly using the official reward.py logic.
"""

import json
import csv
from pathlib import Path
from collections import defaultdict

# Import the grading logic
import sys
sys.path.insert(0, '/Users/jwalinshah/projects/officeqa-arena/.arena/samples/officeqa-uid0004/tests')
from reward import score_answer

def load_gold_answers():
    """Load gold answers from CSV."""
    answers = {}
    with open('/Users/jwalinshah/projects/officeqa-arena/data/officeqa_full.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            uid = row['uid']
            answers[uid] = row['answer']
    return answers

def get_trace_answer(trace_path):
    """Extract the final answer from a trace JSON."""
    try:
        with open(trace_path, 'r') as f:
            trace = json.load(f)

        # Navigate through trace structure to find final answer
        trajectory = trace.get('trajectory', trace)

        # Check in steps - look for the last step's message
        if 'steps' in trajectory:
            steps = trajectory['steps']
            if steps:
                # Get the last step's message
                last_step = steps[-1]
                if 'message' in last_step:
                    return last_step['message']

        # Check in turns
        if 'turns' in trace:
            turns = trace['turns']
            if turns:
                last_turn = turns[-1]
                if isinstance(last_turn, dict):
                    if 'message' in last_turn:
                        return last_turn['message']
                    if 'output' in last_turn:
                        return last_turn['output']

        return None
    except Exception as e:
        return None

def score_version(version_name, traces_dir):
    """Score a single version."""
    version_path = Path(traces_dir) / version_name
    if not version_path.exists():
        return None

    gold_answers = load_gold_answers()
    scores = []
    results = defaultdict(list)  # Track individual question results

    # Find all uid*.json files
    trace_files = sorted(version_path.glob('officeqa-uid*.json'))

    if not trace_files:
        return None

    for trace_file in trace_files:
        uid_lower = trace_file.stem.replace('officeqa-', '')  # e.g., 'uid0001'
        uid_upper = uid_lower.upper()  # e.g., 'UID0001'

        if uid_upper not in gold_answers:
            continue

        gold = gold_answers[uid_upper]
        predicted = get_trace_answer(trace_file)

        if predicted is None:
            results['no_answer'].append(uid_upper)
            scores.append(0.0)
        else:
            try:
                score = score_answer(gold, predicted, tolerance=0.01)
                scores.append(score)
                if score == 1.0:
                    results['correct'].append(uid_upper)
                else:
                    results['wrong'].append((uid_upper, gold, predicted))
            except Exception as e:
                results['error'].append((uid_upper, str(e)))
                scores.append(0.0)

    if not scores:
        return None

    total_score = sum(scores)
    percentage = (total_score / len(scores) * 100) if scores else 0

    return {
        'version': version_name,
        'score': total_score,
        'percentage': percentage,
        'total_questions': len(scores),
        'correct': len(results['correct']),
        'wrong': len(results['wrong']),
        'no_answer': len(results['no_answer']),
        'errors': len(results['error']),
        'details': results
    }

def main():
    traces_dir = Path('/Users/jwalinshah/projects/officeqa-arena/traces')

    # List of versions to score
    versions = [
        'v8_155',
        'v9_158',
        'v10_163',
        'v12_171',
        'v13_150',
        'v13',
        'v20_best',
    ]

    results = []
    for version in versions:
        print(f"Scoring {version}...", end=' ', flush=True)
        result = score_version(version, traces_dir)
        if result:
            results.append(result)
            print(f"✓ {result['percentage']:.1f}% ({result['score']}/{result['total_questions']})")
        else:
            print("✗ No traces found")

    # Sort by percentage descending
    results.sort(key=lambda x: x['percentage'], reverse=True)

    print("\n" + "="*80)
    print(f"{'Version':<20} {'Score':<20} {'Correct':<12} {'Wrong':<12} {'No Answer':<12}")
    print("="*80)
    for r in results:
        print(f"{r['version']:<20} {r['percentage']:>6.1f}% ({r['score']:>3.0f}/{r['total_questions']:<3.0f})")
        print(f"{'':20} Correct: {r['correct']:<3}   Wrong: {r['wrong']:<3}   No Answer: {r['no_answer']:<3}   Errors: {r['errors']}")
        if r['errors'] > 0:
            print(f"  Sample error: {r['details']['error'][0] if r['details']['error'] else 'N/A'}")
        print()

    # Print summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    for r in results:
        print(f"{r['version']:20s}: {r['percentage']:6.1f}%")

if __name__ == '__main__':
    main()
