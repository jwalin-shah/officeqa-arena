#!/usr/bin/env python3
"""Zero-dependency MCP stdio server for v15 — 4 tools: search, read_table, compute, get_cpi."""
import ast, json, math, os, re, sqlite3, statistics, sys
from pathlib import Path

# --- Anti-spin & caching ---
_call_count = 0
_cache = {}
WARN_AT, STOP_AT = 10, 15
NAG_AT = 8

ANSWER_PATH = os.environ.get("ANSWER_PATH", "/app/answer.txt")


def _auto_draft(value):
    """Write a draft answer if none exists yet."""
    if not os.path.exists(ANSWER_PATH):
        try:
            os.makedirs(os.path.dirname(ANSWER_PATH) or ".", exist_ok=True)
            open(ANSWER_PATH, "w").write(str(value))
        except Exception:
            pass

# --- CPI-U annual averages (1913-2024) ---
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

# --- Tool: search ---
def search(query, year=None, dir=None):
    keywords = query.lower().split()
    results = []
    # SQLite index fast path
    idx = Path("/tmp/officeqa_index.db")
    if idx.exists():
        try:
            con = sqlite3.connect(str(idx))
            ph = " OR ".join("header LIKE ?" for _ in keywords)
            for file, header, line_no in con.execute(
                f"SELECT file, header, line_no FROM table_headers WHERE {ph} LIMIT 20",
                [f"%{kw}%" for kw in keywords],
            ).fetchall():
                results.append((10, file, line_no, header))
            con.close()
        except Exception:
            pass
    dirs = ([Path(dir)] if dir else []) + [
        Path(os.environ.get("RESOURCES_DIR", "/app/resources")),
        Path(os.environ.get("CORPUS_DIR", "/app/corpus")),
    ]
    seen = {r[1] for r in results}
    for d in dirs:
        if not d.exists(): continue
        for fp in sorted(d.rglob("*.txt")):
            if not fp.is_file() or str(fp) in seen: continue
            try: lines = fp.read_text(errors="replace").split("\n")
            except Exception: continue
            for i, ll in enumerate(l.lower() for l in lines):
                if all(kw in ll for kw in keywords):
                    score = sum(ll.count(kw) for kw in keywords) + (5 if year and str(year) in fp.name else 0)
                    results.append((score, str(fp), i + 1, lines[i].strip()))
                    seen.add(str(fp))
                    break
    results.sort(key=lambda x: -x[0])
    out = []
    for _, fp, lineno, ctx in results[:10]:
        try:
            al = Path(fp).read_text(errors="replace").split("\n")
            context = "\n".join(al[max(0, lineno-2):lineno+2])
        except Exception:
            context = ctx
        out.append({"file": fp, "line": lineno, "context": context})
    return json.dumps(out if out else [{"message": "no matches found"}])


# --- Tool: read_table ---
def read_table(file_path, start_line=None, end_line=None, row_filter=None, year=None):
    fp = Path(file_path)
    if not fp.exists(): return json.dumps({"error": f"file not found: {file_path}"})
    try: all_lines = fp.read_text(errors="replace").split("\n")
    except Exception as e: return json.dumps({"error": str(e)})
    if start_line is not None or end_line is not None:
        lines = all_lines[max(0, (start_line or 1) - 1):(end_line or len(all_lines))]
    else:
        lines = all_lines
    sample = "\n".join(lines[:20])
    delim = "\t" if sample.count("\t") > sample.count("|") else "|"
    header_idx = next(
        (i for i, ln in enumerate(lines) if len([c for c in ln.split(delim) if c.strip()]) >= 2),
        None
    )
    if header_idx is None: return sample[:3000]
    headers = [c.strip() for c in lines[header_idx].split(delim)]
    col_indices = list(range(len(headers)))
    if year:
        filtered = [0] + [j for j in range(1, len(headers)) if str(year) in headers[j]]
        if len(filtered) > 1: col_indices = filtered
    out, row_count = [], 0
    for ln in lines[header_idx + 1:]:
        if row_count >= 80: break
        row = [c.strip() for c in ln.split(delim)]
        if not any(row): continue
        label = row[0] if row else ""
        if row_filter and row_filter.lower() not in label.lower(): continue
        for j in col_indices[1:]:
            if j < len(row) and row[j]:
                out.append(f"{label}, {headers[j] if j < len(headers) else f'col{j}'}: {row[j]}")
        row_count += 1
    return "\n".join(out) if out else sample[:3000]


