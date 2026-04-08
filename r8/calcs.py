#!/usr/bin/env python3
"""CLI calculator for OfficeQA financial questions. No external deps.

Usage: python3 calcs.py CMD [args...]
"""

import ast, math, statistics, sys


# ---------------------------------------------------------------------------
# Standalone math helpers (no numpy)
# ---------------------------------------------------------------------------

def _parse_list(s):
    """Parse 'v1,v2,...' into list of floats."""
    return [float(x.strip()) for x in s.split(",") if x.strip()]


def _pct_change(old, new):
    if old == 0:
        raise ValueError("division by zero in pct_change")
    return (new - old) / old * 100


def _cagr(start, end, years):
    if start == 0 or years == 0:
        raise ValueError("start and years must be nonzero for cagr")
    return ((end / start) ** (1.0 / years) - 1) * 100


def _mean(v):
    if not v:
        raise ValueError("empty list")
    return sum(v) / len(v)


def _median(v):
    return statistics.median(v)


def _stdev(v):
    return statistics.stdev(v)


def _pstdev(v):
    return statistics.pstdev(v)


def _variance(v):
    return statistics.variance(v)


def _geometric_mean(v):
    if not v:
        raise ValueError("empty list")
    return math.exp(sum(math.log(x) for x in v) / len(v))


def _harmonic_mean(v):
    return statistics.harmonic_mean(v)


def _cv(v):
    m = _mean(v)
    if m == 0:
        raise ValueError("mean is zero, cv undefined")
    return _stdev(v) / abs(m) * 100


def _theil(v):
    if not v:
        raise ValueError("empty list")
    m = _mean(v)
    if m == 0:
        raise ValueError("mean is zero")
    n = len(v)
    return sum((x / m) * math.log(x / m) for x in v if x > 0) / n


def _kl(p, q):
    if len(p) != len(q):
        raise ValueError("p and q must have same length")
    return sum(pi * math.log(pi / qi) for pi, qi in zip(p, q) if pi > 0 and qi > 0)


def _gini(v):
    if not v:
        raise ValueError("empty list")
    s = sorted(v)
    n = len(s)
    m = _mean(s)
    if m == 0:
        return 0.0
    total = sum(abs(a - b) for i, a in enumerate(s) for b in s)
    return total / (2 * n * n * m)


def _hhi(v):
    if not v:
        raise ValueError("empty list")
    t = sum(v)
    if t == 0:
        raise ValueError("sum is zero")
    return sum((x / t * 100) ** 2 for x in v)


def _correlation(x, y):
    if len(x) != len(y):
        raise ValueError("x and y must have same length")
    n = len(x)
    if n < 2:
        raise ValueError("need at least 2 data points")
    mx, my = _mean(x), _mean(y)
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    dx = math.sqrt(sum((xi - mx) ** 2 for xi in x))
    dy = math.sqrt(sum((yi - my) ** 2 for yi in y))
    if dx == 0 or dy == 0:
        raise ValueError("zero variance, correlation undefined")
    return num / (dx * dy)


def _moving_avg(v, window):
    w = int(window)
    if w <= 0:
        raise ValueError("window must be positive")
    return [_mean(v[max(0, i - w + 1):i + 1]) for i in range(len(v))]


def _linreg(x, y):
    if len(x) != len(y):
        raise ValueError("x and y must have same length")
    n = len(x)
    if n < 2:
        raise ValueError("need at least 2 data points")
    mx, my = _mean(x), _mean(y)
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    den = sum((xi - mx) ** 2 for xi in x)
    if den == 0:
        raise ValueError("zero variance in x")
    slope = num / den
    intercept = my - slope * mx
    return slope, intercept


# ---------------------------------------------------------------------------
# Polynomial fit via normal equations (Gaussian elimination)
# ---------------------------------------------------------------------------

def _gauss_solve(A, b):
    """Solve Ax=b for small systems via Gaussian elimination with pivoting."""
    n = len(b)
    # Augmented matrix
    M = [row[:] + [bi] for row, bi in zip(A, b)]
    for col in range(n):
        # Partial pivot
        max_row = max(range(col, n), key=lambda r: abs(M[r][col]))
        M[col], M[max_row] = M[max_row], M[col]
        if abs(M[col][col]) < 1e-15:
            raise ValueError("singular matrix in polyfit")
        for row in range(col + 1, n):
            f = M[row][col] / M[col][col]
            for j in range(col, n + 1):
                M[row][j] -= f * M[col][j]
    # Back substitution
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (M[i][n] - sum(M[i][j] * x[j] for j in range(i + 1, n))) / M[i][i]
    return x


