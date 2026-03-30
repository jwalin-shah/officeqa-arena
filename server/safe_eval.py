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
