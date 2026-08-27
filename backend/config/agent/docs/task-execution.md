# 任务执行（Task Execution）

本章说明如何启动系统、创建/运行/监控任务，以及任务在磁盘上的真实布局。

> 所有路径相对 `PROJECT_ROOT`（即 `Y:\VideoLingoLc`）。

---

## 1. 启动系统

系统**不是**单进程 FastAPI 服务，而是由 `backend/manager.py` 统一编排的**多进程套件**。直接 `python backend/main.py` 只会启动主后端，缺 Redis / Celery / GPU 服务，任务基本都会失败。

```bash
backend.bat                 # Windows 双击
# 或
python backend/manager.py            # 默认 manager=18001, backend=11001
python backend/manager.py 18001 11001
```

`manager.py` 负责：准备 venv（`venv312`）、启动 Redis（6379）、按需启动 GPU 服务、启动 Celery worker（`control_plane_worker`、`voiceforge_worker`）、启动主后端 uvicorn（11001），并按需启动 social / cutia / llm-router，且维持看门狗自动重启。

### 1.1 关键服务与端口

| 服务 | 入口 | 端口 |
|---|---|---|
| Manager | `backend/manager.py` | 18001 |
| 主后端（业务 API） | `backend/main.py` | 11001 |
| Redis（Celery broker / GPU 协调） | `redis-server.exe` | 6379 |
| Celery Worker（控制平面） | `backend/control_plane/celery_runtime.py` | broker Redis 6379 |
| GPU 服务（可选） | `backend/gpu_service/manager.py` | 无独立端口（经 Redis 协调） |
| 前端 dev | `frontend/`（Vite） | 代理 `/api`→11001、`/ws`→11001 |

---

## 2. 创建并运行任务

### 2.1 运行入口

通过工作流相关端点触发运行：

- `POST /api/workflows/{wf_id}/execute`：运行整条工作流。
- `POST /api/workflows/{wf_id}/execute-node`：从指定节点往后执行。
- `POST /api/workflows/{wf_id}/spawn-task`：派生独立执行任务。
- `POST /api/workflows/{wf_id}/debug-task`：调试运行。

这些端点都调用 `backend/control_plane/workflow_runtime.py::submit_workflow`，由控制平面落地执行（见 `workflow-orchestration.md` 第 3 节）。

任务状态查询：

- `GET /api/tasks`：任务列表。
- `GET /api/tasks/{task_id}`：单个任务详情（节点状态、进度、产物）。
- `POST /api/tasks/{task_id}/cancel`：取消。

### 2.2 状态机

节点/任务状态由 `backend/control_plane/runtime.py` 中的状态机管理：

```
pending → running → success
                 → failed
                 → cancelled
                 → timeout
```

`transition()` / `queue_for()` / `ResourceTokens` 控制状态流转与并发（见 2.3）。

### 2.3 并发模型

并发由两层决定：

1. **Celery worker 进程数**：`control_plane_worker` / `voiceforge_worker` 的并发配置，决定同时能跑多少个 Celery 任务。
2. **资源令牌（ResourceTokens）**：在 `workflow_runtime.py` 中按节点类型分配 `gpu` / `tts` / `io` 令牌，限制同类资源并发：
   - `RESOURCE_BY_NODE_TYPE`：`asr`/`vocal_separation`/`track_separation` → `gpu`；`tts`/`dub_task` → `tts`。
   - `RESOURCE_FREE_NODE_TYPES`：纯网络/API 节点（如 `llm_request`、`platform_download`）不占本地计算令牌，可高并发。
   - `GPU_SERVICE_MANAGED_NODE_TYPES`：启用 GPU 服务后，ASR/分离类走 GPU lane，worker 侧不再扣 `gpu` 令牌（避免双重限流）。

`backend/engine/thread_scheduler.py` 的 `ThreadScheduler` 属于遗留路径，新建能力无需改动。

---

## 3. 磁盘布局（真实工作区）

当前控制平面执行路径的工作区：

```
control_plane_workspaces/            # 根目录由 CONTROL_PLANE_WORKSPACE_ROOT 控制
  <task_id>/                         # task_id 来自 SQLite 任务记录
    task.json                        # 任务元数据 + 各节点状态（兼容副本）
    cache/                          # 中间产物（节点间传递）
    output/                         # 最终交付物
```

- `task_dir` 会作为 `BaseStep.run(task_dir, ...)` 的第一个参数传入，节点应在 `cache/` 写中间产物、`output/` 写结果，不要写到仓库根或其它全局位置，避免多任务互相污染。
- 任务/节点状态同时持久化在 SQLite（`data/control-plane.db`，Alembic 迁移），`task.json` 是供读取/排查的兼容副本。

### 3.1 产物命名约定

节点输出文件名遵循：

```
<base_name>_<node_id>.<ext>
```

例如 `asr` 节点（node_id=`a1b2c3`）输出 `asr_result_a1b2c3.json`。

**读取时不要硬编码完整文件名**，用模块级函数反查：

```python
from backend.steps.base_step import find_artifact
path = find_artifact(os.path.join(task_dir, "cache"), "asr_result.json")
```

`find_artifact(directory, base_name)`：在 `directory` 中找以 `<base_name>` 开头、后缀匹配的文件，忽略中间的 `_<node_id>`；多匹配取首个，无后缀的优先。详见 `file-management.md`。

---

## 4. 监控与排查

- **WebSocket**：`/ws/tasks/{task_id}` 实时推送节点进度/日志。
- **日志**：`logs/`；子进程内 `print()` 经 `step_worker` 的日志转发（`@LOG@`/`@PROGRESS@` 协议）回传到任务事件流，便于排查"卡住"问题。
- **取消**：`POST /api/tasks/{task_id}/cancel`，父线程创建取消标记文件，子进程协作退出（不回调的步骤由父线程 kill 进程树兜底）。

---

## 5. Agent 执行红线

1. **不要**用 `python backend/main.py` 单启来验证任务——缺依赖会失败，走 `manager.py` 或 `*.bat`。
2. 调用业务 API 用 **11001**；调用 Manager 用 **18001**；不要假设 8000。
3. 任务工作区是 `control_plane_workspaces/<task_id>/`，产物进 `cache/`/`output/`，不要写仓库根或全局临时目录。
4. 文件名带 `_<node_id>` 后缀，一律用 `find_artifact` 反查。
5. 改完节点/Step 后做 `read_lints` / 类型检查；新增模型落 `_model_cache/` 并登记 `models-store.json`（见 `file-management.md`）。
