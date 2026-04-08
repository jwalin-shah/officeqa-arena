#!/usr/bin/env python3
"""Query Treasury Bulletin data from pre-built SQLite DB.

Usage:
  python3 q.py                        -- show this help + schema
  python3 q.py preview                -- list all files/tables with columns
  python3 q.py tables                 -- list all (file, table_num) with headers
  python3 q.py columns FILE [TABLE]   -- list distinct col_labels for a file
  python3 q.py search TERM [TERM2 ..] -- search rows matching ALL terms (top 50)
  python3 q.py lookup FILE TBL ROW COL -- lookup a specific cell
  python3 q.py "SELECT ..."           -- run arbitrary SQL

Schema: cells(file, table_num, row_label, col_label, time_key, value, value_num, raw)
  row_label = row identifier (e.g. "1955", "January", "Army")
  col_label = fully qualified column (e.g. "Defense Department Military functions")
  time_key  = normalized YYYY or YYYY-MM (e.g. "1955", "1955-07")
  value     = cleaned string, value_num = float or NULL, raw = original text

Examples:
  python3 q.py search defense 1955
  python3 q.py "SELECT col_label, value FROM cells WHERE time_key='1955' AND col_label LIKE '%Defense%'"
  python3 q.py lookup page_6.txt 1 "1955" "Total"
  python3 q.py columns page_6.txt
"""
import sqlite3, re, os, sys, glob, gzip, shutil
from html.parser import HTMLParser

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
_DB_CANDIDATES = [
    os.environ.get("DB_PATH", ""),
    "/installed-agent/data/db.sqlite",
    "/installed-agent/data/db.sqlite.gz",
]
RES_DIR = os.environ.get("RES_DIR", "/app/resources")

