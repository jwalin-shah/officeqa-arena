#!/usr/bin/env python3
"""OfficeQA Arena CLI — self-contained, zero external deps.
Commands: search  read  calc  cpi  fy  index  ask  verify
"""
import ast, json, math, os, re, sqlite3, statistics, sys, urllib.request

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
INDEX_DB = "/tmp/officeqa_index.db"
ANSWER_FILE = os.environ.get("ANSWER_PATH", "/app/answer.txt")
CALL_LOG = "/tmp/officeqa_tool_calls.count"

def _bump_call_count():
    """Track total tool calls across invocations. Nag after 8."""
    try:
        n = int(open(CALL_LOG).read().strip()) + 1 if os.path.exists(CALL_LOG) else 1
    except Exception:
        n = 1
    open(CALL_LOG, "w").write(str(n))
    if n >= 12:
        print(f"\n*** STOP SEARCHING. Write your answer NOW: printf '%s' \"VALUE\" > {ANSWER_FILE} ***\n", file=sys.stderr)
    elif n >= 8 and not os.path.exists(ANSWER_FILE):
        print(f"\n--- {n} tool calls used. No answer.txt yet. Write your best answer soon. ---\n", file=sys.stderr)
    return n

def _auto_draft(value):
    """Write a draft answer.txt if none exists yet."""
    if not os.path.exists(ANSWER_FILE):
        try:
            os.makedirs(os.path.dirname(ANSWER_FILE), exist_ok=True)
            open(ANSWER_FILE, "w").write(str(value))
            print(f"  [draft answer.txt written: {value}]", file=sys.stderr)
        except Exception:
            pass

# --- safe AST evaluator ---
def _safe_eval(expression, variables=None):
    variables = variables or {}
    def _col(args):
        r = []
        for a in args:
            r.extend(_ev(e) for e in a.elts) if isinstance(a, ast.List) else r.append(_ev(a))
        return r
    def _ev(n):
        if isinstance(n, ast.Expression): return _ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)): return float(n.value)
        if isinstance(n, ast.Name):
            if n.id in variables: return float(variables[n.id])
            raise ValueError(f"unknown variable: {n.id}")
        if isinstance(n, ast.UnaryOp):
            if isinstance(n.op, ast.USub): return -_ev(n.operand)
            if isinstance(n.op, ast.UAdd): return _ev(n.operand)
        if isinstance(n, ast.BinOp):
            L, R, op = _ev(n.left), _ev(n.right), n.op
            if isinstance(op, ast.Add): return L + R
            if isinstance(op, ast.Sub): return L - R
            if isinstance(op, ast.Mult): return L * R
            if isinstance(op, ast.Div):
                if R == 0: raise ValueError("division by zero")
                return L / R
            if isinstance(op, ast.Pow): return L ** R
            if isinstance(op, ast.Mod): return L % R
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            fn = n.func.id
            if fn == "abs": return abs(_ev(n.args[0]))
            if fn == "round":
                a = [_ev(x) for x in n.args]
                return round(a[0], int(a[1])) if len(a) == 2 else round(a[0])
            if fn in ("min", "max"): return (min if fn == "min" else max)(_col(n.args))
            if fn == "sqrt": return math.sqrt(_ev(n.args[0]))
            if fn == "log": return math.log(*[_ev(x) for x in n.args])
            if fn == "exp": return math.exp(_ev(n.args[0]))
            if fn == "sum": return sum(_col(n.args))
            if fn == "mean": v = _col(n.args); return sum(v) / len(v)
            if fn == "stdev": return statistics.stdev(_col(n.args))
            if fn == "pstdev": return statistics.pstdev(_col(n.args))
            if fn == "median": return statistics.median(_col(n.args))
            if fn == "pct_change":
                a = [_ev(x) for x in n.args]
                if a[0] == 0: raise ValueError("division by zero")
                return (a[1] - a[0]) / a[0] * 100
            if fn == "cagr":
                a = [_ev(x) for x in n.args]
                return ((a[1] / a[0]) ** (1.0 / a[2]) - 1) * 100
            if fn == "variance": return statistics.variance(_col(n.args))
            if fn == "pvariance": return statistics.pvariance(_col(n.args))
            if fn == "geometric_mean": return statistics.geometric_mean(_col(n.args))
            if fn == "harmonic_mean": return statistics.harmonic_mean(_col(n.args))
        raise ValueError(f"unsupported: {ast.dump(n)}")
    return _ev(ast.parse(expression.strip().replace("^", "**"), mode="eval"))

