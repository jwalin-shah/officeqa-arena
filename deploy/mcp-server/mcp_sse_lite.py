#!/usr/bin/env python3
"""Lightweight MCP SSE server — no SQLite DB required.

Exposes only the DB-free tools:
  - compute_expression  (safe arithmetic)
  - get_cpi_index       (reads bundled CSV)
  - get_fiscal_year_bounds (pure computation)

Usage:
    python3 mcp_sse_lite.py                     # default 0.0.0.0:8081
    python3 mcp_sse_lite.py --port 8081
"""
from __future__ import annotations

import argparse
import ast
import builtins
import csv
import json
import logging
import math
import statistics
from pathlib import Path

from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger("mcp_sse_lite")

_DEFAULT_HOST = "0.0.0.0"
_DEFAULT_PORT = 8081

mcp = FastMCP(
    "officeqa-arena-lite",
    host=_DEFAULT_HOST,
    port=_DEFAULT_PORT,
)

# ---------------------------------------------------------------------------
# CPI data cache
# ---------------------------------------------------------------------------

_CPI_DATA: dict | None = None
_SCRIPT_DIR = Path(__file__).resolve().parent


def _load_cpi() -> dict:
    global _CPI_DATA
    if _CPI_DATA is not None:
        return _CPI_DATA

    csv_path = _SCRIPT_DIR / "cpi_monthly.csv"
    if not csv_path.exists():
        _CPI_DATA = {"annual": {}, "monthly": {}}
        return _CPI_DATA

    annual: dict[int, float] = {}
    monthly: dict[str, float] = {}

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yr = int(row.get("year") or row.get("Year") or 0)
            mo = row.get("month") or row.get("Month") or row.get("period") or ""
            val_str = row.get("value") or row.get("Value") or row.get("index") or row.get("Index") or row.get("CPI") or ""
            if not val_str or not yr:
                continue
            val = float(val_str)
            if mo and mo not in ("", "0", "Annual", "annual", "Avg"):
                try:
                    m = int(mo)
                    if 1 <= m <= 12:
                        monthly[f"{yr}-{m:02d}"] = val
                except ValueError:
                    pass
            else:
                annual[yr] = val

    # If we only have monthly data, compute annual averages
    if not annual and monthly:
        from collections import defaultdict
        by_year: dict[int, list[float]] = defaultdict(list)
        for key, val in monthly.items():
            y = int(key.split("-")[0])
            by_year[y].append(val)
        for y, vals in by_year.items():
            annual[y] = sum(vals) / len(vals)

    _CPI_DATA = {"annual": annual, "monthly": monthly}
    return _CPI_DATA


# ---------------------------------------------------------------------------
# safe_eval_finance (inlined from server/safe_eval.py)
# ---------------------------------------------------------------------------

