#!/bin/bash
set -euo pipefail

# Arena install script — runs inside the competition container before agent starts.
# Container has: Ubuntu 24.04, Python 3.12, /app/corpus/ with .txt files
# Our code is at: /installed-agent/
# OpenHands SDK is installed separately by the harness template.

# 1. Install system deps (zstd for DB decompression, sqlite3 for fallback queries)
apt-get update -qq
apt-get install -y -qq --no-install-recommends zstd python3-pip sqlite3 2>/dev/null || true

# 2. Install Python deps
pip3 install --break-system-packages --quiet msgpack zstandard numpy scipy 2>/dev/null || \
  python3 -m pip install --break-system-packages --quiet msgpack zstandard numpy scipy 2>/dev/null || true

# 3. Decompress bundled DB (guaranteed to be in the tarball)
OPTIMAL_DB="/installed-agent/officeqa_optimal.sqlite3"
OPTIMAL_ZST="/installed-agent/officeqa_optimal.sqlite3.zst"
if [ ! -f "$OPTIMAL_DB" ] && [ -f "$OPTIMAL_ZST" ]; then
  echo "Decompressing bundled optimal DB..."
  zstd -d "$OPTIMAL_ZST" -o "$OPTIMAL_DB" -f
  echo "Bundled DB ready: $(du -h "$OPTIMAL_DB" | cut -f1)"
fi

# 4. Try downloading enriched DB (may have more data than bundled)
DB_PATH="/app/corpus/officeqa_enriched.sqlite3"
if [ ! -f "$DB_PATH" ]; then
  echo "Downloading enriched DB..."
  if curl -fsSL --max-time 180 http://147.182.206.223:9090/officeqa_v3.sqlite3.zst | zstd -d -o "$DB_PATH" -f 2>/dev/null; then
    echo "DB downloaded: $(du -h "$DB_PATH" | cut -f1)"
  else
    echo "Download failed — using bundled DB"
    if [ -f "$OPTIMAL_DB" ]; then
      ln -sf "$OPTIMAL_DB" "$DB_PATH" 2>/dev/null || true
    fi
  fi
fi

# 5. Make scripts executable
chmod +x /installed-agent/run_mcp.sh 2>/dev/null || true
chmod +x /installed-agent/fallback_query.py 2>/dev/null || true

echo "Install complete."
