#!/usr/bin/env python3
"""Fallback DB query tool — use when MCP tools are unavailable.

Usage:
    python3 /installed-agent/fallback_query.py search <metric> [year]
    python3 /installed-agent/fallback_query.py series <metric> <year>
    python3 /installed-agent/fallback_query.py tables <query>
    python3 /installed-agent/fallback_query.py sql "SELECT ..."
    python3 /installed-agent/fallback_query.py schema
    python3 /installed-agent/fallback_query.py compute "<expr>" '{"a":1,"b":2}'

The DB is auto-discovered from OFFICEQA_SQLITE_DB env var or standard paths.
"""

import json
import math
import os
import sqlite3
import sys


def _find_db():
    """Find the SQLite database."""
    candidates = [
        os.environ.get("OFFICEQA_SQLITE_DB", ""),
        "/installed-agent/officeqa_optimal.sqlite3",
        "/app/corpus/officeqa_enriched.sqlite3",
        "/app/corpus/officeqa_corpus.sqlite3",
        "/installed-agent/officeqa_slim_v2.sqlite3",
        "/installed-agent/data/officeqa_slim_v2.sqlite3",
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    # Last resort: scan
    for d in ["/app/corpus", "/installed-agent/data", "/installed-agent"]:
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.endswith(".sqlite3"):
                    return os.path.join(d, f)
    return None


def _connect():
    db = _find_db()
    if not db:
        print("ERROR: No SQLite database found.", file=sys.stderr)
        print("Try: zstd -d /installed-agent/officeqa_optimal.sqlite3.zst -o /installed-agent/officeqa_optimal.sqlite3 -f", file=sys.stderr)
        sys.exit(1)
    print(f"DB: {db}", file=sys.stderr)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn


def cmd_schema(conn):
    """Print table names and column info."""
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    for (t,) in tables:
        cols = conn.execute(f"PRAGMA table_info([{t}])").fetchall()
        cnt = conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
        col_names = [c["name"] for c in cols]
        print(f"\n{t} ({cnt:,} rows): {', '.join(col_names)}")


def cmd_search(conn, metric, year=None):
    """Search canonical_facts for a metric, optionally filtered by year."""
    has_cf = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='canonical_facts'"
    ).fetchone()
    has_ml = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='master_ledger'"
    ).fetchone()

    results = []
    terms = [f"%{w}%" for w in metric.lower().split()]

    # Search canonical_facts
    if has_cf:
        where = " AND ".join(
            ["(LOWER(metric_key) LIKE ? OR LOWER(row_label) LIKE ? OR LOWER(table_title) LIKE ?)"]
            * len(terms)
        )
        params = []
        for t in terms:
            params.extend([t, t, t])
        if year:
            where += " AND year = ?"
            params.append(int(year))
        rows = conn.execute(
            f"SELECT canonical_key, metric_key, time_key, year, month, value, "
            f"unit_type, table_title, row_label, column_label, period_basis, source_file "
            f"FROM canonical_facts WHERE {where} ORDER BY variant_count DESC LIMIT 20",
            params,
        ).fetchall()
        for r in rows:
            results.append({k: r[k] for k in r.keys()})

    # Search master_ledger if canonical had few results
    if has_ml and len(results) < 5:
        where_ml = " AND ".join(["LOWER(metric_slug) LIKE ?"] * len(terms))
        params_ml = list(terms)
        if year:
            where_ml += " AND time_key LIKE ?"
            params_ml.append(f"%{year}%")
        ml_rows = conn.execute(
            f"SELECT metric_slug, time_key, value, table_title, source_file, period_basis "
            f"FROM master_ledger WHERE {where_ml} ORDER BY ROWID DESC LIMIT 15",
            params_ml,
        ).fetchall()
        for r in ml_rows:
            results.append({"source": "master_ledger", **{k: r[k] for k in r.keys()}})

    if results:
        print(json.dumps(results[:20], indent=2, default=str))
    else:
        print("No results found.")


def cmd_series(conn, metric, year):
    """Get monthly time series for a metric and year."""
    terms = [f"%{w}%" for w in metric.lower().split()]

    where = " AND ".join(
        ["(LOWER(metric_key) LIKE ? OR LOWER(row_label) LIKE ?)"] * len(terms)
    )
    params = []
    for t in terms:
        params.extend([t, t])
    params.append(int(year))

    rows = conn.execute(
        f"SELECT metric_key, time_key, year, month, value, unit_type, row_label "
        f"FROM canonical_facts WHERE {where} AND year = ? AND month IS NOT NULL "
        f"ORDER BY month",
        params,
    ).fetchall()

    if rows:
        total = 0.0
        for r in rows:
            d = {k: r[k] for k in r.keys()}
            print(json.dumps(d, default=str))
            if r["value"] is not None:
                total += float(r["value"])
        print(f"\nSUM = {total}")
    else:
        print("No monthly data found. Try: search <metric> <year>")


def cmd_tables(conn, query):
    """Search for tables matching a query."""
    terms = [f"%{w}%" for w in query.lower().split()]
    where = " AND ".join(["LOWER(table_title_norm) LIKE ?"] * len(terms))
    rows = conn.execute(
        f"SELECT table_pk, source_file, table_title_norm, table_family "
        f"FROM table_index WHERE {where} LIMIT 20",
        terms,
    ).fetchall()
    if rows:
        for r in rows:
            print(json.dumps({k: r[k] for k in r.keys()}, default=str))
    else:
        print("No tables found.")


def cmd_sql(conn, query):
    """Run a read-only SQL query."""
    q = query.strip()
    if not q.upper().startswith("SELECT"):
        print("ERROR: Only SELECT queries allowed.", file=sys.stderr)
        sys.exit(1)
    try:
        rows = conn.execute(q).fetchall()
        if rows:
            for r in rows[:50]:
                print(json.dumps({k: r[k] for k in r.keys()}, default=str))
            if len(rows) > 50:
                print(f"... ({len(rows)} total rows, showing first 50)")
        else:
            print("No rows returned.")
    except Exception as e:
        print(f"SQL error: {e}", file=sys.stderr)


def cmd_compute(expr_str, vars_str=None):
    """Evaluate a math expression with optional variables."""
    variables = {}
    if vars_str:
        variables = json.loads(vars_str)

    ns = {
        "abs": abs, "round": round, "min": min, "max": max,
        "sum": sum, "len": len, "pow": pow,
        "sqrt": math.sqrt, "log": math.log, "log10": math.log10,
        "exp": math.exp, "pi": math.pi, "e": math.e,
    }
    ns.update(variables)

    try:
        result = eval(expr_str, {"__builtins__": {}}, ns)
        print(f"Result: {result}")
    except Exception as e:
        print(f"Compute error: {e}", file=sys.stderr)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "compute":
        cmd_compute(sys.argv[2] if len(sys.argv) > 2 else "",
                     sys.argv[3] if len(sys.argv) > 3 else None)
        return

    conn = _connect()

    if cmd == "schema":
        cmd_schema(conn)
    elif cmd == "search":
        metric = sys.argv[2] if len(sys.argv) > 2 else ""
        year = sys.argv[3] if len(sys.argv) > 3 else None
        cmd_search(conn, metric, year)
    elif cmd == "series":
        metric = sys.argv[2] if len(sys.argv) > 2 else ""
        year = sys.argv[3] if len(sys.argv) > 3 else ""
        cmd_series(conn, metric, int(year))
    elif cmd == "tables":
        query = " ".join(sys.argv[2:])
        cmd_tables(conn, query)
    elif cmd == "sql":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        cmd_sql(conn, query)
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
