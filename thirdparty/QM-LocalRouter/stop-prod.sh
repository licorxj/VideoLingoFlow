#!/usr/bin/env bash
#
# LocalRouter - Production Stop (Linux/macOS)
# Stops the server started by start-prod.sh.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIDFILE="$SCRIPT_DIR/run/prod-backend.pid"

if [ ! -f "$PIDFILE" ]; then
    echo "Production server is not running (no pid file)."
    exit 0
fi

PID=$(cat "$PIDFILE" 2>/dev/null || echo "")
if [ -z "$PID" ] || ! kill -0 "$PID" 2>/dev/null; then
    echo "Production server is not running (stale pid file)."
    rm -f "$PIDFILE"
    exit 0
fi

echo "Stopping production server (PID: $PID)..."
kill "$PID" 2>/dev/null || true
for _ in 1 2 3 4 5; do
    if ! kill -0 "$PID" 2>/dev/null; then
        break
    fi
    sleep 1
done
if kill -0 "$PID" 2>/dev/null; then
    kill -9 "$PID" 2>/dev/null || true
fi
rm -f "$PIDFILE"
echo "Production server stopped."
