#!/bin/bash
# Run once when sandbox starts.
set -e

export ARENA_NO_AUTO_UPDATE=1
echo 'export ARENA_NO_AUTO_UPDATE=1' >> ~/.bashrc

echo "=== Installing arena CLI ==="
mkdir -p /tmp/arena-install
tar -xzf /tmp/arena-cli-latest.tar.gz -C /tmp/arena-install
ARENA_INSTALL_DIR="$HOME/.arena" bash /tmp/arena-install/install.sh
export PATH="$HOME/.arena/bin:$PATH"
echo 'export PATH="$HOME/.arena/bin:$PATH"' >> ~/.bashrc

echo "=== Starting Docker daemon ==="
dockerd &>/tmp/dockerd.log &
sleep 5

echo "=== Pulling officeqa corpus image ==="
docker pull ghcr.io/sentient-agi/harbor/officeqa-corpus:latest

echo "=== Bootstrap complete ==="
arena doctor
