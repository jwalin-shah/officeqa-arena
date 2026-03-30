"""Safe arithmetic evaluator for finance expressions.

Supports: +, -, *, /, **, %, unary +/-, and whitelisted functions
(abs, round, min, max, sum, sqrt, log, ln, exp, geometric_mean, prod).
"""

from __future__ import annotations

import ast
import builtins
import math


def safe_eval_finance(expression: str, variables: dict[str, float] | None = None) -> float:
    """Evaluate a limited arithmetic expression with named variables and numeric literals.

    Raises ``ValueError`` on unsupported syntax or unknown variable names.
    """
    variables = variables or {}

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
            if fn == "min" and len(node.args) >= 2:
                return float(min(_eval(a) for a in node.args))
            if fn == "max" and len(node.args) >= 2:
                return float(max(_eval(a) for a in node.args))
            if fn == "sqrt" and len(node.args) == 1:
                return math.sqrt(_eval(node.args[0]))
            if fn == "log" and len(node.args) in {1, 2}:
                args = [_eval(a) for a in node.args]
                return math.log(*args)
            if fn == "ln" and len(node.args) == 1:
                return math.log(_eval(node.args[0]))
            if fn == "exp" and len(node.args) == 1:
                return math.exp(_eval(node.args[0]))
            if fn == "sum" and len(node.args) >= 1:
                return float(sum(_eval(a) for a in node.args))
            if fn == "pow" and len(node.args) == 2:
                return _eval(node.args[0]) ** _eval(node.args[1])
            if fn == "prod" and len(node.args) >= 1:
                return float(math.prod(_eval(a) for a in node.args))
            if fn == "geometric_mean" and len(node.args) >= 1:
                vals = [_eval(a) for a in node.args]
                return float(math.prod(vals) ** (1.0 / len(vals)))
            if fn == "mean" and len(node.args) >= 1:
                vals = [_eval(a) for a in node.args]
                return float(sum(vals) / len(vals))
        raise ValueError("unsupported_expression")

    expr = expression.strip()
    # Reject assignment syntax with helpful message
    if "=" in expr and not any(op in expr for op in ["==", "!=", ">=", "<="]):
        # Check if it's like "x = 1 + 2" (assignment)
        parts = expr.split("=", 1)
        if parts[0].strip().isidentifier():
            raise ValueError(
                f"Assignment not supported. Use just the expression: {parts[1].strip()}"
            )
    tree = ast.parse(expr, mode="eval")
    return _eval(tree)
