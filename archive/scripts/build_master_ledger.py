#!/usr/bin/env python3
"""Build the master_ledger table from enriched table_cell_blobs.

The master_ledger is a flat, deduplicated index of ALL values by
(metric_slug, time_key). It powers the search_ledger() tool — the
fastest retrieval path for known metrics.

Pipeline order:
  1. reingest_from_json.py → builds table_cell_blobs
  2. enrich_calendar_totals.py → adds CY/FY synthetic rows to blobs
  3. precompute_indexes.py → builds col/row lookup tables
  4. build_master_ledger.py (THIS SCRIPT) → flattens blobs into master_ledger

Usage:
    python3 scripts/build_master_ledger.py [--db /path/to/db.sqlite3]
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import msgpack
    import zstandard
except ImportError:
    print("ERROR: msgpack and zstandard required. pip install msgpack zstandard")
    sys.exit(1)

_dctx = zstandard.ZstdDecompressor()


def _normalize_metric(label: str) -> str:
    """Normalize a label into a metric_slug for consistent lookups."""
    if not label:
        return ""
    s = label.lower().strip()
    # Remove footnote markers (1/, 2/, etc.)
    s = re.sub(r'\s*\d+/', '', s)
    # Remove punctuation except spaces and hyphens
    s = re.sub(r'[^\w\s\-]', '', s)
    # Collapse whitespace
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _build_time_key(year: int | None, month: int | None, row_type: str, period_scope: str) -> str | None:
    """Build a time_key from cell metadata."""
    if year is None:
        return None

    if row_type and "synthetic_cy" in row_type:
        return f"CY{year}"
    if row_type and "synthetic_fy" in row_type:
        return f"FY{year}"
    if month is not None:
        return f"{year}-{int(month):02d}"
    return str(year)


def _determine_period_basis(row_type: str, period_scope: str, month: int | None) -> str:
    """Determine the period_basis for a cell."""
    if row_type and "synthetic_cy" in row_type:
        return "calendar"
    if row_type and "synthetic_fy" in row_type:
        return "fiscal"
    if period_scope:
        return period_scope
    if month is not None:
        return "monthly"
    return "annual"


def build_master_ledger(conn: sqlite3.Connection) -> int:
    """Build master_ledger table from table_cell_blobs.

    Returns the number of rows inserted.
    """
    # Drop and recreate
    conn.execute("DROP TABLE IF EXISTS master_ledger")
    conn.execute("""
        CREATE TABLE master_ledger (
            metric_slug TEXT NOT NULL,
            time_key TEXT NOT NULL,
            period_basis TEXT NOT NULL,
            value REAL,
            value_raw TEXT,
            table_pk INTEGER NOT NULL,
            source_file TEXT,
            table_title TEXT,
            row_type TEXT,
            PRIMARY KEY (metric_slug, time_key, table_pk)
        )
    """)

    # Get table metadata
    tables = conn.execute("""
        SELECT table_pk, table_title, source_file, period_basis
        FROM table_index
    """).fetchall()

    table_meta = {}
    for t in tables:
        table_meta[t["table_pk"]] = {
            "title": t["table_title"] or "",
            "source": t["source_file"] or "",
            "period_basis": t["period_basis"] or "",
        }

    # Check which storage to use
    has_blobs = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='table_cell_blobs'"
    ).fetchone()

    total_inserted = 0
    batch = []
    batch_size = 10000

    def flush_batch():
        nonlocal total_inserted
        if not batch:
            return
        conn.executemany(
            """INSERT OR REPLACE INTO master_ledger
               (metric_slug, time_key, period_basis, value, value_raw,
                table_pk, source_file, table_title, row_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            batch,
        )
        total_inserted += len(batch)
        batch.clear()

    if has_blobs:
        # Read from compressed blobs
        blob_rows = conn.execute(
            "SELECT table_pk, data FROM table_cell_blobs"
        ).fetchall()

        for i, blob_row in enumerate(blob_rows):
            pk = blob_row["table_pk"]
            meta = table_meta.get(pk, {"title": "", "source": "", "period_basis": ""})

            try:
                raw = _dctx.decompress(blob_row["data"])
                obj = msgpack.unpackb(raw, raw=False)
            except Exception:
                continue

            for cell in obj.get("rows", []):
                # Extract cell data using short keys
                cl = cell.get("cl", "")  # column_label
                rl = cell.get("rl", "")  # row_label
                y = cell.get("y")        # year
                m = cell.get("m")        # month
                nv = cell.get("nv")      # normalized_value
                vr = cell.get("vr", "")  # value_raw
                rt = cell.get("rt", "")  # row_type
                ps = cell.get("ps", "")  # period_scope

                if nv is None or cl == "":
                    continue

                # Build metric_slug from column_label
                # For synthetic rows with " — " in row_label, the category is in rl
                metric = _normalize_metric(cl)
                if not metric:
                    continue

                # Also index by row_label if it's not a synthetic/CY/FY label
                # This catches cases where the metric is in the row, not column
                rl_lower = rl.lower() if rl else ""
                is_synthetic = rl_lower.startswith("cy") or rl_lower.startswith("fy")

                time_key = _build_time_key(y, m, rt, ps)
                if not time_key:
                    continue

                period_basis = _determine_period_basis(rt, ps, m)

                try:
                    value = float(nv)
                except (TypeError, ValueError):
                    continue

                batch.append((
                    metric, time_key, period_basis, value, vr,
                    pk, meta["source"], meta["title"], rt or None,
                ))

                # For non-synthetic rows, also index by row_label as metric
                if rl and not is_synthetic and len(rl) > 2:
                    rl_metric = _normalize_metric(rl)
                    if rl_metric and rl_metric != metric:
                        batch.append((
                            rl_metric, time_key, period_basis, value, vr,
                            pk, meta["source"], meta["title"], rt or None,
                        ))

                if len(batch) >= batch_size:
                    flush_batch()

            if (i + 1) % 500 == 0:
                flush_batch()
                conn.commit()
                print(f"  ... processed {i+1}/{len(blob_rows)} tables, {total_inserted:,} rows")

    else:
        # Fallback: read from table_first_table_cells
        print("No table_cell_blobs found, reading from table_first_table_cells...")
        cursor = conn.execute("""
            SELECT fc.table_pk, fc.column_label, fc.row_label,
                   fc.year, fc.month, fc.normalized_value, fc.value_raw,
                   fc.time_scope
            FROM table_first_table_cells fc
            WHERE fc.normalized_value IS NOT NULL
              AND fc.column_label != ''
        """)

        for i, row in enumerate(cursor):
            pk = row["table_pk"]
            meta = table_meta.get(pk, {"title": "", "source": "", "period_basis": ""})

            metric = _normalize_metric(row["column_label"])
            if not metric:
                continue

            y = row["year"]
            m = row["month"]
            time_key = _build_time_key(y, m, "", meta["period_basis"])
            if not time_key:
                continue

            period_basis = _determine_period_basis("", meta["period_basis"], m)

            try:
                value = float(row["normalized_value"])
            except (TypeError, ValueError):
                continue

            batch.append((
                metric, time_key, period_basis, value, row["value_raw"] or "",
                pk, meta["source"], meta["title"], None,
            ))

            # Also index by row_label
            rl = row["row_label"] or ""
            if rl and len(rl) > 2:
                rl_metric = _normalize_metric(rl)
                if rl_metric and rl_metric != metric:
                    batch.append((
                        rl_metric, time_key, period_basis, value, row["value_raw"] or "",
                        pk, meta["source"], meta["title"], None,
                    ))

            if len(batch) >= batch_size:
                flush_batch()

            if (i + 1) % 100000 == 0:
                flush_batch()
                conn.commit()
                print(f"  ... processed {i+1:,} cells, {total_inserted:,} ledger rows")

    flush_batch()

    # Create indexes for fast lookup
    print("Creating indexes...")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ml_metric ON master_ledger(metric_slug)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ml_metric_time ON master_ledger(metric_slug, time_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ml_time ON master_ledger(time_key)")

    conn.commit()
    return total_inserted


def main() -> None:
    parser = argparse.ArgumentParser(description="Build master_ledger from enriched DB")
    parser.add_argument("--db", default="data/officeqa_corpus.sqlite3",
                        help="Path to enriched SQLite DB")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"ERROR: DB not found at {args.db}")
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    print(f"Building master_ledger from {args.db}...")
    t0 = time.time()

    count = build_master_ledger(conn)

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s")
    print(f"Master ledger rows: {count:,}")

    # Stats
    metrics = conn.execute("SELECT COUNT(DISTINCT metric_slug) FROM master_ledger").fetchone()[0]
    time_keys = conn.execute("SELECT COUNT(DISTINCT time_key) FROM master_ledger").fetchone()[0]
    print(f"Distinct metrics: {metrics:,}")
    print(f"Distinct time_keys: {time_keys:,}")

    # Sample
    print("\nSample entries:")
    for row in conn.execute(
        "SELECT metric_slug, time_key, period_basis, value, source_file FROM master_ledger LIMIT 5"
    ).fetchall():
        print(f"  {row['metric_slug'][:30]:30s} | {row['time_key']:8s} | {row['period_basis']:8s} | {row['value']:>12.1f} | {row['source_file']}")

    conn.close()


if __name__ == "__main__":
    main()
