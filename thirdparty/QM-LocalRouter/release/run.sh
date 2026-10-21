#!/usr/bin/env bash
# LocalRouter - Run the packaged executable (PyInstaller build)
# Windows counterpart: run.bat
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

export HOST="${HOST:-127.0.0.1}"
export BACKEND_PORT="${BACKEND_PORT:-12002}"

exec "$DIR/apirouter" "$@"