def safe_eval_finance(expression: str, variables: dict[str, float] | None = None) -> float | list[float]:
    variables = variables or {}

    def _eval_list(node: ast.AST) -> list[float]:
        if isinstance(node, ast.List):
            return [_eval(elt) for elt in node.elts]
        return [_eval(node)]

    def _collect_args(args: list[ast.AST]) -> list[float]:
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
            if isinstance(op, ast.Add): return left + right
            if isinstance(op, ast.Sub): return left - right
            if isinstance(op, ast.Mult): return left * right
            if isinstance(op, ast.Div):
                if right == 0: raise ValueError("division_by_zero")
                return left / right
            if isinstance(op, ast.Pow): return left ** right
            if isinstance(op, ast.Mod): return left % right
            if isinstance(op, ast.BitXor): return left ** right
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn = node.func.id
            if fn == "abs":
                return float(builtins.abs(*[_eval(a) for a in node.args]))
            if fn == "round":
                args = [_eval(a) for a in node.args]
                return float(builtins.round(args[0], int(args[1])) if len(args) == 2 else builtins.round(args[0]))
            if fn in ("min", "max"):
                vals = _collect_args(node.args)
                return float(min(vals) if fn == "min" else max(vals))
            if fn == "sqrt" and len(node.args) == 1:
                return math.sqrt(_eval(node.args[0]))
            if fn == "log":
                args = [_eval(a) for a in node.args]
                return math.log(*args)
            if fn == "ln" and len(node.args) == 1:
                return math.log(_eval(node.args[0]))
            if fn == "exp" and len(node.args) == 1:
                return math.exp(_eval(node.args[0]))
            if fn == "sum":
                return float(sum(_collect_args(node.args)))
            if fn == "pow" and len(node.args) == 2:
                return _eval(node.args[0]) ** _eval(node.args[1])
            if fn == "prod":
                return float(math.prod(_collect_args(node.args)))
            if fn == "geometric_mean":
                vals = _collect_args(node.args)
                return float(math.prod(vals) ** (1.0 / len(vals)))
            if fn == "mean":
                vals = _collect_args(node.args)
                return float(sum(vals) / len(vals))
            if fn == "stdev":
                vals = _collect_args(node.args)
                if len(vals) < 2: raise ValueError("stdev requires at least 2 values")
                return float(statistics.stdev(vals))
            if fn == "len":
                return float(len(_collect_args(node.args)))
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
                if den == 0: raise ValueError("linreg: all x values are identical")
                slope = num / den
                intercept = y_mean - slope * x_mean
                return [float(slope), float(intercept)]
            if fn == "cagr" and len(node.args) == 3:
                args = [_eval(a) for a in node.args]
                return ((args[1] / args[0]) ** (1.0 / args[2]) - 1) * 100
            if fn == "median":
                vals = sorted(_collect_args(node.args))
                n = len(vals)
                if n == 0: raise ValueError("median requires at least 1 value")
                mid = n // 2
                return float(vals[mid]) if n % 2 else float((vals[mid - 1] + vals[mid]) / 2)
            if fn == "variance":
                vals = _collect_args(node.args)
                if len(vals) < 2: raise ValueError("variance requires at least 2 values")
                m = sum(vals) / len(vals)
                return float(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))
            if fn == "theil":
                # Theil T index: (1/n) * sum((y_i/mean) * ln(y_i/mean))
                vals = _collect_args(node.args)
                if len(vals) < 2: raise ValueError("theil requires at least 2 values")
                if any(v <= 0 for v in vals): raise ValueError("theil requires all positive values")
                m = sum(vals) / len(vals)
                return float(sum((v / m) * math.log(v / m) for v in vals) / len(vals))
            if fn == "theil_l":
                # Theil L (MLD) index: (1/n) * sum(ln(mean/y_i))
                vals = _collect_args(node.args)
                if len(vals) < 2: raise ValueError("theil_l requires at least 2 values")
                if any(v <= 0 for v in vals): raise ValueError("theil_l requires all positive values")
                m = sum(vals) / len(vals)
                return float(sum(math.log(m / v) for v in vals) / len(vals))
            if fn == "gini":
                vals = sorted(_collect_args(node.args))
                n = len(vals)
                if n < 2: raise ValueError("gini requires at least 2 values")
                s = sum(vals)
                if s == 0: raise ValueError("gini: sum of values is zero")
                return float(sum((2 * (i + 1) - n - 1) * vals[i] for i in range(n)) / (n * s))
            if fn in ("pct_change", "pct_diff"):
                # pct_change(old, new) -> (new - old) / old * 100
                args = [_eval(a) for a in node.args]
                if len(args) != 2: raise ValueError("pct_change(old, new) requires 2 args")
                if args[0] == 0: raise ValueError("division_by_zero")
                return float((args[1] - args[0]) / args[0] * 100)
            if fn == "abs_pct_diff":
                # Symmetric percent difference: |a-b| / ((a+b)/2) * 100
                args = [_eval(a) for a in node.args]
                if len(args) != 2: raise ValueError("abs_pct_diff(a, b) requires 2 args")
                if (args[0] + args[1]) == 0: raise ValueError("division_by_zero")
                return float(abs(args[0] - args[1]) / ((args[0] + args[1]) / 2) * 100)
            if fn == "herfindahl":
                # Herfindahl-Hirschman Index: sum((s_i/total)^2)
                vals = _collect_args(node.args)
                total = sum(vals)
                if total == 0: raise ValueError("herfindahl: sum is zero")
                return float(sum((v / total) ** 2 for v in vals))
        if isinstance(node, ast.List):
            if len(node.elts) == 1:
                return _eval(node.elts[0])
            raise ValueError("list_at_top_level_use_a_function")
        raise ValueError("unsupported_expression")

    expr = expression.strip()
    if "=" in expr and not any(op in expr for op in ["==", "!=", ">=", "<="]):
        parts = expr.split("=", 1)
        if parts[0].strip().isidentifier():
            raise ValueError(f"Assignment not supported. Use just the expression: {parts[1].strip()}")
    expr = expr.replace("^", "**")
    tree = ast.parse(expr, mode="eval")
    return _eval(tree)


# ---------------------------------------------------------------------------
# Tool: compute_expression
# ---------------------------------------------------------------------------

