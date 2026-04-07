"""
Tools for Treasury data analysis.
These provide structured calculation and verification capabilities.
"""

import json
import subprocess
import sys
from pathlib import Path

# Add calcs module
sys.path.insert(0, str(Path(__file__).parent))
import calcs

def run_command(cmd):
    """Execute a shell command and return output."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return "", "Command timeout"
    except Exception as e:
        return "", str(e)

def identify_metric(question):
    """
    Identify what type of metric the question is asking for.

    Returns: One of [sum, mean, median, pct_change, cagr, stdev, geom_mean, range, other]
    """
    question_lower = question.lower()

    # Check for specific metrics
    if any(word in question_lower for word in ['sum', 'total', 'all']):
        return 'sum'
    elif any(word in question_lower for word in ['average', 'mean', 'avg']):
        return 'mean'
    elif 'geometric mean' in question_lower:
        return 'geom_mean'
    elif any(word in question_lower for word in ['percent change', 'percentage change']):
        return 'pct_change'
    elif 'cagr' in question_lower or 'compound annual growth' in question_lower:
        return 'cagr'
    elif any(word in question_lower for word in ['standard deviation', 'stdev']):
        return 'stdev'
    elif 'median' in question_lower:
        return 'median'
    elif 'range' in question_lower and ('maximum' in question_lower or 'minimum' in question_lower):
        return 'range'
    else:
        return 'other'

def identify_time_period(question):
    """
    Extract time period from question.
    Returns: Dict with year(s), calendar vs fiscal, months if specified.
    """
    import re

    period = {
        'years': [],
        'type': 'calendar',  # or 'fiscal'
        'months': None,
    }

    # Find years (1900-2100)
    years = re.findall(r'\b(19\d{2}|20\d{2})\b', question)
    if years:
        period['years'] = [int(y) for y in years]

    # Check fiscal vs calendar
    if 'fiscal' in question.lower() or 'fy' in question.lower():
        period['type'] = 'fiscal'
    elif 'calendar' in question.lower() or 'cy' in question.lower():
        period['type'] = 'calendar'

    # Check for specific months
    month_names = ['january', 'february', 'march', 'april', 'may', 'june',
                   'july', 'august', 'september', 'october', 'november', 'december']
    months = [m for m in month_names if m in question.lower()]
    if months:
        period['months'] = months

    return period

def calculate(metric, values):
    """
    Perform calculation based on identified metric.

    Args:
        metric: Type of calculation (sum, mean, pct_change, etc.)
        values: List of numeric values, or dict for complex metrics

    Returns: Calculated result or error message
    """
    try:
        if metric == 'sum':
            result = calcs.sum_values(values)
        elif metric == 'mean' or metric == 'average':
            result = calcs.arithmetic_mean(values)
        elif metric == 'geom_mean':
            result = calcs.geometric_mean(values)
        elif metric == 'median':
            result = calcs.median(values)
        elif metric == 'stdev':
            result = calcs.stdev_sample(values)
        elif metric == 'pct_change':
            # Expects dict with 'old' and 'new' keys
            if isinstance(values, dict) and 'old' in values and 'new' in values:
                result = calcs.pct_change(values['old'], values['new'])
            else:
                result = None
        elif metric == 'cagr':
            # Expects dict with 'start', 'end', 'years' keys
            if isinstance(values, dict):
                result = calcs.cagr(values.get('start'), values.get('end'), values.get('years'))
            else:
                result = None
        elif metric == 'range':
            result = calcs.range_val(values)
        else:
            result = None

        return result
    except Exception as e:
        return f"Error: {str(e)}"

def extract_numbers(text):
    """
    Extract all numeric values from text.
    Returns: List of floats/ints found in text.
    """
    import re

    # Find numbers (including decimals and negatives)
    pattern = r'-?\d+\.?\d*'
    matches = re.findall(pattern, text)

    try:
        numbers = [float(m) for m in matches if m and m != '.']
        return numbers
    except:
        return []

def search_and_extract(search_pattern, directory='/app/resources'):
    """
    Search for files matching pattern and extract numbers.

    Args:
        search_pattern: Grep pattern to search for
        directory: Where to search (default: /app/resources)

    Returns: Dict with matches and extracted numbers
    """
    cmd = f"grep -r '{search_pattern}' {directory} 2>/dev/null | head -20"
    stdout, stderr = run_command(cmd)

    if not stdout:
        return {
            'found': False,
            'matches': [],
            'numbers': []
        }

    lines = stdout.split('\n')
    numbers = []
    for line in lines:
        numbers.extend(extract_numbers(line))

    return {
        'found': True,
        'matches': lines,
        'numbers': list(set(numbers))  # Unique numbers
    }

def verify_answer(question, answer):
    """
    Basic sanity check on answer.

    Returns: Dict with is_reasonable, concerns, suggestions
    """
    concerns = []

    # Check if answer is a number
    try:
        answer_num = float(answer)
    except:
        return {
            'is_reasonable': False,
            'concerns': ['Answer is not numeric'],
            'suggestions': ['Ensure you extract just the number, no units']
        }

    # Check if answer is in reasonable range
    if answer_num < 0 and 'negative' not in question.lower():
        concerns.append('Answer is negative but question suggests positive')

    if answer_num > 1e15:
        concerns.append('Answer seems very large (>1 quadrillion)')

    # Check for common mistakes
    if answer_num > 1000000 and 'million' in question.lower():
        concerns.append('Answer might be in wrong unit (very large for millions)')

    return {
        'is_reasonable': len(concerns) == 0,
        'concerns': concerns,
        'suggestions': ['Double-check the calculation', 'Verify units match question']
    }

def write_answer(answer, output_file='/app/answer.txt'):
    """Write answer to output file."""
    try:
        with open(output_file, 'w') as f:
            f.write(str(answer))
        return True
    except Exception as e:
        return False

# Example usage
if __name__ == '__main__':
    # Test metric identification
    q1 = "What was the total expenditures for defense in 1940?"
    q2 = "What is the percentage change from 1940 to 1950?"

    print(f"Q1 metric: {identify_metric(q1)}")  # sum
    print(f"Q2 metric: {identify_metric(q2)}")  # pct_change

    # Test calculation
    print(f"Calculate sum([1,2,3,4,5]): {calculate('sum', [1,2,3,4,5])}")  # 15
    print(f"Calculate mean([1,2,3,4,5]): {calculate('mean', [1,2,3,4,5])}")  # 3
