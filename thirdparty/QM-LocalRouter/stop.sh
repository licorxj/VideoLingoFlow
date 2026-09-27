#!/usr/bin/env bash
#
# LocalRouter - One-click Stop (Linux/macOS)
# Stops the frontend, backend and Service Manager started by start.sh.
#
# Usage:
#   ./stop.sh             # or: bash stop.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/scripts/manage.sh" stop
