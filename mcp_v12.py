#!/usr/bin/env python3
"""MCP stdio server v12 — tools MiniMax might actually use.

Tools:
  search_files(query) — grep across all /app/resources/ files, return matching lines with context
  get_cpi(year) — CPI-U annual average 1913-2024
  fiscal_year(year) — FY start/end dates (pre/post 1977)
  calculate(expression) — safe math with stats functions
"""
import ast, glob, json, math, os, re, statistics, subprocess, sys

# ── CPI-U Annual Averages ────────────────────────────────────────────────────
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

# ── Tool definitions ─────────────────────────────────────────────────────────
TOOLS = [
    {
        "name": "search_files",
        "description": (
            "Search all files in /app/resources/ for a keyword or pattern. "
            "Returns matching lines with 2 lines of context. "
            "Use this instead of grep to find specific values, row labels, or table headers. "
            "Much faster than reading entire files."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term or regex pattern"},
                "file_pattern": {"type": "string", "description": "Optional glob like '*_page_*.txt' to limit search", "default": "*"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_cpi",
        "description": "Get CPI-U annual average (base 1982-84=100) for inflation adjustment. Covers 1913-2024. Use: real = nominal * (target_cpi / source_cpi).",
        "inputSchema": {
            "type": "object",
            "properties": {"year": {"type": "integer", "description": "Calendar year (1913-2024)"}},
            "required": ["year"],
        },
    },
    {
        "name": "fiscal_year",
        "description": "Get U.S. fiscal year date boundaries. Before 1977: Jul-Jun. From 1977: Oct-Sep.",
        "inputSchema": {
            "type": "object",
            "properties": {"year": {"type": "integer", "description": "Fiscal year number"}},
            "required": ["year"],
        },
    },
    {
        "name": "calculate",
        "description": (
            "Calculate a math expression. Supports: +, -, *, /, **, abs, round, min, max, sum, sqrt, log, exp, "
            "mean, stdev, pstdev, median, variance, pct_change(old,new), cagr(start,end,years)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Math expression, e.g. 'pct_change(1000, 1500)' or 'stdev([10,20,30])'"},
            },
            "required": ["expression"],
        },
    },
]

# ── search_files implementation ──────────────────────────────────────────────
def search_files(query, file_pattern="*"):
    resource_dir = "/app/resources/"
    pattern = os.path.join(resource_dir, file_pattern)
    files = sorted(glob.glob(pattern))
    if not files:
        return f"No files matching {file_pattern} in {resource_dir}"
    
    results = []
    for fpath in files:
        if os.path.isdir(fpath):
            continue
        try:
            with open(fpath, 'r', errors='replace') as f:
                lines = f.readlines()
            for i, line in enumerate(lines):
                if re.search(query, line, re.IGNORECASE):
                    start = max(0, i - 2)
                    end = min(len(lines), i + 3)
                    context = ''.join(lines[start:end])
                    results.append(f"--- {os.path.basename(fpath)} line {i+1} ---\n{context}")
        except:
            continue
    
    if not results:
        return f"No matches for '{query}' in {len(files)} files"
    
    # Limit output size
    output = '\n'.join(results[:20])
    if len(results) > 20:
        output += f"\n... and {len(results)-20} more matches"
    return output

# ── Safe expression evaluator ────────────────────────────────────────────────
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
        if isinstance(node, ast.Expression): return _ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id in variables: return float(variables[node.id])
            raise ValueError(f"unknown variable: {node.id}")
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub): return -_ev(node.operand)
            if isinstance(node.op, ast.UAdd): return _ev(node.operand)
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
        raise ValueError(f"unsupported: {ast.dump(node)}")
    expr = expression.strip().replace("^", "**")
    tree = ast.parse(expr, mode="eval")
    return _ev(tree)

# ── Tool dispatch ────────────────────────────────────────────────────────────
def call_tool(name, arguments):
    if name == "search_files":
        return search_files(arguments["query"], arguments.get("file_pattern", "*"))
    
    if name == "get_cpi":
        yr = int(arguments["year"])
        val = CPI.get(yr)
        if val is None:
            return f"CPI not available for {yr}. Range: 1913-2024."
        return json.dumps({"year": yr, "cpi": val})
    
    if name == "fiscal_year":
        fy = int(arguments["year"])
        if fy <= 1976:
            return json.dumps({"fy": fy, "start": f"{fy-1}-07-01", "end": f"{fy}-06-30", "rule": "pre-1977 Jul-Jun"})
        return json.dumps({"fy": fy, "start": f"{fy-1}-10-01", "end": f"{fy}-09-30", "rule": "post-1976 Oct-Sep"})
    
    if name == "calculate":
        expr = arguments["expression"]
        try:
            result = _safe_eval(expr)
            return json.dumps({"result": result, "expression": expr})
        except Exception as e:
            return json.dumps({"error": str(e), "expression": expr})
    
    return json.dumps({"error": f"unknown tool: {name}"})

# ── MCP JSON-RPC protocol ───────────────────────────────────────────────────
def handle_message(msg):
    method = msg.get("method", "")
    mid = msg.get("id")
    if mid is None:
        return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "officeqa-tools", "version": "2.0.0"},
        }}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params", {})
        try:
            text = call_tool(params.get("name", ""), params.get("arguments", {}))
        except Exception as e:
            text = json.dumps({"error": str(e)})
        return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line: continue
        try:
            msg = json.loads(line)
        except:
            continue
        resp = handle_message(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

if __name__ == "__main__":
    main()
