"""Safe arithmetic evaluator for finance expressions.

Supports: +, -, *, /, **, %, unary +/-, and whitelisted functions
(abs, round, min, max, sum, sqrt, log, ln, exp, geometric_mean, prod,
mean, linreg, boxcox, stdev).
"""

from __future__ import annotations

import ast
import builtins
import math
import statistics


def safe_eval_finance(expression: str, variables: dict[str, float] | None = None) -> float | list[float]:
    """Evaluate a limited arithmetic expression with named variables and numeric literals.

    Raises ``ValueError`` on unsupported syntax or unknown variable names.
    """
    variables = variables or {}

    def _eval_list(node: ast.AST) -> list[float]:
        """Evaluate a node that might be a list, returning a flat list of floats."""
        if isinstance(node, ast.List):
            return [_eval(elt) for elt in node.elts]
        return [_eval(node)]

    def _collect_args(args: list[ast.AST]) -> list[float]:
        """Collect function arguments, unpacking any list literals."""
        result: list[float] = []
        for a in args:
            if isinstance(a, ast.List):
                result.extend(_eval(elt) for elt in a.elts)
            else:
                result.append(_eval(a))
        return result

    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return float(node.value)
            raise ValueError("only_numeric_constants_allowed")
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise ValueError(f"unknown_variable:{node.id}")
            return float(variables[node.id])
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -_eval(node.operand)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd):
            return _eval(node.operand)
        if isinstance(node, ast.BinOp):
            left, right = _eval(node.left), _eval(node.right)
            op = node.op
            if isinstance(op, ast.Add):
                return left + right
            if isinstance(op, ast.Sub):
                return left - right
            if isinstance(op, ast.Mult):
                return left * right
            if isinstance(op, ast.Div):
                if right == 0:
                    raise ValueError("division_by_zero")
                return left / right
            if isinstance(op, ast.Pow):
                return left ** right
            if isinstance(op, ast.Mod):
                return left % right
            if isinstance(op, ast.BitXor):
                # Handle ^ as power (common model mistake)
                return left ** right
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn = node.func.id
            if fn == "abs":
                args = [_eval(a) for a in node.args]
                return float(builtins.abs(*args))
            if fn == "round":
                args = [_eval(a) for a in node.args]
                if len(args) == 2:
                    return float(builtins.round(args[0], int(args[1])))
                return float(builtins.round(args[0]))
            if fn == "min":
                vals = _collect_args(node.args)
                return float(min(vals))
            if fn == "max":
                vals = _collect_args(node.args)
                return float(max(vals))
            if fn == "sqrt" and len(node.args) == 1:
                return math.sqrt(_eval(node.args[0]))
            if fn == "log" and len(node.args) in {1, 2}:
                args = [_eval(a) for a in node.args]
                return math.log(*args)
            if fn == "ln" and len(node.args) == 1:
                return math.log(_eval(node.args[0]))
            if fn == "exp" and len(node.args) == 1:
                return math.exp(_eval(node.args[0]))
            if fn == "sum":
                vals = _collect_args(node.args)
                return float(sum(vals))
            if fn == "pow" and len(node.args) == 2:
                return _eval(node.args[0]) ** _eval(node.args[1])
            if fn == "prod":
                vals = _collect_args(node.args)
                return float(math.prod(vals))
            if fn == "geometric_mean":
                vals = _collect_args(node.args)
                return float(math.prod(vals) ** (1.0 / len(vals)))
            if fn == "mean":
                vals = _collect_args(node.args)
                return float(sum(vals) / len(vals))
            if fn == "stdev":
                vals = _collect_args(node.args)
                if len(vals) < 2:
                    raise ValueError("stdev requires at least 2 values")
                return float(statistics.stdev(vals))
            if fn == "len":
                vals = _collect_args(node.args)
                return float(len(vals))
            if fn == "linreg" and len(node.args) == 2:
                x_vals = _eval_list(node.args[0])
                y_vals = _eval_list(node.args[1])
                n = len(x_vals)
                if n != len(y_vals) or n < 2:
                    raise ValueError("linreg requires two equal-length lists of 2+ values")
                x_mean = sum(x_vals) / n
                y_mean = sum(y_vals) / n
                num = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, y_vals))
                den = sum((x - x_mean) ** 2 for x in x_vals)
                if den == 0:
                    raise ValueError("linreg: all x values are identical")
                slope = num / den
                intercept = y_mean - slope * x_mean
                return [float(slope), float(intercept)]
            if fn == "cagr" and len(node.args) == 3:
                args = [_eval(a) for a in node.args]
                start_val, end_val, n_years = args
                return ((end_val / start_val) ** (1.0 / n_years) - 1) * 100
            if fn == "theil_index":
                vals = _collect_args(node.args)
                n = len(vals)
                m = sum(vals) / n
                return float(sum(v / m * math.log(v / m) for v in vals) / n)
            if fn == "cv":
                vals = _collect_args(node.args)
                m = sum(vals) / len(vals)
                variance = sum((v - m) ** 2 for v in vals) / (len(vals) - 1)
                return float(math.sqrt(variance) / m)
            if fn == "median":
                vals = sorted(_collect_args(node.args))
                n = len(vals)
                if n == 0:
                    raise ValueError("median requires at least 1 value")
                mid = n // 2
                return float(vals[mid]) if n % 2 else float((vals[mid - 1] + vals[mid]) / 2)
            if fn == "variance":
                vals = _collect_args(node.args)
                if len(vals) < 2:
                    raise ValueError("variance requires at least 2 values")
                m = sum(vals) / len(vals)
                return float(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))
            if fn == "correlation" and len(node.args) == 2:
                x_vals = _eval_list(node.args[0])
                y_vals = _eval_list(node.args[1])
                n = len(x_vals)
                if n != len(y_vals) or n < 2:
                    raise ValueError("correlation requires two equal-length lists of 2+ values")
                x_m = sum(x_vals) / n
                y_m = sum(y_vals) / n
                num = sum((x - x_m) * (y - y_m) for x, y in zip(x_vals, y_vals))
                den_x = math.sqrt(sum((x - x_m) ** 2 for x in x_vals))
                den_y = math.sqrt(sum((y - y_m) ** 2 for y in y_vals))
                if den_x == 0 or den_y == 0:
                    raise ValueError("correlation: zero variance in one variable")
                return float(num / (den_x * den_y))
            if fn == "percentile" and len(node.args) >= 2:
                # percentile(val1, val2, ..., p) — last arg is percentile
                all_args = [_eval(a) for a in node.args]
                p = all_args[-1]
                vals = sorted(all_args[:-1])
                if not (0 <= p <= 100):
                    raise ValueError("percentile must be 0-100")
                k = (p / 100) * (len(vals) - 1)
                lo = int(k)
                hi = min(lo + 1, len(vals) - 1)
                return float(vals[lo] + (k - lo) * (vals[hi] - vals[lo]))
            if fn == "interpolate" and len(node.args) == 3:
                a, b, t = [_eval(x) for x in node.args]
                return float(a + (b - a) * t)
            if fn == "boxcox" and len(node.args) == 2:
                x = _eval(node.args[0])
                lam = _eval(node.args[1])
                if x <= 0:
                    raise ValueError("boxcox requires x > 0")
                return float(math.log(x)) if lam == 0 else float(((x ** lam) - 1.0) / lam)
            if fn == "mad":  # mean absolute deviation
                vals = _collect_args(node.args)
                m = sum(vals) / len(vals)
                return float(sum(abs(v - m) for v in vals) / len(vals))
            if fn == "skewness":
                vals = _collect_args(node.args)
                n = len(vals)
                if n < 3:
                    raise ValueError("skewness requires 3+ values")
                m = sum(vals) / n
                s = math.sqrt(sum((v - m) ** 2 for v in vals) / (n - 1))
                if s == 0:
                    return 0.0
                return float((n / ((n - 1) * (n - 2))) * sum(((v - m) / s) ** 3 for v in vals))
            if fn == "kurtosis":
                vals = _collect_args(node.args)
                n = len(vals)
                if n < 4:
                    raise ValueError("kurtosis requires 4+ values")
                m = sum(vals) / n
                s = math.sqrt(sum((v - m) ** 2 for v in vals) / (n - 1))
                if s == 0:
                    return 0.0
                k4 = sum(((v - m) / s) ** 4 for v in vals)
                return float((n * (n + 1) / ((n - 1) * (n - 2) * (n - 3))) * k4 - 3 * (n - 1) ** 2 / ((n - 2) * (n - 3)))
            if fn == "gini":
                vals = sorted(_collect_args(node.args))
                n = len(vals)
                if n == 0 or sum(vals) == 0:
                    return 0.0
                return float(sum((2 * i - n - 1) * v for i, v in enumerate(vals, 1)) / (n * sum(vals)))
            if fn == "hhi":  # Herfindahl-Hirschman Index
                vals = _collect_args(node.args)
                total = sum(vals)
                if total == 0:
                    return 0.0
                return float(sum((v / total) ** 2 for v in vals))
            if fn == "zscore" and len(node.args) == 3:
                x, m, s = [_eval(a) for a in node.args]
                if s == 0:
                    raise ValueError("zscore: stdev cannot be 0")
                return float((x - m) / s)
            if fn == "iqr":
                vals = sorted(_collect_args(node.args))
                n = len(vals)
                q1_idx = (n - 1) * 0.25
                q3_idx = (n - 1) * 0.75
                lo1, lo3 = int(q1_idx), int(q3_idx)
                hi1, hi3 = min(lo1 + 1, n - 1), min(lo3 + 1, n - 1)
                q1 = vals[lo1] + (q1_idx - lo1) * (vals[hi1] - vals[lo1])
                q3 = vals[lo3] + (q3_idx - lo3) * (vals[hi3] - vals[lo3])
                return float(q3 - q1)
            if fn == "kl_divergence" and len(node.args) == 2:
                p_vals = _eval_list(node.args[0])
                q_vals = _eval_list(node.args[1])
                if len(p_vals) != len(q_vals):
                    raise ValueError("kl_divergence: lists must be same length")
                return float(sum(p * math.log(p / q) for p, q in zip(p_vals, q_vals) if p > 0 and q > 0))
            if fn == "exp_smooth" and len(node.args) == 2:
                vals = _eval_list(node.args[0])
                alpha = _eval(node.args[1])
                s = vals[0]
                for v in vals[1:]:
                    s = alpha * v + (1 - alpha) * s
                return float(s)
            if fn == "local_maxima" or fn == "count_peaks":
                vals = _collect_args(node.args)
                if len(vals) < 3:
                    return 0.0
                count = 0
                for i in range(1, len(vals) - 1):
                    if vals[i] > vals[i - 1] and vals[i] > vals[i + 1]:
                        count += 1
                return float(count)
            if fn == "local_minima" or fn == "count_troughs":
                vals = _collect_args(node.args)
                if len(vals) < 3:
                    return 0.0
                count = 0
                for i in range(1, len(vals) - 1):
                    if vals[i] < vals[i - 1] and vals[i] < vals[i + 1]:
                        count += 1
                return float(count)
        # Handle ast.List at top level (return first element as float)
        if isinstance(node, ast.List):
            if len(node.elts) == 1:
                return _eval(node.elts[0])
            raise ValueError("list_at_top_level_use_a_function")
        raise ValueError("unsupported_expression")

    expr = expression.strip()
    # Reject assignment syntax with helpful message
    if "=" in expr and not any(op in expr for op in ["==", "!=", ">=", "<="]):
        parts = expr.split("=", 1)
        if parts[0].strip().isidentifier():
            raise ValueError(
                f"Assignment not supported. Use just the expression: {parts[1].strip()}"
            )
    # Replace ^ with ** for exponentiation (common model mistake)
    # But only when ^ is used as power, not XOR (rare in finance)
    expr = expr.replace("^", "**")
    tree = ast.parse(expr, mode="eval")
    return _eval(tree)
