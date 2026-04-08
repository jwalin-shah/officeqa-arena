#!/usr/bin/env python3
"""Zero-dependency MCP stdio server for OfficeQA Arena.

Implements the MCP JSON-RPC protocol using only Python stdlib.
Provides: get_cpi, compute, fiscal_year_bounds

Goose spawns this as a stdio extension. Reads JSON lines from stdin,
writes JSON lines to stdout. All logging goes to stderr.
"""
import json
import math
import statistics
import sys

# ── CPI-U Annual Averages (BLS, base 1982-84=100) ──────────────────────────
CPI = {
    1913:9.9,1914:10.0,1915:10.1,1916:10.9,1917:12.8,1918:15.1,1919:17.3,
    1920:20.0,1921:17.9,1922:16.8,1923:17.1,1924:17.1,1925:17.5,1926:17.7,
    1927:17.4,1928:17.2,1929:17.2,1930:16.7,1931:15.2,1932:13.6,1933:12.9,
    1934:13.4,1935:13.7,1936:13.9,1937:14.4,1938:14.1,1939:13.9,1940:14.0,
    1941:14.7,1942:16.3,1943:17.3,1944:17.6,1945:18.0,1946:19.5,1947:22.3,
    1948:24.1,1949:23.8,1950:24.1,1951:26.0,1952:26.5,1953:26.7,1954:26.9,
    1955:26.8,1956:27.2,1957:28.1,1958:28.9,1959:29.1,1960:29.6,1961:29.9,
    1962:30.2,1963:30.6,1964:31.0,1965:31.5,1966:32.4,1967:33.4,1968:34.8,
    1969:36.7,1970:38.8,1971:40.5,1972:41.8,1973:44.4,1974:49.3,1975:53.8,
    1976:56.9,1977:60.6,1978:65.2,1979:72.6,1980:82.4,1981:90.9,1982:96.5,
    1983:99.6,1984:103.9,1985:107.6,1986:109.6,1987:113.6,1988:118.3,
    1989:124.0,1990:130.7,1991:136.2,1992:140.3,1993:144.5,1994:148.2,
    1995:152.4,1996:156.9,1997:160.5,1998:163.0,1999:166.6,2000:172.2,
    2001:177.1,2002:179.9,2003:184.0,2004:188.9,2005:195.3,2006:201.6,
    2007:207.3,2008:215.3,2009:214.5,2010:218.1,2011:224.9,2012:229.6,
    2013:233.0,2014:236.7,2015:237.0,2016:240.0,2017:245.1,2018:251.1,
    2019:255.7,2020:258.8,2021:271.0,2022:292.7,2023:304.7,2024:314.2,
}

# ── Tool definitions ────────────────────────────────────────────────────────
TOOLS = [
    {
        "name": "get_cpi",
        "description": (
            "Get CPI-U annual average index (BLS, base 1982-84=100). "
            "Use for inflation adjustment: real = nominal * (target_cpi / source_cpi). "
            "Covers 1913-2024."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "year": {"type": "integer", "description": "Calendar year (1913-2024)"}
            },
            "required": ["year"],
        },
    },
    {
        "name": "fiscal_year_bounds",
        "description": (
            "Get U.S. federal fiscal year start/end dates. "
            "Pre-1977: Jul 1 (Y-1) to Jun 30 (Y). Post-1976: Oct 1 (Y-1) to Sep 30 (Y)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "fiscal_year": {"type": "integer", "description": "Fiscal year number"}
            },
            "required": ["fiscal_year"],
        },
    },
    {
        "name": "compute",
        "description": (
            "Safe math evaluator. Supports: +, -, *, /, ** (power), abs(), round(), "
            "min(), max(), sum(), sqrt(), log(), exp(), mean(), stdev(), median(), "
            "pct_change(old,new), cagr(start,end,years). "
            "Pass variable values in the 'vars' dict."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "expr": {"type": "string", "description": "Math expression"},
                "vars": {
                    "type": "object",
                    "description": "Variable name->value mapping",
                    "additionalProperties": {"type": "number"},
                },
            },
            "required": ["expr"],
        },
    },
]

# ── Safe expression evaluator ───────────────────────────────────────────────
import ast

