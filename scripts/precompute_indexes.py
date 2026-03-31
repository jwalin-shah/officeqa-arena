#!/usr/bin/env python3
"""Precompute lookup tables into the SQLite DB for faster MCP tool queries.

This is DATA STRUCTURING, not answer precomputation.
Run before submission: python3 scripts/precompute_indexes.py data/officeqa_corpus.sqlite3
"""
import sqlite3
import sys
import time


def main(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # 1. Column label lookup: distinct (table_pk, column_label) pairs
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

    # 2. Row label lookup from table_first_table_cells
    print("Building row label lookup...")
    t0 = time.time()
    conn.execute("DROP TABLE IF EXISTS row_label_lookup")
    # Use table_first_table_cells which exists on both DB schemas
    has_normalized = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='normalized_rows'"
    ).fetchone()[0]
    if has_normalized:
        conn.execute("""
            CREATE TABLE row_label_lookup AS
            SELECT DISTINCT
                ti.table_pk,
                nr.row_label,
                nr.row_label_norm
            FROM normalized_rows nr
            JOIN table_index ti ON ti.table_group_id = nr.table_group_id
            WHERE nr.row_label != ''
              AND (nr.row_type IS NULL OR nr.row_type != 'header')
              AND length(nr.row_label) > 2
        """)
    else:
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

    # 3. Table summary: one row per table_pk with all column names concatenated
    print("Building table summary...")
    t0 = time.time()
    conn.execute("DROP TABLE IF EXISTS table_summary")

    # Check available columns in table_index
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
    print("\nDone. New tables: col_label_lookup, row_label_lookup, table_summary")

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
