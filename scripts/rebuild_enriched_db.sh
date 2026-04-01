#!/bin/bash
set -euo pipefail

# Full DB rebuild pipeline: enrich → build master_ledger → compress → upload
#
# Usage:
#   bash scripts/rebuild_enriched_db.sh /path/to/officeqa_slim_v2.sqlite3
#
# Or on the droplet:
#   bash scripts/rebuild_enriched_db.sh /root/officeqa-serve/officeqa_slim_v2.sqlite3

DB_PATH="${1:-data/officeqa_corpus.sqlite3}"

if [ ! -f "$DB_PATH" ]; then
  echo "ERROR: DB not found at $DB_PATH"
  echo "Usage: bash scripts/rebuild_enriched_db.sh /path/to/db.sqlite3"
  exit 1
fi

echo "=========================================="
echo "OfficeQA DB Rebuild Pipeline"
echo "DB: $DB_PATH"
echo "=========================================="

# Check deps
python3 -c "import msgpack, zstandard" 2>/dev/null || {
  echo "Installing msgpack + zstandard..."
  pip3 install --quiet msgpack zstandard
}

# Step 1: Enrich with CY/FY totals
echo ""
echo "Step 1: Enriching CY/FY totals..."
python3 scripts/enrich_calendar_totals.py --db "$DB_PATH" --min-months 12

# Step 2: Build precomputed indexes
echo ""
echo "Step 2: Building indexes..."
python3 scripts/precompute_indexes.py "$DB_PATH"

# Step 3: Build master_ledger
echo ""
echo "Step 3: Building master_ledger..."
python3 scripts/build_master_ledger.py --db "$DB_PATH"

# Step 4: VACUUM to reclaim space
echo ""
echo "Step 4: VACUUMing DB..."
python3 -c "
import sqlite3
conn = sqlite3.connect('$DB_PATH')
conn.execute('VACUUM')
conn.close()
print('VACUUM complete.')
"

# Step 5: Compress
echo ""
echo "Step 5: Compressing..."
DB_DIR=$(dirname "$DB_PATH")
DB_NAME=$(basename "$DB_PATH")
ZST_PATH="${DB_DIR}/${DB_NAME}.zst"

# Use zstd level 19 for best compression (slow but small)
zstd -19 -T0 -f "$DB_PATH" -o "$ZST_PATH"
echo "Compressed: $(ls -lh "$ZST_PATH" | awk '{print $5}') -> $ZST_PATH"

# Step 6: Upload to web server (if on droplet)
WEB_DIR="/var/www/officeqa"
if [ -d "$WEB_DIR" ]; then
  echo ""
  echo "Step 6: Copying to web server..."
  cp "$ZST_PATH" "$WEB_DIR/officeqa_slim_v2.sqlite3.zst"
  echo "Available at: http://$(hostname -I | awk '{print $1}'):9090/officeqa_slim_v2.sqlite3.zst"
else
  echo ""
  echo "Step 6: Skipped (not on droplet). Upload manually:"
  echo "  scp $ZST_PATH root@157.245.243.14:/var/www/officeqa/officeqa_slim_v2.sqlite3.zst"
fi

echo ""
echo "=========================================="
echo "Rebuild complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. If on droplet: DB is already served at http://157.245.243.14:9090/"
echo "  2. If local: scp the .zst to the droplet"
echo "  3. Rebuild Daytona snapshot (if using): python3 scripts/daytona_sandbox.py snapshot"
echo "  4. Submit to Arena: arena submit"
