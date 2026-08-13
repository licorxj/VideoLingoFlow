#!/usr/bin/env bash
#
# LocalRouter - Database Initialization (Linux/macOS)
#
# Usage:
#   chmod +x init_db.sh
#   ./init_db.sh
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "======================================================"
echo "  LocalRouter - Database Initialization"
echo "======================================================"

# Find Python
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: Python is not installed. Please install Python 3.10+."
    exit 1
fi

echo "Using Python: $PYTHON ($($PYTHON --version 2>&1))"

# Run the Python initialization script
$PYTHON init_db.py
