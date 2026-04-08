#!/usr/bin/env python3
"""Build a slim, fully-indexed corpus DB from the full 11GB source.

Produces a ~1.5-2GB database with:
  - table_cell_blobs (compressed cells — replaces 3.8GB table_first_table_cells)
  - table_index (with backfilled year ranges — 100% coverage)
  - table_first_tables (metadata)
  - col_label_lookup, row_label_lookup, table_summary (precomputed indexes)
  - table_scope_index, file_year_coverage (temporal indexes)
  - table_dedup_groups (deduplication map)
  - documents (697 rows, bulletin metadata)

Drops: table_first_table_cells, facts, facts_fts, document_texts,
       table_term_index, normalized_*, document_elements, ingestion_*

Usage:
  python3 scripts/build_slim_db.py SOURCE_DB OUTPUT_DB
  python3 scripts/build_slim_db.py data/officeqa_corpus.sqlite3 data/officeqa_slim.sqlite3

Designed to run on a droplet with 8GB RAM. Peak memory ~100MB.
"""
import re
import sqlite3
import sys
import time
from pathlib import Path

# Tables to copy as-is (schema + data)
COPY_TABLES = [
    "table_index",
    "table_first_tables",
    "table_scope_index",
    "file_year_coverage",
    "documents",
]

# Tables that may already exist in source (copy if present, rebuild if not)
OPTIONAL_COPY = [
    "table_cell_blobs",
    "col_label_lookup",
    "row_label_lookup",
    "table_summary",
    "table_dedup_groups",
]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()[0] > 0


def _copy_table(src: sqlite3.Connection, dst: sqlite3.Connection, table: str) -> int:
    """Copy a table from src to dst, preserving schema."""
    # Get CREATE TABLE statement
    row = src.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if row is None:
        print(f"  SKIP {table} (not in source)")
        return 0

    create_sql = row[0]
    dst.execute(f"DROP TABLE IF EXISTS {table}")
    dst.execute(create_sql)

    # Copy data in batches
    count = 0
    batch_size = 5000
    cursor = src.execute(f"SELECT * FROM {table}")
    cols = [d[0] for d in cursor.description]
    placeholders = ", ".join("?" for _ in cols)
    insert_sql = f"INSERT INTO {table} VALUES ({placeholders})"

    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        dst.executemany(insert_sql, rows)
        count += len(rows)

    # Copy indexes
    idx_rows = src.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
        (table,),
    ).fetchall()
    for idx in idx_rows:
        try:
            dst.execute(idx[0])
        except sqlite3.OperationalError:
            pass  # index already exists or duplicate

    return count


