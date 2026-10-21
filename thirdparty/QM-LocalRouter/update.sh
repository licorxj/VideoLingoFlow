#!/usr/bin/env bash
#
# LocalRouter - Update Code (Linux/macOS)
# Windows counterpart: update.bat
#
# Pulls the latest code, then incrementally applies what changed:
#   - backend/requirements.txt changed -> pip install
#   - frontend package files changed   -> npm install
#   - frontend source changed          -> npm run build
# The database schema is upgraded automatically when the backend starts.
#
# Usage:
#   ./update.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========================================"
echo "  LocalRouter - Update Code"
echo "========================================"

if ! command -v git >/dev/null 2>&1; then
    echo -e "${RED}ERROR: git not found.${NC}"
    exit 1
fi
if [ ! -d ".git" ]; then
    echo -e "${RED}ERROR: run this script inside the repository directory.${NC}"
    exit 1
fi

# true if any file under the given path changed between the two commits
changed() {
    [ -n "$(git diff --name-only "$OLD_HEAD" "$NEW_HEAD" -- "$1")" ]
}

OLD_HEAD=$(git rev-parse HEAD)

echo "[1/3] Pulling latest code (git pull --ff-only)..."
if ! git pull --ff-only; then
    echo -e "${RED}ERROR: git pull failed.${NC}"
    echo -e "${YELLOW}Commit or stash your local changes first (git stash), then re-run.${NC}"
    exit 1
fi

NEW_HEAD=$(git rev-parse HEAD)
if [ "$OLD_HEAD" = "$NEW_HEAD" ]; then
    echo -e "${GREEN}Already up to date, nothing to do.${NC}"
    exit 0
fi
echo "Code updated: $(git rev-parse --short "$OLD_HEAD") -> $(git rev-parse --short "$NEW_HEAD")"

# --- [2/3] Backend dependencies ---
if [ ! -x "$SCRIPT_DIR/backend/venv/bin/python" ]; then
    echo -e "${YELLOW}Python venv not found - falling back to full setup...${NC}"
    exec "$SCRIPT_DIR/setup.sh"
fi
if changed backend/requirements.txt; then
    echo "[2/3] requirements.txt changed - installing backend dependencies..."
    "$SCRIPT_DIR/backend/venv/bin/python" -m pip install -r "$SCRIPT_DIR/backend/requirements.txt"
else
    echo "[2/3] Backend dependencies unchanged."
fi

# --- [3/3] Frontend ---
NEED_NPM=0
[ -d "$SCRIPT_DIR/frontend/node_modules" ] || NEED_NPM=1
if changed frontend/package.json || changed frontend/package-lock.json; then NEED_NPM=1; fi
if [ "$NEED_NPM" = "1" ]; then
    echo "[3/3] Frontend dependencies changed - npm install..."
    (cd "$SCRIPT_DIR/frontend" && npm install)
else
    echo "[3/3] Frontend dependencies unchanged."
fi

NEED_BUILD=0
[ -f "$SCRIPT_DIR/frontend/dist/index.html" ] || NEED_BUILD=1
[ "$NEED_NPM" = "1" ] && NEED_BUILD=1
if changed frontend/src || changed frontend/index.html || changed frontend/vite.config.ts \
    || changed frontend/public || changed frontend/tailwind.config.js || changed frontend/postcss.config.js; then
    NEED_BUILD=1
fi
if [ "$NEED_BUILD" = "1" ]; then
    echo "Rebuilding frontend (npm run build)..."
    (cd "$SCRIPT_DIR/frontend" && npm run build)
else
    echo "Frontend build unchanged."
fi

echo ""
echo -e "${GREEN}Update complete!${NC} Database schema is upgraded automatically on next start."
echo "Restart running services to apply the update:"
echo "  Production: ./stop-prod.sh && ./start-prod.sh"
echo "  Dev:        ./stop.sh && ./start.sh"
