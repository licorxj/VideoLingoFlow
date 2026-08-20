#!/usr/bin/env bash
# ============================================================
#  正式版：激活 venv312 虚拟环境（不隔离 CUDA / 环境，
#  使用系统已安装的 CUDA）。激活后进入交互式 shell。
#  用法：bash activate-venv.sh
# ============================================================
cd "$(dirname "$0")"
if [ ! -f venv312/bin/activate ]; then
    echo "[错误] 未找到 venv312 虚拟环境，请先运行 install.sh"
    exit 1
fi
source venv312/bin/activate
echo "VideoLingoLc venv 已激活（使用系统 CUDA 环境）"
exec "${SHELL:-bash}"
