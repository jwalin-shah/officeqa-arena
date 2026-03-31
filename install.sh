#!/bin/bash
set -euo pipefail

# Arena install script — runs inside the competition container before agent starts.
# Container has: Ubuntu 24.04, Python 3.12, /app/corpus/ with .txt files
# Our code is at: /installed-agent/

# 1. Install system deps
apt-get update -qq
apt-get install -y -qq --no-install-recommends curl zstd python3-pip 2>/dev/null || true

# 2. Install Python deps for MCP server
pip3 install --break-system-packages --quiet msgpack zstandard 2>/dev/null || \
  python3 -m pip install --break-system-packages --quiet msgpack zstandard 2>/dev/null || true

# 3. Install OpenCode CLI
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh | bash
export NVM_DIR="$HOME/.nvm"
\. "$NVM_DIR/nvm.sh" || true
nvm install 22
npm i -g opencode-ai@latest
opencode --version

# 4. Download enriched SQLite DB (with master_ledger, CY/FY totals)
DB_PATH="/app/corpus/officeqa_corpus.sqlite3"
if [ ! -f "$DB_PATH" ]; then
  echo "Downloading enriched DB..."
  curl -fsSL http://64.23.196.53:9090/officeqa_slim_v2.sqlite3.zst | zstd -d -o "$DB_PATH" -f
  echo "DB downloaded: $(ls -lh $DB_PATH | awk '{print $5}')"
fi

# 5. Make MCP server executable
chmod +x /installed-agent/run_mcp.sh

echo "Install complete."
