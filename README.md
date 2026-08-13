# VideoLingoFlow

面向桌面/本地部署的**一站式 AI 视频创作与出海本地化平台**。基于节点式工作流，覆盖视频字幕、翻译、配音、剪辑、AI 编辑、批量生产、多平台发布，并内置**多人协作、共享社区、项目专用 AI 助手（小 Pi）**三大协作能力——一个人、一台电脑，就能把一部视频变成多语言、多平台、带配音带字幕的成品。

## 功能特性

### 核心生产链路

- **节点式工作流**：基于 `@xyflow/react` 的可视化 DAG 编排，40+ 内置节点（输入/下载/音频/ASR/翻译/字幕/配音/合成/生图/发布），支持自定义节点（导入、字段级规则校验、端口语义连线），工作流可保存、复用、批量重跑。
- **ASR 语音识别**：多引擎可选——WhisperX、FunASR（SenseVoice/MiMo）、Qwen3-ASR、ElevenLabs 等，支持热词、说话人切分。
- **TTS 语音合成**：Edge-TTS 免费自然；晴沐配音谷（VoiceForge）支持音色克隆、声音资产库、批量合成、情绪标签。
- **视频剪辑**：内置 Cutia 编辑器（端口 4100）与剪辑工作台，节点级剪辑 AI Agent 可接收文字指令。
- **批量生产**：批量工作台一次导入多条素材、多任务并行调度、限流与失败重试，单条视频成本摊薄到接近零。
- **AI 能力**：LLM 翻译/反思/总结/标题生成，术语表统一译法；集成本地大模型路由器（LLM Router，多 Provider 多策略）。
- **多平台发布**：集成 Social 模块（抖音/B 站/小红书/YouTube/TikTok 等），标题、标签、封面一次配好，支持定时发布。

### 三大协作能力

- **多人协作**：基于控制平面的用户/角色/项目权限体系 + WebSocket 实时协作。支持局域网模式（LAN）与远程网络协作（Remote Mode，配 Cloudflare Tunnel），成员申请审批、项目级资源中心（素材/产物上传下载）、审计日志。
- **共享社区**：把自定义**节点**与**工作流**打包分享到云端社区（Cloudflare Worker + R2 + D1），或从社区导入别人分享的资源，一键复用成熟流程。
- **项目专用 AI 助手「小 Pi」**：内嵌于工作台的智能体，可指定六种角色（通用/节点创建/工作流编排/任务执行/文件整理/作品发布），流式对话、会话历史留存、支持工具调用，帮助完成编排、排查、发布准备。

### 平台底座

- **控制平面（Control Plane）**：FastAPI + SQLite + Redis/Celery 的任务调度与运行时——任务生命周期管理、节点级产物清理、资源队列（GPU/TTS/LLM/IO）限流、健康检查、Prometheus 指标、备份恢复、Alembic 迁移。
- **监控运维**：实时日志（rich 格式化 + 后台日志页）、进程管理器状态面板（Manager 端口 18001）、一键重启各服务。
- **本地优先**：数据、素材、模型缓存全部落本地（`_model_cache/`），不依赖订阅制云端服务，长期成本可控、商业素材不外泄。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | Python 3.12、FastAPI、Uvicorn、SQLAlchemy、Alembic、Celery |
| 前端 | React 18、Vite、TypeScript、Tailwind CSS、zustand、@xyflow/react |
| 任务队列 | Celery + Redis（`--pool=threads`，方案 C 子进程隔离执行） |
| 数据库 | SQLite（本地 `data/control-plane.db`）/ PostgreSQL（Docker 集群部署） |
| AI/ML | WhisperX、FunASR、Edge-TTS、Qwen/多模型 LLM、demucs、FFmpeg |
| 云服务 | Cloudflare Worker/R2/D1（共享社区）、Cloudflare Tunnel（远程协作） |

## 目录结构