def _resolve_db():
    """Find or create DB. Returns path to usable SQLite file."""
    # Explicit override
    env_path = os.environ.get("DB_PATH", "")
    if env_path and os.path.exists(env_path):
        return env_path

    # Pre-built DB
    plain = "/installed-agent/data/db.sqlite"
    if os.path.exists(plain):
        return plain

    # Gzipped pre-built DB
    gz = "/installed-agent/data/db.sqlite.gz"
    if os.path.exists(gz):
        out = plain if os.access(os.path.dirname(plain), os.W_OK) else "/tmp/db.sqlite"
        if not os.path.exists(out):
            with gzip.open(gz, "rb") as f_in, open(out, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            print(f"[Decompressed DB: {gz} -> {out}]", file=sys.stderr)
        return out

    # Fallback: build from .txt files in /app/resources/ (task-specific data)
    fallback_path = "/tmp/task_data.db"
    if os.path.exists(fallback_path):
        return fallback_path

    txt_files = glob.glob(os.path.join(RES_DIR, "*.txt"))
    if not txt_files:
        print(f"ERROR: No DB found and no .txt files in {RES_DIR}", file=sys.stderr)
        sys.exit(1)

    n_cells, n_files, n_tables = _build_db(fallback_path)
    print(f"[Built DB from {RES_DIR} .txt files: {n_cells} cells, {n_files} files, {n_tables} tables]", file=sys.stderr)
    return fallback_path


# ---------------------------------------------------------------------------
# Month parsing
# ---------------------------------------------------------------------------
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_PAT = "|".join(_MONTHS.keys())

# ---------------------------------------------------------------------------
# HTML table parser (handles colspan/rowspan)
# ---------------------------------------------------------------------------
class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self._rows = []
        self._cur = []
        self._cell = []
        self._in_cell = False
        self._colspan = 1
        self._rowspan = 1
        self._pending = {}
        self._ri = -1

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._rows = []
            self._pending = {}
            self._ri = -1
        elif tag == "tr":
            self._ri += 1
            self._cur = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._cell = []
            self._colspan = 1
            self._rowspan = 1
            for name, value in attrs:
                if name == "colspan" and value:
                    try: self._colspan = max(1, int(value))
                    except: pass
                if name == "rowspan" and value:
                    try: self._rowspan = max(1, int(value))
                    except: pass

    def handle_data(self, data):
        if self._in_cell:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._in_cell:
            text = " ".join("".join(self._cell).split()).strip()
            ci = len(self._cur)
            while (self._ri, ci) in self._pending:
                self._cur.append(self._pending.pop((self._ri, ci)))
                ci = len(self._cur)
            for c in range(self._colspan):
                ci = len(self._cur)
                while (self._ri, ci) in self._pending:
                    self._cur.append(self._pending.pop((self._ri, ci)))
                    ci = len(self._cur)
                self._cur.append(text)
                for r in range(1, self._rowspan):
                    self._pending[(self._ri + r, ci)] = text
            self._in_cell = False
        elif tag == "tr" and self._cur is not None:
            ci = len(self._cur)
            while (self._ri, ci) in self._pending:
                self._cur.append(self._pending.pop((self._ri, ci)))
                ci = len(self._cur)
            if self._cur:
                self._rows.append(self._cur)
        elif tag == "table" and self._rows:
            self.tables.append(self._rows)


def _parse_tables(html):
    p = _TableParser()
    try:
        p.feed(html)
    except:
        pass
    return p.tables

# ---------------------------------------------------------------------------
# Multi-row header merging
# ---------------------------------------------------------------------------
def _merge_headers(rows):
    if len(rows) < 3:
        return ([str(c or "").strip() for c in rows[0]] if rows else [], rows[1:] if rows else [])

    first = [str(c or "").strip() for c in rows[0]]
    second = [str(c or "").strip() for c in rows[1]]
    data_cells = first[1:] if len(first) > 1 else first
    if not data_cells:
        return first, rows[1:]

    empty_count = sum(1 for c in data_cells if not c)
    repeat_count = sum(1 for i, c in enumerate(data_cells) if i > 0 and c == data_cells[i-1] and c)
    differs = 0
    for i in range(min(len(first), len(second))):
        if first[i] and second[i] and first[i] != second[i]:
            if not re.match(r'^[\d,.\-()\$% ]+$', second[i].strip()):
                differs += 1

    is_multi_row = (empty_count / len(data_cells) > 0.5 if data_cells else False) or \
                   (repeat_count >= 2 and differs >= 2)

    if is_multi_row and len(second) >= len(first):
        merged = []
        for i in range(max(len(first), len(second))):
            top = first[i] if i < len(first) else ""
            bot = second[i] if i < len(second) else ""
            if top and bot and top != bot:
                merged.append(f"{top} {bot}")
            elif top:
                merged.append(top)
            else:
                merged.append(bot)
        return merged, rows[2:]

    if len(first) == len(second):
        year_count = sum(1 for c in data_cells if re.fullmatch(r"(?:19|20)\d{2}", c))
        second_data = second[1:] if len(second) > 1 else second
        month_count = sum(1 for c in second_data if c.strip().lower().rstrip(".") in _MONTHS)
        if data_cells and year_count / len(data_cells) > 0.5 and second_data and month_count / len(second_data) > 0.3:
            merged = []
            for i in range(len(first)):
                top = first[i]
                bot = second[i] if i < len(second) else ""
                if top and bot and re.fullmatch(r"(?:19|20)\d{2}", top):
                    merged.append(f"{bot} {top}")
                elif top and bot:
                    merged.append(f"{top} {bot}")
                elif top:
                    merged.append(top)
                else:
                    merged.append(bot)
            return merged, rows[2:]

    return first, rows[1:]

# ---------------------------------------------------------------------------
# Numeric & time parsing
# ---------------------------------------------------------------------------
def _clean_value(v):
    t = str(v or "").strip()
    t = re.sub(r'\s*\d+/', '', t)
    t = t.rstrip(' p').rstrip(' r').rstrip(' e').strip()
    if t.startswith('(') and t.endswith(')'):
        t = '-' + t[1:-1]
    return t

def _to_float(v):
    t = _clean_value(v).replace(',', '').replace('$', '').replace('%', '').strip()
    try:
        return float(t)
    except:
        return None

def _parse_time_key(label, active_year=None):
    raw = str(label or "").strip().lower().rstrip(".")
    m = re.match(r'^(\d{4})[-/]\s*(' + _MONTH_PAT + r')\.?', raw, re.I)
    if m:
        return f"{m.group(1)}-{_MONTHS[m.group(2).lower().rstrip('.').strip()]:02d}"
    m = re.match(r'^(' + _MONTH_PAT + r')\.?\s+(\d{4})', raw, re.I)
    if m:
        return f"{m.group(2)}-{_MONTHS[m.group(1).lower().rstrip('.').strip()]:02d}"
    m = re.match(r'^(\d{4})\b', raw)
    if m:
        return m.group(1)
    cleaned = re.sub(r'\s*[pre]\s*$', '', raw).rstrip(".")
    if cleaned in _MONTHS and active_year:
        return f"{active_year}-{_MONTHS[cleaned]:02d}"
    return ""

# ---------------------------------------------------------------------------
# Fallback DB builder (from .txt files)
# ---------------------------------------------------------------------------
def _build_db(db_path):
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""CREATE TABLE cells (
        file TEXT, table_num INT, row_label TEXT, col_label TEXT,
        time_key TEXT, value TEXT, value_num REAL, raw TEXT
    )""")
    c.execute("""CREATE TABLE tables_meta (
        file TEXT, table_num INT, title TEXT, headers TEXT
    )""")

    txt_files = sorted(glob.glob(os.path.join(RES_DIR, "*.txt")))
    total = 0
    meta = []

    for fp in txt_files:
        fname = os.path.basename(fp)
        try:
            content = open(fp).read()
        except:
            continue

        title = ""
        pre_table = content.split("<table>")[0] if "<table>" in content else ""
        for line in pre_table.split("\n"):
            line = line.strip()
            if line.startswith("Table ") or line.startswith("TABLE "):
                title = line
                break
            if len(line) > 10 and not line.startswith("```") and not line.startswith("#"):
                title = line

        tables = _parse_tables(content)
        for ti, grid in enumerate(tables):
            if len(grid) < 2:
                continue
            headers, data_rows = _merge_headers(grid)
            header_str = " | ".join(h for h in headers)
            meta.append((fname, ti + 1, title, header_str))

            ym = re.search(r'(\d{4})_(\d{2})', fname)
            file_year = int(ym.group(1)) if ym else None
            active_year = file_year

            for row in data_rows:
                if not row or not any(str(x or "").strip() for x in row):
                    continue
                row_label = str(row[0] or "").strip()

                m = re.match(r'^(\d{4})\b', row_label)
                if m:
                    active_year = int(m.group(1))

                time_key = _parse_time_key(row_label, active_year)

                for ci in range(1, min(len(row), len(headers))):
                    raw_val = str(row[ci] or "").strip()
                    if not raw_val or raw_val in ("-", "\u2022", "*", "...", "\u2014"):
                        continue
                    col = headers[ci] if ci < len(headers) else f"col_{ci}"
                    cleaned = _clean_value(raw_val)
                    num = _to_float(raw_val)
                    c.execute("INSERT INTO cells VALUES (?,?,?,?,?,?,?,?)",
                              (fname, ti + 1, row_label, col, time_key, cleaned, num, raw_val))
                    total += 1

    for m in meta:
        c.execute("INSERT INTO tables_meta VALUES (?,?,?,?)", m)

    c.execute("CREATE INDEX idx_time ON cells(time_key)")
    c.execute("CREATE INDEX idx_col ON cells(col_label)")
    c.execute("CREATE INDEX idx_row ON cells(row_label)")
    c.execute("CREATE INDEX idx_file ON cells(file)")
    conn.commit()
    conn.close()
    return total, len(txt_files), len(meta)


# ---------------------------------------------------------------------------
# Query commands
# ---------------------------------------------------------------------------
def _print_table(headers, rows, max_width=60):
    """Print aligned columns, truncating to max_width per column."""
    if not rows:
        print("(no results)")
        return
    all_rows = [headers] + [[str(v) for v in r] for r in rows]
    widths = [0] * len(headers)
    for r in all_rows:
        for i, v in enumerate(r):
            if i < len(widths):
                widths[i] = min(max(widths[i], len(v)), max_width)
    fmt = " | ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*[h[:max_width] for h in headers]))
    print("-+-".join("-" * w for w in widths))
    for r in rows:
        vals = [(str(v)[:max_width] if v is not None else "") for v in r]
        while len(vals) < len(widths):
            vals.append("")
        print(fmt.format(*vals))


def do_preview(conn):
    """List all files and tables with column headers and sample data."""
    rows = conn.execute(
        "SELECT file, table_num, title, headers FROM tables_meta ORDER BY file, table_num"
    ).fetchall()
    if not rows:
        # No tables_meta — try cells directly
        rows = conn.execute(
            "SELECT DISTINCT file, table_num FROM cells ORDER BY file, table_num"
        ).fetchall()
        for file, tnum in rows:
            print(f"FILE: {file}  TABLE: {tnum}")
            cols = conn.execute(
                "SELECT DISTINCT col_label FROM cells WHERE file=? AND table_num=? LIMIT 20",
                (file, tnum)).fetchall()
            print(f"  Columns: {', '.join(c[0] for c in cols)}")
            labels = conn.execute(
                "SELECT DISTINCT row_label FROM cells WHERE file=? AND table_num=? LIMIT 10",
                (file, tnum)).fetchall()
            print(f"  Rows: {', '.join(r[0] for r in labels)}")
            print()
        return

    for file, tnum, title, headers in rows:
        print(f"FILE: {file}  TABLE: {tnum}")
        if title:
            print(f"  Title: {title}")
        print(f"  Columns: {headers}")
        labels = conn.execute(
            "SELECT DISTINCT row_label FROM cells WHERE file=? AND table_num=? LIMIT 15",
            (file, tnum)).fetchall()
        print(f"  Rows: {', '.join(r[0] for r in labels)}")
        sample = conn.execute(
            "SELECT row_label, col_label, value FROM cells WHERE file=? AND table_num=? LIMIT 3",
            (file, tnum)).fetchall()
        for s in sample:
            print(f"  Ex: row={s[0]}, col={s[1]}, val={s[2]}")
        print()


def do_tables(conn):
    """List all distinct (file, table_num) with headers."""
    # Try tables_meta first
    rows = conn.execute(
        "SELECT file, table_num, title, headers FROM tables_meta ORDER BY file, table_num"
    ).fetchall()
    if rows:
        for file, tnum, title, headers in rows:
            label = f"{file} T{tnum}"
            if title:
                label += f"  {title[:80]}"
            print(label)
            print(f"  {headers}")
        return

    # Fallback: derive from cells
    rows = conn.execute(
        "SELECT DISTINCT file, table_num FROM cells ORDER BY file, table_num"
    ).fetchall()
    for file, tnum in rows:
        cols = conn.execute(
            "SELECT DISTINCT col_label FROM cells WHERE file=? AND table_num=? LIMIT 20",
            (file, tnum)).fetchall()
        print(f"{file} T{tnum}")
        print(f"  {' | '.join(c[0] for c in cols)}")


def do_columns(conn, file, table_num=None):
    """List distinct col_labels for a file (optionally filtered by table)."""
    if table_num is not None:
        cols = conn.execute(
            "SELECT DISTINCT col_label FROM cells WHERE file=? AND table_num=?",
            (file, table_num)).fetchall()
    else:
        cols = conn.execute(
            "SELECT DISTINCT col_label FROM cells WHERE file=?",
            (file,)).fetchall()
    if not cols:
        # Try partial file match
        cols = conn.execute(
            "SELECT DISTINCT col_label FROM cells WHERE file LIKE ?",
            (f"%{file}%",)).fetchall()
    if cols:
        for c in cols:
            print(c[0])
    else:
        print(f"No columns found for file '{file}'")


def do_search(conn, terms):
    """Multi-term AND search across row_label, col_label, file. Ranked by match count."""
    if not terms:
        print("Usage: python3 q.py search TERM [TERM2 ...]")
        return

    # Build WHERE clause: each term must match at least one of the fields
    conditions = []
    params = []
    for term in terms:
        t = f"%{term}%"
        conditions.append(
            "(row_label LIKE ? COLLATE NOCASE OR col_label LIKE ? COLLATE NOCASE OR file LIKE ? COLLATE NOCASE)"
        )
        params.extend([t, t, t])

    where = " AND ".join(conditions)

    # Score by how many fields each row matches (more = more relevant)
    score_parts = []
    score_params = []
    for term in terms:
        t = f"%{term}%"
        score_parts.append(
            "(CASE WHEN row_label LIKE ? COLLATE NOCASE THEN 1 ELSE 0 END + "
            "CASE WHEN col_label LIKE ? COLLATE NOCASE THEN 1 ELSE 0 END + "
            "CASE WHEN file LIKE ? COLLATE NOCASE THEN 1 ELSE 0 END)"
        )
        score_params.extend([t, t, t])

    score_expr = " + ".join(score_parts)

    query = f"""
        SELECT file, table_num, row_label, col_label, value, value_num,
               ({score_expr}) as relevance
        FROM cells
        WHERE {where}
        ORDER BY relevance DESC, file, table_num, row_label
        LIMIT 50
    """
    all_params = score_params + params
    rows = conn.execute(query, all_params).fetchall()

    print(f"=== Search: {' + '.join(terms)} ({len(rows)} results) ===\n")

    if not rows:
        print("No matches found.")
        return

    # Print as table
    headers = ["file", "tbl", "row_label", "col_label", "value"]
    display = [(r[0], str(r[1]), r[2], r[3], r[4]) for r in rows]
    _print_table(headers, display)


def do_lookup(conn, file, table_num, row, col):
    """Look up a specific cell value."""
    rows = conn.execute(
        """SELECT row_label, col_label, value, value_num, raw
           FROM cells
           WHERE file LIKE ? AND table_num=?
             AND row_label LIKE ? AND col_label LIKE ?
           LIMIT 10""",
        (f"%{file}%", int(table_num), f"%{row}%", f"%{col}%")
    ).fetchall()
    if rows:
        for r in rows:
            print(f"row={r[0]} | col={r[1]} | value={r[2]} | num={r[3]} | raw={r[4]}")
    else:
        print(f"No cell found: file={file} table={table_num} row={row} col={col}")
        # Suggest closest matches
        nearby = conn.execute(
            "SELECT DISTINCT row_label FROM cells WHERE file LIKE ? AND table_num=? LIMIT 10",
            (f"%{file}%", int(table_num))).fetchall()
        if nearby:
            print(f"Available rows: {', '.join(r[0] for r in nearby)}")
        nearby_cols = conn.execute(
            "SELECT DISTINCT col_label FROM cells WHERE file LIKE ? AND table_num=? LIMIT 10",
            (f"%{file}%", int(table_num))).fetchall()
        if nearby_cols:
            print(f"Available cols: {', '.join(c[0] for c in nearby_cols)}")


def do_query(conn, query):
    """Run arbitrary SQL."""
    try:
        cur = conn.execute(query)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = []
        for row in cur:
            rows.append(row)
            if len(rows) >= 500:
                break
        if cols and rows:
            _print_table(cols, rows)
            if len(rows) >= 500:
                print("... (truncated at 500)")
        elif cols:
            print(" | ".join(cols))
            print("(no results)")
        else:
            print("OK")
    except Exception as e:
        print(f"SQL Error: {e}")


def _show_schema(conn):
    """Show DB stats alongside usage."""
    print(__doc__)
    try:
        cnt = conn.execute("SELECT COUNT(*) FROM cells").fetchone()[0]
        files = conn.execute("SELECT COUNT(DISTINCT file) FROM cells").fetchone()[0]
        tables = conn.execute("SELECT COUNT(DISTINCT file || '|' || table_num) FROM cells").fetchone()[0]
        print(f"DB: {cnt:,} cells across {files} files, {tables} tables\n")
    except:
        print("DB: (empty or not yet built)\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    db_path = _resolve_db()
    conn = sqlite3.connect(db_path)

    if len(sys.argv) < 2:
        _show_schema(conn)
        return

    cmd = sys.argv[1].strip()

    if cmd.lower() == "preview":
        do_preview(conn)
    elif cmd.lower() == "tables":
        do_tables(conn)
    elif cmd.lower() == "columns":
        if len(sys.argv) < 3:
            print("Usage: python3 q.py columns FILE [TABLE_NUM]")
            return
        file = sys.argv[2]
        tnum = int(sys.argv[3]) if len(sys.argv) > 3 else None
        do_columns(conn, file, tnum)
    elif cmd.lower() == "search":
        do_search(conn, [t.lower() for t in sys.argv[2:]])
    elif cmd.lower() == "lookup":
        if len(sys.argv) < 6:
            print("Usage: python3 q.py lookup FILE TABLE_NUM ROW COL")
            return
        do_lookup(conn, sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    elif cmd.upper().startswith("SELECT") or cmd.upper().startswith("WITH") or cmd.upper().startswith("PRAGMA"):
        do_query(conn, " ".join(sys.argv[1:]))
    else:
        # Try as SQL anyway
        do_query(conn, " ".join(sys.argv[1:]))


if __name__ == "__main__":
    main()
