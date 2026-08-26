# Agent 能力索引（Capability Index）

本文件是 agent 理解 VideoLingoFlow（中文：流连视听）项目的总入口。它描述系统的**运行架构、服务端口、内置能力、关键代码入口**，并指向更详细的子文档。agent 在执行任何任务前，应先读本文，再按需跳转到对应的子文档。

> **重要前提**：本文档描述的是**当前代码实现的真实状态**，而非历史版本。如果某处与代码不符，以代码为准，并回写本文档。

---

## 0. 一句话定位

VideoLingoFlow（中文：流连视听）是一个**本地优先（local-first）的视频翻译 / 配音 / 发布一体化工作站**：用户输入一个视频（本地文件或平台链接），系统通过可视化**工作流（workflow）**编排一系列**节点（node）**，完成下载 → 语音识别 → 翻译 → 字幕 → 配音 → 合成 → 发布等步骤，并可在前端对工作流全程可视化监控与人工干预。

---

## 1. 运行架构（必读）

系统**不是**一个单进程 FastAPI 服务，而是一个由 **`backend/manager.py` 统一编排的多进程套件**。直接双击 `*.bat` 或 `python backend/main.py` 只会启动主后端，缺少 manager 守护、GPU 服务、Celery、Redis 等依赖，绝大多数任务会失败。

### 1.1 各服务与端口（来自 `backend/manager.py`）

| 服务 | 进程入口 | 端口 | 说明 |
|---|---|---|---|
| **Manager（管理守护进程）** | `backend/manager.py` | **18001** | 启动/停止/看门狗/重启其它所有服务；提供 `/manager/*` HTTP 控制接口 |
| **主后端（Main Backend）** | `backend/main.py`（uvicorn `backend.main:app`） | **11001** | FastAPI，承载工作流、节点、任务、文件、ASR、TTS、GPU 代理等全部业务 API |
| **Celery Worker（控制平面）** | `backend/control_plane/celery_runtime.py` | （broker Redis 6379） | 异步任务执行，队列：`videolingo_cpu` / `videolingo_gpu` / `videolingo_llm` / `videolingo_tts` / `videolingo_io` |
| **GPU 服务层（可选）** | `backend/gpu_service/manager.py` | 无独立端口（经 Redis 6379 协调） | 仅在 `GPU_SERVICE_ENABLED=1` 时启动；负责 ASR / 分离类节点的显存 lane 调度 |
| **Redis** | `redis-server.exe`（项目自带） | **6379** | Celery broker 与 GPU 服务的共享状态/队列后端 |
| **LLM Router 代理** | `backend/llm_router`（如存在） | **8800** | OpenAI 兼容代理，供客户端把 model 填为"路由策略名" |
| **Cutia（剪辑）** | `backend/...`（cutia） | **4100** | 视频剪辑/合成相关服务 |
| **Social 后端** | `social-auto-upload-web-ui`（Flask+Waitress） | **5409** | 社交平台自动发布后端 |
| **Social 前端（静态）** | 构建产物静态服务 | **5173** | 社交发布 UI（注意：不是主前端 dev server） |
| **Social MCP** | `npm start` | **5410** | 社交发布 MCP 服务器 |
| **主前端（dev）** | `frontend/`（Vite） | 默认 Vite 端口（通常 5173，若冲突自动 +1） | React 前端；Vite 代理 `/api`→11001、`/ws`→11001（ws）、社交相关→对应端口 |

> **端口记忆要点**：
> - 主后端业务 API = **11001**（不是 8000）
> - Manager 控制面 = **18001**
> - 前端 dev server 的 Vite 代理目标 = **11001**
> - GPU 服务**没有 HTTP 端口**，它通过 Redis（6379）与主后端通信

### 1.2 启动方式（规范）

```bash
# 开发/生产统一入口（推荐）：
backend.bat            # Windows 双击
# 或
python backend/manager.py            # 默认 manager=18001, backend=11001
python backend/manager.py 18001 11001   # 自定义端口
```

`manager.py` 会：准备 venv 环境、启动 Redis、启动 GPU 服务（若启用）、启动 Celery worker、启动主后端 uvicorn、按需启动 social / cutia / llm-router，并维持看门狗自动重启。

### 1.3 任务执行链路（逻辑层）

```
用户在前端创建工作流 → POST /api/run-task
  → ControlPlane 记录 Task/TaskNode（SQLite: data/control-plane.db）
  → ThreadScheduler / Celery 调度各节点
  → 每个节点 = 一个 Step 实例（backend/steps/s_*.py），按依赖拓扑顺序执行
  → GPU 类节点（asr/vocal_separation/track_separation）若启用 GPU 服务则交由 lane 调度
  → 产物写入 tasks/<task_id>/{cache,output}
  → 进度经 /ws WebSocket 实时推回前端
```

