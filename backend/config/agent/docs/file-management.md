# 文件整理能力（面向文件整理助手）

> 本能力文档供文件整理助手按需读取。所有路径相对 PROJECT_ROOT。

## 1. 目标与职责

本能力文档服务于 VideoLingoFlow（中文名：流连视听）内置的文件整理助手。用户在以下场景中会寻求文件整理助手的帮助：

- 梳理项目目录结构、解释"某个文件/文件夹是干什么的、放在哪里"；
- 整理素材、字幕、音频、导出产物，规划存放位置与命名规范；
- 清理任务产生的中间产物、释放磁盘空间；
- 归档或导出产物、整理多人协作资源中心中的资产；
- 检查目录中是否存在异常、重复、临时文件。

### 1.1 核心职责

1. **定位与解释**：根据用户描述定位对应目录或文件，说明其用途与归属（以本能力文档第 2 节为准）。
2. **整理与归档**：在可写边界内（见第 5 节）帮助移动、归类、重命名、清理文件。
3. **命名规范**：为素材/字幕/音频/导出产物给出并执行统一命名建议（见第 4 节）。
4. **安全检查**：整理前先识别目录属性（只读/可写/禁止访问），不越界操作。
5. **可回滚**：任何删除/移动操作先说明后果，破坏性操作需用户确认。

### 1.2 不负责的边界

- 不修改业务代码、不增删节点/接口文件（那是节点创建与工作流编排助手的职责）；
- 不直接读写数据库文件（`data/control-plane.db` 等），数据库变更一律走应用功能或备份/恢复脚本；
- 不处理 `backend/auth` 及任何凭据、订阅、授权相关文件；
- 不清理正在运行的任务所属的工作区。

---

## 2. 项目目录总览（各目录用途）

PROJECT_ROOT 是 VideoLingoFlow 的安装根目录（本机示例：`Y:\VideoLingoLc`）。以下为顶层目录与文件。

### 2.1 后端 `backend/`

| 目录/文件 | 用途 | 整理相关要点 |
|---|---|---|
| `backend/api/` | 全部 REST / WebSocket 路由（`tasks.py`、`workflows.py`、`batch.py`、`history.py`、`file_browser.py`、`ws.py` 等） | 代码，只读 |
| `backend/control_plane/` | 控制平面：任务/节点 ORM 模型、任务运行时、安全、资产/检查点、备份恢复 | 代码，只读 |
| `backend/engine/` | 执行引擎：批量执行器、步骤流水线、任务管理、产物检测 | 代码，只读 |
| `backend/steps/` | 40+ 节点执行步骤（`s00_platform_download.py`、`s01_download.py`、`s02_asr.py`、`s06_subtitle_gen.py`、`s09_tts.py`、`s14_output.py` 等） | 代码，只读 |
| `backend/config/` | 配置与定义：`config.yaml`、`builtin_node_types.py`、`workflows/*.json`（全局工作流）、`node_types/{id}.json`（自定义节点）、`subtitle_presets/`、`*_interfaces.json`、`workflow_groups.json` 等 | 配置文件，一般只读；其中 `agent/` 为智能体知识目录 |
| `backend/llm/` `backend/asr/` `backend/tts/` `backend/imagegen/` `backend/separation/` | 各能力域引擎族 | 代码，只读 |
| `backend/voiceforge/` | 晴沐配音谷：独立 DB + 资产/音色/文本处理 + Celery 任务 | 代码，只读；其资产数据见 `data/` 与 `data/assets/` |
| `backend/aigc/` `backend/publish/` `backend/editor/` `backend/pi_rpc/` `backend/auth/` | AIGC 服务、多平台发布、剪辑工作台、小 Pi 桥接、订阅/授权守卫 | 代码，只读；**`backend/auth/` 禁止访问** |
| `backend/utils/` | 工具：ffmpeg 封装、响度、字幕样式、音频分段/变速、视频处理 | 代码，只读 |
| `backend/main.py` `manager.py` `installer.py` `workflow_validation.py` | 入口文件：FastAPI 入口（端口 11001）、进程管理器（18001）、安装脚本、工作流规范化 | 代码，只读 |

### 2.2 前端 `frontend/`

| 目录 | 用途 | 整理相关要点 |
|---|---|---|
| `frontend/src/pages/` | 页面：Workbench、BatchWorkshop、History、SocialPublish、EditingWorkbench、VoiceForge、Settings、llm-router、Collaboration、Logs、Community、About | 代码，只读 |
| `frontend/src/components/` | 组件：`workflow/`、`batch/`、`collaboration/`、`community/`、`agent/`、`settings/`、`task/`、`ui/` 等 | 代码，只读 |
| `frontend/src/api/` | API 客户端（与后端路由一一对应） | 代码，只读 |
| `frontend/src/stores/` `frontend/src/lib/` | zustand 状态、类型与工具 | 代码，只读 |
| `frontend/dist/` | 前端构建产物 | 可整体重建，删除/重建前需确认构建流程 |

