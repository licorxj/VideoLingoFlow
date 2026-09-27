#!/usr/bin/env bash
#
# LocalRouter - Production Startup (Linux/macOS)
# Windows counterpart: start-prod.bat
#
# Usage:
#   ./start-prod.sh             # start (builds the frontend if dist is missing)
#   ./start-prod.sh rebuild     # force npm run build first
#   ./stop-prod.sh              # stop
#
# Runs ONE uvicorn process that serves the built frontend (frontend/dist)
# and the API on the same port — no Vite dev server, no Node at runtime.
# For the dev frontend use start.sh instead.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========================================"
echo "  LocalRouter - Production Startup"
echo "========================================"

# --- Load root .env (ports etc.) ---
if [ -f ".env" ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi
BACKEND_PORT="${BACKEND_PORT:-12002}"
HOST_BIND="${HOST:-0.0.0.0}"

VENV_PY="$SCRIPT_DIR/backend/venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
    echo -e "${RED}ERROR: backend venv not found. Run ./install.sh first.${NC}"
    exit 1
fi

RUN_DIR="$SCRIPT_DIR/run"
PIDFILE="$RUN_DIR/prod-backend.pid"
LOGFILE="$RUN_DIR/prod-backend.log"
mkdir -p "$RUN_DIR"

# --- [1/2] Frontend build ---
if [ "${1:-}" != "rebuild" ] && [ -f "$SCRIPT_DIR/frontend/dist/index.html" ]; then
    echo "[1/2] Frontend build found (frontend/dist), skipping build. Use '$0 rebuild' to rebuild."
else
    if ! command -v npm >/dev/null 2>&1; then
        echo -e "${RED}ERROR: frontend/dist missing and npm not found. Install Node.js 18+ and run ./install.sh.${NC}"
        exit 1
    fi
    echo "[1/2] Building frontend (npm run build)..."
    (cd "$SCRIPT_DIR/frontend" && npm run build)
fi

# --- [2/2] Start server (API + built frontend on one port) ---
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo -e "${YELLOW}Production server already running (PID: $(cat "$PIDFILE")).${NC}"
    exit 0
fi
rm -f "$PIDFILE"

echo "[2/2] Starting uvicorn on port $BACKEND_PORT (API + frontend)..."
cd "$SCRIPT_DIR/backend"
nohup "$VENV_PY" -m uvicorn app.main:app --host "$HOST_BIND" --port "$BACKEND_PORT" \
    > "$LOGFILE" 2>&1 &
PID=$!
echo "$PID" > "$PIDFILE"
cd "$SCRIPT_DIR"

sleep 2
if ! kill -0 "$PID" 2>/dev/null; then
    echo -e "${RED}ERROR: server failed to start. Check $LOGFILE${NC}"
    rm -f "$PIDFILE"
    exit 1
fi
echo -e "  ${GREEN}Production server started (PID: $PID)${NC}"
echo ""
echo "  UI:       http://localhost:$BACKEND_PORT"
echo "  API docs: http://localhost:$BACKEND_PORT/docs"
echo "  Logs:     $LOGFILE"
echo "  Stop:     ./stop-prod.sh"
