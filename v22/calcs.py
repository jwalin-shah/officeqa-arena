"""
Pre-built calculation functions for Treasury data analysis.
Use these to ensure correct formula application.
"""

import statistics
import math

def pct_change(old, new):
    """Calculate percentage change: ((new - old) / old) * 100"""
    if old == 0:
        return None
    return ((new - old) / old) * 100

def pct_change_rounded(old, new, decimals=2):
    """Percentage change rounded to specified decimals."""
    result = pct_change(old, new)
    if result is None:
        return None
    return round(result, decimals)

def cagr(start, end, years):
    """
    Compound Annual Growth Rate: (end/start)^(1/n) - 1
    Returns as decimal (e.g., 0.05 for 5%), multiply by 100 for percentage.
    """
    if start <= 0 or years <= 0:
        return None
    return (end / start) ** (1 / years) - 1

def geometric_mean(values):
    """Calculate geometric mean of values."""
    if not values or any(v <= 0 for v in values):
        return None
    return statistics.geometric_mean(values)

def arithmetic_mean(values):
    """Calculate arithmetic mean (average) of values."""
    if not values:
        return None
    return statistics.mean(values)

def stdev_sample(values):
    """Sample standard deviation."""
    if not values or len(values) < 2:
        return None
    return statistics.stdev(values)

def stdev_population(values):
    """Population standard deviation."""
    if not values:
        return None
    return statistics.pstdev(values)

def median(values):
    """Calculate median value."""
    if not values:
        return None
    return statistics.median(values)

def range_val(values):
    """Calculate range: max - min."""
    if not values:
        return None
    return max(values) - min(values)

def sum_values(values):
    """Sum of values (simple wrapper for clarity)."""
    if not values:
        return 0
    return sum(values)

def kullback_leibler_divergence(p, q):
    """
    Kullback-Leibler divergence: sum(p_i * log(p_i / q_i))
    p and q should be probability distributions (sum to 1).
    """
    if not p or not q or len(p) != len(q):
        return None

    kl = 0
    for p_i, q_i in zip(p, q):
        if p_i > 0 and q_i > 0:
            kl += p_i * math.log(p_i / q_i)
    return kl

def print_calc(operation, values, result):
    """Helper to print calculation steps for verification."""
    print(f"{operation}: {values}")
    print(f"Result: {result}")
    print()

if __name__ == '__main__':
    # Test examples
    print("Testing calculations:")

    # Percentage change
    print(f"pct_change(100, 150): {pct_change(100, 150)}")  # 50
    print(f"pct_change(150, 100): {pct_change(150, 100)}")  # -33.33

    # Geometric mean
    print(f"geometric_mean([1, 2, 4, 8]): {geometric_mean([1, 2, 4, 8])}")  # 2.828...

    # Range
    print(f"range_val([10, 20, 15, 5]): {range_val([10, 20, 15, 5])}")  # 15