### 2.3 数据与运行时目录

| 目录 | 用途 | 整理相关要点 |
|---|---|---|
| `data/` | 运行时数据：`control-plane.db`（SQLite 控制平面库）、`redis/`、`workspace/`、`assets/` | **可写但需谨慎**：数据库文件绝不直接改；`workspace/` 为默认安全工作区；`assets/` 为资源中心资产根（`CONTROL_PLANE_ASSET_ROOT=data/assets`） |
| `data/workspace/` | Pi 会话默认安全工作区，存放生成的素材 | **Pi 助手的主要可写区**，整理任务优先落在这里 |
| `control_plane_workspaces/` | 任务工作区：`{task_id}/cache`（中间产物）、`output`（导出产物）、`workflow.json`、`task.json` | 中间产物与最终产物的核心落位，见第 3 节 |
| `.runtime/` | 本机运行时覆盖配置（`local_env.bat`） | 环境配置，只读，勿改勿删 |
| `_model_cache/` | 模型下载缓存（HF/ModelScope/torch.hub） | 可清理以释放空间，但删除后需重新下载 |

### 2.4 第三方与部署

| 目录 | 用途 | 整理相关要点 |
|---|---|---|
| `thirdparty/` | 第三方组件：`pi`（小 Pi 运行时）、`cutia`（编辑器）、`QM-LocalRouter`、social 等 | 只读，勿动内部文件 |
| `deploy/` | Docker 集群部署（docker-compose/nginx/TLS） | 只读 |
| `cloudflare/` | 共享社区 Worker（`src/index.js` + wrangler.toml + schema.sql） | 只读 |
| `scripts/llmrouter/` | LLM Router 管理脚本 | 脚本，只读 |
| `scripts/control_plane_backup.py` | 控制平面备份脚本 | 备份操作可调用 |

### 2.5 文档与根目录脚本

| 路径 | 用途 | 整理相关要点 |
|---|---|---|
| `docs/` | 项目文档（项目目录功能说明、项目架构、节点新建规范等） | 只读，整理时勿移动 |
| `install.bat` / `install.sh` | 跨平台安装 | 只读 |
| `start.bat` / `start.sh` | 一键启动：前端 + 全部后端服务 | 只读 |
| `backend.bat` | 单独启动主后端 | 只读 |
| `activate-venv.bat` / `activate-venv.sh` | 进入 venv312（不隔离环境） | 只读 |

---

## 3. 素材/字幕/音频/导出产物的整理规范

VideoLingoFlow 的产物由任务驱动产生，**默认落位在任务工作区** `control_plane_workspaces/{task_id}/`。一次典型任务（下载 → ASR → 翻译 → 字幕 → TTS → 合并 → 导出）会在此目录内留下多类文件。

### 3.1 产物类别与默认位置

| 类别 | 典型内容 | 默认位置 |
|---|---|---|
| 源素材 | 平台下载的视频/音频、用户上传的原始素材 | `{task_id}/cache` 或 `data/workspace/`、`data/assets/` |
| 字幕 | ASR 转写结果、对齐后字幕、烧录用字幕（srt/ass 等） | `{task_id}/cache`（中间态） |
| 音频 | 分离的人声/伴奏、TTS 合成音频、混音结果 | `{task_id}/cache`（中间态） |
| 视频中间产物 | 分段视频、合并/压字幕后的视频 | `{task_id}/cache` |
| 导出产物 | 最终成片、封面、发布包 | `{task_id}/output` |

> 依据：`control_plane_workspaces/` 目录约定为 `{task_id}/cache`（中间产物）、`output`（导出产物）、`workflow.json`、`task.json`。

### 3.2 整理原则

1. **任务工作区是"运行时结构"**：`{task_id}/`、`cache/`、`output/` 由任务运行时按约定创建，整理时不要改动它们的相对关系，不要重命名 `{task_id}` 文件夹，否则任务状态与产物关联会失效。
2. **中间产物默认不归档**：`cache/` 中的中间文件（中间字幕、分段音频等）通常不需要保留；任务删除时随任务一并清理。
3. **导出产物按需归档**：`output/` 中的成片如需长期保存，可复制（而非移动）到 `data/workspace/` 或用户指定目录归档。
4. **任务删除走 API**：删除任务及其文件夹应调用 `DELETE /api/tasks/{id}`（后端 `backend/api/tasks.py` 实现"删除任务+文件夹"），不要手工删除 `control_plane_workspaces/{task_id}/` 以免留下孤儿记录。
5. **协作资产走资源中心**：多人协作模式下，需要共享给项目成员的素材/产物应通过资源中心（`backend/api/control_plane_assets.py`）上传到 `data/assets/`，而不是散落在任务工作区。

