#!/bin/bash
set -euo pipefail
# Arena install script for nomcp/goose harness.
# The goose harness already installs: Node.js, uv, goose CLI, goose config.
# We only need: system deps for DB handling + pre-decompress the DB.

# 1. System deps (zstd for .zst fallback, sqlite3 for debug)
apt-get update -qq
apt-get install -y -qq --no-install-recommends zstd sqlite3 2>/dev/null || true

# 2. Python deps solve.py needs (openai for LLM calls)
pip3 install --break-system-packages --quiet openai 2>/dev/null || \
  python3 -m pip install --break-system-packages --quiet openai 2>/dev/null || true

# 3. Pre-decompress DB so solve.py skips decompression at runtime.
#    solve.py checks /tmp/officeqa.db first (DB_PATH), so put it there.
DB_TARGET="/tmp/officeqa.db"
if [ ! -f "$DB_TARGET" ] || [ "$(stat -c%s "$DB_TARGET" 2>/dev/null || stat -f%z "$DB_TARGET" 2>/dev/null)" -lt 1000000 ]; then
    # Look for gzip version (bundled in skills/)
    for GZ in /installed-agent/skills/officeqa_optimal.sqlite3.gz \
              /installed-agent/officeqa_optimal.sqlite3.gz \
              ~/.config/goose/skills/officeqa_optimal.sqlite3.gz; do
        if [ -f "$GZ" ]; then
            echo "Decompressing DB from $GZ ..."
            python3 -c "
import gzip, shutil
with gzip.open('$GZ','rb') as f_in, open('$DB_TARGET','wb') as f_out:
    shutil.copyfileobj(f_in, f_out)
" && echo "DB ready: $(du -h "$DB_TARGET" | cut -f1)" && break
        fi
    done
    # Fallback: try zstd version
    if [ ! -f "$DB_TARGET" ] || [ "$(stat -c%s "$DB_TARGET" 2>/dev/null || stat -f%z "$DB_TARGET" 2>/dev/null)" -lt 1000000 ]; then
        for ZST in /installed-agent/skills/officeqa_optimal.sqlite3.zst \
                   /installed-agent/officeqa_optimal.sqlite3.zst; do
            if [ -f "$ZST" ]; then
                echo "Decompressing DB from $ZST ..."
                zstd -d "$ZST" -o "$DB_TARGET" --force && echo "DB ready: $(du -h "$DB_TARGET" | cut -f1)" && break
            fi
        done
    fi
fi

echo "Install complete."