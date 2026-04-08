#!/usr/bin/env python3
"""Safe math evaluator with financial helper functions."""
import ast, math, operator, statistics, sys

SAFE_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}

FUNCS = {
    "sum": sum, "mean": statistics.mean, "median": statistics.median,
    "stdev": statistics.stdev, "pstdev": statistics.pstdev,
    "min": min, "max": max, "abs": abs, "round": round,
    "sqrt": math.sqrt, "log": math.log, "exp": math.exp,
    "geometric_mean": statistics.geometric_mean,
    "pct_change": lambda old, new: ((new - old) / abs(old)) * 100,
    "cagr": lambda begin, end, years: ((end / begin) ** (1 / years) - 1) * 100,
}
CONSTS = {"pi": math.pi, "e": math.e}

def safe_eval(node):
    if isinstance(node, ast.Expression):
        return safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant: {node.value!r}")
    if isinstance(node, ast.UnaryOp) and type(node.op) in SAFE_OPS:
        return SAFE_OPS[type(node.op)](safe_eval(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in SAFE_OPS:
        return SAFE_OPS[type(node.op)](safe_eval(node.left), safe_eval(node.right))
    if isinstance(node, ast.Call):
        name = node.func.id if isinstance(node.func, ast.Name) else None
        if name not in FUNCS:
            raise ValueError(f"Unknown function: {name}")
        args = [safe_eval(a) for a in node.args]
        fn = FUNCS[name]
        # sum/mean/median/stdev/pstdev/geometric_mean/min/max take a list
        if name in ("sum","mean","median","stdev","pstdev","geometric_mean","min","max") and len(args) > 1:
            return fn(args)
        return fn(*args)
    if isinstance(node, ast.Name):
        if node.id in CONSTS:
            return CONSTS[node.id]
        raise ValueError(f"Unknown name: {node.id}")
    raise ValueError(f"Unsupported expression: {ast.dump(node)}")

def main():
    if len(sys.argv) < 2:
        print("Usage: calc.py EXPRESSION"); sys.exit(1)
    expr = " ".join(sys.argv[1:])
    try:
        tree = ast.parse(expr, mode="eval")
        result = safe_eval(tree)
        # Print integers cleanly, floats with reasonable precision
        if isinstance(result, float) and result == int(result) and abs(result) < 1e15:
            print(int(result))
        else:
            print(f"{result:.6f}".rstrip("0").rstrip(".") if isinstance(result, float) else result)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr); sys.exit(1)

if __name__ == "__main__":
    main()
