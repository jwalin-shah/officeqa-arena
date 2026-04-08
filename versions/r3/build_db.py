#!/usr/bin/env python3
"""Parse all .txt files in /app/resources/ into a SQLite DB at /tmp/data.db.
Run once at start: python3 /app/resources/build_db.py

Creates tables:
  - cells(file, table_num, row_label, col_header, value, raw_value)
  - tables_meta(file, table_num, first_header_row)

Query with: python3 /app/resources/q.py "SQL"
"""
import sqlite3, re, os, sys, glob

DB_PATH = "/tmp/data.db"
RES_DIR = os.environ.get("RES_DIR", "/app/resources")

def parse_html_tables(html, filename):
    """Extract all HTML tables into (table_num, row_label, col_header, value, raw) tuples."""
    results = []
    table_num = 0

    for table_match in re.finditer(r'<table>(.*?)</table>', html, re.DOTALL):
        table_num += 1
        table_html = table_match.group(1)
        rows_raw = re.findall(r'<tr>(.*?)</tr>', table_html, re.DOTALL)

        # Build grid with rowspan/colspan
        grid = []
        pending = {}

        for ri, row_html in enumerate(rows_raw):
            cells = re.findall(r'<(th|td)(.*?)>(.*?)</(?:th|td)>', row_html, re.DOTALL)
            row = []
            ci = 0

            while (ri, ci) in pending:
                row.append(pending.pop((ri, ci)))
                ci += 1

            for tag, attrs, content in cells:
                while (ri, ci) in pending:
                    row.append(pending.pop((ri, ci)))
                    ci += 1

                val = re.sub(r'<[^>]+>', '', content).strip()
                colspan = int(m.group(1)) if (m := re.search(r'colspan="(\d+)"', attrs)) else 1
                rowspan = int(m.group(1)) if (m := re.search(r'rowspan="(\d+)"', attrs)) else 1

                for c in range(colspan):
                    while (ri, ci) in pending:
                        row.append(pending.pop((ri, ci)))
                        ci += 1
                    row.append(val if c == 0 else "")
                    for r in range(1, rowspan):
                        pending[(ri + r, ci)] = val if c == 0 else ""
                    ci += 1

            while (ri, ci) in pending:
                row.append(pending.pop((ri, ci)))
                ci += 1

            grid.append(row)

        if len(grid) < 2:
            continue

        # Determine headers: first 1-2 rows
        headers = grid[0]
        data_start = 1

        # Check if row 2 is sub-headers
        if len(grid) > 2:
            row2 = grid[1]
            non_empty = [c for c in row2 if c.strip()]
            if non_empty and all(len(c) < 40 for c in non_empty):
                numeric = sum(1 for c in non_empty if re.match(r'^[\d,.\-()\$% ]+$', c.strip()))
                if numeric < len(non_empty) / 2:
                    merged = []
                    for i in range(max(len(headers), len(row2))):
                        h1 = headers[i].strip() if i < len(headers) else ""
                        h2 = row2[i].strip() if i < len(row2) else ""
                        merged.append(f"{h1} > {h2}" if h1 and h2 else h1 or h2)
                    headers = merged
                    data_start = 2

        # Extract cells
        first_header = " | ".join(h.strip() for h in headers)
        for row in grid[data_start:]:
            if not row or not any(c.strip() for c in row):
                continue
            row_label = row[0].strip() if row else ""
            for ci in range(1, min(len(row), len(headers))):
                raw_val = row[ci].strip() if ci < len(row) else ""
                if not raw_val or raw_val in ("-", "•", "*", "..."):
                    continue
                # Clean value
                cleaned = raw_val
                cleaned = re.sub(r'\s*\d+/', '', cleaned)  # footnotes
                if cleaned.startswith('(') and cleaned.endswith(')'):
                    cleaned = '-' + cleaned[1:-1]
                cleaned = cleaned.rstrip(' p').strip()
                col_header = headers[ci].strip() if ci < len(headers) else f"col_{ci}"

                results.append((filename, table_num, row_label, col_header, cleaned, raw_val, first_header))

    return results

