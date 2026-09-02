#!/usr/bin/env bash
set -euo pipefail

# 仓库根 = 脚本所在目录(thirdparty)的上级
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "============================================================"
echo "  构建 cutia standalone（非 Windows 本机验证，不提交）"
echo "  说明：此脚本用于在非 Windows 平台验证 cutia 构建链路可"
echo "        用（bun install + build:web）。产出的 standalone 为"
echo "        本平台原生，跨平台不可用，请勿提交到 git。"
echo "  参数：--clean  构建后删除 apps/web/standalone（不留存）"
echo "        --git    仍 git add 并提交（不推荐，跨平台无效）"
echo "============================================================"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "[ERROR] 未找到 $PY，请先安装 Python 3.10+。"
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "[WARN] 未找到 node。build:web 需要 Node.js（>= 18），将尝试继续；"
  echo "       若构建失败，请先安装 Node.js 后再试。"
fi

GIT_ADD=0
CLEAN=0
for a in "$@"; do
  case "$a" in
    --git)   GIT_ADD=1 ;;
    --clean) CLEAN=1 ;;
  esac
done

echo
echo "[1/1] 调用 install_thirdparty.ensure_cutia(True) 构建 ..."
( cd "$SCRIPT_DIR" && "$PY" -c "import install_thirdparty; raise SystemExit(0 if install_thirdparty.ensure_cutia(True) else 1)" )

STANDALONE="$SCRIPT_DIR/cutia/apps/web/standalone"

if [ "$CLEAN" -eq 1 ]; then
  echo "[clean] 删除 $STANDALONE（本机验证无需留存）"
  rm -rf "$STANDALONE"
  echo "[OK] 已清理。"
  exit 0
fi

echo
echo "[OK] cutia 构建完成: $STANDALONE"
echo
if [ "$GIT_ADD" -eq 1 ]; then
  echo "[WARN] 你选择了 --git：非 Windows 原生 standalone 仅供本机使用，"
  echo "       提交后 Windows 用户无法使用。仅在确定仅本平台分发时才提交。"
  if [ -d "$REPO/.git" ]; then
    git -C "$REPO" add thirdparty/cutia/apps/web/standalone
    echo "[OK] 已 git add。请人工 review 后提交。"
  fi
else
  echo "[INFO] 默认不提交（非 Windows 原生产物跨平台无效）。"
  echo "       本机验证后清理: $0 --clean"
  echo "       强制提交(不推荐): $0 --git"
fi