def _txt_files(dirs):
    out = []
    for d in dirs:
        if os.path.isdir(d):
            for root, _, fns in os.walk(d):
                out.extend(os.path.join(root, f) for f in fns if f.endswith(".txt"))
    return out

def _parse_flag(args, flag):
    """Return (value, remaining_args) for --flag VALUE."""
    try:
        i = args.index(flag)
        return args[i + 1], args[:i] + args[i + 2:]
    except (ValueError, IndexError):
        return None, args

# --- cmd: search ---
def cmd_search(args):
    _bump_call_count()
    year, args = _parse_flag(args, "--year")
    dir_val, args = _parse_flag(args, "--dir")
    query = " ".join(args).strip()
    if not query:
        print("Usage: search \"query\" [--year YYYY] [--dir DIR]"); return
    dirs = [dir_val] if dir_val else [
        os.environ.get("RESOURCES_DIR", "/app/resources"),
        os.environ.get("CORPUS_DIR", "/app/corpus"),
    ]
    year_str = str(year) if year else None

    db_hits = []
    if os.path.exists(INDEX_DB):
        try:
            con = sqlite3.connect(INDEX_DB)
            like = f"%{query.lower()}%"
            db_hits = con.execute(
                "SELECT file_path, start_line, header_text FROM table_headers "
                "WHERE lower(keywords) LIKE ? OR lower(header_text) LIKE ? LIMIT 20",
                (like, like),
            ).fetchall()
            con.close()
        except Exception:
            pass

    txt_files = _txt_files(dirs)
    if not txt_files:
        print("No .txt files found."); return

    results, terms = [], query.lower().split()
    for fpath in txt_files:
        boost = 2 if (year_str and year_str in os.path.basename(fpath)) else 1
        try:
            lines = open(fpath, encoding="utf-8", errors="replace").readlines()
        except OSError:
            continue
        for idx, line in enumerate(lines):
            ll = line.lower()
            hits = sum(1 for t in terms if t in ll)
            if not hits: continue
            ctx = "".join(lines[max(0, idx-1):idx+2]).rstrip()
            results.append((hits * boost, fpath, idx + 1, ctx))

    results.sort(key=lambda x: -x[0])
    seen, printed = set(), 0
    for score, fpath, lineno, ctx in results:
        k = (fpath, lineno)
        if k in seen: continue
        seen.add(k)
        print(f"[{fpath}:{lineno}] (score={score})")
        for ln in ctx.splitlines(): print(f"  {ln}")
        print()
        printed += 1
        if printed >= 10: break

    if db_hits and printed == 0:
        print("--- SQLite index matches ---")
        for fp, sl, ht in db_hits[:5]:
            print(f"[{fp}:{sl}] {ht}")
    elif printed == 0:
        print(f"No matches found for: {query}")

# --- table parser ---
def _parse_table(lines, row_filter=None, year_filter=None, max_rows=80):
    pc = sum(1 for l in lines if l.count("|") >= 2)
    tc = sum(1 for l in lines if l.count("\t") >= 2)
    delim = "|" if pc >= tc else "\t"
    rows = []
    for l in lines:
        if l.rstrip("\n").count(delim) >= 2:
            parts = [c.strip() for c in l.rstrip("\n").split(delim) if c.strip()]
            if parts: rows.append(parts)
    if not rows: return None
    hi = next((i for i, r in enumerate(rows) if len(r) >= 2), 0)
    headers = rows[hi]
    if year_filter:
        yr = str(year_filter)
        keep = [0] + [j for j, h in enumerate(headers) if yr in h]
        if len(keep) <= 1: keep = list(range(len(headers)))
    else:
        keep = list(range(len(headers)))
    out, n = [], 0
    for row in rows[hi + 1:]:
        if not row: continue
        label = row[0]
        if row_filter and row_filter.lower() not in label.lower(): continue
        for j in keep[1:]:
            if j < len(row):
                out.append(f"{label}, {headers[j] if j < len(headers) else f'col{j}'}: {row[j]}")
        n += 1
        if n >= max_rows:
            out.append(f"... truncated at {max_rows} rows ..."); break
    return "\n".join(out) if out else "(no matching rows)"

