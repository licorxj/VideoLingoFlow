# 工作流编排（Workflow Orchestration）

本章说明工作流（workflow）的 JSON 结构、节点如何连线、运行引擎如何驱动，以及内置工作流如何存放。

> 所有路径相对 `PROJECT_ROOT`（即 `Y:\VideoLingoLc`）。

---

## 1. 工作流 JSON 结构

一个工作流是一个 JSON 文件，核心是两个数组：`nodes` 与 `edges`。

### 1.1 节点（node）

节点类型由 **`data.nodeType`** 指定（React Flow 节点可能同时带顶层 `type` 用于视觉渲染，但语义类型以 `data.nodeType` 为准，校验器 `backend/workflow_validation.py::normalize_workflow` 读取的就是它）。

```json
{
  "id": "n_asr_1",
  "type": "asr",
  "position": {"x": 120, "y": 80},
  "data": {
    "nodeType": "asr",
    "label": "语音识别",
    "config": { "model": "whisperx", "language": "auto" }
  }
}
```

- `id`：节点实例唯一 id（运行时用于产物文件名后缀、连线解析）。
- `data.nodeType`：节点类型 id，必须存在于 `builtin_node_types.py` 或 `config/node_types/*.json`。
- `data.config`：该节点配置项（对应节点定义的 `defaultConfig` / `configFields`）。
- `data.label`：展示名（可空，默认取节点类型名）。

### 1.2 连线（edge）

每条 edge 把一个节点的输出端口连到另一个节点的输入端口：

```json
{
  "id": "e1",
  "source": "n_download_1",
  "target": "n_asr_1",
  "sourceHandle": "out-filepath",
  "targetHandle": "in-subtitle"
}
```

- `source` / `target`：源/目标节点 id。
- `sourceHandle`：**`out-<输出端口 id>`**（注意前缀 `out-`）。
- `targetHandle`：**`in-<输入端口 id>`**（注意前缀 `in-`）。

校验器按 `out-*` / `in-*` 前缀解析端口；端口 `type` 类型一致才能连（例如 `subtitle` 输出只能连 `subtitle` 输入）。

### 1.3 工作流顶层字段（示意）

```json
{
  "id": "wf_demo_001",
  "name": "示例工作流",
  "version": "1.0",
  "nodes": [ ... ],
  "edges": [ ... ],
  "vars": { }
}
```

---

## 2. 存储位置

- **工作流模板**：`backend/config/workflows/<id>.json`（目录由 `WORKFLOWS_DIR` 指定）。
- **工作流分组索引**：`backend/config/workflow_groups.json`（分组 → 工作流列表）。
- **自定义节点类型**：`backend/config/node_types/<id>.json`（由 `/api/node-types` 写入，见 `node-creation.md` B 节）。

保存/读取由 `backend/api/workflows.py` 负责；前端通过 `GET /api/workflows` 列出、`POST /api/workflows` 新建、`PUT /api/workflows/{id}` 更新、`DELETE` 删除。

---

## 3. 运行引擎

工作流运行由函数入口 `submit_workflow(...)`（位于 `backend/control_plane/workflow_runtime.py`）驱动，由以下 API 触发：

- `POST /api/workflows/{wf_id}/execute`：运行整条工作流。
- `POST /api/workflows/{wf_id}/execute-node`：从某个节点往后执行。
- `POST /api/workflows/{wf_id}/spawn-task`：派生一个独立执行任务。
- `POST /api/workflows/{wf_id}/debug-task`：调试运行（保留中间产物便于排查）。

执行链路：

```
submit_workflow(wf_id, ...)
  → 在 SQLite（data/control-plane.db）建 Task / TaskNode 记录
  → control_plane/runtime.py 状态机按依赖拓扑调度各节点
      （transition / queue_for / ResourceTokens 控制并发）
  → 每个节点作为一个 Celery 任务，派发到 Celery worker
      （control_plane/celery_runtime.py，队列按资源类型：cpu/gpu/tts/io/llm）
  → worker 内：
       thread 域  → 直接调用 Step（同进程线程）
       process 域 → 启动子进程 python -m backend.control_plane.step_worker
  → step_worker 用 get_step_instance(node_type) 取 BaseStep 实例，
      注入 _node_id/_node_config/_step_inputs，调用 run(task_dir, callback, cancel_callback)
  → 产物写入 control_plane_workspaces/<task_id>/{cache,output}
  → 进度经 /ws/tasks/{task_id} 实时推回前端
```

### 3.1 节点状态机

每个节点 / 任务的状态流转（`control_plane/runtime.py`）：

```
pending → running → success
                 → failed
                 → cancelled   （用户取消）
                 → timeout     （超时）
```

- 取消：`POST /api/tasks/{task_id}/cancel`（`request_cancel` 创建取消标记文件，子进程协作退出）。
- 任务状态同时持久化在 SQLite（`data/control-plane.db`）与 workspace 内的 `task.json`（兼容读取）。

### 3.2 工作区目录

每次运行的工作区在 `control_plane_workspaces/<task_id>/`（根目录由环境变量 `CONTROL_PLANE_WORKSPACE_ROOT` 控制，默认 `Path.cwd()/"control_plane_workspaces"`），含：

- `cache/`：节点间传递的中间产物。
- `output/`：最终交付物。
- `task.json`：任务元数据 / 各节点状态（兼容副本）。

`backend/engine/thread_scheduler.py` 管理的 `tasks/` 目录属于遗留线程池路径，新建能力勿用。

---

## 4. 节点类型元数据来源

前端编辑器渲染节点卡片（分类、端口、设置项）所需的全部元数据，来自：

- `GET /api/node-types`：返回合并了内置（`builtin_node_types.py`）与自定义（`config/node_types/*.json`）的全部节点类型。
- `GET /api/node-types/schema`：节点类型 JSON schema。

`backend/api/node_types.py` 负责读取/合并/校验/CRUD。新增内置节点后无需改前端，刷新即可看到。

---

## 5. 子文档与工具

- 节点定义与 Step 实现：见 `node-creation.md`。
- 任务运行 / 监控 / 目录结构：见 `task-execution.md`、`file-management.md`。
- 工作流 JSON 合法性校验：`backend/workflow_validation.py::normalize_workflow`（连线、端口、必填项）。
- 工作流内置分组与默认模板在 `backend/config/workflows/` 与 `workflow_groups.json`。
