#!/bin/bash
set -euo pipefail

# Rebuild enriched DB on the droplet and serve it.
#
# Run this FROM YOUR LOCAL MACHINE:
#   bash scripts/droplet_rebuild.sh
#
# What it does:
#   1. Syncs latest code to droplet
#   2. SSHs in and runs the full rebuild pipeline
#   3. DB is automatically served at http://157.245.243.14:9090/

DROPLET="root@157.245.243.14"
REMOTE_DIR="/root/officeqa-serve"
DB_PATH="/root/officeqa-serve/officeqa_slim_v2.sqlite3"

echo "=== Step 1: Sync code to droplet ==="
rsync -avz --exclude='__pycache__' --exclude='.git' --exclude='data/' \
  --exclude='results/' --exclude='.arena/' --exclude='.env' \
  --exclude='node_modules/' --exclude='poll_log.jsonl' \
  ./ "${DROPLET}:${REMOTE_DIR}/"
echo "Code synced."

echo ""
echo "=== Step 2: Run rebuild on droplet ==="
ssh "${DROPLET}" bash -s <<'REMOTE_SCRIPT'
set -euo pipefail
cd /root/officeqa-serve

# Ensure deps
pip3 install --quiet msgpack zstandard 2>/dev/null || true

DB="/root/officeqa-serve/officeqa_slim_v2.sqlite3"

# Check if DB exists (decompressed)
if [ ! -f "$DB" ]; then
  echo "Decompressing DB..."
  ZST="/var/www/officeqa/officeqa_slim_v2.sqlite3.zst"
  if [ -f "$ZST" ]; then
    zstd -d -f "$ZST" -o "$DB"
  else
    echo "ERROR: No DB found at $DB or $ZST"
    exit 1
  fi
fi

echo "DB size: $(ls -lh $DB | awk '{print $5}')"

# Run enrichment
echo ""
echo "--- Enriching CY/FY totals ---"
python3 scripts/enrich_calendar_totals.py --db "$DB" --min-months 12

# Run indexes
echo ""
echo "--- Building indexes ---"
python3 scripts/precompute_indexes.py "$DB"

# Build master_ledger
echo ""
echo "--- Building master_ledger ---"
python3 scripts/build_master_ledger.py --db "$DB"

# Verify synthesis
echo ""
echo "--- Verifying synthesis (first 100 tables) ---"
python3 scripts/verify_synthesis.py --db "$DB" --limit 100

# Compress and serve
echo ""
echo "--- Compressing and serving ---"
zstd -19 -T0 -f "$DB" -o "/var/www/officeqa/officeqa_slim_v2.sqlite3.zst"
echo "Compressed: $(ls -lh /var/www/officeqa/officeqa_slim_v2.sqlite3.zst | awk '{print $5}')"
echo ""
echo "DB now served at: http://157.245.243.14:9090/officeqa_slim_v2.sqlite3.zst"
REMOTE_SCRIPT

echo ""
echo "=== Done! ==="
echo ""
echo "Next steps:"
echo "  1. Sync code changes: rsync (already done above)"
echo "  2. If using Daytona: rebuild snapshot with: python3 scripts/daytona_sandbox.py snapshot"
echo "  3. Submit: cd to droplet and run: arena submit"
echo "  4. Or submit locally if arena CLI is configured"