### 3.3 素材整理规范

- 新素材优先放入 `data/workspace/`（Pi 会话默认安全工作区），避免写入代码目录；
- 供多人协作共享的素材放入 `data/assets/`（资源中心资产根）；
- 单个任务专用素材可留在其任务工作区 `{task_id}/cache`，任务结束后如需保留再归档。

### 3.4 字幕/音频中间产物整理规范

- 字幕、音频属于"可再生成"的中间产物：ASR/TTS 引擎与步骤可重跑，因此**默认不保留，不单独归档**；
- 若用户明确要求保留（如用于人工校对），复制到 `data/workspace/` 下单独命名目录，如 `subtitle_backup/`、`audio_stems/`；
- 烧录样式预设位于 `backend/config/subtitle_presets/`，属配置而非产物，不要混入产物目录。

### 3.5 导出产物整理规范

- 导出成片统一归档到用户指定目录或 `data/workspace/`，建议一次任务一个子目录；
- 归档时保留 `workflow.json` 副本（记录生成链路），便于追溯"这个片子是怎么做出来的"；
- 发布前的成片（多平台发布用）需额外核对命名与合规性，见《作品发布能力》文档。

---

## 4. 命名规范建议

以下规范为**建议**，应用于新建目录与归档文件；已有任务工作区（`{task_id}` 等）的名称是运行时约定，**不得修改**。

### 4.1 任务与工作区

- 任务工作区沿用运行时生成的 `{task_id}`（32 位十六进制），不重命名、不嵌套自定义目录；
- 用户自定义项目/批次名称只体现在 `task.json` 与数据库记录中，不体现在目录名上。

### 4.2 素材

- 格式：`{类别}_{来源/日期}_{描述}.{ext}`，如 `source_platform_20260813_raw.mp4`、`asset_poster.png`；
- 类别建议：`source`（源素材）、`asset`（共享资产）、`temp`（临时）前缀区分。

### 4.3 字幕

- 保留语言与用途信息：`{任务名}_{语言}_{用途}.{ext}`，如 `intro_zh_translated.srt`、`intro_zh_burn.ass`；
- 字幕与对应视频同名同目录，便于播放器自动加载。

### 4.4 音频

- 区分声源与用途：`{任务名}_vocals.wav`、`{任务名}_instrumental.wav`、`{任务名}_tts_zh.wav`、`{任务名}_mix.wav`；
- 混音产物加 `mix`/`final` 后缀，避免与干声混淆。

### 4.5 导出产物

- 建议 `{作品名}_{语言}_{分辨率/质量}_{日期}.{ext}`，如 `mydemo_zh_1080p_20260813.mp4`；
- 封面、简介等附属文件与成片同目录，用 `{作品名}_cover.png`、`{作品名}_desc.txt` 形式配套。

### 4.6 通用规则

- 文件名使用小写字母 + 数字 + `_`/`-`，避免空格与中文标点（跨平台兼容）；
- 不覆盖已有文件：归档前先检查目标是否存在同名文件；
- 避免在文件名中写入密钥、token、完整 URL 等敏感信息。

---

## 5. 文件访问边界（只读/可写/禁止）

整理操作前先判断目标路径归属哪一类。

### 5.1 只读目录（不创建/不修改/不删除）

- `backend/`（全部代码与配置，含 `backend/config/agent/` 智能体知识目录）
- `frontend/src/`、`frontend/public/`
- `docs/`
- `thirdparty/`、`deploy/`、`cloudflare/`
- `scripts/`
- `.runtime/`（本机运行时配置 `local_env.bat`）
- 根目录脚本与配置文件（`install.bat`、`start.bat`、`activate-venv.bat` 等）

### 5.2 可写但需谨慎

| 路径 | 允许的整理操作 | 禁止操作 |
|---|---|---|
| `data/workspace/` | 创建归档目录、存放/移动/重命名素材与产物 | 删除用户未确认的既有内容 |
| `data/assets/` | 经资源中心管理共享资产 | 直接增删（应走应用接口，避免与数据库记录不一致） |
| `control_plane_workspaces/{task_id}/` | 查看产物、复制产物归档 | 重命名目录、运行中删除、手工删任务文件夹（用 API） |
| `data/`（数据库） | 只读查看 | 直接修改/删除 `control-plane.db`；备份用 `scripts/control_plane_backup.py` |
| `_model_cache/` | 清理以释放空间 | 用户未确认时删除（会触发重新下载） |
| `frontend/dist/` | 作为构建产物可重建 | 运行中删除 |

