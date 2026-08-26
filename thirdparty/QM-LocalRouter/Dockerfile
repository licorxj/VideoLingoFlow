# syntax=docker/dockerfile:1

# ============================================================
# LLM API Router - Multi-stage Docker Build
# ------------------------------------------------------------
# 架构（单容器运行两个进程，由 entrypoint.sh 管理）：
#   - nginx   :12001  前端静态文件 + /api、/v1 反向代理（支持 SSE 流式）
#   - uvicorn :12002  后端 API 服务
#
# 用法：
#   docker build -t localrouter .
#   docker run -d -p 12001:12001 -p 12002:12002 \
#     -v localrouter_data:/app/backend/data localrouter
# ============================================================

# ---------- Stage 1: 构建前端 ----------
FROM node:20-alpine AS frontend-build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
RUN npm run build

# ---------- Stage 2: 运行环境（后端 + nginx 网关） ----------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    BACKEND_PORT=12002 \
    FRONTEND_PORT=12001 \
    TZ=Asia/Shanghai

WORKDIR /app

# 安装 nginx（静态文件 + 反向代理）、curl（健康检查）、时区数据
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        nginx \
        curl \
        ca-certificates \
        tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/conf.d/default.conf \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo "$TZ" > /etc/timezone

# 先拷贝依赖清单，利用 Docker 层缓存加速重复构建
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# 拷贝后端源码
COPY backend/ ./backend/
COPY service_manager.py ./

# 拷贝前端构建产物
COPY --from=frontend-build /app/dist ./frontend/dist

# 创建非 root 运行用户，并初始化数据目录骨架
RUN useradd --system --uid 1001 --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/backend/data/backups /app/backend/data/icons \
    && chown -R app:app /app \
    && chown -R app:app /var/cache/nginx

# 部署 nginx 配置模板与启动脚本
COPY docker/nginx.conf /etc/nginx/nginx.conf.template
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 12001
EXPOSE 12002

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:12002/api/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
