#!/usr/bin/env bash
# ============================================================
#  正式版一键启动·生产模式（Linux / macOS）：不隔离 CUDA / 环境，
#  不启动 Vite dev server；前端由后端同源托管构建产物 frontend/dist，
#  访问 http://127.0.0.1:11001/ 即为生产版前端。
#  使用前请先运行 install.sh 完成 Python / 依赖 / 第三方扩展安装。
#  用法：bash start-prod.sh [--rebuild]
#        --rebuild  强制重新构建前端（默认：dist 已存在时直接复用）
# ============================================================
set -u
cd "$(dirname "$0")"

# 生产模式：主后端隐藏窗口，仅保留 Manager 一个窗口
export VIDEOLINGO_PROD_MODE=1

# 自动打开默认浏览器（Linux: xdg-open / macOS: open）
open_browser() {
    if command -v xdg-open >/dev/null 2>&1; then xdg-open "$1"
    elif command -v open >/dev/null 2>&1; then open "$1"
    else echo "[Frontend] 请手动打开: $1"; fi
}

# 端口就绪探测（bash /dev/tcp；就绪即返回，无固定等待）
poll_port() {
    for _ in $(seq 1 120); do
        if (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; then
            exec 3>&- 3<&- 2>/dev/null
            return 0
        fi
        sleep 1
    done
    return 1
}

PY="venv312/bin/python"
if [ ! -x "$PY" ]; then
    echo "[错误] 未找到 Python 虚拟环境 venv312，请先运行 install.sh"
    exit 1
fi

# 依赖自检
"$PY" -c "import sqlite3, alembic, celery, redis, sqlalchemy" >/dev/null 2>&1 || {
    echo "[错误] Python 依赖不完整，请先运行 install.sh"
    exit 1
}

mkdir -p data/assets data/workspace data/checkpoints data/backups logs

# 前端：生产构建（由后端同源托管 frontend/dist）
if [ "${1:-}" != "--rebuild" ] && [ -f frontend/dist/index.html ]; then
    echo "[Frontend] 使用现有构建产物 frontend/dist（如需重建请运行 bash start-prod.sh --rebuild）"
elif [ ! -d frontend/node_modules ]; then
    echo "[错误] frontend/node_modules 不存在，无法构建前端"
    echo "       请先运行 install.sh 或在前端目录执行 npm install"
    exit 1
else
    echo "[Frontend] 构建生产版本（npm run build）..."
    (cd frontend && npm run build) || {
        echo "[错误] 前端构建失败"
        exit 1
    }
fi

# Manager 端口检查（占用则先关闭再启动）
MANAGER_PID=""
if command -v lsof >/dev/null 2>&1; then
    MANAGER_PID=$(lsof -ti tcp:18001 2>/dev/null | head -n1)
elif command -v fuser >/dev/null 2>&1; then
    MANAGER_PID=$(fuser 18001/tcp 2>/dev/null | tr -d ' ' | head -n1)
elif command -v ss >/dev/null 2>&1; then
    MANAGER_PID=$(ss -tlnp 2>/dev/null | grep ':18001 ' | grep -o 'pid=[0-9]*' | head -n1 | cut -d= -f2)
elif command -v netstat >/dev/null 2>&1; then
    MANAGER_PID=$(netstat -tlnp 2>/dev/null | grep ':18001 ' | grep -o 'LISTEN.*' | grep -o '[0-9]*/' | head -n1 | tr -d '/')
fi
if [ -n "$MANAGER_PID" ]; then
    echo "[Manager] 端口 18001 已被占用（PID: $MANAGER_PID），先停止已运行的 Manager..."
    kill -9 "$MANAGER_PID" 2>/dev/null
    for _ in $(seq 1 30); do
        if command -v lsof >/dev/null 2>&1 && ! lsof -ti tcp:18001 >/dev/null 2>&1; then break
        elif command -v ss >/dev/null 2>&1 && ! ss -tln 2>/dev/null | grep -q ':18001 '; then break
        elif command -v netstat >/dev/null 2>&1 && ! netstat -tln 2>/dev/null | grep -q ':18001 '; then break
        fi
        sleep 1
    done
    echo "[Manager] 已停止旧 Manager，端口 18001 已释放。"
fi

echo "[生产模式] 前端: http://127.0.0.1:11001/  （后端同源托管 frontend/dist）"
# 端口就绪后自动打开默认浏览器（无固定等待，就绪即开）
(poll_port 11001 && open_browser "http://127.0.0.1:11001" >/dev/null 2>&1 &)
echo "按 Ctrl+C 停止（后端全部服务由 Manager 管理）"
exec "$PY" backend/manager.py
