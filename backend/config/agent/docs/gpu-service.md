# GPU 服务（GPU Service）

VideoLingoFlow（中文：流连视听）的 GPU 计算不是"某个节点自己加载模型"，而是由一层**独立的 GPU 服务（GPU Service Layer）**统一接管显存调度。本文说明它的职责、开关、配置与 agent 接入方式。

> 本文档基于 `backend/gpu_service/*` 与 `backend/control_plane/workflow_runtime.py` 的**当前实现**。

---

## 1. 它解决什么问题

ASR（WhisperX）、人声分离（demucs）、音轨分离等节点会加载大模型并长时间占用 GPU 显存与 GIL。若放任多任务并发，会：
- 显存 OOM；
- 单进程 uvicorn 事件循环被长推理饿死，前端失联。

GPU 服务层把这类计算集中到一个**带 lane（车道）调度**的服务中：按显存余量动态增减 lane 进程、空闲超时释放显存、任务排队不超限。主后端 worker 侧不再自行扣 `gpu` 资源令牌（避免双重限流）。

---

## 2. 架构

```
主后端 worker（asr/vocal_separation/track_separation 节点）
   │  提交 job（经 Redis 队列）
   ▼
GPU 服务层  backend/gpu_service/manager.py
   ├─ monitor.py   显存监测（free/used，压力判定）
   ├─ lane.py      lane 进程池（每个 lane 一个子进程跑模型）
   ├─ jobs.py      任务入队/出队/进度/取消/结果
   └─ config.py    全部通过环境变量配置
   │  状态/结果经 Redis
   ▼
主后端 worker 取回结果，继续后续节点
```

- **无独立 HTTP 端口**：GPU 服务通过 **Redis（6379）** 与主后端通信，使用 `videolingo:gpu:*` 键（见 `config.py` 的 `status_key`/`job_queue_key`/`result_key`/`progress_key`/`cancel_key`）。
- 由 `manager.py` 在 `GPU_SERVICE_ENABLED=1` 时启动（`start_gpu_service()` → `python -m backend.gpu_service.manager`）。

---

## 3. 启用与关闭

开关完全由环境变量 `GPU_SERVICE_ENABLED` 控制（在 `manager.py` 注入到子进程环境）：

```bash
# 启用
set GPU_SERVICE_ENABLED=1      # 或 true / yes / on
python backend/manager.py
```

判定逻辑：`backend/gpu_service/config.enabled()` 读 `GPU_SERVICE_ENABLED`（默认 `"0"` 关闭）。若未启用：
- GPU 服务进程不启动；
- 主后端运行时 `gpu_service_enabled()` 返回 False；
- ASR/分离类节点改为由 worker 侧 `gpu` 资源令牌限流（回退到本地直接执行）。

运行时也可通过 Manager 控制面动态启停：
- `POST /manager/start-gpu-service`
- `POST /manager/stop-gpu-service`
- `POST /manager/restart-gpu-service`

---

## 4. 配置项（环境变量，见 `gpu_service/config.py`）

全部带安全默认值，单卡即可运行：

| 变量 | 默认 | 含义 |
|---|---|---|
| `GPU_SERVICE_ENABLED` | `0` | 是否启用服务层 |
| `GPU_SERVICE_REDIS_URL` | `redis://127.0.0.1:6379/2`（回退 `CONTROL_PLANE_CELERY_BROKER_URL`） | Redis 地址（独立 DB 2） |
| `GPU_SERVICE_MAX_LANES` | `3` | lane 进程上限（显存充足时最大并发路数） |
| `GPU_SERVICE_LANE_IDLE_TIMEOUT` | `600` | lane 空闲（秒）超时退出，释放显存 |
| `GPU_SERVICE_PRESSURE_IDLE_TIMEOUT` | `60` | 显存紧张（free < 2×headroom）时空闲超时，显著更短 |
| `GPU_SERVICE_VRAM_HEADROOM_GB` | `3.0` | 剩余显存低于此值不再分配新 lane（防 OOM 排队） |
| `GPU_SERVICE_JOB_TIMEOUT` | `3600` | 单任务执行上限（秒） |
| `GPU_SERVICE_HEARTBEAT_TTL` | `30` | lane 心跳/状态键 TTL（秒） |

---

## 5. 哪些节点由 GPU 服务接管

由 `workflow_runtime.py` 的 `GPU_SERVICE_MANAGED_NODE_TYPES` 定义：

```python
GPU_SERVICE_MANAGED_NODE_TYPES = {"asr", "vocal_separation", "track_separation"}
```

以及资源映射 `RESOURCE_BY_NODE_TYPE`：

```python
RESOURCE_BY_NODE_TYPE = {
    "asr": "gpu",
    "vocal_separation": "gpu",
    "track_separation": "gpu",
    "tts": "tts",
    "dub_task": "tts",
}
```

运行时逻辑（`workflow_runtime._gpu_service_active()`）：
- 若 GPU 服务启用 → 这些节点提交给 lane，worker 侧**跳过 `gpu` 令牌**（避免双重限流）；
- 若未启用 → 这些节点由 worker 侧 `gpu`/`tts` 令牌限流，本地直接执行。

> **重要**：不要新增"需要 GPU 的节点"时绕过 `GPU_SERVICE_MANAGED_NODE_TYPES` / `RESOURCE_BY_NODE_TYPE`，否则会破坏统一的限流与调度。新增 GPU 节点应在 `RESOURCE_BY_NODE_TYPE` 登记资源类型，并视是否交由服务层在 `GPU_SERVICE_MANAGED_NODE_TYPES` 登记。

---

## 6. 任务生命周期（对 agent 透明）

1. worker 节点提交 job 到 `videolingo:gpu:jobs`（或 lane 专属队列）；
2. 某 lane 进程领取 job，执行模型推理，写入 `progress_key`；
3. 完成写 `result_key`，失败/取消写对应状态；
4. worker 取回结果继续工作流；
5. lane 空闲超过 `LANE_IDLE_TIMEOUT` 自动退出释放显存；显存紧张时按 `PRESSURE_IDLE_TIMEOUT` 更快释放。

取消：worker 或用户取消时写 `cancel_key`，lane 轮询中止当前 job。

---

## 7. Agent 操作建议

| 场景 | 做法 |
|---|---|
| 本机有 GPU、要跑 ASR/分离 | 设 `GPU_SERVICE_ENABLED=1` 后启动 manager |
| 仅 CPU / 无 GPU | 保持默认关闭，节点走 worker 侧令牌限流 |
| 改 GPU 服务代码 | 改 `backend/gpu_service/*`，重启用 `POST /manager/restart-gpu-service` |
| 调并发/显存策略 | 调对应环境变量（见第 4 节），重启 GPU 服务生效 |
| 排查 GPU 任务卡住 | 看 Redis `videolingo:gpu:*` 状态键、monitor 日志、`logs/` |
| 新增 GPU 节点 | 在 `step_registry` 注册 Step，并在 `RESOURCE_BY_NODE_TYPE` / `GPU_SERVICE_MANAGED_NODE_TYPES` 登记 |
