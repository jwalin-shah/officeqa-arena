#!/usr/bin/env bash
# Build MCP bundle tarball with latest server code and prompt examples
# Only includes necessary files - excludes __pycache__, .pyc, etc.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_DIR="${SCRIPT_DIR}/mcp_bundle_build"
OUTPUT_FILE="${SCRIPT_DIR}/mcp_bundle.tar.gz"

echo "Building MCP bundle..."

# Create clean bundle directory
rm -rf "$BUNDLE_DIR"
mkdir -p "$BUNDLE_DIR"

# Copy server code (exclude __pycache__, .pyc, .pytest_cache, etc)
echo "  → Copying server code..."
mkdir -p "$BUNDLE_DIR/server"
find "$SCRIPT_DIR/server" -type f -name "*.py" | while read f; do
  # Only copy .py files, exclude test files
  if [[ ! "$f" =~ test ]]; then
    cp "$f" "$BUNDLE_DIR/server/"
  fi
done

# Copy prompt templates (only the markdown files we actually use)
echo "  → Copying prompts..."
mkdir -p "$BUNDLE_DIR/prompts"
cp "$SCRIPT_DIR/prompts/goose_instructions.md" "$BUNDLE_DIR/prompts/" 2>/dev/null || true
cp "$SCRIPT_DIR/prompts/system.j2" "$BUNDLE_DIR/prompts/" 2>/dev/null || true

# Copy run script
echo "  → Copying run script..."
cp "$SCRIPT_DIR/run_mcp.sh" "$BUNDLE_DIR/"
chmod +x "$BUNDLE_DIR/run_mcp.sh"

# Create tarball (exclude unnecessary files)
echo "  → Creating tarball..."
cd "$BUNDLE_DIR/.."
tar --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='.pytest_cache' \
    --exclude='*.egg-info' \
    --exclude='.git' \
    --exclude='.gitignore' \
    -czf "$OUTPUT_FILE" mcp_bundle_build/

# Show size
SIZE=$(du -h "$OUTPUT_FILE" | cut -f1)
echo "✓ Bundle created: $OUTPUT_FILE ($SIZE)"

# Upload to remote server (optional - requires SSH access)
if [ "${UPLOAD:-0}" = "1" ]; then
  REMOTE_HOST="${REMOTE_HOST:-147.182.206.223}"
  REMOTE_PATH="${REMOTE_PATH:-/var/www/html}"
  echo "  → Uploading to $REMOTE_HOST:$REMOTE_PATH..."
  scp "$OUTPUT_FILE" "root@$REMOTE_HOST:$REMOTE_PATH/" || echo "Upload failed - copy manually if needed"
fi

# Cleanup
rm -rf "$BUNDLE_DIR"

echo "Ready to use. Next OOM-fix run will download this bundle."
