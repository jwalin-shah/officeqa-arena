#!/bin/bash
# Patch the Harbor OpenCode install template so Arena containers get:
#   - Our zero-dependency MCP server (server/ package)
#   - The lean SQLite DB (downloaded + decompressed at install time)
#   - A run_mcp.sh launcher script
#
# This replaces the old build_arena_install.sh which bundled a heavy venv
# and the full MCP SDK. Our new server has zero pip dependencies.
#
# Usage:
#   bash scripts/build_install.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

ARENA_PYTHON="${ARENA_PYTHON:-$HOME/.arena/venv/bin/python3}"
if [ ! -x "$ARENA_PYTHON" ]; then
  echo "Error: Arena venv python not found at $ARENA_PYTHON" >&2
  echo "Set ARENA_PYTHON to the correct path." >&2
  exit 1
fi

# --- Locate the Harbor install template ---
TEMPLATE_PATH=$("$ARENA_PYTHON" - <<'PY'
import importlib
from pathlib import Path
mod = importlib.import_module("harbor.agents.installed.opencode")
print(Path(mod.__file__).parent / "install-opencode.sh.j2")
PY
)
echo "Template: $TEMPLATE_PATH"

# --- Build the tarball of our server/ package ---
# We tar up the files under a server/ prefix so they can be imported as
# `python3 -m server.mcp_stdio` from the parent directory.
MCP_BUNDLE=$(
  tar czf - \
    --exclude='__pycache__' --exclude='*.pyc' \
    -C "$REPO_ROOT" \
    server/__init__.py \
    server/mcp_stdio.py \
    server/tools.py \
    server/db.py \
    server/safe_eval.py \
    data/reference/cpi_monthly.csv \
    data/reference/cpi_series.csv \
    data/reference/exchange_rates.csv \
    data/reference/agency_alias.json \
    data/reference/national_gdp.csv \
  | base64
)

# --- The wrapper script written into the container ---
read -r -d '' MCP_WRAPPER <<'WRAPPER_EOF' || true
#!/bin/bash
export OFFICEQA_SQLITE_DB="/app/corpus/officeqa_corpus.sqlite3"
cd /opt/officeqa
exec python3 -m server.mcp_stdio
WRAPPER_EOF

# --- Assemble the prelude block ---
# This block is prepended to the install template. It runs inside the
# container BEFORE the agent starts.
read -r -d '' PRELUDE <<'EOF' || true
# ==== OfficeQA MCP bundle install ====
apt-get update -qq
apt-get install -y -qq python3 zstd >/dev/null 2>&1

mkdir -p /opt/officeqa
cd /opt/officeqa

# Extract our zero-dependency MCP server code
base64 -d << 'OFFICEQA_BUNDLE_EOF' | tar xzf -
EOF

read -r -d '' MIDDLE <<'EOF' || true
OFFICEQA_BUNDLE_EOF

# Download and stream-decompress the lean SQLite database (no temp file)
echo "Downloading + decompressing lean DB (streaming)..."
mkdir -p /app/corpus
python3 -c "
import subprocess, urllib.request
resp = urllib.request.urlopen('http://209.38.74.239:9090/officeqa_lean_v2.sqlite3.zst')
proc = subprocess.Popen(['zstd', '-d', '-o', '/app/corpus/officeqa_corpus.sqlite3', '-f'], stdin=subprocess.PIPE)
while True:
    chunk = resp.read(1048576)
    if not chunk:
        break
    proc.stdin.write(chunk)
proc.stdin.close()
proc.wait()
print('exit code:', proc.returncode)
"
echo "DB ready at /app/corpus/officeqa_corpus.sqlite3"

# Write the MCP launcher script
cat > /opt/officeqa/run_mcp.sh << 'OFFICEQA_WRAPPER_EOF'
EOF

read -r -d '' POST_WRAPPER <<'EOF' || true
OFFICEQA_WRAPPER_EOF
chmod +x /opt/officeqa/run_mcp.sh

# ==== End OfficeQA MCP bundle install ====
EOF

# --- Patch the template ---
tmp="$(mktemp)"

if grep -q "OfficeQA MCP bundle install" "$TEMPLATE_PATH"; then
  echo "Updating existing patch in: $TEMPLATE_PATH"
  # Remove existing block
  sed '/# ==== OfficeQA MCP bundle install ====/,/# ==== End OfficeQA MCP bundle install ====/d' "$TEMPLATE_PATH" > "$tmp"
  final_tmp="$(mktemp)"
  {
    printf '%s\n' "$PRELUDE"
    printf '%s\n' "$MCP_BUNDLE"
    printf '%s\n' "$MIDDLE"
    printf '%s\n' "$MCP_WRAPPER"
    printf '%s\n' "$POST_WRAPPER"
    cat "$tmp"
  } > "$final_tmp"
  mv "$final_tmp" "$TEMPLATE_PATH"
  rm "$tmp"
else
  echo "Patching: $TEMPLATE_PATH"
  {
    printf '%s\n' "$PRELUDE"
    printf '%s\n' "$MCP_BUNDLE"
    printf '%s\n' "$MIDDLE"
    printf '%s\n' "$MCP_WRAPPER"
    printf '%s\n' "$POST_WRAPPER"
    cat "$TEMPLATE_PATH"
  } > "$tmp"
  mv "$tmp" "$TEMPLATE_PATH"
fi

echo
echo "Done. Harbor install template patched."
echo "Container MCP launcher: /opt/officeqa/run_mcp.sh"
echo "DB will be downloaded at container startup (~2s download + ~13s decompress)."
