# VideoLingoFlow

> 🌐 Language / 语言：**English** · [简体中文](README.md)

An AI-powered automation & creation framework built around **local-first, infinitely extensible, and multi-user collaborative** principles. It turns video subtitling, translation, dubbing, editing, AI enhancement, batch production, and multi-platform publishing into a three-pillar system — **node-based workflows + chat-driven Agent execution + pluggable capability interfaces**. Whether you are a solo creator, a studio, or a distributed team, you can orchestrate any task with the same framework.

> **In one sentence**: every task is a visual node graph; every capability is a pluggable interface; every instruction executes via conversation. Nodes, interfaces, and Agents combine freely — infinite tasks, full freedom.

---

## Why This Framework

Traditional automation tools hard-code features, require code changes to extend, and rely on manual file transfer for collaboration. VideoLingoFlow addresses three fundamental problems by design:

- **A standardized task model**: every task is a Directed Acyclic Graph (DAG). Each node is a reusable capability unit; nodes pass data through semantically-typed ports. Task = graph; graph = saveable, reusable, re-runnable in batch, and shareable.
- **Capabilities decoupled from orchestration**: capability interfaces (ASR / TTS / image generation / source separation / AIGC / publishing…) are fully separated from orchestration. Adding a capability means registering one interface — **zero changes to the orchestration layer**. Conversely, reshaping a production pipeline is just drag-and-drop wiring — zero changes to the capability layer.
- **Extensible by everyone**: the framework ships three extension mechanisms — **custom nodes**, **new capability interfaces**, and **Agent-as-a-node**. Extensions mount like plugins without touching the framework core.

> That is why this is not just a "video tool" — it is a **creation operating system** that can host any AI workflow.

---

## Core Capabilities

### 1. Node-Based Workflows with Custom Nodes

A visual DAG canvas built on `@xyflow/react` ships with **40+ built-in nodes** covering input, platform download, audio, ASR, translation, subtitles, dubbing, composition, image generation, and publishing. Highlights:

- **Custom nodes**: add a node with the "definition + execution step + rule validation + registration" four-piece convention. Field-level validation, semantic port wiring, and artifact layout rules are all built in.
- Workflows can be saved, reused, and re-run in batch; node-level artifact management and cleanup are handled automatically by the control plane.

### 2. Capability Interfaces — Add Any, Freely

The capability layer is organized by **interface domains**: ASR / TTS / image generation / source separation / AIGC / publishing. Each domain supports **switching between multiple providers** (e.g., ASR: WhisperX, FunASR, Qwen3-ASR, ElevenLabs…). Adding a new capability interface = define the data model + implement the invocation + register the domain — **no orchestration changes required**. Example: to integrate a new TTS provider, register a TTS interface and every workflow immediately gains it.

### 3. Chat-Driven Agent Task Execution

The built-in project assistant **"Pi"** lets you command the entire pipeline in **natural language**:

- **Configure interfaces**: switch and configure capability interfaces through conversation;
- **Create nodes**: describe what you need and the Agent generates the custom node definition and steps;
- **Schedule tasks**: issue tasks verbally; the Agent parses them into workflows and dispatches execution;
- **Troubleshoot & organize**: stream conversations to debug issues, organize files, and prepare publishing.

Pi supports six roles (General / Node Creation / Workflow Orchestration / Task Execution / File Organization / Publishing), keeps session history, and supports tool calls.

### 4. Agent-as-a-Node — Orchestrate Freely

The framework implements Agents as **built-in node types** (`pi_agent` general agent node, `editor_agent` editing agent node). You can drag an Agent directly onto the canvas and wire it with regular capability nodes — **the Agent is both a conversation assistant and a step in the pipeline**. Outputs from previous steps feed into the Agent, and the Agent's output flows to downstream nodes. Text-command-driven execution and visual orchestration merge seamlessly.

### 5. Infinite Tasks with Batch & Scheduling

- **Batch workbench**: import multiple assets at once, run tasks in parallel with rate limiting and failure retries;
- **Lifecycle management**: orchestrated by the control plane (FastAPI + SQLite + Redis/Celery) with resource queues (GPU / TTS / LLM / IO), health checks, Prometheus metrics, and backup/restore.

---

## Collaboration & Community

### 6. Shared Community — One-Click Share & Import of Nodes and Workflows

