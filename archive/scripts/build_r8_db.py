#!/usr/bin/env python3
"""Build r8/data/db.sqlite from parsed JSON files (HTML tables) using q.py's parser.

Reads from: /tmp/officeqa_reingest/officeqa_repo/treasury_bulletins_parsed/jsons/
Writes to:  r8/data/db.sqlite  (+  r8/data/db.sqlite.gz)
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'r8'))

from q import _parse_tables, _merge_headers, _clean_value, _to_float, _parse_time_key

import sqlite3, glob, re, gzip, shutil, json

JSON_DIR = '/tmp/officeqa_reingest/officeqa_repo/treasury_bulletins_parsed/jsons/'
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'r8', 'data', 'db.sqlite')
GZ_PATH = DB_PATH + '.gz'

# Values to skip -- not meaningful data
SKIP_VALUES = frozenset({
    "", "-", "\u2022", "*", "...", "\u2014", "nan", "n.a.", "n.a",
    ".....", "......", "....", "-*",
})

# Row labels that are section headers, not data rows
SKIP_ROW_PREFIXES = frozenset({
    "LIABILITIES", "ASSETS", "INCOME AND EXPENSE", "GOVERNMENT EQUITY",
})


def build():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("PRAGMA journal_mode=OFF")
    c.execute("PRAGMA synchronous=OFF")
    c.execute("PRAGMA page_size=4096")
    c.execute("""CREATE TABLE cells (
        file TEXT, table_num INT, row_label TEXT, col_label TEXT,
        time_key TEXT, value TEXT, value_num REAL, raw TEXT
    )""")
    c.execute("""CREATE TABLE tables_meta (
        file TEXT, table_num INT, title TEXT, headers TEXT
    )""")

    json_files = sorted(glob.glob(os.path.join(JSON_DIR, '*.json')))
    print(f"Found {len(json_files)} JSON files")

    total = 0
    skipped = 0
    meta = []
    batch = []
    BATCH_SIZE = 50000
    n_tables_total = 0

    for fi, fp in enumerate(json_files):
        fname = os.path.basename(fp).replace('.json', '.txt')
        try:
            with open(fp) as f:
                data = json.load(f)
        except Exception as e:
            print(f"  SKIP {fname}: {e}")
            continue

        elements = data.get('document', {}).get('elements', [])
        last_title = ""
        table_idx = 0

        for elem in elements:
            etype = elem.get('type', '')

            if etype in ('title', 'section_header', 'caption'):
                last_title = elem.get('content', '').strip()[:200]
                continue

            if etype != 'table':
                continue

            html = elem.get('content', '')
            if not html or '<tr' not in html.lower():
                continue

            tables = _parse_tables(html)
            for grid in tables:
                if len(grid) < 2:
                    continue
                table_idx += 1
                n_tables_total += 1

                headers, data_rows = _merge_headers(grid)
                header_str = " | ".join(h for h in headers)
                meta.append((fname, table_idx, last_title, header_str))

                ym = re.search(r'(\d{4})_(\d{2})', fname)
                file_year = int(ym.group(1)) if ym else None
                active_year = file_year

                for row in data_rows:
                    if not row or not any(str(x or "").strip() for x in row):
                        continue
                    row_label = str(row[0] or "").strip()

                    # Skip pure section-header rows
                    if row_label in SKIP_ROW_PREFIXES:
                        skipped += 1
                        continue

                    m = re.match(r'^(\d{4})\b', row_label)
                    if m:
                        active_year = int(m.group(1))

                    time_key = _parse_time_key(row_label, active_year)

                    for ci in range(1, min(len(row), len(headers))):
                        raw_val = str(row[ci] or "").strip()
                        if raw_val.lower() in SKIP_VALUES:
                            skipped += 1
                            continue
                        col = headers[ci] if ci < len(headers) else f"col_{ci}"
                        cleaned = _clean_value(raw_val)
                        num = _to_float(raw_val)
                        batch.append((fname, table_idx, row_label, col, time_key, cleaned, num, raw_val))
                        total += 1

                        if len(batch) >= BATCH_SIZE:
                            c.executemany("INSERT INTO cells VALUES (?,?,?,?,?,?,?,?)", batch)
                            batch = []

        if (fi + 1) % 100 == 0:
            print(f"  Processed {fi + 1}/{len(json_files)} files, {total:,} cells, {n_tables_total} tables")

    if batch:
        c.executemany("INSERT INTO cells VALUES (?,?,?,?,?,?,?,?)", batch)

    c.executemany("INSERT INTO tables_meta VALUES (?,?,?,?)", meta)

    print(f"Creating indexes...")
    c.execute("CREATE INDEX idx_file ON cells(file)")
    c.execute("CREATE INDEX idx_time ON cells(time_key)")
    c.execute("CREATE INDEX idx_col ON cells(col_label)")
    c.execute("CREATE INDEX idx_row ON cells(row_label)")

    conn.commit()

    # Stats
    cnt = conn.execute("SELECT COUNT(*) FROM cells").fetchone()[0]
    files_cnt = conn.execute("SELECT COUNT(DISTINCT file) FROM cells").fetchone()[0]
    tables_cnt = conn.execute("SELECT COUNT(DISTINCT file || '|' || table_num) FROM cells").fetchone()[0]
    numeric_cnt = conn.execute("SELECT COUNT(*) FROM cells WHERE value_num IS NOT NULL").fetchone()[0]

    conn.close()

    db_size = os.path.getsize(DB_PATH)
    print(f"\nDone: {cnt:,} cells ({numeric_cnt:,} numeric) across {files_cnt} files, {tables_cnt} tables")
    print(f"Skipped: {skipped:,} empty/na values")
    print(f"DB size: {db_size / 1024 / 1024:.1f} MB")

    # Gzip
    print(f"Compressing to {GZ_PATH}...")
    with open(DB_PATH, 'rb') as f_in, gzip.open(GZ_PATH, 'wb', compresslevel=9) as f_out:
        shutil.copyfileobj(f_in, f_out)
    gz_size = os.path.getsize(GZ_PATH)
    print(f"Gzipped size: {gz_size / 1024 / 1024:.1f} MB")

if __name__ == '__main__':
    build()