# --- cmd: read ---
def cmd_read(args):
    _bump_call_count()
    if not args:
        print("Usage: read FILE [--lines START-END] [--row-filter TEXT] [--year YYYY]"); return
    fpath = args[0]
    lr, args = _parse_flag(args[1:], "--lines")
    rf, args = _parse_flag(args, "--row-filter")
    yf, args = _parse_flag(args, "--year")
    if not os.path.exists(fpath):
        print(f"File not found: {fpath}"); return
    all_lines = open(fpath, encoding="utf-8", errors="replace").readlines()
    if lr:
        m = re.match(r"(\d+)-(\d+)", lr)
        lines = all_lines[int(m.group(1))-1:int(m.group(2))] if m else all_lines
    else:
        lines = all_lines
    result = _parse_table(lines, row_filter=rf, year_filter=yf)
    if result is not None:
        print(result)
    else:
        raw = "".join(lines)
        print(raw[:3000])
        if len(raw) > 3000: print(f"... (truncated, total {len(raw)} chars) ...")

# --- cmd: calc ---
def cmd_calc(args):
    _bump_call_count()
    if not args:
        print("Usage: calc \"expression\" [var=value ...]"); return
    expr, vs = args[0], {}
    for arg in args[1:]:
        if "=" in arg:
            k, v = arg.split("=", 1); vs[k.strip()] = float(v.strip())
    r = _safe_eval(expr, vs)
    out = int(r) if isinstance(r, float) and r == int(r) and abs(r) < 1e15 else r
    print(out)
    _auto_draft(out)

# --- cmd: cpi ---
def cmd_cpi(args):
    if not args: print("Usage: cpi YYYY"); return
    v = CPI.get(int(args[0]))
    print(v if v is not None else f"CPI not available for {args[0]}. Range: 1913-2024.")

# --- cmd: fy ---
def cmd_fy(args):
    if not args: print("Usage: fy YYYY"); return
    fy = int(args[0])
    if fy <= 1976: print(f"FY{fy}: Jul {fy-1} – Jun {fy}  (pre-1977: Jul-Jun)")
    else:          print(f"FY{fy}: Oct {fy-1} – Sep {fy}  (post-1976: Oct-Sep)")

