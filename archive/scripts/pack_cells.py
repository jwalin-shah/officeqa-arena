#!/usr/bin/env python3
"""Pack table_first_table_cells (18.4M rows) into compressed per-table blobs."""

import argparse
import sqlite3
import time

import msgpack
import zstandard as zstd


COLUMNS = [
    "row_ordinal", "row_label", "row_label_norm",
    "column_ordinal", "column_label", "column_label_norm",
    "time_scope", "year", "month",
    "value_raw", "normalized_value", "row_type",
    "confidence", "provenance_snippet", "parse_flags_json",
]

# Short keys matching the column order above
SHORT_KEYS = [
    "ro", "rl", "rn",
    "co", "cl", "cn",
    "ts", "y", "m",
    "vr", "nv", "rt",
    "cf", "ps", "pf",
]

BATCH_SIZE = 1000
PROGRESS_EVERY = 5000
ZSTD_LEVEL = 3

SELECT_CELLS = (
    "SELECT " + ", ".join(COLUMNS) +
    " FROM table_first_table_cells WHERE table_pk = ?"
    " ORDER BY row_ordinal, column_ordinal"
)


def pack_table(rows):
    """Convert rows into a compact dict, omitting None/empty values."""
    cells = []
    for row in rows:
        cell = {}
        for col, key in zip(COLUMNS, SHORT_KEYS):
            val = row[col]
            # Omit None and empty strings
            if val is None or val == "":
                continue
            cell[key] = val
        cells.append(cell)
    return {"rows": cells}


def main():
    parser = argparse.ArgumentParser(description="Pack cell table into compressed blobs")
    parser.add_argument("db", help="Path to officeqa_corpus.sqlite3")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db, timeout=600)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Create destination table
    cur.execute("DROP TABLE IF EXISTS table_cell_blobs")
    cur.execute("""
        CREATE TABLE table_cell_blobs (
            table_pk INTEGER PRIMARY KEY,
            data BLOB NOT NULL,
            cell_count INTEGER NOT NULL,
            raw_bytes INTEGER NOT NULL,
            compressed_bytes INTEGER NOT NULL
        )
    """)
    conn.commit()

    # Get all distinct table_pks
    print("Fetching distinct table_pk values...")
    t0 = time.time()
    pks = [r[0] for r in cur.execute(
        "SELECT DISTINCT table_pk FROM table_first_table_cells ORDER BY table_pk"
    ).fetchall()]
    print(f"  Found {len(pks)} tables in {time.time() - t0:.1f}s")

    compressor = zstd.ZstdCompressor(level=ZSTD_LEVEL)

    total_tables = 0
    total_cells = 0
    total_raw = 0
    total_compressed = 0
    t_start = time.time()

    for batch_start in range(0, len(pks), BATCH_SIZE):
        batch_pks = pks[batch_start : batch_start + BATCH_SIZE]
        inserts = []

        for pk in batch_pks:
            rows = cur.execute(SELECT_CELLS, (pk,)).fetchall()
            obj = pack_table(rows)
            raw = msgpack.packb(obj, use_bin_type=True)
            compressed = compressor.compress(raw)

            inserts.append((pk, compressed, len(rows), len(raw), len(compressed)))
            total_cells += len(rows)
            total_raw += len(raw)
            total_compressed += len(compressed)

        cur.executemany(
            "INSERT INTO table_cell_blobs (table_pk, data, cell_count, raw_bytes, compressed_bytes) VALUES (?,?,?,?,?)",
            inserts,
        )
        conn.commit()
        total_tables += len(batch_pks)

        if total_tables % PROGRESS_EVERY == 0 or total_tables == len(pks):
            elapsed = time.time() - t_start
            rate = total_tables / elapsed if elapsed > 0 else 0
            print(
                f"  {total_tables:>7,}/{len(pks):,} tables | "
                f"{total_cells:>12,} cells | "
                f"raw {total_raw / 1e6:>8.1f} MB | "
                f"zstd {total_compressed / 1e6:>8.1f} MB | "
                f"{rate:>.0f} tables/s"
            )

    elapsed = time.time() - t_start

    # Verify PK index exists (it's implicit on INTEGER PRIMARY KEY)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cell_blobs_pk ON table_cell_blobs(table_pk)")
    conn.commit()

    # Get original table size estimate
    orig_page_count = cur.execute(
        "SELECT SUM(payload) FROM dbstat WHERE name = 'table_first_table_cells'"
    ).fetchone()[0]
    orig_size_mb = (orig_page_count or 0) / 1e6

    ratio = total_raw / total_compressed if total_compressed > 0 else 0

    print()
    print("=" * 60)
    print(f"  Tables packed:        {total_tables:>12,}")
    print(f"  Cells packed:         {total_cells:>12,}")
    print(f"  Raw size:             {total_raw / 1e6:>12.2f} MB")
    print(f"  Compressed size:      {total_compressed / 1e6:>12.2f} MB")
    print(f"  Compression ratio:    {ratio:>12.2f}x")
    print(f"  Original table est:   {orig_size_mb:>12.2f} MB (dbstat payload)")
    print(f"  Time:                 {elapsed:>12.1f}s")
    print("=" * 60)

    conn.close()


if __name__ == "__main__":
    main()
