#!/bin/bash
set -euo pipefail

# =============================================================================
# Full droplet setup: install deps, clone repo, reingest DB, enrich, serve
#
# Run on the droplet:
#   nohup bash droplet_full_setup.sh > /tmp/setup.log 2>&1 &
#   tail -f /tmp/setup.log
#
# Or if you want to watch live:
#   bash droplet_full_setup.sh 2>&1 | tee /tmp/setup.log
# =============================================================================

WORK_DIR="/tmp/officeqa_reingest"
REPO_URL="https://github.com/databricks/officeqa.git"
OUR_REPO="https://github.com/jwalin-shah/officeqa-arena.git"  # adjust if private
JSON_DIR="$WORK_DIR/jsons"
DB_OUTPUT="$WORK_DIR/officeqa_slim_v2.sqlite3"
DB_COMPRESSED="$WORK_DIR/officeqa_slim_v2.sqlite3.zst"
SERVE_DIR="/srv/officeqa"

echo "============================================"
echo "  OfficeQA Droplet Full Setup"
echo "  $(date)"
echo "============================================"
echo ""

mkdir -p "$WORK_DIR" "$SERVE_DIR"

# ── Step 1: System deps ──────────────────────────────────────────
echo "[1/7] Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq git python3-pip zstd nginx curl
pip3 install --break-system-packages msgpack zstandard 2>/dev/null || \
  pip3 install msgpack zstandard
echo "  Done."

# ── Step 2: Get Databricks OfficeQA JSONs ────────────────────────
echo ""
echo "[2/7] Downloading source JSONs from Databricks repo..."