```text
VideoLingoFlow/
├── backend/                  # 后端（FastAPI 主应用，端口 11001）
│   ├── api/                  # 全部 REST/WS 路由（见 docs/项目目录功能说明.md）
│   ├── control_plane/        # 控制平面：DB/模型/运行时/任务调度/Celery/安全
│   ├── engine/               # 执行引擎：批量执行器、步骤流水线、任务管理
│   ├── steps/                # 40+ 节点执行步骤（s_*.py，继承 BaseStep）
│   ├── config/               # 内置节点定义、工作流文件、接口配置
│   ├── voiceforge/           # 晴沐配音谷（独立数据库 + Celery 任务）
│   ├── aigc/                 # AIGC 服务（ComfyUI/即梦/RunningHub）
│   ├── publish/              # 多平台发布（Social MCP 客户端）
│   ├── pi_rpc/               # 小 Pi 智能体桥接（会话管理、RPC 客户端）
│   ├── editor/               # 剪辑工作台 + 剪辑 AI Agent
│   ├── llm/ asr/ tts/ imagegen/ separation/  # 各能力域
│   ├── main.py               # FastAPI 入口
│   ├── manager.py            # 进程管理器（端口 18001）
│   └── venv312/              # Python 3.12 虚拟环境
├── frontend/                 # 前端（React + Vite，开发端口 11003）
│   ├── src/pages/            # 页面：工作流编排/批量/历史/多人协作/社区/配音谷等
│   ├── src/components/       # 组件（workflow/batch/collaboration/community/agent/…）
│   └── dist/                 # 构建产物（由后端同源托管）
├── data/                     # 运行时数据（control-plane.db、redis/）
├── control_plane_workspaces/ # 任务工作区（{task_id}/cache、output、workflow.json、task.json）
├── docs/                     # 知识库文档（智能体与开发者指南，见下方索引）
├── deploy/                   # Docker 集群部署（docker-compose、nginx、TLS）
├── cloudflare/               # 共享社区 Worker（src/index.js + wrangler.toml）
├── thirdparty/               # 第三方组件（pi、cutia、social 等）
├── install.bat / install.sh    # 跨平台安装（Python/依赖/第三方扩展）
├── start.bat / start.sh        # 通用一键启动（前端 dev server + Manager + 全部服务，使用系统 CUDA）
└── start-prod.bat / start-prod.sh  # 生产模式一键启动（不启 Vite，前端由后端托管 dist）
```

## 快速开始

### 环境要求

- Windows 10/11（脚本为 `.bat`/PowerShell）
- Python 3.12（或由安装脚本自动下载）
- Node.js ≥ 18
- Redis（Manager 可自动拉起）
- 可选：NVIDIA GPU + CUDA（本地模型推理）

### 1. 首次安装

运行 `install.bat`（Linux/macOS 用 `install.sh`）：自动检查/安装 Python 3.12 与 Node.js、安装后端依赖（PyTorch 三件套按 CUDA 自动选择）、安装第三方扩展。

### 2. 一键启动

双击 `start.bat`（Linux/macOS 运行 `bash start.sh`）。Manager 会执行 Alembic 迁移、初始化配音谷数据库、拉起 Redis 与各服务。前端以 Vite dev server（端口 11003）启动。

**生产模式**：双击 `start-prod.bat`（Linux/macOS 运行 `bash start-prod.sh`）。不启动 Vite dev server，前端构建产物由后端同源托管（`frontend/dist` 已存在则直接复用，`--rebuild` 参数强制重建），访问 `http://127.0.0.1:11001/` 即为生产版前端。

> 正式版脚本**不隔离环境**：直接使用你自己安装的 CUDA。若你使用将 CUDA 运行时打进 `backend\venv312` 的特殊构建，可用本机隔离版 `一键启动.bat`（该文件不随 git 分发）。

| 服务 | 地址 | 端口 |
| --- | --- | --- |
| 进程管理器 | http://127.0.0.1:18001 | 18001 |
| 主后端（API + 前端） | http://127.0.0.1:11001 | 11001 |
| 前端开发服务器 | http://localhost:11003 | 11003 |
| Social 后端 / MCP | http://127.0.0.1:5409 / 5410 | 5409 / 5410 |
| Social 前端 | http://localhost:5173 | 5173 |
| LLM Router | http://127.0.0.1:8800 | 8800 |
| Cutia 编辑器 | http://127.0.0.1:4100 | 4100 |
| Redis | 127.0.0.1:6379 | 6379 |