def _safe_eval(expression, variables=None):
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
            if isinstance(op, ast.Add): return L + R
            if isinstance(op, ast.Sub): return L - R
            if isinstance(op, ast.Mult): return L * R
            if isinstance(op, ast.Div):
                if R == 0: raise ValueError("division by zero")
                return L / R
            if isinstance(op, ast.Pow): return L ** R
            if isinstance(op, ast.Mod): return L % R
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn = node.func.id
            if fn == "abs": return abs(_ev(node.args[0]))
            if fn == "round":
                a = [_ev(x) for x in node.args]
                return round(a[0], int(a[1])) if len(a) == 2 else round(a[0])
            if fn in ("min", "max"):
                return min(_collect(node.args)) if fn == "min" else max(_collect(node.args))
            if fn == "sqrt": return math.sqrt(_ev(node.args[0]))
            if fn == "log":
                a = [_ev(x) for x in node.args]
                return math.log(*a)
            if fn == "ln": return math.log(_ev(node.args[0]))
            if fn == "exp": return math.exp(_ev(node.args[0]))
            if fn == "sum": return sum(_collect(node.args))
            if fn == "mean":
                v = _collect(node.args)
                return sum(v) / len(v)
            if fn == "stdev": return statistics.stdev(_collect(node.args))
            if fn == "pstdev": return statistics.pstdev(_collect(node.args))
            if fn == "median": return statistics.median(_collect(node.args))
            if fn == "variance": return statistics.variance(_collect(node.args))
            if fn == "pct_change":
                a = [_ev(x) for x in node.args]
                if a[0] == 0: raise ValueError("division by zero")
                return (a[1] - a[0]) / a[0] * 100
            if fn == "cagr":
                a = [_ev(x) for x in node.args]
                return ((a[1] / a[0]) ** (1.0 / a[2]) - 1) * 100
            if fn == "pow": return _ev(node.args[0]) ** _ev(node.args[1])
        raise ValueError(f"unsupported: {ast.dump(node)}")

    expr = expression.strip().replace("^", "**")
    tree = ast.parse(expr, mode="eval")
    return _ev(tree)

# ── Tool dispatch ───────────────────────────────────────────────────────────

def call_tool(name, arguments):
    if name == "get_cpi":
        yr = int(arguments["year"])
        val = CPI.get(yr)
        if val is None:
            return f"CPI not found for {yr}. Available: 1913-2024."
        return json.dumps({"year": yr, "cpi": val, "basis": "CPI-U annual avg, 1982-84=100"})

    if name == "fiscal_year_bounds":
        fy = int(arguments["fiscal_year"])
        if fy <= 1976:
            return json.dumps({"fy": fy, "start": f"{fy-1}-07-01", "end": f"{fy}-06-30", "note": "pre-1977 Jul-Jun"})
        return json.dumps({"fy": fy, "start": f"{fy-1}-10-01", "end": f"{fy}-09-30", "note": "post-1976 Oct-Sep"})

    if name == "compute":
        expr = arguments["expr"]
        vs = {k: float(v) for k, v in (arguments.get("vars") or {}).items()}
        try:
            result = _safe_eval(expr, vs)
            return json.dumps({"result": result, "expr": expr})
        except Exception as e:
            return json.dumps({"error": str(e), "expr": expr})

    return json.dumps({"error": f"unknown tool: {name}"})

# ── MCP JSON-RPC stdio protocol ────────────────────────────────────────────

def handle_message(msg):
    """Handle one JSON-RPC message, return response dict or None for notifications."""
    method = msg.get("method", "")
    mid = msg.get("id")

    # Notifications (no id) — just acknowledge
    if mid is None:
        return None

    if method == "initialize":
        try:
            with open("/tmp/_mcp_initialized.txt", "w") as _f:
                _f.write("initialize called\n")
        except: pass
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "officeqa-minimal", "version": "1.0.0"},
            },
        }

    if method == "tools/list":
        # Breadcrumb: prove this was called
        try:
            with open("/tmp/_mcp_tools_listed.txt", "w") as _f:
                _f.write("tools/list called\n")
        except: pass
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {"tools": TOOLS},
        }

    if method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name", "")
        arguments = params.get("arguments", {})
        try:
            text = call_tool(name, arguments)
        except Exception as e:
            text = json.dumps({"error": str(e)})
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "content": [{"type": "text", "text": text}],
            },
        }

    # Unknown method
    return {
        "jsonrpc": "2.0",
        "id": mid,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main():
    print("officeqa-minimal MCP server starting", file=sys.stderr, flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            print(f"bad json: {line[:100]}", file=sys.stderr, flush=True)
            continue

        resp = handle_message(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
            print(f"handled: {msg.get('method','')} id={msg.get('id','')}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
