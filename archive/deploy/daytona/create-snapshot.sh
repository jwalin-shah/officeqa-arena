#!/bin/bash
# Creates the Daytona snapshot with arena + Docker pre-installed.
# Run once locally. Re-run only if Dockerfile changes.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SNAPSHOT_NAME="officeqa-arena-runner"

echo "=== Building Daytona snapshot: $SNAPSHOT_NAME ==="

daytona snapshot create "$SNAPSHOT_NAME" \
  --dockerfile "$SCRIPT_DIR/Dockerfile" \
  --context "$SCRIPT_DIR" \
  --cpu 4 \
  --memory 5 \
  --disk 10

echo "=== Snapshot created: $SNAPSHOT_NAME ==="
echo "Now run: ./deploy/daytona/launch-sandboxes.sh"
