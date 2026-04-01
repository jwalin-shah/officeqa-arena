#!/bin/bash
set -euo pipefail

apt-get update
apt-get install -y curl zstd python3-pip

# Install Node + OpenCode
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh | bash
export NVM_DIR="$HOME/.nvm"
\. "$NVM_DIR/nvm.sh" || true
command -v nvm &>/dev/null || { echo "Error: NVM failed to load" >&2; exit 1; }
nvm install 22
npm -v


npm i -g opencode-ai@latest


opencode --version

# Install MCP server code
cd /installed-agent
if [ ! -f run_mcp.sh ]; then
  curl -fsSL http://64.23.196.53:9090/officeqa-mcp-server.tar.gz | tar xz -C /installed-agent/
  chmod +x /installed-agent/run_mcp.sh
fi

# Install Python deps for MCP server
pip3 install --quiet msgpack zstandard 2>/dev/null || true

# Pre-download the enriched DB
if [ ! -f /app/corpus/officeqa_corpus.sqlite3 ]; then
  curl -fsSL http://64.23.196.53:9090/officeqa_slim_v2.sqlite3.zst | zstd -d -o /app/corpus/officeqa_corpus.sqlite3 -f
fi