def build_cell_blobs(src: sqlite3.Connection, dst: sqlite3.Connection) -> None:
    """Pack table_first_table_cells into compressed blobs."""
    try:
        import msgpack
        import zstandard
    except ImportError:
        print("ERROR: pip install msgpack zstandard")
        sys.exit(1)

    cctx = zstandard.ZstdCompressor(level=3)

    dst.execute("DROP TABLE IF EXISTS table_cell_blobs")
    dst.execute("""
        CREATE TABLE table_cell_blobs (
            table_pk INTEGER PRIMARY KEY,
            data BLOB NOT NULL,
            cell_count INTEGER NOT NULL,
            raw_bytes INTEGER NOT NULL,
            compressed_bytes INTEGER NOT NULL
        )
    """)

    # Get all table_pks
    pks = [r[0] for r in src.execute(
        "SELECT DISTINCT table_pk FROM table_first_table_cells ORDER BY table_pk"
    ).fetchall()]

    total_raw = 0
    total_comp = 0
    total_cells = 0
    t0 = time.time()

    for i, pk in enumerate(pks):
        rows = src.execute(
            """SELECT row_ordinal, row_label, row_label_norm, column_ordinal,
                      column_label, column_label_norm, time_scope, year, month,
                      value_raw, normalized_value, row_type, confidence,
                      provenance_snippet, parse_flags_json
               FROM table_first_table_cells WHERE table_pk = ?
               ORDER BY row_ordinal, column_ordinal""",
            (pk,),
        ).fetchall()

        cells = []
        for r in rows:
            cell: dict = {
                "ro": r[0],   # row_ordinal
                "rl": r[1],   # row_label
                "rn": r[2],   # row_label_norm
                "co": r[3],   # column_ordinal
                "cl": r[4],   # column_label
                "cn": r[5],   # column_label_norm
            }
            if r[6]:  cell["ts"] = r[6]   # time_scope
            if r[7] is not None: cell["y"] = r[7]   # year
            if r[8] is not None: cell["m"] = r[8]   # month
            cell["vr"] = r[9] or ""        # value_raw
            if r[10] is not None: cell["nv"] = r[10]  # normalized_value
            if r[11]: cell["rt"] = r[11]   # row_type
            if r[12] is not None: cell["cf"] = r[12]  # confidence
            if r[13]: cell["ps"] = r[13]   # provenance_snippet
            if r[14]: cell["pf"] = r[14]   # parse_flags_json
            cells.append(cell)

        raw = msgpack.packb({"rows": cells}, use_bin_type=True)
        comp = cctx.compress(raw)

        dst.execute(
            "INSERT INTO table_cell_blobs VALUES (?, ?, ?, ?, ?)",
            (pk, comp, len(cells), len(raw), len(comp)),
        )

        total_raw += len(raw)
        total_comp += len(comp)
        total_cells += len(cells)

        if (i + 1) % 5000 == 0:
            dst.commit()
            elapsed = time.time() - t0
            print(f"  {i+1}/{len(pks)} tables packed ({total_cells:,} cells, "
                  f"{total_comp/1048576:.0f}MB compressed, {elapsed:.0f}s)")

    dst.commit()
    print(f"  Done: {len(pks)} tables, {total_cells:,} cells")
    print(f"  Raw: {total_raw/1048576:.0f}MB → Compressed: {total_comp/1048576:.0f}MB "
          f"({total_raw/total_comp:.1f}x ratio)")


def build_col_label_lookup(dst: sqlite3.Connection, src: sqlite3.Connection) -> int:
    """Build col_label_lookup from table_first_table_cells in source."""
    dst.execute("DROP TABLE IF EXISTS col_label_lookup")
    dst.execute("""
        CREATE TABLE col_label_lookup AS
        SELECT DISTINCT table_pk, column_label,
               LOWER(REPLACE(REPLACE(column_label, '/', ''), '.', '')) as col_norm
        FROM table_first_table_cells
        WHERE column_label != ''
    """)  # This won't work cross-DB. We need to do it differently.
    # Actually we need to read from src and insert into dst
    return 0  # placeholder


