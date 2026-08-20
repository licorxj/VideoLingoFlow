#!/usr/bin/env bash
# ============================================================
#  VideoLingoLc 安装入口（Linux / macOS）
#  调用跨平台安装器 installer/install.py
#  用法（无需可执行位）：
#      bash install.sh [--skip-backend] [--force-thirdparty]
# ============================================================
set -u
cd "$(dirname "$0")"

PY=""
if [ -x "venv312/bin/python" ]; then
    PY="venv312/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="python3"
elif command -v python >/dev/null 2>&1; then
    PY="python"
fi

if [ -z "$PY" ]; then
    echo "[提示] 未找到 Python，请先安装 Python 3.10+（推荐 3.12）后重跑："
    if [ "$(uname -s)" = "Linux" ]; then
        echo "  Ubuntu/Debian: sudo apt install python3.12 python3.12-venv python3-pip"
        echo "  或 pyenv: pyenv install 3.12 && pyenv local 3.12"
    else
        echo "  macOS: brew install python@3.12"
    fi
    exit 1
fi

echo "============================================================"
echo "  VideoLingoLc 安装程序"
echo "============================================================"
"$PY" installer/install.py "$@"
RC=$?
if [ "$RC" -ne 0 ]; then
    echo "[错误] 安装未完成，退出码: $RC"
    exit "$RC"
fi
echo "[完成] 安装完成"
exit 0