# --- cmd: index ---
def cmd_index(args):
    dir_val, args = _parse_flag(args, "--dir")
    d = dir_val or "/app/corpus"
    txt_files = _txt_files([d])
    if not txt_files: print(f"No .txt files found in {d}"); return
    con = sqlite3.connect(INDEX_DB)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS files
            (path TEXT PRIMARY KEY, year_from_filename TEXT, month_from_filename TEXT, line_count INTEGER);
        CREATE TABLE IF NOT EXISTS table_headers
            (id INTEGER PRIMARY KEY AUTOINCREMENT, file_path TEXT, start_line INTEGER,
             end_line INTEGER, header_text TEXT, years_present TEXT, units TEXT, keywords TEXT);
    """)
    yr_re = re.compile(r"\b(19[0-9]{2}|20[0-2][0-9])\b")
    un_re = re.compile(r"\b(million|billion|thousand|percent|%|dollars)\b", re.I)
    fi, ti = 0, 0
    for fpath in txt_files:
        bn = os.path.basename(fpath)
        ym = re.findall(r"_(\d{4})_(\d{2})_", bn)
        yr_fn, mo_fn = (ym[0][0], ym[0][1]) if ym else (None, None)
        try:
            lines = open(fpath, encoding="utf-8", errors="replace").readlines()
        except OSError:
            continue
        con.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?)", (fpath, yr_fn, mo_fn, len(lines)))
        in_t, ts, ht = False, None, None
        def flush(end_idx, ts=None, ht=None):
            nonlocal ti
            if ht is None: return
            txt = " ".join(l.strip() for l in lines[ts:end_idx][:5])
            yrs = ",".join(sorted(set(yr_re.findall(txt))))
            uts = ",".join(sorted(set(m.lower() for m in un_re.findall(txt))))
            kw = re.sub(r"[|]", " ", ht).lower()
            con.execute(
                "INSERT INTO table_headers (file_path,start_line,end_line,header_text,years_present,units,keywords) VALUES(?,?,?,?,?,?,?)",
                (fpath, ts+1, end_idx, ht, yrs, uts, kw))
            ti += 1
        for idx, line in enumerate(lines):
            is_row = line.count("|") >= 3 or line.count("\t") >= 3
            if is_row and not in_t:
                in_t, ts, ht = True, idx, line.strip()
            elif not is_row and in_t:
                flush(idx, ts, ht); in_t, ts, ht = False, None, None
        if in_t: flush(len(lines), ts, ht)
        fi += 1
    con.commit(); con.close()
    print(f"Indexed {fi} files, {ti} table sections -> {INDEX_DB}")

DEFAULT_ASK_MODEL = "meta-llama/llama-4-scout"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

def _read_file_content(fpath, lines_flag):
    """Read file content, optionally restricted to a line range. Returns up to 4000 chars."""
    if not os.path.exists(fpath):
        return None, f"File not found: {fpath}"
    all_lines = open(fpath, encoding="utf-8", errors="replace").readlines()
    if lines_flag:
        m = re.match(r"(\d+)-(\d+)", lines_flag)
        lines = all_lines[int(m.group(1))-1:int(m.group(2))] if m else all_lines
    else:
        lines = all_lines
    content = "".join(lines)
    return content[:4000], None

def _openrouter_call(system_prompt, user_content, model, api_key):
    """Make a single OpenRouter chat completion call. Returns (text, error)."""
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 100,
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"].strip(), None
    except Exception as e:
        return None, str(e)

# --- cmd: ask ---
def cmd_ask(args):
    _bump_call_count()
    model, args = _parse_flag(args, "--model")
    lines_flag, args = _parse_flag(args, "--lines")
    model = model or DEFAULT_ASK_MODEL
    if len(args) < 2:
        print("Usage: ask FILE \"question\" [--lines N-M] [--model MODEL]"); return
    fpath, question = args[0], args[1]
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print("Error: OPENROUTER_API_KEY env var not set"); return
    content, err = _read_file_content(fpath, lines_flag)
    if err:
        print(err); return
    system = ("You are a data extraction assistant. Given the table data below, "
              "answer the question with ONLY the numeric value. No explanation, no units, just the number.")
    user = f"DATA:\n{content}\n\nQUESTION: {question}"
    answer, err = _openrouter_call(system, user, model, api_key)
    if err:
        print(f"API error: {err}"); print("Could not verify"); return
    print(answer)

# --- cmd: verify ---
def cmd_verify(args):
    _bump_call_count()
    model, args = _parse_flag(args, "--model")
    lines_flag, args = _parse_flag(args, "--lines")
    model = model or DEFAULT_ASK_MODEL
    if len(args) < 3:
        print("Usage: verify FILE \"question\" \"proposed_answer\" [--lines N-M] [--model MODEL]"); return
    fpath, question, proposed = args[0], args[1], args[2]
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print("Error: OPENROUTER_API_KEY env var not set"); return
    content, err = _read_file_content(fpath, lines_flag)
    if err:
        print(err); return
    system = "You are a data verification assistant. Given table data, check whether a proposed answer is correct."
    user = (f"DATA:\n{content}\n\n"
            f"QUESTION: {question}\n"
            f"PROPOSED ANSWER: {proposed}\n\n"
            "Is this correct? If not, what is the correct answer? "
            "Reply with CORRECT or WRONG: [correct_value]")
    answer, err = _openrouter_call(system, user, model, api_key)
    if err:
        print(f"API error: {err}"); print("Could not verify"); return
    print(answer)

COMMANDS = {"search": cmd_search, "read": cmd_read, "calc": cmd_calc,
            "cpi": cmd_cpi, "fy": cmd_fy, "index": cmd_index,
            "ask": cmd_ask, "verify": cmd_verify}

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__.strip()); return
    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        print(f"Unknown command: {cmd}. Available: {', '.join(COMMANDS)}"); sys.exit(1)
    COMMANDS[cmd](sys.argv[2:])

if __name__ == "__main__":
    main()
