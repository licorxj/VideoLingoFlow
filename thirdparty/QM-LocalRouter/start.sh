#!/usr/bin/env bash
#
# LocalRouter - One-click Startup (Linux/macOS)
# Windows counterpart: start.bat
#
# Usage:
#   ./start.sh            # or: bash start.sh
#
# First run automatically creates the venv, installs backend
# dependencies and initializes the database (via scripts/init_db.py).
# All services run in the background; logs and pid files live in run/.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========================================"
echo "  LocalRouter - Starting Services"
echo "========================================"

# --- Load root .env (ports etc.), matching service defaults if absent ---
if [ -f ".env" ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

# --- Check Python ---
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        PYTHON="$cmd"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    echo -e "${RED}ERROR: Python 3 not found. Please install Python 3.10+.${NC}"
    exit 1
fi

# --- Check Node.js ---
if ! command -v npm >/dev/null 2>&1; then
    echo -e "${RED}ERROR: npm not found. Please install Node.js 18+.${NC}"
    exit 1
fi

# --- First run: create venv, install deps, init database ---
VENV_PY="$SCRIPT_DIR/backend/venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
    echo "[setup] Python environment not found, running first-time setup (venv + deps + database)..."
    "$PYTHON" scripts/init_db.py
else
    echo "[setup] Python environment ready, skipping setup."
fi

# --- Start all services in background via the shared manager ---
"$SCRIPT_DIR/scripts/manage.sh" start
