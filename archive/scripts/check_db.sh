#!/usr/bin/env bash
set -euo pipefail

# Validate DB contract — checks that the SQLite DB has the required tables
# for the gold/fallback/silver retrieval paths.
#
# Usage:
#   ./scripts/check_db.sh                          # check local DB
#   ./scripts/check_db.sh /path/to/db.sqlite3      # check specific DB
#   ssh root@64.23.196.53 'bash -s' < scripts/check_db.sh /root/officeqa-serve/officeqa_slim_v2.sqlite3

DB="${1:-}"

if [ -z "$DB" ]; then
  # Auto-detect local DB
  for candidate in \
    "data/officeqa_slim_v2.sqlite3" \
    "data/officeqa_corpus.sqlite3" \
    "/app/corpus/officeqa_enriched.sqlite3" \
    "/app/corpus/officeqa_corpus.sqlite3"
  do
    if [ -f "$candidate" ]; then
      DB="$candidate"
      break
    fi
  done
fi

if [ -z "$DB" ] || [ ! -f "$DB" ]; then
  echo "ERROR: No DB found. Pass a path or run from project root."
  exit 1
fi

echo "=== DB Contract Check ==="
echo "File: $DB"
echo "Size: $(ls -lh "$DB" | awk '{print $5}')"
echo ""

# Required tables for each retrieval path
echo "--- Retrieval Path Tables ---"
for table in canonical_facts master_ledger table_index table_scope_index table_cell_blobs table_first_tables col_label_lookup; do
  count=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='$table';" 2>/dev/null || echo "0")
  if [ "$count" = "1" ]; then
    rows=$(sqlite3 "$DB" "SELECT COUNT(*) FROM $table;" 2>/dev/null || echo "?")
    printf "  %-25s ✓  (%s rows)\n" "$table" "$rows"
  else
    printf "  %-25s ✗  MISSING\n" "$table"
  fi
done

echo ""
echo "--- All Tables ---"
sqlite3 "$DB" "SELECT name, (SELECT COUNT(*) FROM pragma_table_info(name)) as cols FROM sqlite_master WHERE type='table' ORDER BY name;" 2>/dev/null | while IFS='|' read -r name cols; do
  rows=$(sqlite3 "$DB" "SELECT COUNT(*) FROM \"$name\";" 2>/dev/null || echo "?")
  printf "  %-30s %s cols, %s rows\n" "$name" "$cols" "$rows"
done

echo ""
echo "--- Path Availability ---"
has_canonical=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='canonical_facts';" 2>/dev/null || echo "0")
has_ledger=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='master_ledger';" 2>/dev/null || echo "0")

if [ "$has_canonical" = "1" ]; then
  echo "  GOLD PATH (search_canonical):    AVAILABLE"
else
  echo "  GOLD PATH (search_canonical):    UNAVAILABLE"
fi

if [ "$has_ledger" = "1" ]; then
  echo "  FALLBACK (search_ledger):        AVAILABLE"
else
  echo "  FALLBACK (search_ledger):        UNAVAILABLE"
fi

echo ""
echo "Done."
