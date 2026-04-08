#!/usr/bin/env python3
"""Precompute lookup tables into the SQLite DB for faster MCP tool queries.

Supports both old schema (table_first_table_cells) and slim schema (table_cell_blobs).
Run before submission: python3 scripts/precompute_indexes.py data/officeqa_slim_v2.sqlite3
"""
import sqlite3
import sys
import time

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _extract_labels_from_blobs(conn: sqlite3.Connection):
    """Extract distinct (table_pk, col_label, row_label) from table_cell_blobs."""
    import msgpack
    import zstandard
    dctx = zstandard.ZstdDecompressor()

    col_labels = []  # (table_pk, column_label, col_norm)
    row_labels = []  # (table_pk, row_label, row_label_norm)

    seen_col = set()
    seen_row = set()

    blobs = conn.execute("SELECT table_pk, data FROM table_cell_blobs").fetchall()
    for i, blob in enumerate(blobs):
        pk = blob[0]
        try:
            raw = dctx.decompress(blob[1])
            obj = msgpack.unpackb(raw, raw=False)
        except Exception:
            continue

        for cell in obj.get("rows", []):
            cl = cell.get("cl", "")
            rl = cell.get("rl", "")

            if cl and (pk, cl) not in seen_col:
                seen_col.add((pk, cl))
                cn = cl.lower().replace("/", "").replace(".", "").strip()
                col_labels.append((pk, cl, cn))

            if rl and len(rl) > 2 and (pk, rl) not in seen_row:
                seen_row.add((pk, rl))
                rn = rl.lower().replace("/", "").replace(".", "").strip()
                row_labels.append((pk, rl, rn))

        if (i + 1) % 5000 == 0:
            print(f"  ... {i+1}/{len(blobs)} blobs scanned")

    return col_labels, row_labels


def main(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    use_blobs = not _has_table(conn, "table_first_table_cells") and _has_table(conn, "table_cell_blobs")

    if use_blobs:
        print("Using table_cell_blobs (slim DB)...")
        t0 = time.time()
        col_labels, row_labels = _extract_labels_from_blobs(conn)
        print(f"  Extracted {len(col_labels):,} col labels, {len(row_labels):,} row labels in {time.time()-t0:.1f}s")

        # 1. Column label lookup
        print("Building column label lookup...")
        t0 = time.time()
        conn.execute("DROP TABLE IF EXISTS col_label_lookup")
        conn.execute("""
            CREATE TABLE col_label_lookup (
                table_pk INTEGER NOT NULL,
                column_label TEXT NOT NULL,
                col_norm TEXT NOT NULL
            )
        """)
        conn.executemany(
            "INSERT INTO col_label_lookup (table_pk, column_label, col_norm) VALUES (?, ?, ?)",
            col_labels,
        )
        conn.execute("CREATE INDEX idx_col_lookup_norm ON col_label_lookup(col_norm)")
        conn.execute("CREATE INDEX idx_col_lookup_pk ON col_label_lookup(table_pk)")
        print(f"  {len(col_labels):,} entries in {time.time()-t0:.1f}s")

        # 2. Row label lookup
        print("Building row label lookup...")
        t0 = time.time()
        conn.execute("DROP TABLE IF EXISTS row_label_lookup")
        conn.execute("""
            CREATE TABLE row_label_lookup (
                table_pk INTEGER NOT NULL,
                row_label TEXT NOT NULL,
                row_label_norm TEXT NOT NULL
            )
        """)
        conn.executemany(
            "INSERT INTO row_label_lookup (table_pk, row_label, row_label_norm) VALUES (?, ?, ?)",
            row_labels,
        )
        conn.execute("CREATE INDEX idx_row_lookup_norm ON row_label_lookup(row_label_norm)")
        conn.execute("CREATE INDEX idx_row_lookup_pk ON row_label_lookup(table_pk)")
        print(f"  {len(row_labels):,} entries in {time.time()-t0:.1f}s")

    else:
        # Original path using table_first_table_cells
        print("Using table_first_table_cells...")
        print("Building column label lookup...")
        t0 = time.time()
        conn.execute("DROP TABLE IF EXISTS col_label_lookup")
        conn.execute("""
            CREATE TABLE col_label_lookup AS
            SELECT DISTINCT table_pk, column_label,
                   LOWER(REPLACE(REPLACE(column_label, '/', ''), '.', '')) as col_norm
            FROM table_first_table_cells
            WHERE column_label != ''
        """)
        conn.execute("CREATE INDEX idx_col_lookup_norm ON col_label_lookup(col_norm)")
        conn.execute("CREATE INDEX idx_col_lookup_pk ON col_label_lookup(table_pk)")
        count = conn.execute("SELECT count(*) FROM col_label_lookup").fetchone()[0]
        print(f"  {count:,} entries in {time.time()-t0:.1f}s")

        print("Building row label lookup...")
        t0 = time.time()
        conn.execute("DROP TABLE IF EXISTS row_label_lookup")
        conn.execute("""
            CREATE TABLE row_label_lookup AS
            SELECT DISTINCT
                table_pk,
                row_label,
                LOWER(REPLACE(REPLACE(row_label, '/', ''), '.', '')) as row_label_norm
            FROM table_first_table_cells
            WHERE row_label != ''
              AND length(row_label) > 2
        """)
        conn.execute("CREATE INDEX idx_row_lookup_norm ON row_label_lookup(row_label_norm)")
        conn.execute("CREATE INDEX idx_row_lookup_pk ON row_label_lookup(table_pk)")
        count = conn.execute("SELECT count(*) FROM row_label_lookup").fetchone()[0]
        print(f"  {count:,} entries in {time.time()-t0:.1f}s")

    # 3. Table summary
    print("Building table summary...")
    t0 = time.time()
    conn.execute("DROP TABLE IF EXISTS table_summary")

    ti_cols = {r[1] for r in conn.execute("PRAGMA table_info(table_index)").fetchall()}
    period_col = "ti.period_basis" if "period_basis" in ti_cols else "'unknown' AS period_basis"
    freq_col = "ti.frequency" if "frequency" in ti_cols else "'unknown' AS frequency"

    conn.execute(f"""
        CREATE TABLE table_summary AS
        SELECT
            ti.table_pk,
            ti.table_title,
            ti.source_file,
            ti.units_line,
            ti.min_year,
            ti.max_year,
            ti.row_count,
            ti.column_count,
            {period_col},
            {freq_col},
            GROUP_CONCAT(cl.column_label, ' | ') as all_columns
        FROM table_index ti
        LEFT JOIN col_label_lookup cl ON cl.table_pk = ti.table_pk
        GROUP BY ti.table_pk
    """)
    conn.execute("CREATE INDEX idx_summary_pk ON table_summary(table_pk)")
    conn.execute("CREATE INDEX idx_summary_file ON table_summary(source_file)")
    count = conn.execute("SELECT count(*) FROM table_summary").fetchone()[0]
    print(f"  {count:,} entries in {time.time()-t0:.1f}s")

    conn.commit()
    print("\nDone. Tables: col_label_lookup, row_label_lookup, table_summary")

    # Verify
    test = conn.execute(
        "SELECT table_pk, column_label FROM col_label_lookup WHERE col_norm LIKE '%intergovernmental%'"
    ).fetchall()
    print(f"\nVerification: 'intergovernmental' in col_label_lookup: {len(test)} matches")
    for r in test[:3]:
        print(f"  pk={r['table_pk']} col=\"{r['column_label']}\"")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/precompute_indexes.py <db_path>")
        sys.exit(1)
    main(sys.argv[1])