def parse_pipe_tables(text, filename):
    """Parse markdown pipe-delimited tables into same format as HTML parser."""
    results = []
    lines = text.split("\n")
    table_num = 0
    i = 0
    while i < len(lines):
        if re.match(r'^\|[\s-]+\|', lines[i]):
            table_num += 1
            sep_idx = i
            header_start = sep_idx - 1
            while header_start > 0 and '|' in lines[header_start - 1] and lines[header_start - 1].strip().startswith('|'):
                header_start -= 1

            header_cells = []
            for hi in range(header_start, sep_idx):
                cells = [c.strip() for c in lines[hi].split('|')]
                cells = [c for c in cells if c]
                if not header_cells:
                    header_cells = cells
                else:
                    for ci in range(min(len(header_cells), len(cells))):
                        if cells[ci] and cells[ci] != header_cells[ci]:
                            header_cells[ci] = f"{header_cells[ci]} > {cells[ci]}"

            first_header = " | ".join(header_cells)

            j = sep_idx + 1
            while j < len(lines) and '|' in lines[j]:
                cells = [c.strip() for c in lines[j].split('|')]
                cells = [c for c in cells if c or len([x for x in cells if x]) > 1]
                if cells and cells[0] == '':
                    cells = cells[1:]
                if cells and cells[-1] == '':
                    cells = cells[:-1]
                if cells and any(c.strip() for c in cells):
                    row_label = cells[0].strip()
                    for ci in range(1, min(len(cells), len(header_cells))):
                        raw_val = cells[ci].strip() if ci < len(cells) else ""
                        if not raw_val or raw_val in ("-", "•", "*", "...", "nan"):
                            continue
                        cleaned = raw_val
                        cleaned = re.sub(r'\s*\d+/', '', cleaned)
                        if cleaned.startswith('(') and cleaned.endswith(')'):
                            cleaned = '-' + cleaned[1:-1]
                        cleaned = cleaned.rstrip(' p').strip()
                        col_header = header_cells[ci].strip() if ci < len(header_cells) else f"col_{ci}"
                        results.append((filename, table_num, row_label, col_header, cleaned, raw_val, first_header))
                j += 1
            i = j
        else:
            i += 1
    return results

def build():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE cells (
        file TEXT, table_num INT, row_label TEXT, col_header TEXT,
        value TEXT, raw_value TEXT
    )""")
    c.execute("""CREATE TABLE tables_meta (
        file TEXT, table_num INT, headers TEXT
    )""")

    txt_files = glob.glob(os.path.join(RES_DIR, "*.txt"))
    total_cells = 0
    tables_seen = set()

    for fp in txt_files:
        fname = os.path.basename(fp)
        try:
            html = open(fp).read()
        except:
            continue

        rows = parse_html_tables(html, fname)
        if not rows:
            rows = parse_pipe_tables(html, fname)
        for file, tnum, rl, ch, val, raw, hdr in rows:
            c.execute("INSERT INTO cells VALUES (?,?,?,?,?,?)", (file, tnum, rl, ch, val, raw))
            total_cells += 1
            key = (file, tnum)
            if key not in tables_seen:
                tables_seen.add(key)
                c.execute("INSERT INTO tables_meta VALUES (?,?,?)", (file, tnum, hdr))

    c.execute("CREATE INDEX idx_cells_row ON cells(row_label)")
    c.execute("CREATE INDEX idx_cells_col ON cells(col_header)")
    c.execute("CREATE INDEX idx_cells_file ON cells(file)")
    c.execute("CREATE INDEX idx_cells_value ON cells(value)")
    conn.commit()
    conn.close()

    print(f"Built {DB_PATH}: {total_cells} cells from {len(txt_files)} files, {len(tables_seen)} tables")

if __name__ == "__main__":
    build()
