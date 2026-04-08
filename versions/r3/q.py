#!/usr/bin/env python3
"""Query the parsed data DB. Usage:
  python3 q.py "SELECT * FROM cells WHERE row_label LIKE '%Army%'"
  python3 q.py tables              -- list all tables
  python3 q.py schema              -- show schema
"""
import sqlite3, sys, os

DB_PATH = "/tmp/data.db"

def main():
    if not os.path.exists(DB_PATH):
        print("DB not found. Run: python3 /app/resources/build_db.py")
        sys.exit(1)

    if len(sys.argv) < 2:
        print("Usage: python3 q.py SQL_QUERY")
        print("       python3 q.py tables")
        print("       python3 q.py schema")
        sys.exit(1)

    query = " ".join(sys.argv[1:])
    conn = sqlite3.connect(DB_PATH)

    if query.strip().lower() == "schema":
        for row in conn.execute("SELECT sql FROM sqlite_master WHERE type='table'"):
            print(row[0])
        return

    if query.strip().lower() == "tables":
        for row in conn.execute("SELECT file, table_num, headers FROM tables_meta ORDER BY file, table_num"):
            print(f"{row[0]} Table {row[1]}: {row[2][:120]}")
        return

    try:
        cur = conn.execute(query)
        cols = [d[0] for d in cur.description] if cur.description else []
        if cols:
            print(" | ".join(cols))
            print("-" * 40)
        count = 0
        for row in cur:
            print(" | ".join(str(v) for v in row))
            count += 1
            if count >= 200:
                print(f"... (truncated at 200 rows)")
                break
        if count == 0:
            print("(no results)")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
