#!/usr/bin/env bash
#
# LocalRouter - Service Management Script (Linux/macOS)
#
# Usage:
#   ./manage.sh start          # Start all services
#   ./manage.sh stop           # Stop all services
#   ./manage.sh restart        # Restart all services
#   ./manage.sh status         # Show service status
#   ./manage.sh backend-start  # Start only backend
#   ./manage.sh backend-stop   # Stop only backend
#   ./manage.sh backend-restart# Restart only backend
#   ./manage.sh frontend-start # Start only frontend
#   ./manage.sh frontend-stop  # Stop only frontend
#   ./manage.sh logs           # Tail backend logs
#

set -euo pipefail

# --- Configuration ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_DIR="$PROJECT_ROOT/run"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
BACKEND_PORT=${BACKEND_PORT:-12002}
FRONTEND_PORT=${FRONTEND_PORT:-12001}
MANAGER_PORT=${MANAGER_PORT:-12003}

BACKEND_PIDFILE="$RUN_DIR/backend.pid"
FRONTEND_PIDFILE="$RUN_DIR/frontend.pid"
MANAGER_PIDFILE="$RUN_DIR/manager.pid"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

mkdir -p "$RUN_DIR"

# --- Utility Functions ---
detect_python() {
    for cmd in python3 python; do
        if command -v "$cmd" &>/dev/null; then
            echo "$cmd"
            return 0
        fi
    done
    echo ""
    return 1
}

detect_venv_python() {
    local python=""
    python=$(detect_python 2>/dev/null || true)
    if [ -f "$BACKEND_DIR/venv/bin/python" ]; then
        echo "$BACKEND_DIR/venv/bin/python"
    elif [ -f "$BACKEND_DIR/venv/Scripts/python" ]; then
        echo "$BACKEND_DIR/venv/Scripts/python"
    elif [ -n "$python" ]; then
        echo "$python"
    else
        echo ""
    fi
}

