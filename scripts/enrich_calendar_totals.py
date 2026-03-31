#!/usr/bin/env python3
"""Pre-compute calendar-year and fiscal-year totals from monthly data in slim_v2 DB.

For every table with monthly data, this script:
1. Finds all monthly cells (month != None)
2. Groups by (column_label, year)
3. Sums Jan-Dec for CY totals, Jul-Jun (pre-1977) or Oct-Sep (1977+) for FY totals
4. Creates synthetic CY/FY rows only if all 12 months are present
5. Re-packs the enriched blob back into the DB

Cross-bulletin: For tables that appear in multiple bulletins (same table_group_id),
monthly data is merged across bulletins to maximize coverage before summing.

Idempotent: removes any existing CY rows (row_label starts with "CY") before adding.

Usage:
    python3 scripts/enrich_calendar_totals.py [--db /path/to/slim_v2.sqlite3] [--min-months 10]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import msgpack
import zstandard

_cctx = zstandard.ZstdCompressor(level=3)
_dctx = zstandard.ZstdDecompressor()


def _unpack_blob(conn: sqlite3.Connection, table_pk: int) -> dict | None:
    """Decompress and return full blob object {rows: [...]}."""
    row = conn.execute(
        "SELECT data FROM table_cell_blobs WHERE table_pk = ?", (table_pk,)
    ).fetchone()
    if row is None:
        return None
    raw = _dctx.decompress(row[0] if isinstance(row, tuple) else row["data"])
    return msgpack.unpackb(raw, raw=False)


def _pack_and_store(conn: sqlite3.Connection, table_pk: int, obj: dict) -> None:
    """Compress and update blob for table_pk."""
    raw = msgpack.packb(obj, use_bin_type=True)
    compressed = _cctx.compress(raw)
    conn.execute(
        "UPDATE table_cell_blobs SET data = ? WHERE table_pk = ?",
        (compressed, table_pk),
    )


def _format_number(val: float) -> str:
    """Format a number for value_raw field."""
    if val == int(val):
        return f"{int(val):,}"
    return f"{val:,.1f}"


def enrich_table(
    conn: sqlite3.Connection,
    table_pk: int,
    min_months: int = 10,
    group_pks: list[int] | None = None,
) -> tuple[int, int]:
    """Add CY synthetic rows to a single table blob.

    If group_pks is provided, monthly data is merged from all group members
    (cross-bulletin join) before computing totals.

    Returns (cy_rows_added, cy_rows_skipped_incomplete).
    """
    obj = _unpack_blob(conn, table_pk)
    if obj is None:
        return 0, 0

    rows = obj["rows"]

    # Remove any existing synthetic rows (idempotent)
    rows = [r for r in rows if not str(r.get("rl", "")).startswith("CY")
            and not str(r.get("rl", "")).startswith("FY")]

    # Collect monthly cells from this table
    # Key: (column_label, year) -> {month: normalized_value}
    monthly: dict[tuple[str, int], dict[int, float]] = defaultdict(dict)

    for cell in rows:
        m = cell.get("m")
        y = cell.get("y")
        nv = cell.get("nv")
        cl = cell.get("cl", "")
        if m is not None and y is not None and nv is not None and cl:
            try:
                nv_f = float(nv)
                monthly[(cl, int(y))][int(m)] = nv_f
            except (TypeError, ValueError):
                pass

    # Cross-bulletin merge: pull monthly cells from sibling tables
    if group_pks:
        for sibling_pk in group_pks:
            if sibling_pk == table_pk:
                continue
            sib_obj = _unpack_blob(conn, sibling_pk)
            if sib_obj is None:
                continue
            for cell in sib_obj["rows"]:
                m = cell.get("m")
                y = cell.get("y")
                nv = cell.get("nv")
                cl = cell.get("cl", "")
                if m is not None and y is not None and nv is not None and cl:
                    try:
                        nv_f = float(nv)
                        key = (cl, int(y))
                        month_int = int(m)
                        # Only fill gaps — don't overwrite existing data
                        if month_int not in monthly[key]:
                            monthly[key][month_int] = nv_f
                    except (TypeError, ValueError):
                        pass

    # Compute CY totals
    added = 0
    skipped = 0
    max_ro = max((r.get("ro", 0) for r in rows), default=0)

    for (cl, year), month_vals in sorted(monthly.items()):
        # Check coverage: need at least min_months of 1-12
        calendar_months = {m: v for m, v in month_vals.items() if 1 <= m <= 12}
        if len(calendar_months) < min_months:
            skipped += 1
            continue

        total = sum(calendar_months.values())
        max_ro += 1

        # Normalize column label for search
        cl_norm = cl.lower().replace("/", "").replace(".", "").strip()

        cy_row = {
            "ro": max_ro,
            "rl": f"CY{year}",
            "rn": f"cy{year}",
            "co": 0,
            "cl": cl,
            "cn": cl_norm,
            "ts": f"CY{year}",
            "y": year,
            "m": None,
            "vr": _format_number(total),
            "nv": round(total, 4),
            "rt": "synthetic_cy_total",
            "cf": 0.95,
            "ps": "calendar",
            "pf": [],
        }
        # Add series_label and footnote fields if they exist in original rows
        cy_row["sl"] = ""
        cy_row["fn"] = []
        # Flag: months_included for transparency
        cy_row["cy_months"] = len(calendar_months)

        rows.append(cy_row)
        added += 1

    # Compute FY totals
    # FY definition changed in 1976:
    #   FY <= 1976: Jul(Y-1) through Jun(Y)
    #   FY >= 1977: Oct(Y-1) through Sep(Y)
    # We need months from two calendar years, so build a cross-year lookup:
    #   monthly[(cl, cal_year)] -> {month: value}
    # FY1940 (old) = Jul 1939 (m=7,y=1939) + Aug..Dec 1939 + Jan..Jun 1940
    all_years = set()
    for (cl, yr) in monthly:
        all_years.add(yr)

    for fy_year in sorted(all_years):
        # Determine which months belong to this FY
        if fy_year <= 1976:
            # Old: Jul(FY-1) through Jun(FY)
            fy_months = [(fy_year - 1, m_num) for m_num in range(7, 13)]
            fy_months += [(fy_year, m_num) for m_num in range(1, 7)]
        else:
            # New: Oct(FY-1) through Sep(FY)
            fy_months = [(fy_year - 1, m_num) for m_num in range(10, 13)]
            fy_months += [(fy_year, m_num) for m_num in range(1, 10)]

        # For each column, check if we have all 12 FY months
        cols_with_data = set(cl for (cl, yr) in monthly if yr in (fy_year, fy_year - 1))
        for cl in cols_with_data:
            fy_vals = []
            for (cal_yr, m_num) in fy_months:
                val = monthly.get((cl, cal_yr), {}).get(m_num)
                if val is not None:
                    fy_vals.append(val)

            if len(fy_vals) < min_months:
                skipped += 1
                continue

            total = sum(fy_vals)
            max_ro += 1
            cl_norm = cl.lower().replace("/", "").replace(".", "").strip()

            fy_row = {
                "ro": max_ro,
                "rl": f"FY{fy_year}",
                "rn": f"fy{fy_year}",
                "co": 0,
                "cl": cl,
                "cn": cl_norm,
                "ts": f"FY{fy_year}",
                "y": fy_year,
                "m": None,
                "vr": _format_number(total),
                "nv": round(total, 4),
                "rt": "synthetic_fy_total",
                "cf": 0.95,
                "ps": "fiscal",
                "pf": [],
                "sl": "",
                "fn": [],
                "fy_months": len(fy_vals),
            }
            rows.append(fy_row)
            added += 1

    # Always save back: even if nothing was added, old synthetic rows were removed
    obj["rows"] = rows
    _pack_and_store(conn, table_pk, obj)

    return added, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich slim_v2 DB with calendar-year totals")
    parser.add_argument("--db", default="/tmp/officeqa_slim_v2.sqlite3", help="Path to slim_v2 DB")
    parser.add_argument("--min-months", type=int, default=12,
                        help="Minimum months required to create CY row (default: 12)")
    parser.add_argument("--dry-run", action="store_true", help="Count but don't write")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    # Find tables with monthly data
    tables = conn.execute("""
        SELECT table_pk, table_group_id, table_title, has_month_rows,
               min_year, max_year, period_basis
        FROM table_index
        WHERE has_month_rows = 1
        ORDER BY table_pk
    """).fetchall()

    print(f"Found {len(tables)} tables with monthly data")

    # Build group_id -> [table_pks] mapping for cross-bulletin merge
    group_map: dict[str, list[int]] = defaultdict(list)
    for t in tables:
        gid = t["table_group_id"]
        if gid:
            group_map[gid].append(t["table_pk"])

    # Process: pick ONE representative per group (latest bulletin)
    # to avoid duplicating CY rows across all copies
    processed_groups: set[str] = set()
    total_added = 0
    total_skipped = 0
    tables_enriched = 0

    t0 = time.time()
    for i, t in enumerate(tables):
        gid = t["table_group_id"]

        # Skip if we already processed this group
        if gid and gid in processed_groups:
            continue
        if gid:
            processed_groups.add(gid)

        group_pks = group_map.get(gid, []) if gid else None

        if args.dry_run:
            # Just count monthly data
            obj = _unpack_blob(conn, t["table_pk"])
            if obj:
                monthly_cells = sum(1 for r in obj["rows"] if r.get("m") is not None)
                if monthly_cells > 0:
                    print(f"  pk={t['table_pk']} title={t['table_title'][:50]} monthly_cells={monthly_cells}")
            continue

        added, skipped = enrich_table(
            conn, t["table_pk"],
            min_months=args.min_months,
            group_pks=group_pks,
        )
        total_added += added
        total_skipped += skipped
        if added > 0:
            tables_enriched += 1

        if (i + 1) % 500 == 0:
            conn.commit()
            elapsed = time.time() - t0
            print(f"  ... {i+1}/{len(tables)} processed, {total_added} CY rows added ({elapsed:.1f}s)")

    if not args.dry_run:
        conn.commit()

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s")
    print(f"Tables with monthly data: {len(tables)}")
    print(f"Unique groups processed: {len(processed_groups)}")
    print(f"Tables enriched: {tables_enriched}")
    print(f"CY rows added: {total_added}")
    print(f"CY rows skipped (< {args.min_months} months): {total_skipped}")

    conn.close()


if __name__ == "__main__":
    main()
