#!/usr/bin/env python3
"""Backfill missing min_year/max_year in table_index from multiple sources."""

import re
import sqlite3
import sys

YEAR_RE = re.compile(r'\b(1[89]\d{2}|20[0-2]\d)\b')
BULLETIN_RE = re.compile(r'treasury_bulletin_(\d{4})_\d{2}')


def extract_years(text: str) -> list[int]:
    """Extract all 4-digit years (1800-2029) from text."""
    if not text:
        return []
    return [int(m) for m in YEAR_RE.findall(text)]


def tier1_title(cur: sqlite3.Cursor) -> int:
    """Extract years from table_title."""
    cur.execute(
        "SELECT table_pk, table_title FROM table_index "
        "WHERE min_year IS NULL AND table_title IS NOT NULL"
    )
    updates = []
    for pk, title in cur.fetchall():
        years = extract_years(title)
        if years:
            updates.append((min(years), max(years), pk))
    cur.executemany(
        "UPDATE table_index SET min_year=?, max_year=? "
        "WHERE table_pk=? AND min_year IS NULL",
        updates,
    )
    return len(updates)


def tier2_row_label(cur: sqlite3.Cursor) -> int:
    """Extract years from row_label in table_first_table_cells."""
    cur.execute(
        "SELECT t.table_pk, c.row_label "
        "FROM table_index t "
        "JOIN table_first_table_cells c ON c.table_pk = t.table_pk "
        "WHERE t.min_year IS NULL AND c.row_label IS NOT NULL"
    )
    table_years: dict[int, list[int]] = {}
    for pk, label in cur.fetchall():
        years = extract_years(label)
        if years:
            table_years.setdefault(pk, []).extend(years)
    updates = [(min(yrs), max(yrs), pk) for pk, yrs in table_years.items()]
    cur.executemany(
        "UPDATE table_index SET min_year=?, max_year=? "
        "WHERE table_pk=? AND min_year IS NULL",
        updates,
    )
    return len(updates)


def tier3_column_label(cur: sqlite3.Cursor) -> int:
    """Extract years from column_label in table_first_table_cells."""
    cur.execute(
        "SELECT t.table_pk, c.column_label "
        "FROM table_index t "
        "JOIN table_first_table_cells c ON c.table_pk = t.table_pk "
        "WHERE t.min_year IS NULL AND c.column_label IS NOT NULL"
    )
    table_years: dict[int, list[int]] = {}
    for pk, label in cur.fetchall():
        years = extract_years(label)
        if years:
            table_years.setdefault(pk, []).extend(years)
    updates = [(min(yrs), max(yrs), pk) for pk, yrs in table_years.items()]
    cur.executemany(
        "UPDATE table_index SET min_year=?, max_year=? "
        "WHERE table_pk=? AND min_year IS NULL",
        updates,
    )
    return len(updates)


def tier4_bulletin_date(cur: sqlite3.Cursor) -> int:
    """Fallback: use bulletin year from source_file."""
    cur.execute(
        "SELECT table_pk, source_file FROM table_index "
        "WHERE min_year IS NULL AND source_file IS NOT NULL"
    )
    updates = []
    for pk, src in cur.fetchall():
        m = BULLETIN_RE.search(src)
        if m:
            yr = int(m.group(1))
            updates.append((yr - 1, yr, pk))
    cur.executemany(
        "UPDATE table_index SET min_year=?, max_year=? "
        "WHERE table_pk=? AND min_year IS NULL",
        updates,
    )
    return len(updates)


def build_dedup_groups(cur: sqlite3.Cursor) -> int:
    """Create table_dedup_groups aggregation table."""
    cur.execute("DROP TABLE IF EXISTS table_dedup_groups")
    cur.execute("""
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
    cur.execute("SELECT COUNT(*) FROM table_dedup_groups")
    return cur.fetchone()[0]


def main():
    if len(sys.argv) < 2:
        print("Usage: python backfill_years.py <db_path>")
        sys.exit(1)

    db_path = sys.argv[1]
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Baseline
    cur.execute("SELECT COUNT(*) FROM table_index")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM table_index WHERE min_year IS NULL")
    null_before = cur.fetchone()[0]
    print(f"Total tables: {total}")
    print(f"Missing years before backfill: {null_before}")
    print()

    # Tier 1
    n = tier1_title(cur)
    conn.commit()
    print(f"Tier 1 (table_title):   {n:>6} recovered")

    # Tier 2
    n = tier2_row_label(cur)
    conn.commit()
    print(f"Tier 2 (row_label):     {n:>6} recovered")

    # Tier 3
    n = tier3_column_label(cur)
    conn.commit()
    print(f"Tier 3 (column_label):  {n:>6} recovered")

    # Tier 4
    n = tier4_bulletin_date(cur)
    conn.commit()
    print(f"Tier 4 (bulletin date): {n:>6} recovered")

    # Final stats
    cur.execute("SELECT COUNT(*) FROM table_index WHERE min_year IS NULL")
    null_after = cur.fetchone()[0]
    covered = total - null_after
    pct = covered / total * 100 if total else 0
    print()
    print(f"Missing years after backfill: {null_after}")
    print(f"Coverage: {covered}/{total} ({pct:.1f}%)")

    # Dedup groups
    print()
    n_groups = build_dedup_groups(cur)
    conn.commit()
    print(f"Dedup groups created: {n_groups}")

    conn.close()


if __name__ == "__main__":
    main()
