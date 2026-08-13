# ============================================================
# LocalRouter - Multi-stage Docker Build
# ============================================================
# Usage:
#   docker build -t localrouter .
#   docker run -p 12002:12002 -p 12001:12001 localrouter
# ============================================================

# ----- Stage 1: Build Frontend -----
FROM node:20-alpine AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ .
RUN npm run build

# ----- Stage 2: Backend + Serve -----
FROM python:3.12-slim

WORKDIR /app

# Install Node.js for frontend dev server (production mode uses built files)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy backend
COPY backend/ ./backend/
COPY service_manager.py ./

# Copy built frontend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Install Python dependencies
RUN pip install --no-cache-dir -r backend/requirements.txt

# Create data directory
RUN mkdir -p backend/data/backups backend/data/icons

# Environment
ENV BACKEND_PORT=12002
ENV FRONTEND_PORT=12001
ENV HOST=0.0.0.0

# Expose ports
EXPOSE 12002
EXPOSE 12001

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:12002/health || exit 1

# Start both backend and a simple file server for frontend dist
CMD ["sh", "-c", "\
    cd /app/backend && \
    python -m uvicorn app.main:app --host 0.0.0.0 --port 12002 & \
    cd /app/frontend/dist && \
    python -m http.server 12001 & \
    wait \
"]
