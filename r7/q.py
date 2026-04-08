#!/usr/bin/env python3
"""Query treasury data. Auto-builds DB from .txt files on first run.

Usage:
  python3 q.py preview                — see all tables, columns, sample data
  python3 q.py search TERM            — find rows/columns matching term
  python3 q.py "SELECT ... FROM cells ..."  — run SQL

Schema: cells(file, table_num, row_label, col_label, time_key, value, value_num, raw)
  row_label = row identifier (e.g. "1955", "January", "Army")
  col_label = fully qualified column (e.g. "Defense Department Military functions")
  time_key  = normalized YYYY or YYYY-MM (e.g. "1955", "1955-07")
  value     = cleaned string, value_num = float or NULL

Examples:
  python3 q.py "SELECT col_label, value FROM cells WHERE time_key='1955' AND col_label LIKE '%Defense%'"
  python3 q.py "SELECT DISTINCT col_label FROM cells"
  python3 q.py search defense
"""
import sqlite3, re, os, sys, glob
from html.parser import HTMLParser

RES_DIR = os.environ.get("RES_DIR", "/app/resources")
DB_PATH = os.environ.get("DB_PATH", os.path.join(RES_DIR, "data.db"))

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
# HTML table parser (from reingest_from_json.py — handles colspan/rowspan)
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
        self._pending = {}  # (row, col) -> value
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
            # Fill pending rowspan cells
            while (self._ri, ci) in self._pending:
                self._cur.append(self._pending.pop((self._ri, ci)))
                ci = len(self._cur)
            # Add this cell (with colspan expansion)
            for c in range(self._colspan):
                ci = len(self._cur)
                while (self._ri, ci) in self._pending:
                    self._cur.append(self._pending.pop((self._ri, ci)))
                    ci = len(self._cur)
                self._cur.append(text if c == 0 else text)
                # Set rowspan pending
                for r in range(1, self._rowspan):
                    self._pending[(self._ri + r, ci)] = text if c == 0 else text
            self._in_cell = False
        elif tag == "tr" and self._cur is not None:
            # Drain any remaining pending for this row
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
# Multi-row header merging (from reingest_from_json.py)
# ---------------------------------------------------------------------------
def _merge_headers(rows):
    """Detect and merge multi-row headers. Returns (headers, data_rows)."""
    if len(rows) < 3:
        return ([str(c or "").strip() for c in rows[0]] if rows else [], rows[1:] if rows else [])

    first = [str(c or "").strip() for c in rows[0]]
    second = [str(c or "").strip() for c in rows[1]]

    data_cells = first[1:] if len(first) > 1 else first
    if not data_cells:
        return first, rows[1:]

    # Detect multi-row headers: either empty cells (old colspan) or repeated
    # parent values (rowspan-expanded) with different sub-header values
    empty_count = sum(1 for c in data_cells if not c)
    repeat_count = sum(1 for i, c in enumerate(data_cells) if i > 0 and c == data_cells[i-1] and c)
    # Check if row 2 has different non-numeric values in those positions
    differs = 0
    for i in range(min(len(first), len(second))):
        if first[i] and second[i] and first[i] != second[i]:
            if not re.match(r'^[\d,.\-()\$% ]+$', second[i].strip()):
                differs += 1

    is_multi_row = (empty_count / len(data_cells) > 0.5 if data_cells else False) or \
                   (repeat_count >= 2 and differs >= 2)

    # Case 1: multi-row header -> merge parent + sub-header
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

    # Case 2: year cols + month sub-headers
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
    """Clean a raw cell value: footnotes, parens=negative, preliminary markers."""
    t = str(v or "").strip()
    t = re.sub(r'\s*\d+/', '', t)  # footnotes like 1/, 2/
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
    """Parse a row label into a time_key like '1955' or '1955-07'."""
    raw = str(label or "").strip().lower().rstrip(".")
    # "1955-January" or "1958-January"
    m = re.match(r'^(\d{4})[-/]\s*(' + _MONTH_PAT + r')\.?', raw, re.I)
    if m:
        return f"{m.group(1)}-{_MONTHS[m.group(2).lower().rstrip('.').strip()]:02d}"
    # "January 1955"
    m = re.match(r'^(' + _MONTH_PAT + r')\.?\s+(\d{4})', raw, re.I)
    if m:
        return f"{m.group(2)}-{_MONTHS[m.group(1).lower().rstrip('.').strip()]:02d}"
    # Just a year like "1955" or "1955 p" or "1959 (Est.)"
    m = re.match(r'^(\d{4})\b', raw)
    if m:
        return m.group(1)
    # Month name alone (possibly with trailing p/r/e marker)
    cleaned = re.sub(r'\s*[pre]\s*$', '', raw).rstrip(".")
    if cleaned in _MONTHS and active_year:
        return f"{active_year}-{_MONTHS[cleaned]:02d}"
    return ""