---

## 2. 关键代码入口（agent 改代码时优先看这里）

| 关注点 | 入口文件 |
|---|---|
| 服务编排/端口/启动 | `backend/manager.py` |
| HTTP API 路由 | `backend/main.py` + `backend/api/*.py` |
| 工作流运行引擎 | `backend/control_plane/workflow_runtime.py` |
| 线程调度器 | `backend/engine/thread_scheduler.py` |
| 异步任务（Celery） | `backend/control_plane/celery_runtime.py`、`runtime.py` |
| 任务记录与目录 | `backend/engine/task_recorder.py` |
| 节点注册表 | `backend/steps/step_registry.py` |
| 节点类型定义（前端展示） | `backend/config/builtin_node_types.py` |
| 步骤基类 | `backend/steps/base_step.py`（`BaseStep`） |
| GPU 服务层 | `backend/gpu_service/*`（`manager.py`/`lane.py`/`jobs.py`/`config.py`/`client.py`） |
| 自定义节点运行时 | `backend/control_plane/custom_node_runtime.py` |
| 前端工作流编辑器 | `frontend/src/components/workflow/*` |
| 配置/模型仓库 | `data/workspace/pi-agent-config/models-store.json`、`backend/config/*.json` |

---

## 3. 内置能力清单（节点 = 能力单元）

系统由**节点（node）**组成工作流。每个节点在 `builtin_node_types.py` 定义展示元数据（名称/分类/输入/输出/表单/执行域），在 `step_registry.py` 映射到具体的 `S_*` Step 类。

**节点总数随版本增长，当前约 57 个**（不要硬编码"41 个"这类旧数字）。完整定义以 `builtin_node_types.py` 为准。按职能分组（类名 ↔ Step 映射见 `step_registry.py`）：

### 3.1 输入 / 获取
- `platform_download`：从平台链接下载视频
- `search_video`：搜索视频
- `media_to_url`：本地媒体转可访问 URL

### 3.2 语音识别（ASR）
- `asr`：语音识别（WhisperX，GPU 服务接管）
- `s02_asr`：ASR 第二阶段/细粒度
- `demucs_separation`：人声/伴奏分离（usic 分离）
- `vocal_separation`：人声分离（GPU 服务接管）
- `track_separation`：音轨分离（GPU 服务接管）
- `audio_transcode`：音频转码

### 3.3 字幕 / 文本处理
- `sentence_split`：断句
- `subtitle_recognition`：字幕识别（OCR）
- `subtitle_position_search`：字幕位置检测
- `subtitle_translate`：字幕翻译
- `subtitle_theme`：字幕主题/风格
- `reorder_subtitles`：字幕重排
- `subtitle_editor`：字幕编辑
- `json_visual_editor`：JSON 可视化编辑
- `text_editor`：文本编辑

### 3.4 翻译 / LLM
- `summarize`：摘要
- `translate`：翻译
- `llm_request`：通用 LLM 调用
- `text_optimize`：文本润色
- `term_extract`：术语抽取
- `glossary`：术语表
- `term_translate`：术语翻译

### 3.5 配音（TTS）与说话人
- `tts`：文本转语音（占用 tts 资源令牌）
- `dub_task`：配音任务（占用 tts 资源令牌）
- `dub_video`：视频配音
- `speaker_recognition`：说话人识别（pyannote）
- `align_dub`：配音对齐
- `subtitle_matcher`：字幕匹配
- `vc`：变声
- `tts_srt`：字幕驱动 TTS
- `tts_merge`：TTS 合并
- `moss_tts`：Moss TTS
- `tts_interface`：TTS 接口配置

### 3.6 媒体合成 / 剪辑
- `merge_audio_video`：音视频合并
- `video_compose`：视频合成
- `video_transition`：转场
- `watermark`：水印
- `lcwr_watermark_removal`：LCWR 去水印
- `online_watermark_removal`：在线去水印
- `video_enhance`：画质增强
- `video_ocr`：视频 OCR
- `format_convert`：格式转换
- `video_segment`：视频切片
- `video_concat`：视频拼接
- `video_crop`：裁剪
- `video_speed`：倍速
- `add_bgm`：添加背景音乐

### 3.7 视觉 / AIGC
- `subtitle_detect`：字幕检测
- `text2video`：文生视频（AIGC）
- `image2video`：图生视频
- `image_gen`：图像生成

### 3.8 发布 / 社交
- `publish`：发布
- `social_publish`：社交发布
- `xiaopai_publish`：小派发布

