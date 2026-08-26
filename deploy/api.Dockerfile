# VideoLingoFlow 后端 + 前端 镜像
# 统一基座：python:3.12-slim（Debian bookworm）
# GPU 支持：通过 PyTorch cu128 wheel 自带的 CUDA 运行库实现，
#           运行时加 --gpus all 即可，无需 CUDA 基础镜像。
#
# 构建示例（CPU）:
#   docker build -f deploy/api.Dockerfile --build-arg TORCH_INDEX=cpu -t videolingo-api:local .
# 构建示例（GPU / CUDA 12.8）:
#   docker build -f deploy/api.Dockerfile --build-arg TORCH_INDEX=cu128 -t videolingo-api:local .
#
# 默认 TORCH_INDEX=cu128（GPU）。纯 CPU 部署请显式传 cpu。

# ---------- 阶段 1: 前端构建 ----------
FROM node:20-bullseye AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json* ./
# 无 lock 时回退普通 install；有 lock 时用 ci（更快、可复现）
RUN if [ -f package-lock.json ]; then npm ci || npm install; else npm install; fi
COPY frontend/ ./
RUN npm run build && rm -rf /build/frontend/node_modules

# ---------- 阶段 2: 运行时（后端 + 装好的依赖） ----------
FROM python:3.12-slim AS runtime

ARG TORCH_INDEX=cu128
ARG DEBIAN_FRONTEND=noninteractive

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # 业务子进程依赖 `python` 命令与 `ffmpeg`
    CLUSTER_MODE=1 \
    # 模型缓存默认落盘到可挂载目录
    HF_HOME=/app/_model_cache \
    TRANSFORMERS_CACHE=/app/_model_cache/transformers

WORKDIR /app

# 系统依赖：ffmpeg（音频/视频处理）、playwright chromium 运行库、字体（OCR/字幕渲染）
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        libgomp1 \
        libgthread-2.0-0 \
        fonts-dejavu-core \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 业务依赖 `python -m yt_dlp` 等子进程调用，确保 `python` 命令存在
RUN ln -sf /usr/local/bin/python3 /usr/local/bin/python

# 复制依赖清单
COPY backend/requirements.txt backend/requirements-voiceforge.txt /app/backend/

# 1) 先装 PyTorch 三件套（大层，单独缓存；cu128 自带 CUDA 运行库）
RUN if [ "$TORCH_INDEX" = "cpu" ]; then \
        EXTRA="https://download.pytorch.org/whl/cpu"; \
    else \
        EXTRA="https://download.pytorch.org/whl/${TORCH_INDEX}"; \
    fi && \
    pip install --no-cache-dir \
        torch==2.8.0+${TORCH_INDEX} \
        torchvision==0.23.0+${TORCH_INDEX} \
        torchaudio==2.8.0+${TORCH_INDEX} \
        --extra-index-url "$EXTRA"

# 2) 其余 Python 依赖
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# 3) Playwright 浏览器（浏览器自动化 / CloakBrowser 能力）
RUN pip install --no-cache-dir "playwright>=1.60,<2" \
    && playwright install --with-deps chromium

# 复制应用代码
COPY backend/ /app/backend/
COPY alembic.ini /app/alembic.ini
COPY thirdparty/ /app/thirdparty/
COPY config/ /app/config/

# 前端构建产物
COPY --from=frontend /build/frontend/dist /app/frontend/dist

# 运行时目录（数据 / 模型缓存 / 临时预览 由 volume 挂载，这里仅建占位）
RUN mkdir -p /app/data /app/_model_cache /app/temp /app/tasks \
    && find /app -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true

# 健康检查（依赖 `python` 软链，已在上方建立）
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:11001/api/health/ready', timeout=3)" || exit 1

EXPOSE 11001

# 由 docker-compose 的 command 决定运行 uvicorn(api) 还是 celery(worker)
# 默认启动 API；--proxy-headers 配合前置 Nginx 的 X-Forwarded
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "11001", "--proxy-headers"]
