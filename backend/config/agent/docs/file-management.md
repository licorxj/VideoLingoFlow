# 文件管理（File Management）

指导 agent 理解本项目的磁盘布局、任务产物命名约定，以及在 Step 内读写文件应遵循的工具与约定。正确的文件管理能保证工作流节点间产物可靠传递，避免硬编码路径导致的脆弱性。

> 本文档基于当前实现：`backend/control_plane/workflow_runtime.py`、`backend/control_plane/step_worker.py`、`backend/steps/base_step.py`、`backend/api/workflows.py`、`backend/api/node_types.py`。

---

## 1. 仓库级目录布局

```
VideoLingoLc/
├─ backend/
│  ├─ main.py                # 主后端入口（uvicorn, 端口 11001）
│  ├─ manager.py             # 服务编排守护（端口 18001）
│  ├─ steps/                 # 节点 Step 实现（s_*.py）+ step_registry.py
│  ├─ config/
│  │  ├─ builtin_node_types.py   # 内置节点展示定义
│  │  ├─ node_types/             # 自定义节点定义 JSON（<id>.json）
│  │  ├─ workflows/              # 工作流模板 JSON（<id>.json）
│  │  └─ workflow_groups.json    # 工作流分组索引
│  ├─ engine/               # 遗留的线程池调度 / 任务目录（TASKS_ROOT 等）
│  ├─ control_plane/        # Celery 运行时、工作流运行、自定义节点运行时、step_worker
│  ├─ gpu_service/          # GPU 服务层
│  └─ api/                  # HTTP 路由模块
├─ frontend/                # React 前端（Vite）
├─ control_plane_workspaces/ # 运行工作区（运行时生成；见第 2 节）
├─ _model_cache/            # 模型缓存（统一存放，见第 4 节）
├─ data/
│  ├─ control-plane.db      # 控制平面 SQLite（Alembic 迁移；任务/节点记录）
│  └─ workspace/pi-agent-config/models-store.json  # 模型仓库配置
├─ logs/                    # 运行日志
├─ redis-server.exe         # 自带 Redis（Windows）
└─ *.bat / *.sh             # 启动/安装脚本（backend.bat, start.bat ...）
```

---

## 2. 任务工作区（核心）

每次工作流运行的工作区由控制平面在运行时创建于 `control_plane_workspaces/`：

```
control_plane_workspaces/
  <task_id>/                # task_id 来自 SQLite 任务记录
    task.json               # 任务元数据 + 各节点状态（兼容副本）
    cache/                  # 中间产物（节点间传递）
    output/                 # 最终交付物
```

- 工作区根目录由环境变量 `CONTROL_PLANE_WORKSPACE_ROOT` 控制，默认 `Path.cwd()/"control_plane_workspaces"`。
- 该 `task_dir` 会作为 `BaseStep.run(task_dir, ...)` 的第一个参数传入。节点应在 `cache/` 写中间产物、`output/` 写结果，不要写到仓库根或其它全局位置，避免多任务互相污染。
- 任务/节点状态同时持久化在 SQLite（`data/control-plane.db`），`task.json` 是供读取/排查的兼容副本。

`backend/engine/thread_scheduler.py` 里有一套遗留的 `TASKS_ROOT = tasks/`（仓库根 `tasks/`）路径，属于旧线程池执行方式，新建能力勿用。

### 2.1 task.json 字段（兼容副本）

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

不要手动编辑 `task.json` 指望生效——任务状态在内存 + SQLite 中维护，应通过 API / 运行时接口修改。

---

## 3. 产物命名约定（务必遵守）

节点输出的文件名遵循：

```
<base_name>_<node_id>.<ext>
```

例如 `asr` 节点（node_id=`a1b2c3`）输出 `asr_result_a1b2c3.json`。

**读取时不要硬编码完整文件名**。使用模块级函数 `find_artifact(directory, base_name)` 反查（定义于 `backend/steps/base_step.py`）：

```python
import os
from backend.steps.base_step import find_artifact

path = find_artifact(os.path.join(task_dir, "cache"), "asr_result.json")
```

`find_artifact` 的行为：
- 在 `directory` 中查找以 `<base_name>` 开头、后缀 `.<ext>` 的文件；
- 忽略中间的 `_<node_id>`；
- 多匹配时取首个；无 `_<node_id>` 后缀的文件优先。

`BaseStep` 还提供：`check_artifact(task_dir)`、`validate_inputs(task_dir)`、`run(...)`、`rollback(task_dir)` / `clear_artifact(task_dir)`（按 `artifacts` 清理）、`_all_exist(task_dir, files)`。工具类的文本/JSON/SRT 读写请调用各 Step 内部既有辅助函数或标准库，不要依赖不存在的 `read_text_file` / `write_json_file` 等方法。

---

## 4. 模型缓存目录 `_model_cache/`

模型**统一**缓存在仓库根的 `_model_cache/`（项目做了精细管理，而非系统 HF 默认路径）：

- `_model_cache/hub/`：标准 HuggingFace 布局（`models--<org>--<name>/snapshots/<sha>/`），优先 `local_files_only=True` 复用；
- `_model_cache/models/iic/...`：FunASR / ModelScope 旧布局（`.pth` 等）；
- ASR（WhisperX / Qwen3-ASR / FunASR-Nano）、对齐器、分离模型等均从此处加载或自动下载。

agent 新增模型加载逻辑时，应复用既有解析/下载函数，写入 `_model_cache/`，并同步登记 `data/workspace/pi-agent-config/models-store.json`。

---

## 5. 文件相关 API（供 agent 调用/理解）

主后端 `backend/api/`（端口 11001）：

- 工作流/任务：`backend/api/workflows.py`（工作流 CRUD、运行、调试任务；工作区在 `control_plane_workspaces/`）。
- 自定义节点：`backend/api/node_types.py`（节点类型 CRUD、schema、导入/导出）。
- 通用文件：`backend/api/files.py`（项目文件浏览、上传/读取/流式、音频扫描与裁剪）。
- ASR 文件：`backend/api/asr.py`（产物列表/下载）。
- 步骤内读写：遵循 `find_artifact` / `{base}_{node_id}{ext}` 约定，写在 `task_dir` 的 `cache/`/`output/` 下。

---

## 6. Agent 文件操作红线

1. **不硬编码带 node_id 的文件名**：一律用 `find_artifact` 反查。
2. **不写到仓库根/全局临时目录**：产物进 `control_plane_workspaces/<id>/{cache,output}`。
3. **不手动编辑 task.json 指望生效**：状态在内存 + SQLite（`data/control-plane.db`）维护，应通过 API / 运行时接口修改。
4. **模型落 `_model_cache/`**：复用既有解析与下载逻辑，登记 `models-store.json`。
5. **多任务隔离**：不要在不同 task_id 间共享 `cache/`、`output/` 内容。
6. **删除任务用 API/接口**：会一并清理 workspace 目录与 DB 记录，不要手动删一半。
