#!/usr/bin/env bash
#
# LocalRouter - One-time Installation (Linux/macOS)
# Windows counterpart: install.bat
#
# Usage:
#   ./install.sh          # or: bash install.sh
#
# What it does:
#   1. Check prerequisites (Python 3.10+, Node.js 18+, npm)
#   2. Create backend venv, install Python dependencies,
#      create backend/.env + data dirs, initialize the database
#      (via scripts/init_db.py)
#   3. Install frontend dependencies (npm install)
#   4. Create root .env from .env.example (if missing)
#
# Re-running is safe: existing venv/node_modules/.env are kept.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========================================"
echo "  LocalRouter - Installation"
echo "========================================"

fail() {
    echo ""
    echo -e "${RED}ERROR: $1${NC}"
    if [ -n "${2:-}" ]; then
        echo -e "${YELLOW}$2${NC}"
    fi
    exit 1
}

# --- [1/5] Python >= 3.10 ---
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        PYTHON="$cmd"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    fail "Python 3 not found." \
        "Install Python 3.10+ first, e.g.: apt install python3 python3-venv python3-pip  |  brew install python"
fi

PY_MAJOR=$("$PYTHON" -c 'import sys; print(sys.version_info[0])')
PY_MINOR=$("$PYTHON" -c 'import sys; print(sys.version_info[1])')
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    fail "Python 3.10+ required, found $("$PYTHON" --version 2>&1)." \
        "Upgrade Python, e.g.: brew install python  |  apt install python3.10"
fi
echo "[1/5] Python OK: $("$PYTHON" --version 2>&1)  ($PYTHON)"

# --- [2/5] Node.js >= 18 and npm ---
if ! command -v node >/dev/null 2>&1; then
    fail "Node.js not found." "Install Node.js 18+ from https://nodejs.org/ (or via nvm/brew)."
fi
if ! command -v npm >/dev/null 2>&1; then
    fail "npm not found." "npm ships with Node.js - please reinstall Node.js 18+."
fi
NODE_MAJOR=$(node -p 'process.versions.node.split(".")[0]')
if [ "$NODE_MAJOR" -lt 18 ]; then
    fail "Node.js 18+ required, found v$(node -p 'process.versions.node')." \
        "Upgrade Node.js, e.g.: nvm install 18 && nvm use 18"
fi
echo "[2/5] Node.js OK: v$(node -p 'process.versions.node')  (npm: $(npm --version))"

# --- [3/5] Backend: venv + dependencies + database ---
echo "[3/5] Setting up backend (venv, dependencies, database)..."
"$PYTHON" scripts/init_db.py || fail "Backend setup failed." \
    "On Debian/Ubuntu make sure python3-venv and python3-pip are installed."

# --- [4/5] Frontend: npm install ---
if [ -d "$SCRIPT_DIR/frontend/node_modules" ]; then
    echo "[4/5] Frontend dependencies already installed, skipping npm install."
else
    echo "[4/5] Installing frontend dependencies (npm install)..."
    (cd "$SCRIPT_DIR/frontend" && npm install) || fail "npm install failed."
fi

# --- [5/5] Root .env ---
if [ -f "$SCRIPT_DIR/.env" ]; then
    echo "[5/5] Root .env already exists, skipping."
else
    cp .env.example .env
    echo "[5/5] Created .env from .env.example."
fi

# --- Executable bits may be lost when copying the repo around ---
chmod +x "$SCRIPT_DIR/start.sh" "$SCRIPT_DIR/stop.sh" "$SCRIPT_DIR/scripts/"*.sh 2>/dev/null || true

echo ""
echo -e "${GREEN}========================================"
echo "  Installation complete!"
echo "========================================${NC}"
echo ""
echo "Next steps:"
echo "  ./start.sh      Start all services (manager, backend, frontend)"
echo "  ./stop.sh       Stop all services"
echo ""
echo "  Frontend: http://localhost:${FRONTEND_PORT:-12001}"
echo "  Backend:  http://localhost:${BACKEND_PORT:-12002}"
echo "  API docs: http://localhost:${BACKEND_PORT:-12002}/docs"
