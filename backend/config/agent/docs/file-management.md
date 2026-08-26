# 文件管理（File Management）

指导 agent 理解本项目的磁盘布局、任务产物命名约定、以及读写文件时应遵循的工具与约定。正确的文件管理能保证工作流节点间产物可靠传递，避免硬编码路径导致的脆弱性。

> 本文档基于 `backend/engine/task_recorder.py`、`backend/steps/base_step.py`、`backend/api/workflows.py`、`backend/api/asr.py` 的**当前实现**。

---

## 1. 仓库级目录布局

```
VideoLingoLc/
├─ backend/                  # 后端（FastAPI + Celery + GPU 服务）
│  ├─ main.py                # 主后端入口（uvicorn, 端口 11001）
│  ├─ manager.py             # 服务编排守护（端口 18001）
│  ├─ steps/                 # 节点 Step 实现（s_*.py）+ step_registry.py
│  ├─ config/
│  │  ├─ builtin_node_types.py   # 内置节点展示定义
│  │  ├─ node_types/             # 自定义节点定义 JSON（<id>.json）
│  │  └─ workflows/              # 工作流模板 JSON
│  ├─ engine/               # 任务目录管理、调度、ASR 引擎
│  ├─ control_plane/        # Celery 运行时、工作流运行、自定义节点运行时
│  ├─ gpu_service/          # GPU 服务层
│  └─ api/                  # HTTP 路由模块
├─ frontend/                # React 前端（Vite）
├─ tasks/                   # 所有任务的工作目录（运行时生成）
├─ _model_cache/            # 模型缓存（统一存放，见第 4 节）
├─ data/
│  ├─ control-plane.db      # 控制平面 SQLite（Alembic 迁移；任务/节点记录）
│  └─ workspace/pi-agent-config/models-store.json  # 模型仓库配置
├─ logs/                    # 运行日志
├─ redis-server.exe         # 自带 Redis（Windows）
└─ *.bat / *.sh             # 启动/安装脚本（backend.bat, start.bat ...）
```

---

## 2. 任务目录（核心）

每个任务一个独立目录，由 `backend/engine/task_recorder.py` 创建与管理：

```
tasks/
  <task_id>/                # task_id = uuid4().hex[:12]
    task.json               # 任务元数据 + 各节点状态
    cache/                  # 中间产物（节点间传递）
    output/                 # 最终交付物
```

关键 API/函数：
- `TASKS_ROOT` = 仓库根下的 `tasks/`
- `create_task_dir()` → 建目录 + `cache/` + `output/`
- `get_task(id)` / `list_tasks()` / `delete_task(id)`（`shutil.rmtree`）
- `TaskRecorder`：`read()` / `write()` / `update_step(step_id, updates)` / `update_status(status)`

> **约定**：节点读写产物时，目录用 `ctx.workspace`（即 `tasks/<task_id>`），中间文件放 `cache/`，结果放 `output/`。不要写到仓库根或其它全局位置，避免多任务互相污染。

### 2.1 task.json 字段

```json
{
  "task_id": "abc123...",
  "task_name": "demo",
  "status": "running",
  "created_at": "...",
  "updated_at": "...",
  "steps": {
    "<node_id>": {
      "status": "success",
      "percent": 100,
      "message": "...",
      "started_at": "...",
      "finished_at": "..."
    }
  }
}
```

---

## 3. 产物命名约定（务必遵守）

节点输出的文件名遵循：

```
<base_name>_<node_id>.<ext>
```

例如 `asr` 节点（node_id=`a1b2c3`）输出 `asr_result_a1b2c3.json`。

**读取时不要硬编码完整文件名**。使用 `BaseStep.find_artifact(directory, base_name)` 反查：

- 在 `directory` 中查找以 `<base_name>` 开头、后缀 `.<ext>` 的文件；
- 忽略中间的 `_<node_id>`；
- 多匹配时取首个；无 `_<node_id>` 后缀的文件优先。

```python
path = self.find_artifact(ctx.workspace / "cache", "asr_result.json")
```

`base_step.py` 还提供通用读写工具（避免各节点重复造轮子）：
- 文本：`read_text_file(path)` / `write_text_file(path, content)`
- JSON：`read_json_file(path)` / `write_json_file(path, obj)`
- 字幕：`read_srt_file(path)` / `write_srt_file(path, subtitle_list)`
- 通用：`read_any_file(path)` 按扩展名分派

> **错误示范**：`open("cache/asr_result.json")` —— 因为真实文件名带 node_id 后缀，会 FileNotFound。
> **正确做法**：`self.find_artifact(ctx.workspace/"cache", "asr_result.json")`。

---

## 4. 模型缓存目录 `_model_cache/`

模型**统一**缓存在仓库根的 `_model_cache/`（不是系统 HF 默认路径，项目做了精细管理）：

- `_model_cache/hub/`：标准 HuggingFace 布局（`models--<org>--<name>/snapshots/<sha>/`），优先 `local_files_only=True` 复用；
- `_model_cache/models/iic/...`：FunASR / ModelScope 旧布局（`.pth` 等）；
- ASR（WhisperX / Qwen3-ASR / FunASR-Nano）、对齐器、分离模型等均从此处加载或自动下载。

agent 新增模型加载逻辑时，应复用 `alignment_processor.py` / `asr_*.py` 中已有的解析函数，写入 `_model_cache/`，不要散落到用户 home 或临时目录。模型清单维护在 `data/workspace/pi-agent-config/models-store.json`，新增内置模型应同步登记。

---

## 5. 文件相关 API（供 agent 调用/理解）

主后端 `backend/api/` 下与文件相关的路由（端口 11001）：

- 工作流/任务文件：`backend/api/workflows.py`（`TASKS_ROOT` 同 `tasks/`；注意工作流调试任务目录前缀 `flow_`）
- ASR 文件管理：`backend/api/asr.py`（`DOWNLOAD_ROOT`、`task_dir(task_id)`、列表/下载产物）
- 通用文件：按 `find_artifact` / `read_*_file` 约定在 Step 内读写

> 注意 `backend/api/workflows.py` 的 `TASKS_ROOT` 与主后端 `engine/task_recorder.py` 指向同一 `tasks/`，但工作流调试任务目录以 `flow_<wf_id>` 命名，agent 处理时区分普通任务与流程调试任务。

---

## 6. Agent 文件操作红线

1. **不硬编码带 node_id 的文件名**：一律用 `find_artifact` 反查。
2. **不写到仓库根/全局临时目录**：产物进 `tasks/<id>/{cache,output}`。
3. **不手动编辑 task.json 指望生效**：任务状态在内存 + SQLite（`data/control-plane.db`）中维护，应通过 API / `TaskRecorder` / 运行时接口修改。
4. **模型落 `_model_cache/`**：复用既有解析与下载逻辑，登记 `models-store.json`。
5. **多任务隔离**：不要在不同 task_id 间共享 `cache/`、`output/` 内容。
6. **删除任务用 API/接口**：会一并 `rmtree` 目录，不要手动删一半。
