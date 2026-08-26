# 任务执行（Task Execution）

指导 agent 如何在本机启动 VideoLingoFlow（中文：流连视听）、创建并运行一个工作流任务、监控其进度、以及理解任务在磁盘上的组织方式。

> 本文档基于 `backend/manager.py`、`backend/main.py`、`backend/engine/task_recorder.py`、`backend/control_plane/workflow_runtime.py` 的**当前实现**。

---

## 1. 启动系统（关键）

系统由 **`backend/manager.py`** 统一编排。不要单独 `python backend/main.py` —— 那样缺少 Redis、Celery、GPU 服务、Social/Cutia/LLM-Router，绝大多数任务无法完成。

### 1.1 推荐启动入口

```bash
# Windows（双击或命令行）
backend.bat

# 等价于手动启动 manager（默认端口 manager=18001, backend=11001）
python backend/manager.py
python backend/manager.py 18001 11001   # 自定义端口
```

`manager.py` 会按依赖顺序：
1. 准备 venv 环境与 PATH（包括 CUDA / torch lib 的精细处理）；
2. 启动 **Redis**（6379，项目自带 `redis-server.exe`）；
3. 若 `GPU_SERVICE_ENABLED=1`，启动 **GPU 服务层**（`backend/gpu_service/manager.py`）；
4. 启动 **Celery worker**（`backend/control_plane/celery_runtime.py`，队列见 capability-index）；
5. 启动 **主后端 uvicorn**（`backend.main:app`，端口 **11001**）；
6. 按需启动 social / cutia / llm-router / social-mcp；
7. 进入看门狗循环，异常退出自动重启。

### 1.2 端口速查

| 服务 | 端口 |
|---|---|
| Manager 控制面 | **18001**（`/manager/*` HTTP） |
| 主后端 API / WebSocket | **11001**（`/api/*`、`/ws`） |
| Redis | 6379 |
| LLM Router | 8800 |
| Cutia | 4100 |
| Social 后端 / 前端 / MCP | 5409 / 5173 / 5410 |

前端 dev server（Vite）通过代理把 `/api`、`/ws` 指向 **11001**。

### 1.3 Manager 控制接口（HTTP，端口 18001）

`manager.py` 暴露进程管控端点（用于重启/停止某个服务）：

- `GET /manager/status`：所有子进程状态
- `POST /manager/restart-gpu-service` / `start-gpu-service` / `stop-gpu-service`
- `POST /manager/restart-backend` / `stop-backend` 等

agent 在"改完代码需要重启后端"时，应调用这些接口或重启 manager，而非手动 kill。

---

## 2. 创建并运行任务

### 2.1 通过 API 运行

主后端（`main.py`）提供任务运行接口（具体路径以 `backend/main.py` 与 `backend/api/control_plane.py` 为准，常见为 `POST /api/run-task`）。请求体约含：

```json
{
  "workflow_id": "<工作流模板 id 或 JSON>",
  "task_name": "demo",
  "inputs": { "video_url": "..." }
}
```

返回 `task_id`。随后可通过：
- `GET /api/tasks/<task_id>` 查询状态（`backend/engine/task_recorder.py:get_task`）
- `GET /api/tasks` 列出全部任务（`list_tasks`，按 `created_at` 倒序）
- `DELETE /api/tasks/<task_id>` 删除（同时 `shutil.rmtree` 任务目录）
- WebSocket `/ws` 实时进度（节点 percent/status 推送）

### 2.2 任务状态机

任务与节点状态由 `backend/control_plane/runtime.py` 管理（`transition`/`InvalidTransition`/`ResourceLimitError`/`TaskCancelledError`/`TaskTimeoutError`）。节点级状态含：`pending → running → success / failed / cancelled / timeout`。

取消任务：`ThreadScheduler.request_cancel(task_id)` 会设置取消标志并 `terminate()` 子进程；GPU 服务层的任务则通过 cancel key 中止。

### 2.3 并发与资源

- 线程池 `max_workers=3`（可在 `thread_scheduler.py` 调整）；
- GPU 类节点受 GPU 服务层 lane 限制；
- TTS 类节点受 `tts` 资源令牌限制；
- 网络/API 类节点（`RESOURCE_FREE_NODE_TYPES`）不占用本地计算令牌，可多任务并发。

---

## 3. 任务在磁盘上的组织

任务目录由 `backend/engine/task_recorder.py` 创建与管理。

### 3.1 目录结构

```
tasks/
  <task_id>/                # task_id = uuid4().hex[:12]
    task.json               # 任务元数据 + 各节点状态（TaskRecorder 读写）
    cache/                  # 中间产物
    output/                 # 最终产物
```

- `TASKS_ROOT` = 仓库根下的 `tasks/`
- `create_task_dir()` 生成 12 位 hex id，并预建 `cache/`、`output/`

### 3.2 task.json 字段

`task.json` 由 `TaskRecorder` 维护，关键结构：

```json
{
  "task_id": "abc123...",
  "task_name": "demo",
  "status": "running",          // 顶层任务状态
  "created_at": "2026-08-23T10:00:00",
  "updated_at": "2026-08-23T10:05:00",
  "steps": {                    // 各节点（step）状态
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

`TaskRecorder` 方法：`read()` / `write()` / `update_step(step_id, updates)` / `update_status(status)`。

### 3.3 产物文件命名约定

步骤输出文件名遵循 `{base}_{node_id}{ext}`（如 `asr_result_abc123.json`）。读取时用 `backend/steps/base_step.py:find_artifact(directory, base_name)` 反查（忽略 `_<node_id>` 后缀，多匹配取首个，无后缀优先）。**agent 读写产物应优先用 `find_artifact` 而非硬编码文件名**。详见 `file-management.md`。

---

## 4. Agent 常见操作清单

| 目标 | 做法 |
|---|---|
| 启动系统 | 运行 `backend.bat` 或 `python backend/manager.py` |
| 重启后端（改代码后） | 调 `POST /manager/restart-backend` 或重启 manager |
| 重启 GPU 服务 | `POST /manager/restart-gpu-service` |
| 查看任务列表 | `GET /api/tasks` 或 `list_tasks()` |
| 查看某任务详情 | `GET /api/tasks/<id>` 或 `get_task(id)` |
| 删除任务 | `DELETE /api/tasks/<id>` 或 `delete_task(id)` |
| 取消运行中任务 | 经 API 触发 `ThreadScheduler.request_cancel` |
| 读任务产物 | `find_artifact(task_dir, "asr_result.json")` |
| 排查失败 | 看 `task.json` 的 `steps.<node>.message` + `logs/` |

---

## 5. 易错点

1. **端口用错**：业务 API 是 11001，不是 8000；Manager 是 18001。
2. **单独起 main.py**：缺 Redis/Celery/GPU 服务，任务会卡在 pending 或报错。
3. **直接改 task.json 后未重启**：任务状态在内存与 DB 中都有，手动编辑磁盘文件不一定生效，应通过 API/运行时接口。
4. **文件名硬编码**：节点 id 拼接在产物名里，必须用 `find_artifact` 反查。
5. **GPU 双重限流**：启用 GPU 服务后，ASR/分离类节点不应再扣 worker 侧 gpu 令牌（运行时已按 `GPU_SERVICE_MANAGED_NODE_TYPES` 处理）。