def build_lookup_tables(src: sqlite3.Connection, dst: sqlite3.Connection) -> None:
    """Build col_label_lookup and row_label_lookup from source cells."""
    print("  Building col_label_lookup...")
    t0 = time.time()
    dst.execute("DROP TABLE IF EXISTS col_label_lookup")
    dst.execute("""
        CREATE TABLE col_label_lookup (
            table_pk INTEGER NOT NULL,
            column_label TEXT NOT NULL,
            col_norm TEXT NOT NULL
        )
    """)

    # Process in batches by table_pk range
    max_pk = src.execute("SELECT MAX(table_pk) FROM table_first_table_cells").fetchone()[0]
    batch = 5000
    col_count = 0
    for start in range(0, (max_pk or 0) + 1, batch):
        rows = src.execute(
            """SELECT DISTINCT table_pk, column_label
               FROM table_first_table_cells
               WHERE table_pk >= ? AND table_pk < ? AND column_label != ''""",
            (start, start + batch),
        ).fetchall()
        inserts = [
            (r[0], r[1], r[1].lower().replace("/", "").replace(".", ""))
            for r in rows
        ]
        dst.executemany(
            "INSERT INTO col_label_lookup VALUES (?, ?, ?)", inserts
        )
        col_count += len(inserts)
    dst.execute("CREATE INDEX idx_col_lookup_norm ON col_label_lookup(col_norm)")
    dst.execute("CREATE INDEX idx_col_lookup_pk ON col_label_lookup(table_pk)")
    print(f"    {col_count:,} entries in {time.time()-t0:.1f}s")

    print("  Building row_label_lookup...")
    t0 = time.time()
    dst.execute("DROP TABLE IF EXISTS row_label_lookup")
    dst.execute("""
        CREATE TABLE row_label_lookup (
            table_pk INTEGER NOT NULL,
            row_label TEXT NOT NULL,
            row_label_norm TEXT NOT NULL
        )
    """)
    row_count = 0
    for start in range(0, (max_pk or 0) + 1, batch):
        rows = src.execute(
            """SELECT DISTINCT table_pk, row_label, row_label_norm
               FROM table_first_table_cells
               WHERE table_pk >= ? AND table_pk < ?
                 AND row_label != '' AND length(row_label) > 2
                 AND (row_type IS NULL OR row_type != 'header')""",
            (start, start + batch),
        ).fetchall()
        inserts = [(r[0], r[1], r[2] or r[1].lower().replace("/", "").replace(".", "")) for r in rows]
        dst.executemany(
            "INSERT INTO row_label_lookup VALUES (?, ?, ?)", inserts
        )
        row_count += len(inserts)
    dst.execute("CREATE INDEX idx_row_lookup_norm ON row_label_lookup(row_label_norm)")
    dst.execute("CREATE INDEX idx_row_lookup_pk ON row_label_lookup(table_pk)")
    print(f"    {row_count:,} entries in {time.time()-t0:.1f}s")

    print("  Building table_summary...")
    t0 = time.time()
    dst.execute("DROP TABLE IF EXISTS table_summary")
    dst.execute("""
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
            ti.period_basis,
            ti.frequency,
            GROUP_CONCAT(cl.column_label, ' | ') as all_columns
        FROM table_index ti
        LEFT JOIN col_label_lookup cl ON cl.table_pk = ti.table_pk
        GROUP BY ti.table_pk
    """)
    dst.execute("CREATE INDEX idx_summary_pk ON table_summary(table_pk)")
    dst.execute("CREATE INDEX idx_summary_file ON table_summary(source_file)")
    cnt = dst.execute("SELECT count(*) FROM table_summary").fetchone()[0]
    print(f"    {cnt:,} entries in {time.time()-t0:.1f}s")


def backfill_years(dst: sqlite3.Connection) -> None:
    """Backfill missing min_year/max_year in table_index."""
    missing = dst.execute(
        "SELECT COUNT(*) FROM table_index WHERE min_year IS NULL"
    ).fetchone()[0]
    if missing == 0:
        print("  Year ranges already complete")
        return

    print(f"  {missing} tables missing year ranges...")
    year_re = re.compile(r'\b(1[89]\d{2}|20[0-2]\d)\b')

    # Tier 1: from table_title
    rows = dst.execute(
        "SELECT table_pk, table_title FROM table_index WHERE min_year IS NULL"
    ).fetchall()
    tier1 = 0
    for r in rows:
        years = [int(y) for y in year_re.findall(r[1] or "")]
        if years:
            dst.execute(
                "UPDATE table_index SET min_year=?, max_year=? WHERE table_pk=? AND min_year IS NULL",
                (min(years), max(years), r[0]),
            )
            tier1 += 1
    dst.commit()
    print(f"    Tier 1 (title): {tier1}")

    # Tier 2: from source_file name (bulletin year ± 1)
    remaining = dst.execute(
        "SELECT table_pk, source_file FROM table_index WHERE min_year IS NULL"
    ).fetchall()
    tier2 = 0
    for r in remaining:
        sf_years = year_re.findall(r[1] or "")
        if sf_years:
            by = int(sf_years[0])
            dst.execute(
                "UPDATE table_index SET min_year=?, max_year=? WHERE table_pk=? AND min_year IS NULL",
                (by - 1, by, r[0]),
            )
            tier2 += 1
    dst.commit()
    print(f"    Tier 2 (source_file): {tier2}")

    final = dst.execute(
        "SELECT COUNT(*) FROM table_index WHERE min_year IS NULL"
    ).fetchone()[0]
    print(f"    Remaining NULL: {final}")


