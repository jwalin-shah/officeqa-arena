#!/usr/bin/env python3
"""Verify CY/FY synthetic totals match the sum of individual monthly values.

Reads table_cell_blobs, finds synthetic CY/FY rows, manually sums the
constituent monthly values, and reports any discrepancies.

Usage:
    python3 scripts/verify_synthesis.py --db /path/to/db.sqlite3
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import msgpack
import zstandard

_dctx = zstandard.ZstdDecompressor()


def verify_table(conn: sqlite3.Connection, table_pk: int) -> list[dict]:
    """Verify synthetic rows in one table. Returns list of mismatches."""
    row = conn.execute(
        "SELECT data FROM table_cell_blobs WHERE table_pk = ?", (table_pk,)
    ).fetchone()
    if row is None:
        return []

    raw = _dctx.decompress(row["data"])
    obj = msgpack.unpackb(raw, raw=False)
    cells = obj.get("rows", [])

    # Collect monthly values: (column_label, row_label_base, year) -> {month: value}
    monthly: dict[tuple, dict[int, float]] = defaultdict(dict)
    synthetic: list[dict] = []

    for cell in cells:
        rl = cell.get("rl", "")
        cl = cell.get("cl", "")
        y = cell.get("y")
        m = cell.get("m")
        nv = cell.get("nv")
        rt = cell.get("rt", "")

        if rt and ("synthetic_cy" in rt or "synthetic_fy" in rt):
            synthetic.append(cell)
            continue

        if m is not None and y is not None and nv is not None and cl:
            try:
                monthly[(cl, rl, int(y))][int(m)] = float(nv)
            except (TypeError, ValueError):
                pass

    mismatches = []
    for cell in synthetic:
        rl = cell.get("rl", "")
        cl = cell.get("cl", "")
        y = cell.get("y")
        nv = cell.get("nv")
        rt = cell.get("rt", "")

        if nv is None or y is None:
            continue

        synthetic_total = float(nv)

        # Parse the row_label to find the category
        # Format: "CY1940 — National defense" or just "CY1940"
        rl_category = ""
        if " — " in rl:
            rl_category = rl.split(" — ", 1)[1]

        if "synthetic_cy" in rt:
            # Sum Jan-Dec for this column + category
            manual_sum = 0.0
            months_found = 0
            for month in range(1, 13):
                # Try with category, then without
                val = monthly.get((cl, rl_category, y), {}).get(month)
                if val is None and rl_category:
                    # Try with empty row_label (old format)
                    val = monthly.get((cl, "", y), {}).get(month)
                if val is not None:
                    manual_sum += val
                    months_found += 1

            if months_found >= 10:  # need enough months to compare
                delta = abs(synthetic_total - manual_sum)
                if delta > 0.01:
                    mismatches.append({
                        "table_pk": table_pk,
                        "type": "CY",
                        "year": y,
                        "column": cl,
                        "category": rl_category,
                        "synthetic": round(synthetic_total, 2),
                        "manual_sum": round(manual_sum, 2),
                        "delta": round(delta, 2),
                        "months_found": months_found,
                    })

        elif "synthetic_fy" in rt:
            # Sum fiscal year months
            if y <= 1976:
                fy_months = [(y - 1, m) for m in range(7, 13)] + [(y, m) for m in range(1, 7)]
            else:
                fy_months = [(y - 1, m) for m in range(10, 13)] + [(y, m) for m in range(1, 10)]

            manual_sum = 0.0
            months_found = 0
            for cal_yr, month in fy_months:
                val = monthly.get((cl, rl_category, cal_yr), {}).get(month)
                if val is None and rl_category:
                    val = monthly.get((cl, "", cal_yr), {}).get(month)
                if val is not None:
                    manual_sum += val
                    months_found += 1

            if months_found >= 10:
                delta = abs(synthetic_total - manual_sum)
                if delta > 0.01:
                    mismatches.append({
                        "table_pk": table_pk,
                        "type": "FY",
                        "year": y,
                        "column": cl,
                        "category": rl_category,
                        "synthetic": round(synthetic_total, 2),
                        "manual_sum": round(manual_sum, 2),
                        "delta": round(delta, 2),
                        "months_found": months_found,
                    })

    return mismatches


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="Path to enriched SQLite DB")
    parser.add_argument("--limit", type=int, default=0, help="Max tables to check (0=all)")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    # Find tables with synthetic rows
    tables = conn.execute("""
        SELECT table_pk FROM table_index
        WHERE has_month_rows = 1
        ORDER BY table_pk
    """).fetchall()

    print(f"Checking {len(tables)} tables with monthly data...")

    all_mismatches = []
    for i, t in enumerate(tables):
        if args.limit and i >= args.limit:
            break
        mismatches = verify_table(conn, t["table_pk"])
        all_mismatches.extend(mismatches)
        if (i + 1) % 500 == 0:
            print(f"  ... {i+1}/{len(tables)} checked, {len(all_mismatches)} mismatches so far")

    print(f"\n{'='*60}")
    print(f"Total tables checked: {min(len(tables), args.limit or len(tables))}")
    print(f"Total mismatches: {len(all_mismatches)}")

    if all_mismatches:
        print(f"\nMismatches (delta > 0.01):")
        for m in all_mismatches[:50]:
            print(f"  pk={m['table_pk']} {m['type']}{m['year']} col='{m['column'][:30]}' "
                  f"cat='{m['category'][:20]}' "
                  f"synth={m['synthetic']} manual={m['manual_sum']} "
                  f"delta={m['delta']} months={m['months_found']}")
    else:
        print("\nAll synthetic totals match! ✓")

    conn.close()


if __name__ == "__main__":
    main()
