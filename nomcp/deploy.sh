#!/usr/bin/env bash
# Deploy nomcp config as the active arena.yaml for arena submit
#
# This copies:
#   nomcp/arena.yaml -> arena.yaml (root)
#   nomcp/prompts/system.j2 -> prompts/system.j2
#   nomcp/skills/* -> skills/ (root, for arena submission)
#   nomcp/solve.py, search.py, build_index.py -> root (bundled with agent)
#
# After running this, `arena submit` will use the nomcp approach.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "Deploying nomcp config..."

# Backup current arena.yaml
if [ -f "$PROJECT_DIR/arena.yaml" ]; then
    cp "$PROJECT_DIR/arena.yaml" "$PROJECT_DIR/arena.yaml.bak"
    echo "  Backed up arena.yaml -> arena.yaml.bak"
fi

# Copy arena.yaml
cp "$SCRIPT_DIR/arena.yaml" "$PROJECT_DIR/arena.yaml"
echo "  Copied nomcp/arena.yaml -> arena.yaml"

# Copy prompt
mkdir -p "$PROJECT_DIR/prompts"
cp "$SCRIPT_DIR/prompts/system.j2" "$PROJECT_DIR/prompts/nomcp_system.j2"
echo "  Copied nomcp prompt to prompts/nomcp_system.j2"

# Update arena.yaml to point to the right prompt path
sed -i 's|prompt_template_path: "prompts/system.j2"|prompt_template_path: "prompts/nomcp_system.j2"|' "$PROJECT_DIR/arena.yaml"

# Copy skills
mkdir -p "$PROJECT_DIR/skills"
cp "$SCRIPT_DIR/skills/"*.md "$PROJECT_DIR/skills/"
echo "  Copied skills/ files"

# Copy Python tools
for f in solve.py search.py build_index.py; do
    cp "$SCRIPT_DIR/$f" "$PROJECT_DIR/$f"
    echo "  Copied $f"
done

echo ""
echo "Done! Run 'arena submit' from $PROJECT_DIR to submit the nomcp agent."
echo ""
echo "To revert: cp arena.yaml.bak arena.yaml"
