#!/bin/bash
# Full re-ingestion pipeline for the DigitalOcean droplet.
#
# Downloads source JSONs from GitHub, parses them with series_label recovery,
# builds a slim DB with compressed blobs, and serves it.
#
# Usage: bash scripts/droplet_reingest.sh [output_dir]
#   output_dir defaults to /tmp/officeqa_reingest

set -euo pipefail

OUTPUT_DIR="${1:-/tmp/officeqa_reingest}"
REPO_URL="https://github.com/databricks/officeqa.git"
JSON_DIR="$OUTPUT_DIR/jsons"
DB_OUTPUT="$OUTPUT_DIR/officeqa_slim_v2.sqlite3"
DB_COMPRESSED="$OUTPUT_DIR/officeqa_slim_v2.sqlite3.zst"

echo "=== OfficeQA Full Re-ingestion Pipeline ==="
echo "Output dir: $OUTPUT_DIR"
echo ""

mkdir -p "$OUTPUT_DIR"

# ── Step 1: Get source JSONs ───────────────────────────────────────
if [ -d "$JSON_DIR" ] && [ "$(ls -1 "$JSON_DIR"/*.json 2>/dev/null | wc -l)" -gt 600 ]; then
    echo "[1/5] JSONs already present ($JSON_DIR), skipping download"
else
    echo "[1/5] Downloading source JSONs from GitHub..."

    # Sparse checkout — only get the parsed JSONs, not the 20GB PDFs
    CLONE_DIR="$OUTPUT_DIR/officeqa_repo"
    if [ ! -d "$CLONE_DIR" ]; then
        git clone --filter=blob:none --sparse "$REPO_URL" "$CLONE_DIR"
        cd "$CLONE_DIR"
        git sparse-checkout set treasury_bulletins_parsed/jsons treasury_bulletins_parsed/unzip.py
        cd -
    fi

    echo "  Extracting zips..."
    mkdir -p "$JSON_DIR"
    cd "$CLONE_DIR/treasury_bulletins_parsed"
    python3 unzip.py || {
        # Fallback: manual unzip
        for f in jsons/*.zip; do
            echo "  Unzipping $f..."
            python3 -c "
import zipfile, sys
with zipfile.ZipFile('$f') as z:
    z.extractall('jsons/')
"
        done
    }

    # Move JSONs to our working directory
    mv jsons/*.json "$JSON_DIR/" 2>/dev/null || true
    cd -

    JSON_COUNT=$(ls -1 "$JSON_DIR"/*.json 2>/dev/null | wc -l)
    echo "  Extracted $JSON_COUNT JSON files"

    if [ "$JSON_COUNT" -lt 600 ]; then
        echo "  ERROR: Expected ~697 JSONs, got $JSON_COUNT"
        exit 1
    fi
fi

# ── Step 2: Install Python deps ────────────────────────────────────
echo "[2/5] Checking Python dependencies..."
python3 -c "import msgpack; import zstandard" 2>/dev/null || {
    echo "  Installing msgpack and zstandard..."
    pip3 install msgpack zstandard
}

# ── Step 3: Run re-ingestion ───────────────────────────────────────
echo "[3/5] Running re-ingestion (this takes ~20-30 minutes)..."
echo "  Input:  $JSON_DIR"
echo "  Output: $DB_OUTPUT"
echo ""

python3 scripts/reingest_from_json.py \
    --json-dir "$JSON_DIR" \
    --output "$DB_OUTPUT"

# ── Step 4: Compress for serving ───────────────────────────────────
echo ""
echo "[4/5] Compressing with zstd (level 19)..."
zstd -19 -T0 --rm -f "$DB_OUTPUT" -o "$DB_COMPRESSED"

COMP_SIZE=$(du -h "$DB_COMPRESSED" | cut -f1)
echo "  Compressed: $DB_COMPRESSED ($COMP_SIZE)"

# ── Step 5: Serve (if file server is running) ──────────────────────
echo ""
echo "[5/5] Making available for download..."
SERVE_DIR="/var/www/officeqa"
if [ -d "$SERVE_DIR" ]; then
    cp "$DB_COMPRESSED" "$SERVE_DIR/"
    echo "  Copied to $SERVE_DIR/"
    echo "  URL: http://$(hostname -I | awk '{print $1}'):9090/officeqa_slim_v2.sqlite3.zst"
else
    echo "  No serve directory found at $SERVE_DIR"
    echo "  Manual copy: cp $DB_COMPRESSED /path/to/serve/"
fi

echo ""
echo "=== Done ==="
echo "DB: $DB_COMPRESSED ($COMP_SIZE)"
echo ""
echo "To decompress on client:"
echo "  zstd -d officeqa_slim_v2.sqlite3.zst"
