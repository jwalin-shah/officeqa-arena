#!/usr/bin/env bash
set -euo pipefail

# Build MCP bundle, upload to DDB, and verify it's served.
#
# Usage:
#   ./scripts/deploy.sh                  # build + upload + verify
#   ./scripts/deploy.sh --build-only     # just build, don't upload
#   ./scripts/deploy.sh --verify-only    # just check remote bundle is fresh
#
# Called automatically by do_runner_pool.sh before dispatching tasks.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

DDB_HOST="${DDB_HOST:-147.182.206.223}"
DDB_PATH="/var/www/officeqa"
BUNDLE_URL="http://${DDB_HOST}:9090/mcp_bundle.tar.gz"

BUILD_ONLY=false
VERIFY_ONLY=false
QUIET=false

for arg in "$@"; do
  case "$arg" in
    --build-only)  BUILD_ONLY=true ;;
    --verify-only) VERIFY_ONLY=true ;;
    --quiet|-q)    QUIET=true ;;
  esac
done

log() { $QUIET || echo "$@"; }

# ── Verify only ─────────────────────────────────────────────────────
if [ "$VERIFY_ONLY" = true ]; then
  log "Checking remote bundle..."
  remote_size=$(curl -sI "$BUNDLE_URL" 2>/dev/null | grep -i content-length | awk '{print $2}' | tr -d '\r')
  if [ -z "$remote_size" ] || [ "$remote_size" = "0" ]; then
    echo "FAIL: Remote bundle not accessible at $BUNDLE_URL"
    exit 1
  fi
  log "  Remote bundle: ${remote_size} bytes"
  log "  OK"
  exit 0
fi

# ── Record what we're deploying ──────────────────────────────────────
GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
GIT_DIRTY=$(git diff --quiet 2>/dev/null && echo "false" || echo "true")
PROMPT_HASH=$(md5 -q prompts/system.j2 2>/dev/null || md5sum prompts/system.j2 2>/dev/null | cut -d' ' -f1 || echo "unknown")
GOOSE_HASH=$(md5 -q prompts/goose_instructions.md 2>/dev/null || md5sum prompts/goose_instructions.md 2>/dev/null | cut -d' ' -f1 || echo "unknown")

log "=== Deploy MCP Bundle ==="
log "  git: ${GIT_SHA} (dirty: ${GIT_DIRTY})"
log "  system.j2:           ${PROMPT_HASH}"
log "  goose_instructions:  ${GOOSE_HASH}"

# ── Build ────────────────────────────────────────────────────────────
log ""
log "Building bundle..."
UPLOAD=0 bash build_mcp_bundle.sh 2>&1 | while IFS= read -r line; do log "  $line"; done

LOCAL_BUNDLE="mcp_bundle.tar.gz"
LOCAL_SIZE=$(wc -c < "$LOCAL_BUNDLE" | tr -d ' ')
log "  Local bundle: ${LOCAL_SIZE} bytes"

if [ "$BUILD_ONLY" = true ]; then
  log "Done (build only)."
  exit 0
fi

# ── Upload ───────────────────────────────────────────────────────────
log ""
log "Uploading to ${DDB_HOST}..."
scp -o ConnectTimeout=10 "$LOCAL_BUNDLE" "root@${DDB_HOST}:${DDB_PATH}/mcp_bundle.tar.gz"
log "  Uploaded."

# ── Verify ───────────────────────────────────────────────────────────
log ""
log "Verifying remote bundle..."
sleep 1
remote_size=$(curl -sI "$BUNDLE_URL" 2>/dev/null | grep -i content-length | awk '{print $2}' | tr -d '\r')
if [ "$remote_size" = "$LOCAL_SIZE" ]; then
  log "  Remote matches local (${remote_size} bytes)"
else
  echo "WARNING: Size mismatch — local=${LOCAL_SIZE}, remote=${remote_size}"
fi

log ""
log "=== Deploy Complete ==="
log "  Bundle: $BUNDLE_URL"
log "  git: ${GIT_SHA}"
log "  Next container startup will pick up these changes."