# ---------------------------------------------------------------------------
# DB builder
# ---------------------------------------------------------------------------
def build_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
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

        # Extract table title from text before first <table>
        title = ""
        pre_table = content.split("<table>")[0] if "<table>" in content else ""
        # Look for lines like "Table 2.- Expenditures by Agencies"
        for line in pre_table.split("\n"):
            line = line.strip()
            if line.startswith("Table ") or line.startswith("TABLE "):
                title = line
                break
            if len(line) > 10 and not line.startswith("```") and not line.startswith("#"):
                title = line  # last meaningful line before table

        tables = _parse_tables(content)
        for ti, grid in enumerate(tables):
            if len(grid) < 2:
                continue
            headers, data_rows = _merge_headers(grid)
            header_str = " | ".join(h for h in headers)
            meta.append((fname, ti + 1, title, header_str))

            # Detect active year from filename (e.g. treasury_bulletin_1958_10)
            ym = re.search(r'(\d{4})_(\d{2})', fname)
            file_year = int(ym.group(1)) if ym else None
            active_year = file_year  # track most recent year seen

            for row in data_rows:
                if not row or not any(str(x or "").strip() for x in row):
                    continue
                row_label = str(row[0] or "").strip()

                # Update active year from row labels
                m = re.match(r'^(\d{4})\b', row_label)
                if m:
                    active_year = int(m.group(1))

                time_key = _parse_time_key(row_label, active_year)

                for ci in range(1, min(len(row), len(headers))):
                    raw_val = str(row[ci] or "").strip()
                    if not raw_val or raw_val in ("-", "•", "*", "...", "—"):
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


def ensure_db():
    if not os.path.exists(DB_PATH):
        n_cells, n_files, n_tables = build_db()
        print(f"[Built DB: {n_cells} cells from {n_files} files, {n_tables} tables]")


# ---------------------------------------------------------------------------
# Query commands
# ---------------------------------------------------------------------------
def do_preview(conn):
    print("=== TABLES ===\n")
    for row in conn.execute("SELECT file, table_num, title, headers FROM tables_meta ORDER BY file, table_num"):
        file, tnum, title, headers = row
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


def do_search(conn, term):
    t = f"%{term}%"
    print(f"=== Searching '{term}' ===\n")
    cols = conn.execute("SELECT DISTINCT col_label FROM cells WHERE col_label LIKE ? LIMIT 20", (t,)).fetchall()
    if cols:
        print("Columns matching:")
        for c in cols:
            print(f"  {c[0]}")
        print()
    rows = conn.execute(
        "SELECT file, table_num, row_label, col_label, value FROM cells WHERE row_label LIKE ? OR col_label LIKE ? LIMIT 30",
        (t, t)).fetchall()
    if rows:
        print("Data matching:")
        for r in rows:
            print(f"  [{r[0]} T{r[1]}] row={r[2]} | col={r[3]} | val={r[4]}")


def do_query(conn, query):
    try:
        cur = conn.execute(query)
        cols = [d[0] for d in cur.description] if cur.description else []
        if cols:
            print(" | ".join(cols))
            print("-" * 60)
        count = 0
        for row in cur:
            print(" | ".join(str(v) for v in row))
            count += 1
            if count >= 500:
                print(f"... (truncated at 500)")
                break
        if count == 0:
            print("(no results)")
    except Exception as e:
        print(f"Error: {e}")


def main():
    ensure_db()
    if len(sys.argv) < 2:
        print(__doc__)
        return

    conn = sqlite3.connect(DB_PATH)
    cmd = sys.argv[1].strip().lower()
    if cmd == "preview":
        do_preview(conn)
    elif cmd == "search":
        do_search(conn, " ".join(sys.argv[2:]))
    else:
        do_query(conn, " ".join(sys.argv[1:]))


if __name__ == "__main__":
    main()
