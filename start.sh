#!/usr/bin/env bash
# ============================================================
#  正式版一键启动（Linux / macOS）：不隔离 CUDA / 环境，
#  直接使用系统已安装的 CUDA 运行时。
#  使用前请先运行 install.sh 完成 Python / 依赖 / 第三方扩展安装。
#  用法：bash start.sh
# ============================================================
set -u
cd "$(dirname "$0")"

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

# 前端：清理残留 vite 后，后台等待主后端(11001)就绪再启动 Vite dev server（后端先、前端后）
if [ -d frontend/node_modules ]; then
    # 清理 11003/11004 残留前端进程（与 Windows 脚本行为一致）
    if command -v lsof >/dev/null 2>&1; then
        lsof -ti tcp:11003 2>/dev/null | xargs kill -9 2>/dev/null
        lsof -ti tcp:11004 2>/dev/null | xargs kill -9 2>/dev/null
    elif command -v fuser >/dev/null 2>&1; then
        fuser -k 11003/tcp 11004/tcp >/dev/null 2>&1
    fi
    echo "[Frontend] 主后端就绪后将启动 Vite dev server: http://127.0.0.1:11003"
    (poll_port 11001 && (cd frontend && nohup npx vite --port 11003 --strictPort >/dev/null 2>&1 &) && poll_port 11003 && open_browser "http://127.0.0.1:11003" >/dev/null 2>&1) &
else
    echo "[提示] frontend/node_modules 不存在，跳过前端 dev server；可使用构建产物 frontend/dist"
fi

# 当前窗口运行 Manager（worker 输出在此）
echo "[Backend] 启动 Manager（worker 输出在当前窗口）..."
exec "$PY" backend/manager.py
