#!/usr/bin/env bash
# ============================================================
#  第三方扩展安装（Linux / macOS）
#  与 install-thirdparty.bat 等价：找到 Python 后调用跨平台脚本
#  install_thirdparty.py（下载 CloakBrowser + cutia standalone + 三个项目 + pi）
#
#  用法（无需可执行位，直接 bash 调用即可）：
#      bash thirdparty/install-thirdparty.sh [--force]
#  主安装程序调用方式（创建 venv 之后）：
#      bash thirdparty/install-thirdparty.sh
# ============================================================
set -u
cd "$(dirname "$0")/.."

PY=""
if [ -x "venv312/bin/python" ]; then
    PY="venv312/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="python3"
elif command -v python >/dev/null 2>&1; then
    PY="python"
fi

if [ -z "$PY" ]; then
    echo "[错误] 未找到 Python。请先安装 Python 3.12 或创建 venv312 虚拟环境。"
    exit 1
fi

echo "============================================================"
echo "  VideoLingoLc 第三方扩展安装"
echo "============================================================"
"$PY" thirdparty/install_thirdparty.py "$@"
RC=$?
if [ "$RC" -ne 0 ]; then
    echo "[错误] 第三方扩展安装失败，退出码: $RC"
    exit "$RC"
fi
echo "[完成] 第三方扩展安装完成"
exit 0