def _polyfit(x, y, degree):
    if len(x) != len(y):
        raise ValueError("x and y must have same length")
    n = len(x)
    d = int(degree)
    if d < 1 or d > 3:
        raise ValueError("degree must be 1, 2, or 3")
    if n < d + 1:
        raise ValueError(f"need at least {d + 1} data points for degree {d}")
    # Build normal equations: (X^T X) c = X^T y
    # Columns: x^0, x^1, ..., x^d
    m = d + 1
    XtX = [[0.0] * m for _ in range(m)]
    Xty = [0.0] * m
    for i in range(n):
        powers = [x[i] ** p for p in range(m)]
        for r in range(m):
            for c in range(m):
                XtX[r][c] += powers[r] * powers[c]
            Xty[r] += powers[r] * y[i]
    coeffs = _gauss_solve(XtX, Xty)
    return coeffs  # [c0, c1, c2, ...] where y = c0 + c1*x + c2*x^2 + ...


# ---------------------------------------------------------------------------
# Safe eval with AST
# ---------------------------------------------------------------------------

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
            if isinstance(op, ast.FloorDiv):
                if R == 0:
                    raise ValueError("division by zero")
                return L // R
            if isinstance(op, ast.Pow):
                return L ** R
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
                return min(_collect(node.args)) if fn == "min" else max(_collect(node.args))
            if fn == "sqrt":
                return math.sqrt(_ev(node.args[0]))
            if fn == "log":
                a = [_ev(x) for x in node.args]
                return math.log(*a)
            if fn == "log10":
                return math.log10(_ev(node.args[0]))
            if fn == "exp":
                return math.exp(_ev(node.args[0]))
            if fn == "pow":
                a = [_ev(x) for x in node.args]
                return a[0] ** a[1]
            if fn == "sum":
                return sum(_collect(node.args))
            if fn == "len":
                return float(len(_collect(node.args)))
            if fn == "mean":
                return _mean(_collect(node.args))
            if fn == "stdev":
                return _stdev(_collect(node.args))
            if fn == "pstdev":
                return _pstdev(_collect(node.args))
            if fn == "median":
                return _median(_collect(node.args))
            if fn == "variance":
                return _variance(_collect(node.args))
            if fn == "geometric_mean":
                return _geometric_mean(_collect(node.args))
            if fn == "harmonic_mean":
                return _harmonic_mean(_collect(node.args))
            if fn == "cv":
                return _cv(_collect(node.args))
            if fn == "pct_change":
                a = [_ev(x) for x in node.args]
                return _pct_change(a[0], a[1])
            if fn == "cagr":
                a = [_ev(x) for x in node.args]
                return _cagr(a[0], a[1], a[2])
            if fn == "theil":
                return _theil(_collect(node.args))
            if fn == "gini":
                return _gini(_collect(node.args))
            if fn == "hhi":
                return _hhi(_collect(node.args))
            if fn == "kl":
                # kl([p1,p2,...], [q1,q2,...]) — need exactly 2 list args
                if len(node.args) == 2 and isinstance(node.args[0], ast.List) and isinstance(node.args[1], ast.List):
                    p = [_ev(e) for e in node.args[0].elts]
                    q = [_ev(e) for e in node.args[1].elts]
                    return _kl(p, q)
                raise ValueError("kl() requires two list arguments: kl([p1,p2,...], [q1,q2,...])")
            if fn == "correlation":
                if len(node.args) == 2 and isinstance(node.args[0], ast.List) and isinstance(node.args[1], ast.List):
                    x = [_ev(e) for e in node.args[0].elts]
                    y = [_ev(e) for e in node.args[1].elts]
                    return _correlation(x, y)
                raise ValueError("correlation() requires two list arguments")
        raise ValueError(f"unsupported: {ast.dump(node)}")

    expr = expression.strip().replace("^", "**")
    tree = ast.parse(expr, mode="eval")
    return _ev(tree)


# ---------------------------------------------------------------------------
# Format output
# ---------------------------------------------------------------------------

def _fmt(v):
    """Format a number: use int format if it's a whole number."""
    if isinstance(v, float) and v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return str(v)


def _fmt_list(vs):
    return ", ".join(_fmt(v) for v in vs)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

