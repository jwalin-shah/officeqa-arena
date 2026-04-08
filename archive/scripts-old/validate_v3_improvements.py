#!/usr/bin/env python3
"""
Compare V3 results against V1 to measure improvement on known issues.
"""

import json
import csv

def load_questions():
    questions = {}
    with open('data/officeqa_full.csv', 'r') as f:
        for i, row in enumerate(csv.DictReader(f)):
            questions[i] = row
    return questions

def load_results(filename):
    with open(filename, 'r') as f:
        return json.load(f)

def check_cy_annual_total_mismatch(result, question_text):
    """
    Issue 1: CY Annual Total Mismatch
    If calendar year + "total" → should use monthly_series, not annual_total
    """
    if 'result' not in result:
        return None

    r = result['result']
    q_lower = question_text.lower()

    # Is this a calendar year question asking for total?
    is_calendar = r.get('period_type') == 'calendar'
    asks_for_total = any(word in q_lower for word in ['total', 'sum', 'combined'])

    if is_calendar and asks_for_total:
        # Should use monthly_series
        correct = r.get('value_format') == 'monthly_series'
        return correct
    return None

def check_sum_total_computation(result, question_text):
    """
    Issue 2: Sum/Total Computation Error
    If "total" or "sum" in question → computation should be "sum", not "direct"
    """
    if 'result' not in result:
        return None

    r = result['result']
    q_lower = question_text.lower()

    # Does question ask for total/sum?
    asks_for_total = any(word in q_lower for word in ['total', 'sum', 'combined', 'aggregate'])

    if asks_for_total:
        # Should use "sum" computation
        computation = r.get('computation', '').lower()
        # Some questions ask for total but need special handling (e.g., max of totals)
        # For now, check if it's using sum
        correct = 'sum' in computation or computation in ['max', 'min']
        return correct
    return None

def check_regression_detection(result, question_text):
    """
    Issue 3: Regression Mismatch
    If "regression", "fit", "slope", "intercept" → computation should be "linear_regression"
    """
    if 'result' not in result:
        return None

    r = result['result']
    q_lower = question_text.lower()

    # Does question ask for regression?
    asks_for_regression = any(word in q_lower for word in [
        'regression', 'fit', 'slope', 'intercept', 'ols', 'linear model', 'forecast', 'predict'
    ])

    if asks_for_regression:
        computation = r.get('computation', '').lower()
        correct = 'regression' in computation or 'linear' in computation
        return correct
    return None

def check_period_type_clarity(result, question_text):
    """
    Issue 4: Period Type Tagging Error
    FY vs Calendar should be clear and correct
    """
    if 'result' not in result:
        return None

    r = result['result']
    q_lower = question_text.lower()
    period_type = r.get('period_type', '')

    # If explicitly says FY → must be fiscal
    if 'fy' in q_lower or 'fiscal year' in q_lower:
        return period_type == 'fiscal'

    # If explicitly says CY or calendar → must be calendar
    if 'calendar year' in q_lower or ' cy ' in q_lower:
        return period_type == 'calendar'

    # Otherwise, just check it's not empty
    return period_type in ['fiscal', 'calendar']

def analyze_results(v1_results, v3_results, questions):
    """Compare v1 vs v3 on all metrics"""

    metrics = {
        'cy_annual_total': {'v1': [], 'v3': []},
        'sum_total': {'v1': [], 'v3': []},
        'regression': {'v1': [], 'v3': []},
        'period_type': {'v1': [], 'v3': []},
        'has_computation': {'v1': [], 'v3': []},
    }

    for idx in range(len(v1_results)):
        q_text = questions[idx]['question']

        # Check each metric for v1
        cy_result = check_cy_annual_total_mismatch(v1_results[idx], q_text)
        if cy_result is not None:
            metrics['cy_annual_total']['v1'].append(cy_result)

        sum_result = check_sum_total_computation(v1_results[idx], q_text)
        if sum_result is not None:
            metrics['sum_total']['v1'].append(sum_result)

        reg_result = check_regression_detection(v1_results[idx], q_text)
        if reg_result is not None:
            metrics['regression']['v1'].append(reg_result)

        period_result = check_period_type_clarity(v1_results[idx], q_text)
        if period_result is not None:
            metrics['period_type']['v1'].append(period_result)

        has_comp = 'result' in v1_results[idx] and v1_results[idx]['result'].get('computation') is not None
        metrics['has_computation']['v1'].append(has_comp)

        # Check each metric for v3
        cy_result = check_cy_annual_total_mismatch(v3_results[idx], q_text)
        if cy_result is not None:
            metrics['cy_annual_total']['v3'].append(cy_result)

        sum_result = check_sum_total_computation(v3_results[idx], q_text)
        if sum_result is not None:
            metrics['sum_total']['v3'].append(sum_result)

        reg_result = check_regression_detection(v3_results[idx], q_text)
        if reg_result is not None:
            metrics['regression']['v3'].append(reg_result)

        period_result = check_period_type_clarity(v3_results[idx], q_text)
        if period_result is not None:
            metrics['period_type']['v3'].append(period_result)

        has_comp = 'result' in v3_results[idx] and v3_results[idx]['result'].get('computation') is not None
        metrics['has_computation']['v3'].append(has_comp)

    return metrics

def print_comparison(metrics):
    """Print formatted comparison"""
    print("\n" + "="*80)
    print("V3 IMPROVEMENT ANALYSIS")
    print("="*80)

    for metric_name, data in metrics.items():
        v1_results = data['v1']
        v3_results = data['v3']

        if not v1_results:
            continue

        v1_correct = sum(v1_results)
        v1_pct = 100 * v1_correct / len(v1_results)

        v3_correct = sum(v3_results)
        v3_pct = 100 * v3_correct / len(v3_results)

        improvement = v3_pct - v1_pct

        print(f"\n{metric_name.upper().replace('_', ' ')}")
        print(f"  Sample size: {len(v1_results)} questions")
        print(f"  V1: {v1_correct:3d}/{len(v1_results)} ({v1_pct:5.1f}%)")
        print(f"  V3: {v3_correct:3d}/{len(v3_results)} ({v3_pct:5.1f}%)")
        print(f"  Δ:  {improvement:+5.1f} percentage points")

        if improvement > 5:
            print(f"  ✓ SIGNIFICANT IMPROVEMENT")
        elif improvement > 0:
            print(f"  → Improved slightly")
        elif improvement == 0:
            print(f"  = No change")
        else:
            print(f"  ✗ REGRESSION ({improvement:.1f}pp)")

def main():
    print("Loading results...", flush=True)

    questions = load_questions()
    v1 = load_results('decomposition_results.json')
    v3 = load_results('decomposition_results_v3.json')

    print(f"V1 questions: {len(v1)}")
    print(f"V3 questions: {len(v3)}")

    metrics = analyze_results(v1, v3, questions)
    print_comparison(metrics)

    # Overall stats
    print("\n" + "="*80)
    print("OVERALL STATS")
    print("="*80)

    v1_success = sum(1 for r in v1 if 'result' in r)
    v3_success = sum(1 for r in v3 if 'result' in r)

    print(f"V1: {v1_success}/246 successful decompositions")
    print(f"V3: {v3_success}/246 successful decompositions")

if __name__ == "__main__":
    main()