- Package custom **nodes** and **workflows** and upload them to the cloud community (Cloudflare Worker + R2 + D1);
- Browse the community and **one-click import** mature flows shared by others — reuse instantly;
- Team know-how becomes distributable assets, shared with the world.

### 7. Multi-User Collaboration — LAN / Internet / Remote Control

Built on a user / role / project permission system + real-time WebSocket collaboration:

- **LAN mode**: collaboration within a trusted local network, enabled instantly;
- **Internet remote mode (Remote)**: exposes a public domain via Cloudflare Tunnel for real-time collaboration across sites. Off by default; public access is blocked by `RemoteAccessGuard`;
- Project-level resource center (upload/download assets & artifacts), member approval, audit logs, and a process manager panel (Manager port 18001) for remote monitoring and control.

### 8. Teams & Remote Work

Members can edit workflows simultaneously, maintain shared project resources, watch task progress and logs remotely, and start/stop services remotely. One framework covers the collaboration and remote-work needs of **studios, MCNs, and cross-city teams**.

---

## Tech Stack

| Layer | Technology |
| --- | --- |
| Backend | Python 3.12, FastAPI, Uvicorn, SQLAlchemy, Alembic, Celery |
| Frontend | React 18, Vite, TypeScript, Tailwind CSS, zustand, @xyflow/react |
| Task Queue | Celery + Redis (`--pool=threads`, subprocess isolation) |
| Database | SQLite (local `data/control-plane.db`) / PostgreSQL (Docker cluster) |
| AI/ML | WhisperX, FunASR, Edge-TTS, Qwen/multi-model LLM, demucs, FFmpeg |
| Cloud | Cloudflare Worker/R2/D1 (community), Cloudflare Tunnel (remote collaboration) |

## Directory Layout

```text
VideoLingoFlow/
├── backend/                  # Backend (FastAPI main app, port 11001)
│   ├── api/                  # All REST/WS routes
│   ├── control_plane/        # Control plane: DB/models/runtime/scheduling/Celery/security
│   ├── engine/               # Execution engine: batch executor, step pipeline, task management
│   ├── steps/                # 40+ node execution steps (s_*.py, subclass BaseStep)
│   ├── config/               # Built-in node definitions, workflow files, interface config
│   ├── voiceforge/           # VoiceForge TTS (separate DB + Celery tasks)
│   ├── aigc/                 # AIGC services (ComfyUI/Jimeng/RunningHub)
│   ├── publish/              # Multi-platform publishing (Social MCP client)
│   ├── pi_rpc/               # Pi agent bridge (session management, RPC client)
│   ├── editor/               # Editing workbench + editing AI Agent
│   ├── llm/ asr/ tts/ imagegen/ separation/  # Capability domains
│   ├── main.py               # FastAPI entry
│   ├── manager.py            # Process manager (port 18001)
│   └── venv312/              # Python 3.12 virtual environment
├── frontend/                 # Frontend (React + Vite, dev port 11003)
│   └── dist/                 # Build output (served same-origin by backend)
├── data/                     # Runtime data (control-plane.db, redis/)
├── control_plane_workspaces/ # Task workspaces
├── docs/                     # Knowledge base docs (agent & developer guides)
├── deploy/                   # Docker cluster deployment (docker-compose, nginx, TLS)
├── cloudflare/               # Community Worker (src/index.js + wrangler.toml)
├── thirdparty/               # Third-party components (pi, cutia, social, etc.)
├── install.bat / install.sh
├── start.bat / start.sh        # One-click start (dev mode)
└── start-prod.bat / start-prod.sh  # One-click start (production mode)
```

## Quick Start

### Requirements

- Windows 10/11 (`*.bat` scripts) / Linux / macOS
- Python 3.12 (auto-downloaded by installer if missing), Node.js ≥ 18, Redis (auto-started by Manager)
- Optional: NVIDIA GPU + CUDA (local model inference)

### 1. First-Time Install

Run `install.bat` (`install.sh` on Linux/macOS): auto-checks/installs Python 3.12 and Node.js, installs backend dependencies (PyTorch trio selected automatically by platform & CUDA), and installs third-party extensions.

### 2. One-Click Start

Run `start.bat` (or `bash start.sh` on Linux/macOS). Manager runs Alembic migrations, initializes the VoiceForge DB, starts Redis and all services; the frontend runs as a Vite dev server (port 11003).

