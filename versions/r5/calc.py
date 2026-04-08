#!/usr/bin/env python3
"""Safe calculation functions for OfficeQA. Use for any computation."""

import ast, math, statistics, sys


def safe_eval(expression, variables=None):
    variables = variables or {}

    def _collect(args):
        r = []
        for a in args:
            if isinstance(a, ast.List):
                r.extend(_ev(e) for e in a.elts)
            else:
                r.append(_ev(a))
        return r

    def _ev(node):
        if isinstance(node, ast.Expression):
            return _ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id in variables:
                return float(variables[node.id])
            raise ValueError(f"unknown variable: {node.id}")
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                return -_ev(node.operand)
            if isinstance(node.op, ast.UAdd):
                return _ev(node.operand)
        if isinstance(node, ast.BinOp):
            L, R = _ev(node.left), _ev(node.right)
            op = node.op
            if isinstance(op, ast.Add):
                return L + R
            if isinstance(op, ast.Sub):
                return L - R
            if isinstance(op, ast.Mult):
                return L * R
            if isinstance(op, ast.Div):
                if R == 0:
                    raise ValueError("division by zero")
                return L / R
            if isinstance(op, ast.Pow):
                return L**R
            if isinstance(op, ast.Mod):
                return L % R
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn = node.func.id
            if fn == "abs":
                return abs(_ev(node.args[0]))
            if fn == "round":
                a = [_ev(x) for x in node.args]
                return round(a[0], int(a[1])) if len(a) == 2 else round(a[0])
            if fn in ("min", "max"):
                return (
                    min(_collect(node.args))
                    if fn == "min"
                    else max(_collect(node.args))
                )
            if fn == "sqrt":
                return math.sqrt(_ev(node.args[0]))
            if fn == "log":
                a = [_ev(x) for x in node.args]
                return math.log(*a)
            if fn == "exp":
                return math.exp(_ev(node.args[0]))
            if fn == "sum":
                return sum(_collect(node.args))
            if fn == "mean":
                v = _collect(node.args)
                return sum(v) / len(v)
            if fn == "stdev":
                return statistics.stdev(_collect(node.args))
            if fn == "pstdev":
                return statistics.pstdev(_collect(node.args))
            if fn == "median":
                return statistics.median(_collect(node.args))
            if fn == "pct_change":
                a = [_ev(x) for x in node.args]
                if a[0] == 0:
                    raise ValueError("division by zero")
                return (a[1] - a[0]) / a[0] * 100
            if fn == "cagr":
                a = [_ev(x) for x in node.args]
                return ((a[1] / a[0]) ** (1.0 / a[2]) - 1) * 100
            if fn == "variance":
                return statistics.variance(_collect(node.args))
            if fn == "geometric_mean":
                v = _collect(node.args)
                return math.exp(sum(math.log(x) for x in v) / len(v))
            if fn == "harmonic_mean":
                return statistics.harmonic_mean(_collect(node.args))
        raise ValueError(f"unsupported: {ast.dump(node)}")

    expr = expression.strip().replace("^", "**")
    tree = ast.parse(expr, mode="eval")
    return _ev(tree)


def main():
    if len(sys.argv) < 2:
        print("Usage: calc.py 'expression' [var=value ...]")
        print("Examples:")
        print("  calc.py 'pct_change(100, 150)'")
        print("  calc.py 'stdev([10, 20, 30])'")
        print("  calc.py 'cagr(100, 200, 10)'")
        print("  calc.py 'sum([1,2,3]) + mean([4,5,6])'")
        print("  calc.py 'pct_change(old, new)' old=100 new=150")
        sys.exit(1)
    expr = sys.argv[1]
    vs = {}
    for arg in sys.argv[2:]:
        k, v = arg.split("=", 1)
        vs[k] = float(v)
    result = safe_eval(expr, vs)
    print(f"{result}")


if __name__ == "__main__":
    main()
