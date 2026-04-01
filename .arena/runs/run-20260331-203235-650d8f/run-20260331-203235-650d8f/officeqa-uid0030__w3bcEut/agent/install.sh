#!/bin/bash
set -euo pipefail

apt-get update
apt-get install -y curl zstd git python3-pip

# Install Node + OpenCode
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh | bash
export NVM_DIR="$HOME/.nvm"
\. "$NVM_DIR/nvm.sh" || true
command -v nvm &>/dev/null || { echo "Error: NVM failed to load" >&2; exit 1; }
nvm install 22
npm -v


npm i -g opencode-ai@latest


opencode --version

# Install our MCP server + DB
cd /installed-agent
if [ ! -f run_mcp.sh ]; then
  git clone --depth 1 https://github.com/jwalin-shah/officeqa-arena.git /tmp/agent-code
  cp -r /tmp/agent-code/server /installed-agent/server
  cp -r /tmp/agent-code/run_mcp.sh /installed-agent/run_mcp.sh
  cp -r /tmp/agent-code/prompts /installed-agent/prompts
  cp -r /tmp/agent-code/skills /installed-agent/skills
  chmod +x /installed-agent/run_mcp.sh
  rm -rf /tmp/agent-code
fi

# Install Python deps for MCP server
pip3 install --quiet msgpack zstandard 2>/dev/null || true

# Pre-download the enriched DB
if [ ! -f /app/corpus/officeqa_corpus.sqlite3 ]; then
  curl -fsSL http://64.23.196.53:9090/officeqa_slim_v2.sqlite3.zst | zstd -d -o /app/corpus/officeqa_corpus.sqlite3 -f
fi