# --- Tool: compute ---
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

def compute(expression, variables=None):
    try:
        result = _safe_eval(expression, variables)
        _auto_draft(result)
        return json.dumps({"result": result, "expression": expression,
                           "note": "Draft answer saved. Refine if needed."})
    except Exception as e:
        return json.dumps({"error": str(e), "expression": expression})


# --- Tool: get_cpi ---
def get_cpi(year):
    if year in CPI:
        return json.dumps({"year": year, "cpi_u": CPI[year], "base": "1982-84=100"})
    return json.dumps({"error": f"no CPI data for {year}", "range": "1913-2024"})


# --- Tool schemas ---
TOOLS = [
    {
        "name": "search",
        "description": "Search for tables in Treasury Bulletin files using grep-style matching. Returns top 10 matches with file path, line number, and 3-line context.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keywords (space-separated)"},
                "year": {"type": "integer", "description": "Target year — boosts files with that year in filename"},
                "dir": {"type": "string", "description": "Override search directory (optional)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_table",
        "description": "Read and parse a section of a file as a table with vertical serialization (ROW_LABEL, COLUMN: VALUE). Supports line range, row filter, and year column filter.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to the file"},
                "start_line": {"type": "integer", "description": "First line to read (1-indexed)"},
                "end_line": {"type": "integer", "description": "Last line to read (inclusive)"},
                "row_filter": {"type": "string", "description": "Only return rows whose label contains this substring (case-insensitive)"},
                "year": {"type": "integer", "description": "Only include columns containing this year"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "compute",
        "description": "Safe math evaluator. Supports: +,-,*,/,**,%, abs, round, min, max, sum, mean, sqrt, log, exp, stdev, pstdev, median, pct_change(old,new), cagr(start,end,years)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Math expression to evaluate"},
                "variables": {"type": "object", "description": "Optional variable name-to-value mapping"},
            },
            "required": ["expression"],
        },
    },
    {
        "name": "get_cpi",
        "description": "Return CPI-U annual average index for a given year (1913-2024, base 1982-84=100)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "year": {"type": "integer", "description": "Year to look up"},
            },
            "required": ["year"],
        },
    },
]

# --- Dispatch ---
DISPATCH = {
    "search": lambda args: search(args["query"], args.get("year"), args.get("dir")),
    "read_table": lambda args: read_table(
        args["file_path"], args.get("start_line"), args.get("end_line"),
        args.get("row_filter"), args.get("year")
    ),
    "compute": lambda args: compute(args["expression"], args.get("variables")),
    "get_cpi": lambda args: get_cpi(args["year"]),
}

# --- JSON-RPC handler ---
def handle(msg):
    global _call_count
    method = msg.get("method", "")
    mid = msg.get("id")

    if mid is None:
        return None

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "officeqa-v15-mcp", "version": "0.1.0"},
        }}

    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}

    if method == "tools/call":
        params = msg.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        _call_count += 1
        if _call_count > STOP_AT:
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": "HARD STOP: 15 tool calls reached. Write answer.txt NOW with your best answer."}],
                "isError": True,
            }}

        cache_key = json.dumps([tool_name, arguments], sort_keys=True)
        if cache_key in _cache:
            text = _cache[cache_key]
            if _call_count >= WARN_AT:
                text += f"\n\nWARNING: {_call_count}/{STOP_AT} calls used. Wrap up and write answer.txt."
            elif _call_count >= NAG_AT and not os.path.exists(ANSWER_PATH):
                text += f"\n\nNo answer.txt yet — write your answer NOW."
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": text}],
            }}

        fn = DISPATCH.get(tool_name)
        if not fn:
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": f"unknown tool: {tool_name}"}],
                "isError": True,
            }}

        try:
            text = fn(arguments)
        except Exception as e:
            text = json.dumps({"error": str(e)})

        _cache[cache_key] = text

        if _call_count >= WARN_AT:
            text += f"\n\nWARNING: {_call_count}/{STOP_AT} calls used. Wrap up and write answer.txt."
        elif _call_count >= NAG_AT and not os.path.exists(ANSWER_PATH):
            text += f"\n\nNo answer.txt yet — write your answer NOW."

        return {"jsonrpc": "2.0", "id": mid, "result": {
            "content": [{"type": "text", "text": text}],
        }}

    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method: {method}"}}

# --- Main loop ---
def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(msg)
        if resp:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

if __name__ == "__main__":
    main()