@mcp.tool()
def compute_expression(
    expression: str,
    variables: dict | None = None,
) -> str:
    """Safe arithmetic evaluator. Use for ALL math -- never do mental math.

    Supports: +, -, *, /, ** (power), abs(), round(), min(), max(), sum(),
    sqrt(), log(), exp(), geometric_mean(), mean(), prod(), stdev(), pow(), len().
    Use ** for power (^ also works). Pass numeric values as variables.

    Args:
        expression: Math expression (e.g. 'a - b', 'geometric_mean(1,2,3)')
        variables: Variable name->value mapping (e.g. {"a": 494, "b": 154})
    """
    try:
        clean_vars = {k: float(v) for k, v in (variables or {}).items()}
        result = safe_eval_finance(expression, clean_vars)
        return json.dumps({"ok": True, "result": result, "expression_echo": expression})
    except (ValueError, SyntaxError, TypeError, ZeroDivisionError) as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Tool: hp_filter
# ---------------------------------------------------------------------------

@mcp.tool()
def hp_filter(values: list[float], lam: float = 100.0) -> str:
    """Hodrick-Prescott filter. Decomposes a time series into trend and cycle.

    Use for structural balance calculations, output gap analysis, etc.
    Lambda (lam) controls smoothness: 100 for annual data (default), 1600 for quarterly.

    Args:
        values: Time series as a list of numbers (chronological order)
        lam: Smoothing parameter lambda (default 100 for annual data)

    Returns:
        JSON with trend (list), cycle (list), and structural_balance if applicable.
    """
    n = len(values)
    if n < 4:
        return json.dumps({"error": "hp_filter requires at least 4 data points"})
    try:
        # Build the penalty matrix using the second-difference operator
        # Solve (I + lam * D'D) * trend = values  via Cholesky / band matrix
        # Using the standard sparse band-matrix approach
        lam = float(lam)
        y = list(values)

        # Build D'D as a pentadiagonal band (d0, d1, d2)
        # D is (n-2) x n second difference matrix
        # D'D is n x n with bandwidth 2
        d0 = [0.0] * n
        d1 = [0.0] * (n - 1)
        d2 = [0.0] * (n - 2)

        for i in range(n - 2):
            d0[i]     += 1.0
            d0[i + 1] += 4.0
            d0[i + 2] += 1.0
            d1[i]     -= 2.0
            d1[i + 1] -= 2.0
            d2[i]     += 1.0

        # Add lambda * D'D to identity
        a0 = [1.0 + lam * d0[i] for i in range(n)]
        a1 = [lam * d1[i] for i in range(n - 1)]
        a2 = [lam * d2[i] for i in range(n - 2)]

        # Solve via banded Cholesky (LDL' factorization of pentadiagonal)
        # Forward sweep
        for i in range(2, n):
            if i >= 2:
                t = a1[i - 1] / a0[i - 1]
                a0[i] -= t * a1[i - 1]
                if i < n - 1:
                    a1[i] -= t * a2[i - 2] if i >= 2 else 0
                y[i] -= t * y[i - 1]
                if i >= 2:
                    t2 = a2[i - 2] / a0[i - 2]
                    a0[i] -= t2 * a2[i - 2]
                    y[i] -= t2 * y[i - 2]

        # Use scipy-free implementation via numpy-free Cholesky for pentadiagonal
        # Fallback: use iterative method (Whittaker smoother)
        # Re-implement cleanly using Whittaker-Henderson smoother
        # (equivalent to HP filter for second differences)
        trend = _hp_whittaker(values, lam)
        cycle = [values[i] - trend[i] for i in range(n)]

        return json.dumps({
            "ok": True,
            "trend": [round(t, 6) for t in trend],
            "cycle": [round(c, 6) for c in cycle],
            "lam": lam,
            "n": n,
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


def _hp_whittaker(y: list[float], lam: float) -> list[float]:
    """Pure Python Whittaker-Henderson smoother (HP filter for d=2)."""
    n = len(y)
    # Build D'D band (bandwidth 2 pentadiagonal) and solve (I + lam*D'D)z = y
    # Use Thomas algorithm for pentadiagonal systems
    # Coefficients: a[i]*z[i-2] + b[i]*z[i-1] + c[i]*z[i] + d[i]*z[i+1] + e[i]*z[i+2] = y[i]
    # where the matrix is (I + lam * D2'D2)

    # Build D2'D2 explicitly for small n
    # D2'D2[i,j] for second-difference D2
    def d2td2(i, j, n):
        # Coefficients of (D'D) for second difference
        diff = abs(i - j)
        if diff > 2:
            return 0.0
        # D2'D2 is a banded matrix with known coefficients
        vals = {0: [1, -4, 6, -4, 1], 1: [-2, 5, -4, 1], 2: [1, -4, 6]}
        # Use the convolution approach
        result = 0.0
        for k in range(max(0, i - 2), min(n - 2, i + 1)):
            # D[k,i] * D[k,j]
            di = [1, -2, 1][i - k] if 0 <= i - k <= 2 else 0
            dj = [1, -2, 1][j - k] if 0 <= j - k <= 2 else 0
            result += di * dj
        return result

    # Build full matrix (small n, pure Python)
    A = [[0.0] * n for _ in range(n)]
    for i in range(n):
        A[i][i] += 1.0
        for j in range(max(0, i - 2), min(n, i + 3)):
            A[i][j] += lam * d2td2(i, j, n)

    # Solve Ax = y via Gaussian elimination
    b = list(y)
    for col in range(n):
        # Find pivot
        pivot = col
        for row in range(col + 1, min(col + 3, n)):
            if abs(A[row][col]) > abs(A[pivot][col]):
                pivot = row
        A[col], A[pivot] = A[pivot], A[col]
        b[col], b[pivot] = b[pivot], b[col]
        if abs(A[col][col]) < 1e-15:
            continue
        for row in range(col + 1, min(col + 5, n)):
            if row >= n:
                break
            factor = A[row][col] / A[col][col]
            for k in range(col, min(col + 5, n)):
                A[row][k] -= factor * A[col][k]
            b[row] -= factor * b[col]

    # Back substitution
    z = [0.0] * n
    for i in range(n - 1, -1, -1):
        z[i] = b[i]
        for j in range(i + 1, min(i + 5, n)):
            z[i] -= A[i][j] * z[j]
        if abs(A[i][i]) > 1e-15:
            z[i] /= A[i][i]
    return z


# ---------------------------------------------------------------------------
# Tool: get_cpi_index
# ---------------------------------------------------------------------------

@mcp.tool()
def get_cpi_index(year: int, month: int | None = None) -> str:
    """Get CPI-U index value for inflation-adjusted calculations (base: 1982-84=100).

    Args:
        year: Calendar year
        month: Optional month (1-12) for monthly CPI. Omit for annual average.
    """
    data = _load_cpi()
    annual = data["annual"]
    monthly = data["monthly"]

    if month is None or month == 0:
        idx = annual.get(int(year))
        if idx is None:
            return json.dumps({
                "ok": False, "error": "annual_cpi_not_found", "year": year,
                "available_years_sample": sorted(annual.keys())[:8],
            })
        return json.dumps({
            "ok": True, "year": year, "month": None, "index": idx,
            "basis": "CPI-U All Items U.S. city average; annual average (1982-84=100)",
        })

    if month < 1 or month > 12:
        return json.dumps({"ok": False, "error": "invalid_month", "month": month})

    key = f"{year}-{month:02d}"
    idx = monthly.get(key)
    if idx is None:
        return json.dumps({
            "ok": False, "error": "monthly_cpi_not_found", "year": year, "month": month,
        })
    return json.dumps({
        "ok": True, "year": year, "month": month, "index": idx,
        "basis": "CPI-U All Items U.S. city average; monthly (1982-84=100)",
    })


# ---------------------------------------------------------------------------
# Tool: get_fiscal_year_bounds
# ---------------------------------------------------------------------------

@mcp.tool()
def get_fiscal_year_bounds(fiscal_year: int) -> str:
    """Get start/end dates for a U.S. federal fiscal year.

    Before 1977: Jul 1 (Y-1) to Jun 30 (Y). From 1977+: Oct 1 (Y-1) to Sep 30 (Y).

    Args:
        fiscal_year: The fiscal year number (e.g. 1955)
    """
    fy = int(fiscal_year)
    if fy <= 0:
        return json.dumps({"ok": False, "error": "invalid_fiscal_year", "fiscal_year": fy})

    if fy <= 1976:
        return json.dumps({
            "ok": True, "fiscal_year": fy,
            "period_start": f"{fy - 1}-07-01",
            "period_end": f"{fy}-06-30",
            "basis": "U.S. federal fiscal year (Jul 1 - Jun 30, pre-1977)",
        })

    return json.dumps({
        "ok": True, "fiscal_year": fy,
        "period_start": f"{fy - 1}-10-01",
        "period_end": f"{fy}-09-30",
        "basis": "U.S. federal fiscal year (Oct 1 - Sep 30)",
    })


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="OfficeQA Arena MCP SSE Server (Lite)")
    parser.add_argument("--host", default=_DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=_DEFAULT_PORT)
    args = parser.parse_args()

    mcp.settings.host = args.host
    mcp.settings.port = args.port

    # Eagerly load CPI data
    _load_cpi()
    logger.info("Starting MCP streamable-http server on %s:%d", args.host, args.port)
    logger.info("Tools: compute_expression, hp_filter, get_cpi_index, get_fiscal_year_bounds")

    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
