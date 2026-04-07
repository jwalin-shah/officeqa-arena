#!/bin/bash
# Setup v14 testing environment on a remote machine (Daytona or DO droplet).
# Run this LOCALLY — it SSHes in and does everything.
#
# Usage:
#   ./setup_v14_remote.sh <ssh_target>
#   ./setup_v14_remote.sh root@143.198.129.204          # DO runner
#   ./setup_v14_remote.sh root@147.182.206.223          # DO DB droplet
#   ./setup_v14_remote.sh daytona:b300439b              # Daytona sandbox
#
# After setup, SSH in and run:
#   cd /root/officeqa-arena && ./run_local_v14.sh UID0001

set -euo pipefail

TARGET="${1:?Usage: $0 <ssh_target|daytona:sandbox_id>}"
REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

# Detect Daytona vs SSH
if [[ "$TARGET" == daytona:* ]]; then
    SANDBOX_ID="${TARGET#daytona:}"
    SSH_CMD="daytona ssh $SANDBOX_ID --"
    SCP_CMD="daytona cp"
    WORK_DIR="/home/user"
    IS_DAYTONA=1
else
    SSH_CMD="ssh -o StrictHostKeyChecking=no $TARGET"
    SCP_CMD="scp -o StrictHostKeyChecking=no"
    WORK_DIR="/root"
    IS_DAYTONA=0
fi

echo "=== Setting up v14 on $TARGET ==="
echo "Work dir: $WORK_DIR"

# Step 1: Clone repos & install deps
$SSH_CMD bash << 'REMOTE_SETUP'
set -euo pipefail

cd /root 2>/dev/null || cd /home/user

# Install deps
pip3 install pandas 2>/dev/null || pip install pandas 2>/dev/null || true

# Clone officeqa-arena if not present
if [ ! -d officeqa-arena ]; then
    git clone https://github.com/YOUR_USER/officeqa-arena.git officeqa-arena || true
fi
cd officeqa-arena
git pull origin main 2>/dev/null || true

# Clone databricks/officeqa if not present (for page generation)
if [ ! -d /tmp/officeqa_repo ]; then
    echo "Cloning databricks/officeqa..."
    git clone https://github.com/databricks/officeqa.git /tmp/officeqa_repo
fi

# Generate page-level files
PAGES_OUT="/tmp/officeqa_reingest/officeqa_repo/treasury_bulletins_parsed/transformed_page_level"
if [ ! -d "$PAGES_OUT" ] || [ "$(ls "$PAGES_OUT" 2>/dev/null | wc -l)" -lt 1000 ]; then
    echo "Generating page-level files..."
    mkdir -p "$PAGES_OUT"
    cd /tmp/officeqa_repo/treasury_bulletins_parsed
    python3 transform_scripts/transform_files_page_level.py --split-files 2>&1 | tail -5
    # Move generated files to expected location
    if [ -d transformed_page_level ]; then
        cp -r transformed_page_level/* "$PAGES_OUT/" 2>/dev/null || true
    fi
    echo "Generated $(ls "$PAGES_OUT" | wc -l) page files"
else
    echo "Page files already exist: $(ls "$PAGES_OUT" | wc -l) files"
fi

# Copy CSV if not present
if [ ! -f /tmp/officeqa_full.csv ]; then
    echo "ERROR: /tmp/officeqa_full.csv not found — scp it manually"
fi

# Set up /app and /installed-agent directories
mkdir -p /app/resources /app/corpus /installed-agent/v14/server

# Verify goose is installed
which goose >/dev/null 2>&1 && echo "goose: $(goose --version 2>&1 | head -1)" || echo "WARNING: goose not installed"

echo "=== Setup complete ==="
REMOTE_SETUP

# Step 2: Copy CSV if we have it locally
if [ -f /tmp/officeqa_full.csv ]; then
    echo "Copying officeqa_full.csv..."
    if [ "$IS_DAYTONA" = "1" ]; then
        echo "For Daytona, manually copy CSV: daytona cp /tmp/officeqa_full.csv $SANDBOX_ID:/tmp/officeqa_full.csv"
    else
        $SCP_CMD /tmp/officeqa_full.csv "$TARGET:/tmp/officeqa_full.csv"
    fi
fi

echo ""
echo "=== Next steps ==="
echo "1. SSH in: $SSH_CMD"
echo "2. Verify: ls /tmp/officeqa_full.csv && ls /tmp/officeqa_reingest/officeqa_repo/treasury_bulletins_parsed/transformed_page_level/ | wc -l"
echo "3. Test:   cd $WORK_DIR/officeqa-arena && ./run_local_v14.sh UID0001 --dry-run"
echo "4. Run:    ./run_local_v14.sh UID0001"
echo "5. Batch:  ./run_local_v14.sh --batch-file v14/test_uids.txt"