浏览器访问 http://127.0.0.1:11001/ 进入工作台。

### 3. 健康检查

- 存活：`GET /api/health/live`；就绪：`GET /api/health/ready`（校验 schema、数据目录、Redis、Celery Worker）；指标：`GET /api/metrics`

## 配置说明

- **局域网协作**：复制 `.runtime/local_env.bat.template` 为 `local_env.bat`，设 `VIDEOLINGO_LAN_MODE=1` 后重启 Manager，API 与 Manager 监听 `0.0.0.0`（仅限可信局域网）。
- **远程协作**：在「多人协作」页开启远程模式（配 Cloudflare Tunnel 后公网域名可访问），默认关闭时公网请求被 `RemoteAccessGuard` 拦截。
- **模型缓存**：统一放 `_model_cache/`；`HF_ENDPOINT` 默认 `https://hf-mirror.com`；pip 默认清华镜像。
- **备份恢复**：Manager 停止后，`python scripts/control_plane_backup.py backup/restore`（详见 `deploy/README.md` 与文档）。
- **Docker 集群部署**（PostgreSQL + Redis + MinIO + Nginx）：见 `deploy/README.md`，数据库迁移唯一入口 `alembic upgrade head`。

## 文档索引（docs/ 知识库）

> 这些文档面向**开发者与其他智能体**，改代码前请先阅读对应指南。

| 文档 | 内容 | 适合场景 |
| --- | --- | --- |
| [docs/项目架构.md](docs/项目架构.md) | 整体架构：控制平面、任务生命周期、执行域、通信、部署形态 | 快速理解系统如何运转 |
| [docs/项目目录功能说明.md](docs/项目目录功能说明.md) | 逐目录/逐模块功能说明（后端路由、前端页面、三大新功能） | 定位代码、找到入口 |
| [docs/工作流编排指南.md](docs/工作流编排指南.md) | 工作流 JSON 格式、端口连线规则、节点清单、编排步骤 | 按需求编排工作流 |
| [docs/工作流运行指南.md](docs/工作流运行指南.md) | 任务类型与隔离、执行模式、产物清理、节点执行边界、批量、日志 | 排查执行/清理问题 |
| [docs/节点新建规范指南.md](docs/节点新建规范指南.md) | 新建节点四件套、执行域判定、产物命名、输入注入、Checklist | 新增自定义节点 |
| [docs/接口添加指南.md](docs/接口添加指南.md) | 接口体系（ASR/TTS/生图/分离/AIGC）、数据模型、四件套、新增接口/接口域规范 | 添加或扩展能力接口 |
| [docs/推广文档.md](docs/推广文档.md) | 产品卖点与使用场景（对外推广用） | 介绍/售卖 |
| [docs/BS-RoFormer-Infer.md](docs/BS-RoFormer-Infer.md) | BS-RoFormer 人声分离模型推理说明 | 人声分离配置 |

## 常用脚本

| 脚本 | 用途 |
| --- | --- |
| `install.bat` / `install.sh` | 跨平台安装（Python/依赖/第三方扩展） |
| `start.bat` / `start.sh` | 通用一键启动：前端 dev server（11003）+ 全部后端服务（使用系统 CUDA） |
| `start-prod.bat` / `start-prod.sh` | 生产模式一键启动：不启 Vite，前端由后端同源托管 `frontend/dist`（`--rebuild` 强制重建） |
| `backend.bat` | 单独启动主后端 |
| `activate-venv.bat` / `activate-venv.sh` | 进入 `backend\venv312`（不隔离环境） |

## 许可与致谢

- 工作流编辑器基于 `@xyflow/react`；集成开源组件 social-auto-upload-web-ui、QM-LocalRouter、Cutia、Pi、VoiceForge（许可见 `thirdparty/` 各自目录）。