**Production mode**: run `start-prod.bat` / `start-prod.sh`. No Vite dev server — the frontend build is served same-origin by the backend (`frontend/dist` is reused if present; `--rebuild` forces a rebuild). Open `http://127.0.0.1:11001/` for the production UI.

| Service | Address | Port |
| --- | --- | --- |
| Process Manager | http://127.0.0.1:18001 | 18001 |
| Main backend (API + frontend) | http://127.0.0.1:11001 | 11001 |
| Frontend dev server | http://localhost:11003 | 11003 |
| Social backend / MCP | http://127.0.0.1:5409 / 5410 | 5409 / 5410 |
| Social frontend | http://localhost:5173 | 5173 |
| LLM Router | http://127.0.0.1:8800 | 8800 |
| Cutia editor | http://127.0.0.1:4100 | 4100 |
| Redis | 127.0.0.1:6379 | 6379 |

Open http://127.0.0.1:11001/ in your browser to enter the workbench.

### 3. Health Checks

- Liveness: `GET /api/health/live`; readiness: `GET /api/health/ready` (validates schema, data dir, Redis, Celery worker); metrics: `GET /api/metrics`

## Configuration

- **LAN collaboration**: copy `.runtime/local_env.bat.template` to `local_env.bat`, set `VIDEOLINGO_LAN_MODE=1`, and restart Manager. API and Manager then listen on `0.0.0.0` (trusted LAN only).
- **Remote collaboration**: enable Remote mode on the "Collaboration" page (public domain via Cloudflare Tunnel). Off by default — public requests are blocked by `RemoteAccessGuard`.
- **Model cache**: stored under `_model_cache/`; `HF_ENDPOINT` defaults to `https://hf-mirror.com`.
- **Backup/restore**: after stopping Manager, `python scripts/control_plane_backup.py backup/restore` (see `deploy/README.md`).
- **Docker cluster deployment** (PostgreSQL + Redis + MinIO + Nginx): see `deploy/README.md`; the only DB migration entry is `alembic upgrade head`.

## Documentation Index (docs/)

> These docs target **developers and other agents** — read the relevant guide before changing code.

| Doc | Content | Use case |
| --- | --- | --- |
| [docs/项目架构.md](docs/项目架构.md) | Architecture: control plane, task lifecycle, execution domains, communication, deployment | Understand how the system works |
| [docs/项目目录功能说明.md](docs/项目目录功能说明.md) | Per-directory/module description (backend routes, frontend pages, three collaboration capabilities) | Locate code, find entry points |
| [docs/工作流编排指南.md](docs/工作流编排指南.md) | Workflow JSON format, port wiring rules, node list, orchestration steps | Orchestrate workflows |
| [docs/节点新建规范指南.md](docs/节点新建规范指南.md) | Four-piece custom node convention, execution domain, artifact naming, input injection, checklist | Add custom nodes |
| [docs/接口添加指南.md](docs/接口添加指南.md) | Interface domains (ASR/TTS/imagegen/separation/AIGC), data models, four-piece convention | Add or extend capability interfaces |
| [docs/多人协作功能介绍.md](docs/多人协作功能介绍.md) | LAN/remote collaboration, permissions, resource center, audit | Multi-user & remote work |
| [docs/剪辑工作台联动说明.md](docs/剪辑工作台联动说明.md) | Editing workbench & pipeline integration, editing Agent | Use editing capabilities |
| [docs/依赖清单.md](docs/依赖清单.md) | Dependency declarations for the three systems, platform adaptation, install entries | Dependency management |
| [docs/快速开始.md](docs/快速开始.md) | Set up a working environment from scratch | First-time install |

## Common Scripts

| Script | Purpose |
| --- | --- |
| `install.bat` / `install.sh` | Cross-platform install (Python/deps/third-party extensions) |
| `start.bat` / `start.sh` | One-click start: frontend dev server (11003) + all backend services |
| `start-prod.bat` / `start-prod.sh` | Production start: no Vite; frontend served same-origin from `frontend/dist` |
| `backend.bat` | Start the main backend alone |
| `activate-venv.bat` / `activate-venv.sh` | Enter `backend\venv312` |

## License & Credits

- Workflow editor built on `@xyflow/react`; integrates open-source components social-auto-upload-web-ui, QM-LocalRouter, Cutia, Pi, VoiceForge (see their licenses under `thirdparty/`).