JSON_COUNT=$(ls -1 "$JSON_DIR"/*.json 2>/dev/null | wc -l || echo 0)
if [ "$JSON_COUNT" -gt 600 ]; then
    echo "  JSONs already present ($JSON_COUNT files), skipping."
else
    CLONE_DIR="$WORK_DIR/officeqa_repo"
    if [ ! -d "$CLONE_DIR/.git" ]; then
        echo "  Sparse-cloning Databricks officeqa repo..."
        git clone --filter=blob:none --sparse "$REPO_URL" "$CLONE_DIR"
        cd "$CLONE_DIR"
        git sparse-checkout set treasury_bulletins_parsed
        cd -
    else
        echo "  Repo already cloned."
    fi

    echo "  Extracting JSONs..."
    mkdir -p "$JSON_DIR"
    cd "$CLONE_DIR/treasury_bulletins_parsed"

    # Try the provided unzip.py first, fall back to manual
    if [ -f unzip.py ]; then
        python3 unzip.py 2>/dev/null || true
    fi

    # Manual extraction of any remaining zips
    for f in jsons/*.zip; do
        [ -f "$f" ] || continue
        echo "  Unzipping $(basename "$f")..."
        python3 -c "
import zipfile
with zipfile.ZipFile('$f') as z:
    z.extractall('jsons/')
" 2>/dev/null || true
    done

    # Move JSONs to working directory
    cp jsons/*.json "$JSON_DIR/" 2>/dev/null || true
    cd -

    JSON_COUNT=$(ls -1 "$JSON_DIR"/*.json 2>/dev/null | wc -l)
    echo "  Extracted $JSON_COUNT JSON files"

    if [ "$JSON_COUNT" -lt 600 ]; then
        echo "  WARNING: Expected ~697 JSONs, got $JSON_COUNT"
        echo "  Continuing anyway..."
    fi
fi

# ── Step 3: Get our repo scripts ─────────────────────────────────
echo ""
echo "[3/7] Getting officeqa-arena scripts..."

ARENA_DIR="$WORK_DIR/officeqa-arena"
if [ ! -d "$ARENA_DIR/.git" ]; then
    # Try cloning, fall back to SCP from local
    git clone "$OUR_REPO" "$ARENA_DIR" 2>/dev/null || {
        echo "  Git clone failed (repo might be private)."
        echo "  Please SCP the scripts directory manually:"
        echo "    scp -r scripts/ root@$(hostname -I | awk '{print $1}'):/tmp/officeqa_reingest/officeqa-arena/scripts/"
        echo ""
        echo "  Or copy the scripts dir from your local machine."
        echo "  Then re-run this script."

        # Check if scripts are already here from a previous copy
        if [ -f "$ARENA_DIR/scripts/reingest_from_json.py" ]; then
            echo "  Found existing scripts, continuing..."
        else
            exit 1
        fi
    }
else
    echo "  Repo already cloned, pulling latest..."
    cd "$ARENA_DIR" && git pull 2>/dev/null || true && cd -
fi

SCRIPTS="$ARENA_DIR/scripts"
if [ ! -f "$SCRIPTS/reingest_from_json.py" ]; then
    echo "  ERROR: reingest_from_json.py not found at $SCRIPTS/"
    echo "  SCP scripts manually and re-run."
    exit 1
fi

# ── Step 4: Run re-ingestion ─────────────────────────────────────
echo ""
echo "[4/7] Running re-ingestion (this takes 20-30 minutes)..."
echo "  Input:  $JSON_DIR"
echo "  Output: $DB_OUTPUT"
echo "  Started: $(date)"
echo ""

if [ -f "$DB_OUTPUT" ]; then
    DB_SIZE=$(du -h "$DB_OUTPUT" | cut -f1)
    echo "  DB already exists ($DB_SIZE). Skipping reingest."
    echo "  (Delete $DB_OUTPUT to force rebuild)"
else
    cd "$ARENA_DIR"
    python3 scripts/reingest_from_json.py \
        --json-dir "$JSON_DIR" \
        --output "$DB_OUTPUT"
    cd -
    echo "  Reingest complete: $(du -h "$DB_OUTPUT" | cut -f1)"
fi

# ── Step 5: Enrich DB (CY/FY totals, indexes, master ledger) ────
echo ""
echo "[5/7] Enriching DB (CY/FY totals, indexes, master ledger)..."
echo "  Started: $(date)"

cd "$ARENA_DIR"

# CY/FY totals
echo "  Step 5a: CY/FY totals..."
python3 scripts/enrich_calendar_totals.py --db "$DB_OUTPUT" --min-months 12 2>&1 | tail -3

# Precomputed indexes
echo "  Step 5b: Precomputed indexes..."
python3 scripts/precompute_indexes.py "$DB_OUTPUT" 2>&1 | tail -3

# Master ledger
echo "  Step 5c: Master ledger..."
if [ -f scripts/build_master_ledger.py ]; then
    python3 scripts/build_master_ledger.py --db "$DB_OUTPUT" 2>&1 | tail -3
else
    echo "  build_master_ledger.py not found, skipping."
fi

cd -

# VACUUM
echo "  Step 5d: VACUUM..."
python3 -c "
import sqlite3
conn = sqlite3.connect('$DB_OUTPUT')
conn.execute('VACUUM')
conn.close()
print('  VACUUM complete.')
"

echo "  Enrichment complete: $(du -h "$DB_OUTPUT" | cut -f1)"

# ── Step 6: Compress ─────────────────────────────────────────────
echo ""
echo "[6/7] Compressing with zstd..."

zstd -19 -T0 -f "$DB_OUTPUT" -o "$DB_COMPRESSED"
echo "  Compressed: $(du -h "$DB_COMPRESSED" | cut -f1)"

# ── Step 7: Serve via nginx ──────────────────────────────────────
echo ""
echo "[7/7] Deploying to web server..."

cp "$DB_COMPRESSED" "$SERVE_DIR/officeqa_slim_v2.sqlite3.zst"

# Also copy the uncompressed DB in case useful
# cp "$DB_OUTPUT" "$SERVE_DIR/officeqa_slim_v2.sqlite3"

# Ensure nginx is running
systemctl start nginx 2>/dev/null || nginx 2>/dev/null || true

IP=$(hostname -I | awk '{print $1}')
echo "  Served at: http://${IP}:9090/officeqa_slim_v2.sqlite3.zst"
echo ""

# Verify it's accessible
sleep 1
if curl -sI "http://localhost:9090/officeqa_slim_v2.sqlite3.zst" | head -1 | grep -q 200; then
    echo "  ✓ HTTP 200 — file is accessible"
else
    echo "  ✗ File not accessible via HTTP. Check nginx config."
    echo "  nginx config should have: root /srv/officeqa; on port 9090"
fi

echo ""
echo "============================================"
echo "  Setup complete! $(date)"
echo "============================================"
echo ""
echo "DB URL:  http://${IP}:9090/officeqa_slim_v2.sqlite3.zst"
echo "DB size: $(du -h "$DB_COMPRESSED" | cut -f1) compressed"
echo "         $(du -h "$DB_OUTPUT" | cut -f1) uncompressed"
echo ""
echo "Next steps:"
echo "  1. Update install.sh DB_URL to http://${IP}:9090/officeqa_slim_v2.sqlite3.zst"
echo "  2. Run: arena test --smoke"
echo "  3. If good: arena submit"
