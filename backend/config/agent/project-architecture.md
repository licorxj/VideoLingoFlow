# VideoLingoFlow Project Architecture

## Product Scope

VideoLingoFlow (Chinese name: 流连视听) is a local-first AI video localization and production application. Its workflows cover media intake, download, ASR, sentence processing, translation, subtitle rendering, TTS and dubbing, audio/video merge, editing, batch execution, publishing, and long-form voice production.

## Repository Layout

- `frontend/`: React 18, TypeScript, Vite, Tailwind CSS, React Router, Zustand, TanStack Query, Radix UI, and `@xyflow/react` workflow editing.
- `frontend/src/api/`: frontend HTTP API clients.
- `frontend/src/components/`: shared UI, layout, workflow, settings, and agent components.
- `frontend/src/pages/`: routed page features.
- `backend/`: FastAPI application, workflow execution engine, AI capabilities, and local service integrations.
- `backend/api/`: feature-scoped REST and WebSocket routers.
- `backend/engine/`: task orchestration, batch execution, scheduling, artifacts, and step running.
- `backend/steps/`: executable workflow node implementations.
- `backend/control_plane/`: persistent task/workspace models, queue dispatch, checkpoints, assets, migration, backup, and custom-node runtime execution.
- `backend/config/`: YAML/JSON configuration, node schemas, workflow definitions, subtitle presets, and this agent knowledge directory.
- `data/`: mutable local runtime data, assets, databases, workspace files, session data, and generated outputs.
- `data/workspace/`: default safe workspace for Pi sessions and generated task materials.
- `thirdparty/`: vendored Pi, QM-LocalRouter, Cutia, and social publishing integrations.
- `scripts/`: operational tooling, including LLM Router helpers and backup scripts.
- `.runtime/`: local runtime environment definitions.
- `deploy/`: Docker Compose, Nginx, and production deployment assets.

## Application Topology

The primary application is a React single-page application served by FastAPI. During development, Vite serves the frontend and proxies backend requests. In production, FastAPI mounts `frontend/dist`.

FastAPI router composition is in `backend/main.py`. Feature APIs use `/api/*`; realtime endpoints use `/ws/*`; preview media is mounted at `/temp`.

Workflow execution is split between the execution engine and Control Plane. The Control Plane persists task lifecycle, dispatches Celery work by resource type, records checkpoints/artifacts, and supports retry and recovery.

## Local Runtime

The local environment source is `.runtime/local_env.bat`. It defines local-mode data roots, a SQLite Control Plane database, and Redis URLs for VoiceForge and Celery.

- `CONTROL_PLANE_DATA_ROOT=data`
- `CONTROL_PLANE_DATABASE_PATH=data/control-plane.db`
- `CONTROL_PLANE_ASSET_ROOT=data/assets`
- Redis: `redis://127.0.0.1:6379/2` for broker-related work and `redis://127.0.0.1:6379/3` for results.

On Windows, `start.bat` and the root launch scripts load `.runtime/local_env.bat`, discover local tools, activate `venv312`, and start `backend/manager.py`. Production launch scripts serve `frontend/dist`; development launch can start Vite after dependencies are available.

## Backend Virtual Environment

Use `venv312` for backend Python execution. Do not assume a system Python has the required packages.

Key backend technologies are Python 3.12, FastAPI/Uvicorn, Pydantic, SQLAlchemy, Alembic, Redis, Celery, FFmpeg, MoviePy, OpenCV, ASR engines, TTS engines, and model-provider integrations.

## Default Local Services

- Manager: `http://127.0.0.1:18001`
- Main FastAPI backend: `http://127.0.0.1:11001`
- Vite frontend: `http://127.0.0.1:11003`
- Redis: `127.0.0.1:6379`
- LLM Router: `http://127.0.0.1:8800`
- Social backend: `http://127.0.0.1:5409`
- Social MCP: `http://127.0.0.1:5410`

## Optional GPU Service

`backend/gpu_service/` is a Redis-backed local GPU lane manager, separate from Celery resource queues. When `GPU_SERVICE_ENABLED` is true, Manager starts it and the runtime can dispatch ASR and separation work through it. Lanes are constrained by `GPU_SERVICE_MAX_LANES`, `GPU_SERVICE_VRAM_HEADROOM_GB`, `GPU_SERVICE_LANE_IDLE_TIMEOUT`, and `GPU_SERVICE_JOB_TIMEOUT`; unavailable service paths fall back to the existing execution route.

## Safety Boundary

`backend/auth` is an access-prohibited directory. Do not inspect or alter it. Account, registration, subscription, payment, and entitlement features are outside the agent's supported scope.
