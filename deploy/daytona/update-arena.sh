#!/bin/bash
# Update arena CLI in the snapshot.
# Usage: ./update-arena.sh ~/Downloads/arena-cli-latest.tar.gz
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NEW_TAR="${1:-$HOME/Downloads/arena-cli-latest.tar.gz}"

if [ ! -f "$NEW_TAR" ]; then
  echo "Error: tarball not found at $NEW_TAR"
  echo "Download the latest arena-cli-latest.tar.gz and pass its path as an argument."
  exit 1
fi

echo "=== Updating arena tarball ==="
cp "$NEW_TAR" "$SCRIPT_DIR/arena-cli-latest.tar.gz"

# Show version being installed
VERSION=$(tar -xzf "$SCRIPT_DIR/arena-cli-latest.tar.gz" -O version.json 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin)['version'])" 2>/dev/null || echo "unknown")
echo "Arena version: $VERSION"

echo "=== Deleting old snapshot ==="
daytona snapshot delete "officeqa-arena-runner" 2>/dev/null || true
echo "Waiting for deletion to propagate..."
sleep 10

echo "=== Rebuilding snapshot ==="
"$SCRIPT_DIR/create-snapshot.sh"