HELP = """\
Usage: calcs.py CMD [args...]

Commands:
  eval "expression" [var=value ...]   Safe math eval (supports all functions)
  linreg x1,x2,... y1,y2,...          Linear regression -> slope, intercept
  polyfit x1,x2,... y1,y2,... DEG    Polynomial fit (degree 1-3) -> c0, c1, ...
  pct_change old new                  Percentage change
  cagr start end years                Compound annual growth rate (%)
  stdev v1,v2,...                      Sample standard deviation
  pstdev v1,v2,...                     Population standard deviation
  mean v1,v2,...                       Arithmetic mean
  median v1,v2,...                     Median
  geometric_mean v1,v2,...             Geometric mean
  variance v1,v2,...                   Sample variance
  cv v1,v2,...                         Coefficient of variation (%)
  theil v1,v2,...                      Theil index
  kl p1,p2,... q1,q2,...              KL divergence
  gini v1,v2,...                       Gini coefficient
  hhi v1,v2,...                        Herfindahl-Hirschman Index
  correlation x1,x2,... y1,y2,...     Pearson correlation
  moving_avg v1,v2,... WINDOW         Moving average
  help                                 Show this message

eval functions (composable in expressions):
  abs, round, min, max, sqrt, log, log10, exp, pow, sum, len,
  mean, stdev, pstdev, median, variance, geometric_mean, harmonic_mean,
  cv, pct_change, cagr, theil, gini, hhi, kl, correlation

Examples:
  calcs.py eval "pct_change(100, 150)"
  calcs.py eval "mean([10,20,30]) + stdev([10,20,30])"
  calcs.py eval "x * 1.05" x=1000
  calcs.py linreg 1,2,3,4 10,20,30,40
  calcs.py polyfit 1,2,3,4 10,20,30,40 2
  calcs.py pct_change 100 150
  calcs.py cagr 100 200 10
  calcs.py moving_avg 1,2,3,4,5 3
"""


def main():
    if len(sys.argv) < 2 or sys.argv[1] == "help":
        print(HELP.strip())
        sys.exit(0)

    cmd = sys.argv[1]

    try:
        if cmd == "eval":
            if len(sys.argv) < 3:
                print("Error: eval requires an expression")
                sys.exit(1)
            expr = sys.argv[2]
            vs = {}
            for arg in sys.argv[3:]:
                k, v = arg.split("=", 1)
                vs[k.strip()] = float(v.strip())
            result = safe_eval(expr, vs)
            print(_fmt(result))

        elif cmd == "linreg":
            x = _parse_list(sys.argv[2])
            y = _parse_list(sys.argv[3])
            slope, intercept = _linreg(x, y)
            print(f"{_fmt(slope)}, {_fmt(intercept)}")

        elif cmd == "polyfit":
            x = _parse_list(sys.argv[2])
            y = _parse_list(sys.argv[3])
            deg = int(sys.argv[4])
            coeffs = _polyfit(x, y, deg)
            print(_fmt_list(coeffs))

        elif cmd == "pct_change":
            old, new = float(sys.argv[2]), float(sys.argv[3])
            print(_fmt(_pct_change(old, new)))

        elif cmd == "cagr":
            start, end, years = float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
            print(_fmt(_cagr(start, end, years)))

        elif cmd == "stdev":
            print(_fmt(_stdev(_parse_list(sys.argv[2]))))

        elif cmd == "pstdev":
            print(_fmt(_pstdev(_parse_list(sys.argv[2]))))

        elif cmd == "mean":
            print(_fmt(_mean(_parse_list(sys.argv[2]))))

        elif cmd == "median":
            print(_fmt(_median(_parse_list(sys.argv[2]))))

        elif cmd == "geometric_mean":
            print(_fmt(_geometric_mean(_parse_list(sys.argv[2]))))

        elif cmd == "variance":
            print(_fmt(_variance(_parse_list(sys.argv[2]))))

        elif cmd == "cv":
            print(_fmt(_cv(_parse_list(sys.argv[2]))))

        elif cmd == "theil":
            print(_fmt(_theil(_parse_list(sys.argv[2]))))

        elif cmd == "kl":
            p = _parse_list(sys.argv[2])
            q = _parse_list(sys.argv[3])
            print(_fmt(_kl(p, q)))

        elif cmd == "gini":
            print(_fmt(_gini(_parse_list(sys.argv[2]))))

        elif cmd == "hhi":
            print(_fmt(_hhi(_parse_list(sys.argv[2]))))

        elif cmd == "correlation":
            x = _parse_list(sys.argv[2])
            y = _parse_list(sys.argv[3])
            print(_fmt(_correlation(x, y)))

        elif cmd == "moving_avg":
            v = _parse_list(sys.argv[2])
            window = int(sys.argv[3])
            result = _moving_avg(v, window)
            print(_fmt_list(result))

        else:
            print(f"Unknown command: {cmd}")
            print("Run 'calcs.py help' for usage.")
            sys.exit(1)

    except (IndexError, ValueError) as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