### 5.3 禁止访问（拒绝）

- `backend/auth/`：订阅/授权守卫相关，**任何情况不得读取或改动**；
- 任何包含凭据、密钥、会话令牌、订阅/授权/支付逻辑的文件（如接口配置中的敏感字段）——不读取、不展示、不搬运；
- 运行时路径策略（黑名单）中列出的路径：不得通过 shell、符号链接或间接方式绕过。

### 5.4 遵守运行时路径策略

- 所有路径必须相对 PROJECT_ROOT 解析，且落在上述允许边界内；
- 用户要求操作边界外路径时，先说明边界并请求明确授权；
- 文件整理默认只影响用户工作产物，不触碰代码、配置、数据库与第三方组件。

---

## 6. 常见整理场景与步骤

### 6.1 梳理/解释目录结构

1. 用文件浏览工具（`files.ts` 对应的 `/api/files` 或本地读取）列出目标目录；
2. 对照第 2 节表格说明各目录用途；
3. 遇到 `{task_id}` 目录，解释其为任务工作区（`cache`/`output`/`workflow.json`/`task.json`），并可用 `task.json` 说明该任务内容。

### 6.2 整理某次任务的产物

1. 确认任务已结束（终态：succeeded/failed，见 `history.py`）；
2. 读取 `control_plane_workspaces/{task_id}/workflow.json` 与 `output/` 内容，识别导出产物；
3. 在 `data/workspace/` 下创建归档目录（按第 4 节命名），**复制**导出产物并附 `workflow.json` 副本；
4. 汇报归档位置与文件清单；如需删除任务工作区，提示用 `DELETE /api/tasks/{id}`。

### 6.3 释放磁盘空间

1. 找出可清理项：`_model_cache/`（模型缓存）、`control_plane_workspaces/` 中已结束任务的 `cache/`、`data/redis/` 旧数据、`frontend/dist/`（可重建）；
2. 逐项列出大小与清理后果，请用户确认后再操作；
3. 任务相关清理优先走 API 删除任务，避免孤儿目录；
4. 确认磁盘空间与保留内容后再执行删除。

### 6.4 备份关键数据

1. 数据库：调用 `scripts/control_plane_backup.py`（或应用内备份功能）备份 `data/control-plane.db`；
2. 用户产物：复制 `data/workspace/` 与任务 `output/` 到备份盘；
3. 配置：`.runtime/local_env.bat`、`backend/config/config.yaml` 等配置文件按需复制（注意脱敏）。

### 6.5 检查异常/重复/临时文件

1. 扫描任务工作区与 `data/workspace/` 中的 `*.tmp`、`*.part`、`~$*` 等临时文件，列出后由用户确认再清理；
2. 检查同名/近似同名产物，提示去重；
3. 检查产物与数据库记录是否一致（如目录存在但任务已被删除的孤儿目录），报告给用户，不擅自删除。

---

## 7. 注意与禁忌

1. **不改动任务工作区结构**：`{task_id}`、`cache/`、`output/` 由运行时约定，重命名或移动会导致任务状态与产物关联失效。
2. **不手工删任务目录**：删除任务及其文件夹请走 `DELETE /api/tasks/{id}`，避免遗留孤儿记录。
3. **不直接操作数据库**：`data/control-plane.db` 与配音谷/协作等 DB 只读，变更走应用功能或备份脚本。
4. **不在任务运行中清理**：任务执行中的工作区、`data/redis/` 队列数据不可动。
5. **不碰 `backend/auth/` 与凭据**：任何情况下不读取、不展示、不搬运认证/订阅/授权相关文件与敏感配置。
6. **不修改代码与配置**：`backend/`、`frontend/src/`、`docs/`、`thirdparty/`、`.runtime/` 等只读；即使"顺手"也不整理其中文件。
7. **删除前必须确认**：任何删除、覆盖、批量移动操作，先列出清单与后果，获得用户明确同意。
8. **优先复制而非移动**：归档产物用复制，保留任务工作区原样，便于任务回看与重跑。
9. **不绕过运行时路径策略**：不得用 shell、链接或间接路径访问黑名单/边界外路径。
10. **不臆造目录**：不向用户描述来源文档与代码中不存在的目录；遇到未知目录先读取确认再回答。
