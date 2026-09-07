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
用户在前端创建工作流 → POST /api/workflows/{wf_id}/execute
  → ControlPlane（workflow_runtime.submit_workflow）记录 Task/TaskNode（SQLite: data/control-plane.db）
  → 状态机（control_plane/runtime.py）按依赖拓扑调度，每个节点派发为 Celery 任务
  → 每个节点 = 一个 Step 实例（backend/steps/s_*.py），worker 内按 execution_domain 执行（thread 同进程 / process 子进程）
  → GPU 类节点（asr/vocal_separation/track_separation）若启用 GPU 服务则交由 lane 调度
  → 产物写入 control_plane_workspaces/<task_id>/{cache,output}
  → 进度经 /ws/tasks/{task_id} WebSocket 实时推回前端
```

---

## 2. 关键代码入口（agent 改代码时优先看这里）

| 关注点 | 入口文件 |
|---|---|
| 服务编排/端口/启动 | `backend/manager.py` |
| HTTP API 路由 | `backend/main.py` + `backend/api/*.py` |
| 工作流运行引擎 | `backend/control_plane/workflow_runtime.py` |
| 线程调度器（遗留路径） | `backend/engine/thread_scheduler.py`（仅旧线程池路径；控制平面执行走 Celery） |
| 异步任务（Celery） | `backend/control_plane/celery_runtime.py`、`runtime.py` |
| 任务/工作区记录 | `backend/control_plane/workflow_runtime.py`（写 task.json 到 `control_plane_workspaces/<task_id>/`） |
| 节点注册表 | `backend/steps/step_registry.py` |
| 节点类型定义（前端展示） | `backend/config/builtin_node_types.py` |
| 节点定义校验（分类/端口/字段白名单） | `backend/config/node_schema.py` |
| 自定义节点定义与运行时 | `backend/config/node_types/*.json` + `backend/control_plane/custom_node_runtime.py` |
| 步骤基类 | `backend/steps/base_step.py`（`BaseStep`） |
| 前端节点兜底表（API 不可用时） | `frontend/src/lib/fallbackNodeTypes.ts` |
| GPU 服务层 | `backend/gpu_service/*`（`manager.py`/`lane.py`/`jobs.py`/`config.py`/`client.py`） |
| 自定义节点运行时 | `backend/control_plane/custom_node_runtime.py` |
| 前端工作流编辑器 | `frontend/src/components/workflow/*` |
| 配置/模型仓库 | `data/workspace/pi-agent-config/models-store.json`、`backend/config/*.json` |

---

## 3. 内置能力清单（节点 = 能力单元）

系统由**节点（node）**组成工作流。每个节点在 `builtin_node_types.py` 定义展示元数据（名称/分类/输入/输出/表单/执行域），在 `step_registry.py` 映射到具体的 `S_*` Step 类。

**当前内置节点 108 个**（另有 3 个自定义节点：`groupnode_mtbj91n4`、`groupnode_mtbj9s8i`、`hyperframe_render`；合计 111 个，数量随版本增长，不要硬编码旧数字）。完整定义以 `builtin_node_types.py` 为准；**权威清单见 `docs/node_catalog.md`**（按分组表格罗列 id / 名称 / 描述 / 执行域 / 输入 / 输出接口，含自定义节点，总计 111 个），新增或修改节点后在 `PROJECT_ROOT` 下运行 `python scripts/generate_node_catalog.py` 重新生成。

下面按 `category`（后端白名单值）分组罗列**真实存在**的节点（`·子进程` 表示 `execution_domain="process"`；`·未注册` 表示尚未注册进 `step_registry._STEPS`）：

#### 输入输出（`io`）
- `archive_artifacts`：产物文件归档
- `file_load`：文件加载
- `input`：输入 ·未注册
- `output`：输出
- `text_input`：文本输入框

#### 预览（`preview`）
- `image_compare`：图片对比
- `image_preview`：图片预览器
- `video_preview`：视频预览器

#### 音频处理（`audio`）
- `audio_cut_by_subtitle`：按字幕切割音频
- `audio_denoise`：降噪
- `audio_transcode`：音频转码
- `extract_audio`：音频分离
- `merge_audio`：音视频配音对齐
- `merge_dub`：配音拼接
- `track_mix`：音轨混流
- `track_separation`：音轨分离 ·子进程
- `vocal_separation`：人声分离 ·子进程

#### 视频处理（`video`）
- `cutia`：Cutia 交互剪辑
- `lcwr_watermark_removal`：LCWR 去水印 ·子进程
- `merge_dub_video`：音视频合成
- `merge_sub_video`：字幕烧录
- `online_watermark_removal`：在线去水印去字幕
- `subtitle_position_search`：OCR 字幕查找
- `subtitle_recognition`：OCR 字幕识别
- `video_cut_by_subtitle`：按字幕切割视频
- `video_frame_extract`：视频抽帧
- `video_region_composite`：视频区域贴片
- `video_region_crop`：视频截取区域
- `video_scale`：视频缩放
- `video_split`：视频切割
- `video_transcode`：视频转码
- `watermark`：水印添加

#### AI 生成（`ai_gen`）
- `ai_video_gen`：AI 生视频
- `cover`：AI 封面设计
- `image_gen`：AI 生图 ·子进程
- `image_mask`：图片蒙版
- `llm_request`：通用 LLM 请求 ·子进程
- `seedance_autovideo` / `seedance_flf2video` / `seedance_img2video` / `seedance_txt2video`：即梦生视频系列 ·子进程
- `seedream_fusion` / `seedream_grid` / `seedream_img2img` / `seedream_layer` / `seedream_txt2img` / `seedream_websearch`：Seedream 生图系列 ·子进程
- `tts`：语音合成 ·子进程

#### 翻译相关（`translation`）
- `ai_punctuate`：AI 标点补全
- `ai_subtitle_correct`：AI 字幕纠错
- `asr`：语音识别 ·子进程
- `asr_postprocess`：ASR 后处理 ·子进程
- `asr_recognize`：ASR 识别 ·子进程
- `asr_result_validate`：ASR 结果校验
- `dub_task`：生成配音任务
- `sentence_preprocess`：断句预处理
- `sentence_split`：句子分割
- `subtitle_align`：译文断句和双语对齐
- `subtitle_gen`：字幕生成
- `summarize`：内容总结 ·子进程
- `translate`：逐句翻译 ·子进程
- `translate_task_name`：翻译项目名称

#### 流程控制（`flow_control`）
- `loop`：循环 ·未注册
- `run_wait`：运行等待
- `timed_delay`：定时执行

#### 网络请求（`network_request`）
- `http_request`：网络请求 ·子进程
- `media_to_url`：媒体转链接
- `platform_download`：平台视频下载 ·子进程
- `qm_virtual_mailbox`：QM 虚拟邮箱

#### AIGC 流程链（`aigc`）
- `aigc_comfyui`：ComfyUI 生图
- `aigc_jimeng`：即梦 CLI 生成 ·子进程
- `aigc_runninghub`：RunningHub 生成 ·子进程
- `agi_project`：项目立项·剧本创作（起始节点：创建项目 + LLM 故事骨架，creation_id 贯穿下游）
- `agi_character`：人物资产创作（LLM 生成人物设定，发布公共角色库 + 多视角图）
- `agi_voice`：人物音色生产 ·子进程（按 voice_design 合成音色样本→vf 引用→绑定人物 voice_ref）
- `agi_scene`：场景资产创作 ·子进程（场景概念图）
- `agi_chapter`：章节剧本（LLM 生成章节）
- `agi_shot`：分镜剧本（LLM 生成分镜）
- `agi_shot_frames`：分镜首尾帧 ·子进程（首/尾帧图，整章批处理，角色/场景参考图注入）
- `agi_shot_video`：分镜视频制作 ·子进程（图生视频，整章批处理，画面+运镜提示词）
- `agi_shot_dub`：分镜配音 ·子进程（逐句 TTS 音色克隆 + 拼接，整章批处理，同步产出 SRT）
- `agi_shot_export`：分镜导出 ·子进程（视频+配音/BGM/音效混流，可烧录字幕，整章批处理）
- `agi_chapter_export`：章节导出 ·子进程（分镜成片拼接）
- `image_grid_split`：图片宫格切割

#### 素材库（`asset`，均 ·子进程）
- `audio_asset_library`、`image_asset_library`、`video_asset_library`、`character_asset_library`、`voice_asset_library`、`voice_character`

#### 智能体（`agent`）
- `editor_agent`：剪辑 AI Agent ·子进程
- `pi_agent`：小 Pi 通用智能体 ·子进程

#### 工具（`utility`）
- `json_editor`：JSON 编辑
- `json_to_text`：JSON 转文本
- `json_visual_editor`：JSON 可视化编辑
- `output_merge_list`：输出合并为列表
- `srt_to_json`：SRT 字幕转 JSON
- `srt_to_text`：SRT 转文本
- `subtitle_editor`：字幕编辑
- `text_editor`：文本编辑
- `video_publish`：视频发布 ·子进程

#### 文件操作（`file`）
- `file_rename`：文件改名
- `path_to_title`：路径转标题
- `resolve_path`：取文件路径

#### HyperFrames（`hyperframes`，均 ·子进程）
- `hyperframes_creative`：创意（产出 `BRIEF.md`）
- `hyperframes_render`：按 `BRIEF.md` 渲染成片
- `hyperframes_cli`：HyperFrames CLI 工具
- `hyperframes_agent`：复合节点，驱动小 Pi 跑完「创意 → 渲染」
- `hyperframe_render`（自定义节点）：单文件 HTML 直渲染，不经 `BRIEF.md`

> **Frontend-only / 透传节点**（无实际后端逻辑，映射到 `PassthroughStep`）：`video_preview`、`image_preview`、`image_compare`。

> **子进程隔离节点**：控制平面按 `execution_domain="process"` 判定，当前共 44 个（上面标注 `·子进程` 的那些；数量随版本增长，以 `docs/node_catalog.md` 为准）。
> 旧 `backend/engine/thread_scheduler.py` 里的 `PROCESS_ISOLATED_NODE_TYPES = {asr, vocal_separation, track_separation, http_request}` 属于**遗留线程池路径**，不是控制平面的判定依据。

### 3.11 执行域（execution_domain）

节点类型定义中每个节点带 `execution_domain` 字段，**运行时只认两种取值**（`workflow_runtime._execution_domain()`）：
- **`thread`**：在线程池中执行（默认，绝大多数节点）
- **`process`**：在独立子进程中执行（`python -m backend.control_plane.step_worker <args.json>`），用于重型/长时推理，可硬停止

优先级：节点 `data.config.execution_domain` > 环境变量 `PROCESS_DOMAIN_EXTRA` > 内置类型定义。

> 历史遗留：`ai_punctuate`、`ai_subtitle_correct` 写着 `execution_domain="llm"`，运行时等价于 `thread`，**新节点不要使用该值**。
> 自定义节点不受此字段影响（走 `custom_node_runtime`）。
> **没有 `gpu` 执行域**：GPU 计算由 GPU 服务层接管（见 `gpu-service.md`），节点仍声明 `process`/`thread`，运行时按 `GPU_SERVICE_MANAGED_NODE_TYPES` 交给 GPU lane。

---

## 4. 资源与并发模型（重要）

工作流运行时按节点类型分配**资源令牌**，避免本地资源被压垮（`workflow_runtime.py`）：

- `RESOURCE_BY_NODE_TYPE`：`asr`/`vocal_separation`/`track_separation` → `gpu` 令牌；`tts`/`dub_task` → `tts` 令牌
- `RESOURCE_FREE_NODE_TYPES`：纯网络/API 调用节点（`llm_request`、`summarize`、`translate`、`sentence_split`、`http_request`、`platform_download`）以及循环容器 `loop` 不占本地计算令牌，可多任务并发
- `GPU_SERVICE_MANAGED_NODE_TYPES`：`{asr, vocal_separation, track_separation}` 启用 GPU 服务后，显存调度交给服务层，worker 侧不再扣 gpu 令牌（避免双重限流）

并发由 **Celery worker 进程数 + 资源令牌** 共同决定（`ThreadScheduler` 的 `max_workers=3` 属于遗留 engine 线程池路径，不在当前控制平面执行链路中）。`request_cancel` 可终止任务及其子进程。

---

## 5. 数据 / 文件布局

- 任务目录：`control_plane_workspaces/<task_id>/`，含 `task.json`（任务元数据/节点状态，兼容副本）、`cache/`、`output/`（权威状态在 `data/control-plane.db`）
- 控制平面数据库：`data/control-plane.db`（SQLite；Alembic 迁移）
- 素材库：`cp_images`/`cp_videos`/`cp_characters`/`cp_creation_assets` 在控制面库；音色/音频素材在 `voiceforge_data/voiceforge.db`（查询方式见 `material-search.md`）
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
| `material-search.md` | 本地素材库（图片/视频/角色/创作资产/音色/音频）结构与查询：`local-material-search` 技能、Python/CLI 查询接口、路径与 `vf:` 引用还原约定 |
| `skill-mcp-install.md` | 技能节点、MCP 安装节点、外部工具集成 |
| `hyperframes.md` | HyperFrames 视频创作节点（创意 → 渲染）、技能源码位置与排错 |

---

## 7. Agent 操作红线（必读）

1. **不要**用 `python backend/main.py` 单独启动来"验证任务"——缺依赖会失败，应走 `manager.py` 或对应 `*.bat`。
2. **端口**：调用业务 API 用 `11001`；调用 Manager 用 `18001`；**不要**假设 8000。
3. **加节点**：必须同时改 `builtin_node_types.py`（展示）与 `step_registry.py`（映射），否则节点不可运行。详见 `node-creation.md`。
   - `category`、端口 `type`、`configFields.type` 必须取自 `node_schema.py` 的白名单（自定义节点走 API 会被强校验）；
   - `execution_domain` 只有 `thread` / `process` 两种有效值，不要写 `llm` / `gpu`；
   - 建议同步 `frontend/src/lib/fallbackNodeTypes.ts`。
4. **不要臆造节点 id**：使用节点前先在 `docs/node_catalog.md` 或 `builtin_node_types.py` 核对，历史文档中曾出现大量不存在的 id。
5. **GPU 节点**：不要让 worker 与 GPU 服务双重限流；遵循 `GPU_SERVICE_MANAGED_NODE_TYPES` 约定。
6. **任务产物**：文件名遵循 `{base}_{node_id}{ext}` 约定，用 `find_artifact()` 反查，详见 `file-management.md`。
7. **改动后**：关注 `read_lints` / 类型检查，保持 `backend/requirements.txt` 与 `data/workspace/pi-agent-config/models-store.json` 一致。
