#!/bin/sh
# ============================================================
# LLM API Router - 容器启动脚本
# 1. 以 root 准备运行环境：数据卷权限、nginx 配置渲染
# 2. 降权为 app 用户，同时启动 uvicorn（后端）与 nginx（网关）
# 3. 任一进程退出即结束容器，便于编排系统感知故障
# ============================================================
set -e

if [ "$(id -u)" = "0" ]; then
    # 确保数据目录存在且属主正确（首次挂载的 volume 属主可能是 root）
    mkdir -p /app/backend/data/backups /app/backend/data/icons
    chown -R app:app /app/backend/data

    # 渲染 nginx 配置（仅替换声明过的端口变量）
    envsubst '${BACKEND_PORT} ${FRONTEND_PORT}' \
        < /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf

    # 降权为 app 用户重新执行本脚本
    exec setpriv --reuid=app --regid=app --init-groups /bin/sh "$0" "$@"
fi

cd /app/backend

# 启动后端 API 服务
python -m uvicorn app.main:app --host "$HOST" --port "$BACKEND_PORT" &
UVICORN_PID=$!

# 启动 nginx 网关（前台运行）
nginx -g 'daemon off;' &
NGINX_PID=$!

cleanup() {
    kill "$UVICORN_PID" "$NGINX_PID" 2>/dev/null || true
    wait 2>/dev/null || true
}
trap cleanup INT TERM

# 任一进程退出则整体退出
while true; do
    if ! kill -0 "$UVICORN_PID" 2>/dev/null || ! kill -0 "$NGINX_PID" 2>/dev/null; then
        echo "One of the processes exited, shutting down container." >&2
        cleanup
        exit 1
    fi
    sleep 2
done
