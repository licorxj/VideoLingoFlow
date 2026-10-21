#!/usr/bin/env bash
#
# LocalRouter - First-time Setup (Linux/macOS)
# Windows counterpart: setup.bat
#
# Run right after cloning the repository. Pulls the latest code and
# performs the full environment installation (venv, backend deps,
# database init, frontend npm install).
#
# Usage:
#   git clone <repo-url>
#   cd QM-LocalRouter
#   ./setup.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
NC='\033[0m'

echo "========================================"
echo "  LocalRouter - First-time Setup"
echo "========================================"

if ! command -v git >/dev/null 2>&1; then
    echo -e "${RED}ERROR: git not found. Please install git first.${NC}"
    exit 1
fi
if [ ! -d ".git" ]; then
    echo -e "${RED}ERROR: run this script inside the cloned repository directory.${NC}"
    exit 1
fi

echo "[1/2] Pulling latest code (git pull --ff-only)..."
git pull --ff-only

echo ""
echo "[2/2] Installing environment and dependencies..."
exec "$SCRIPT_DIR/install.sh"