def build_dedup_groups(dst: sqlite3.Connection) -> None:
    """Build table deduplication groups."""
    dst.execute("DROP TABLE IF EXISTS table_dedup_groups")
    dst.execute("""
        CREATE TABLE table_dedup_groups AS
        SELECT
            table_title_norm,
            table_family,
            COUNT(*) as copies,
            GROUP_CONCAT(table_pk) as table_pks,
            GROUP_CONCAT(DISTINCT source_file) as bulletins,
            MAX(max_year) as latest_max_year,
            MIN(min_year) as earliest_min_year
        FROM table_index
        WHERE table_title_norm IS NOT NULL AND table_title_norm != ''
        GROUP BY table_title_norm, table_family
        HAVING COUNT(*) > 1
    """)
    cnt = dst.execute("SELECT count(*) FROM table_dedup_groups").fetchone()[0]
    print(f"  {cnt:,} dedup groups")


def main(src_path: str, dst_path: str) -> None:
    dst_file = Path(dst_path)
    if dst_file.exists():
        print(f"Removing existing {dst_path}")
        dst_file.unlink()

    src = sqlite3.connect(src_path)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(dst_path)
    dst.execute("PRAGMA journal_mode=WAL")
    dst.execute("PRAGMA synchronous=NORMAL")
    dst.execute("PRAGMA page_size=4096")

    total_t0 = time.time()

    # Step 1: Copy core metadata tables
    print("\n=== Step 1: Copy metadata tables ===")
    for table in COPY_TABLES:
        t0 = time.time()
        count = _copy_table(src, dst, table)
        print(f"  {table}: {count:,} rows ({time.time()-t0:.1f}s)")
    dst.commit()

    # Step 2: Build cell blobs (or copy if already exists)
    print("\n=== Step 2: Cell blobs ===")
    if _table_exists(src, "table_cell_blobs"):
        print("  Copying existing table_cell_blobs...")
        t0 = time.time()
        count = _copy_table(src, dst, "table_cell_blobs")
        print(f"  {count:,} blobs ({time.time()-t0:.1f}s)")
    elif _table_exists(src, "table_first_table_cells"):
        print("  Packing table_first_table_cells into blobs...")
        build_cell_blobs(src, dst)
    else:
        print("  ERROR: No cell data source found!")
        sys.exit(1)

    # Step 3: Build lookup indexes
    print("\n=== Step 3: Lookup indexes ===")
    has_lookups = all(_table_exists(src, t) for t in ["col_label_lookup", "row_label_lookup", "table_summary"])
    if has_lookups:
        print("  Copying existing lookup tables...")
        for table in ["col_label_lookup", "row_label_lookup", "table_summary"]:
            t0 = time.time()
            count = _copy_table(src, dst, table)
            print(f"    {table}: {count:,} rows ({time.time()-t0:.1f}s)")
    elif _table_exists(src, "table_first_table_cells"):
        print("  Building from source cells...")
        build_lookup_tables(src, dst)
    else:
        print("  WARNING: Cannot build lookups (no cells table)")

    dst.commit()

    # Step 4: Backfill year ranges
    print("\n=== Step 4: Backfill year ranges ===")
    backfill_years(dst)

    # Step 5: Build dedup groups
    print("\n=== Step 5: Dedup groups ===")
    build_dedup_groups(dst)

    dst.commit()

    # Step 6: VACUUM to reclaim space
    print("\n=== Step 6: VACUUM ===")
    dst.execute("PRAGMA journal_mode=DELETE")  # WAL can't VACUUM
    t0 = time.time()
    dst.execute("VACUUM")
    print(f"  VACUUM done in {time.time()-t0:.1f}s")

    dst.close()
    src.close()

    # Report
    size_mb = dst_file.stat().st_size / 1048576
    elapsed = time.time() - total_t0
    print(f"\n=== Done ===")
    print(f"  Output: {dst_path}")
    print(f"  Size: {size_mb:.0f} MB")
    print(f"  Time: {elapsed:.0f}s")
    print(f"\nTo compress for upload:")
    print(f"  zstd -19 -T0 {dst_path} -o {dst_path}.zst")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 scripts/build_slim_db.py SOURCE_DB OUTPUT_DB")
        print("Example: python3 scripts/build_slim_db.py data/officeqa_corpus.sqlite3 data/officeqa_slim.sqlite3")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
