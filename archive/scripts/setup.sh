#!/bin/bash
# One-time project setup: creates venv, installs deps, checks .env
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== OfficeQA Arena Setup ==="

# ── 1. Create venv ──────────────────────────────────────────────
if [ ! -d ".venv" ]; then
  echo "[1/3] Creating Python venv..."
  python3 -m venv .venv
else
  echo "[1/3] venv already exists"
fi

source .venv/bin/activate
echo "  Python: $(python3 --version) at $(which python3)"

# ── 2. Install deps ─────────────────────────────────────────────
echo "[2/3] Installing dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
pip install daytona python-dotenv -q
echo "  Installed: openai, pyyaml, jinja2, mcp, daytona, python-dotenv"

# ── 3. Check .env ───────────────────────────────────────────────
if [ ! -f ".env" ]; then
  echo "[3/3] Creating .env from template..."
  cp .env.example .env
  echo ""
  echo "  *** IMPORTANT: Edit .env and fill in your API keys ***"
  echo "  Required: OPENROUTER_API_KEY, DAYTONA_API_KEY"
  echo ""
  echo "  vi .env"
else
  echo "[3/3] .env exists"
  # Check for required keys
  missing=""
  grep -q "^OPENROUTER_API_KEY=sk-" .env 2>/dev/null || missing="$missing OPENROUTER_API_KEY"
  grep -q "^DAYTONA_API_KEY=." .env 2>/dev/null || missing="$missing DAYTONA_API_KEY"
  if [ -n "$missing" ]; then
    echo "  WARNING: Missing or empty keys:$missing"
  else
    echo "  All required keys present"
  fi
fi

echo ""
echo "=== Setup complete ==="
echo "Activate with:  source .venv/bin/activate"
echo "Then run:        python3 scripts/daytona_sandbox.py snapshot"