### 3.9 集成 / 工具
- `http_request`：HTTP 请求（进程隔离）
- `email`：邮件
- `qm_virtual_mailbox`：企业邮虚拟邮箱
- `code_runner`：代码执行
- `skill`：技能节点
- `web_crawler`：网页爬取
- `browser`：浏览器操作
- `search`：搜索
- `agent`：智能体（pi_agent）
- `mcp`：MCP 工具
- `mcp_install`：MCP 安装

### 3.10 控制流 / 工作流
- `workflow`：子工作流
- `condition`：条件分支
- `loop`：循环
- `merge`：合并
- `delay`：延时
- `run_wait`：运行等待
- `comment`：注释
- `input`：输入变量
- `output`：输出变量

> **Frontend-only 节点**（无后端 Step，仅前端展示/预览）：
> `video_preview`、`image_preview`

> **进程隔离节点**（`PROCESS_ISOLATED_NODE_TYPES`，在独立子进程运行以释放 GIL）：
> `asr`、`vocal_separation`、`track_separation`、`http_request`

### 3.11 执行域（execution_domain）

节点类型定义中每个节点带 `execution_domain` 字段，取值：
- **`thread`**：在线程池中执行（默认，绝大多数节点）
- **`process`**：在独立子进程中执行（重型/长时推理，避免阻塞 uvicorn 事件循环）

> 注意：**没有 `gpu` 执行域**。GPU 计算由"GPU 服务层"接管（见 `gpu-service.md`），节点本身仍声明为 `process` 或 `thread`，运行时根据 `GPU_SERVICE_MANAGED_NODE_TYPES` 决定把 ASR/分离类任务交给 GPU lane。

---

## 4. 资源与并发模型（重要）

工作流运行时按节点类型分配**资源令牌**，避免本地资源被压垮（`workflow_runtime.py`）：

- `RESOURCE_BY_NODE_TYPE`：`asr`/`vocal_separation`/`track_separation` → `gpu` 令牌；`tts`/`dub_task` → `tts` 令牌
- `RESOURCE_FREE_NODE_TYPES`：纯网络/API 调用节点（`llm_request`、`summarize`、`translate`、`sentence_split`、`http_request`、`platform_download`）不占本地计算令牌，可多任务并发
- `GPU_SERVICE_MANAGED_NODE_TYPES`：`{asr, vocal_separation, track_separation}` 启用 GPU 服务后，显存调度交给服务层，worker 侧不再扣 gpu 令牌（避免双重限流）

`ThreadScheduler` 默认 `max_workers=3`，`request_cancel` 可终止任务及其子进程。

---

## 5. 数据 / 文件布局

- 任务目录：`tasks/<task_id>/`，含 `task.json`（任务元数据/节点状态）、`cache/`、`output/`
- 控制平面数据库：`data/control-plane.db`（SQLite；Alembic 迁移）
- 模型缓存：`_model_cache/`、`data/workspace/pi-agent-config/models-store.json`
- 工作流模板：`backend/config/workflows/*.json`
- 日志：`logs/`
- 更多见 `file-management.md`

---

## 6. 子文档导航

| 文档 | 用途 |
|---|---|
| `task-execution.md` | 如何启动系统、创建/运行/监控任务、任务目录结构 |
| `workflow-orchestration.md` | 工作流 JSON 结构、节点连接、运行引擎、内置工作流 |
| `node-creation.md` | 新增一个内置/自定义节点的完整规范（前后端） |
| `file-management.md` | 产物命名约定、task.json 字段、文件读写工具 |
| `gpu-service.md` | GPU 服务层（lane 调度、显存管理、开关与配置） |
| `publishing.md` | 社交/平台发布节点与配置 |
| `skill-mcp-install.md` | 技能节点、MCP 安装节点、外部工具集成 |

---

## 7. Agent 操作红线（必读）

1. **不要**用 `python backend/main.py` 单独启动来"验证任务"——缺依赖会失败，应走 `manager.py` 或对应 `*.bat`。
2. **端口**：调用业务 API 用 `11001`；调用 Manager 用 `18001`；**不要**假设 8000。
3. **加节点**：必须同时改 `builtin_node_types.py`（展示）与 `step_registry.py`（映射），否则节点不可运行。详见 `node-creation.md`。
4. **GPU 节点**：不要让 worker 与 GPU 服务双重限流；遵循 `GPU_SERVICE_MANAGED_NODE_TYPES` 约定。
5. **任务产物**：文件名遵循 `{base}_{node_id}{ext}` 约定，用 `find_artifact()` 反查，详见 `file-management.md`。
6. **改动后**：关注 `read_lints` / 类型检查，保持 `backend/requirements.txt` 与 `data/workspace/pi-agent-config/models-store.json` 一致。