is_running() {
    local pid_file="$1"
    if [ -f "$pid_file" ]; then
        local pid
        pid=$(cat "$pid_file" 2>/dev/null || echo "")
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

print_status() {
    local name="$1"
    local pid_file="$2"
    if is_running "$pid_file"; then
        printf "  ${GREEN}%-15s RUNNING${NC} (PID: %s)\n" "$name" "$(cat "$pid_file")"
    else
        printf "  ${RED}%-15s STOPPED${NC}\n" "$name"
    fi
}

write_pid() {
    local pid_file="$1"
    echo "$$" > "$pid_file"
}

cleanup_pid() {
    local pid_file="$1"
    rm -f "$pid_file"
}

# --- Backend Management ---
backend_start() {
    local python
    python=$(detect_venv_python)
    if [ -z "$python" ]; then
        echo -e "${RED}ERROR: Python not found. Run scripts/init_db.sh first.${NC}"
        exit 1
    fi

    if is_running "$BACKEND_PIDFILE"; then
        echo -e "${YELLOW}Backend is already running (PID: $(cat "$BACKEND_PIDFILE"))${NC}"
        return 0
    fi

    echo "Starting Backend (uvicorn) on port $BACKEND_PORT..."
    cd "$BACKEND_DIR"
    nohup "$python" -m uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" \
        > "$RUN_DIR/backend.log" 2>&1 &
    local pid=$!
    echo "$pid" > "$BACKEND_PIDFILE"
    cd "$PROJECT_ROOT"

    # Wait briefly to check startup
    sleep 2
    if kill -0 "$pid" 2>/dev/null; then
        echo -e "  ${GREEN}Backend started successfully (PID: $pid)${NC}"
    else
        echo -e "  ${RED}Backend failed to start. Check logs: $RUN_DIR/backend.log${NC}"
        rm -f "$BACKEND_PIDFILE"
        return 1
    fi
}

backend_stop() {
    if ! is_running "$BACKEND_PIDFILE"; then
        echo -e "${YELLOW}Backend is not running${NC}"
        rm -f "$BACKEND_PIDFILE"
        return 0
    fi

    local pid
    pid=$(cat "$BACKEND_PIDFILE")
    echo "Stopping Backend (PID: $pid)..."
    kill "$pid" 2>/dev/null || true

    # Wait for process to exit
    for i in {1..5}; do
        if ! kill -0 "$pid" 2>/dev/null; then
            break
        fi
        sleep 1
    done

    # Force kill if still running
    if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
    fi

    cleanup_pid "$BACKEND_PIDFILE"
    echo -e "  ${GREEN}Backend stopped${NC}"
}

# --- Frontend Management ---
frontend_start() {
    if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
        echo "Installing frontend dependencies..."
        cd "$FRONTEND_DIR"
        npm install > "$RUN_DIR/frontend-install.log" 2>&1 || {
            echo -e "  ${RED}npm install failed. Check frontend-install.log${NC}"
            cd "$PROJECT_ROOT"
            return 1
        }
        cd "$PROJECT_ROOT"
    fi

    if is_running "$FRONTEND_PIDFILE"; then
        echo -e "${YELLOW}Frontend is already running (PID: $(cat "$FRONTEND_PIDFILE"))${NC}"
        return 0
    fi

    echo "Starting Frontend (Vite) on port $FRONTEND_PORT..."
    cd "$FRONTEND_DIR"
    FRONTEND_PORT="$FRONTEND_PORT" nohup npm run dev > "$RUN_DIR/frontend.log" 2>&1 &
    local pid=$!
    echo "$pid" > "$FRONTEND_PIDFILE"
    cd "$PROJECT_ROOT"

    sleep 3
    if kill -0 "$pid" 2>/dev/null; then
        echo -e "  ${GREEN}Frontend started successfully (PID: $pid)${NC}"
    else
        echo -e "  ${RED}Frontend failed to start. Check logs: $RUN_DIR/frontend.log${NC}"
        rm -f "$FRONTEND_PIDFILE"
        return 1
    fi
}

frontend_stop() {
    if ! is_running "$FRONTEND_PIDFILE"; then
        echo -e "${YELLOW}Frontend is not running${NC}"
        rm -f "$FRONTEND_PIDFILE"
        return 0
    fi

    local pid
    pid=$(cat "$FRONTEND_PIDFILE")
    echo "Stopping Frontend (PID: $pid)..."
    kill "$pid" 2>/dev/null || true

    for i in {1..5}; do
        if ! kill -0 "$pid" 2>/dev/null; then
            break
        fi
        sleep 1
    done

    if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
    fi

    cleanup_pid "$FRONTEND_PIDFILE"
    echo -e "  ${GREEN}Frontend stopped${NC}"
}

# --- Service Manager ---
manager_start() {
    local python
    python=$(detect_venv_python)
    if [ -z "$python" ]; then
        python=$(detect_python)
    fi
    if [ -z "$python" ]; then
        echo -e "${RED}ERROR: Python not found${NC}"
        return 1
    fi

    if is_running "$MANAGER_PIDFILE"; then
        echo -e "${YELLOW}Service Manager is already running (PID: $(cat "$MANAGER_PIDFILE"))${NC}"
        return 0
    fi

    echo "Starting Service Manager on port $MANAGER_PORT..."
    nohup "$python" "$PROJECT_ROOT/service_manager.py" > "$RUN_DIR/manager.log" 2>&1 &
    local pid=$!
    echo "$pid" > "$MANAGER_PIDFILE"
    sleep 1
    echo -e "  ${GREEN}Service Manager started (PID: $pid)${NC}"
}

manager_stop() {
    if ! is_running "$MANAGER_PIDFILE"; then
        echo -e "${YELLOW}Service Manager is not running${NC}"
        rm -f "$MANAGER_PIDFILE"
        return 0
    fi
    local pid
    pid=$(cat "$MANAGER_PIDFILE")
    echo "Stopping Service Manager (PID: $pid)..."
    kill "$pid" 2>/dev/null || true
    cleanup_pid "$MANAGER_PIDFILE"
    echo -e "  ${GREEN}Service Manager stopped${NC}"
}

# --- Commands ---
case "${1:-help}" in
    start)
        echo "Starting all services..."
        manager_start
        backend_start
        frontend_start
        echo ""
        echo -e "${GREEN}All services started!${NC}"
        echo "  Backend:  http://localhost:$BACKEND_PORT"
        echo "  Frontend: http://localhost:$FRONTEND_PORT"
        echo "  Manager:  http://localhost:$MANAGER_PORT"
        echo "  Docs:     http://localhost:$BACKEND_PORT/docs"
        ;;
    stop)
        echo "Stopping all services..."
        frontend_stop
        backend_stop
        manager_stop
        echo -e "${GREEN}All services stopped${NC}"
        ;;
    restart)
        "$0" stop
        sleep 1
        "$0" start
        ;;
    status)
        echo "Service status:"
        print_status "Backend" "$BACKEND_PIDFILE"
        print_status "Frontend" "$FRONTEND_PIDFILE"
        print_status "Manager" "$MANAGER_PIDFILE"
        ;;
    backend-start)
        backend_start
        ;;
    backend-stop)
        backend_stop
        ;;
    backend-restart)
        backend_stop
        sleep 1
        backend_start
        ;;
    frontend-start)
        frontend_start
        ;;
    frontend-stop)
        frontend_stop
        ;;
    logs)
        tail -f "$RUN_DIR/backend.log"
        ;;
    help|--help|-h)
        echo "LocalRouter - Service Management"
        echo ""
        echo "Usage: $0 <command>"
        echo ""
        echo "Commands:"
        echo "  start              Start all services"
        echo "  stop               Stop all services"
        echo "  restart            Restart all services"
        echo "  status             Show service status"
        echo "  backend-start      Start only backend"
        echo "  backend-stop       Stop only backend"
        echo "  backend-restart    Restart only backend"
        echo "  frontend-start     Start only frontend"
        echo "  frontend-stop      Stop only frontend"
        echo "  logs               Tail backend logs"
        echo ""
        ;;
    *)
        echo -e "${RED}Unknown command: $1${NC}"
        echo "Usage: $0 {start|stop|restart|status|logs|backend-start|backend-stop|backend-restart|frontend-start|frontend-stop}"
        exit 1
        ;;
esac
