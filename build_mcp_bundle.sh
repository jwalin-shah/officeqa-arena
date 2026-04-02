#!/usr/bin/env bash
# Build MCP bundle tarball with latest server code and prompt examples

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_DIR="${SCRIPT_DIR}/mcp_bundle_build"
OUTPUT_FILE="${SCRIPT_DIR}/mcp_bundle.tar.gz"

echo "Building MCP bundle..."

# Create clean bundle directory
rm -rf "$BUNDLE_DIR"
mkdir -p "$BUNDLE_DIR"

# Copy server code
echo "  → Copying server code..."
cp -r "$SCRIPT_DIR/server" "$BUNDLE_DIR/"

# Copy prompt templates
echo "  → Copying prompts..."
mkdir -p "$BUNDLE_DIR/prompts"
cp "$SCRIPT_DIR/prompts/goose_instructions.md" "$BUNDLE_DIR/prompts/"

# Copy run script
echo "  → Copying run script..."
cp "$SCRIPT_DIR/run_mcp.sh" "$BUNDLE_DIR/"

# Create tarball
echo "  → Creating tarball..."
cd "$BUNDLE_DIR/.."
tar -czf "$OUTPUT_FILE" mcp_bundle_build/

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
