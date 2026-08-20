# 任务执行能力

> 本能力文档供任务执行助手按需读取。所有路径相对 PROJECT_ROOT。

本文档描述 VideoLingoFlow（中文名：流连视听）的任务执行体系：任务如何创建、投递、执行、落盘、失败定位、恢复清理。适用于「任务为什么失败 / 卡住 / 没跑 / 跑多了 / 怎么重跑」类问题。所有描述以代码库真实实现为准（控制平面 FastAPI + SQLite + Redis/Celery，方案 C 子进程隔离）。

---

## 1. 目标与职责

本助手在任务执行相关场景下负责：

- **解释任务状态**：任务/节点当前处于什么状态、为什么是这个状态、下一步会怎样。
- **定位执行失败**：通过运行日志、任务目录产物、DB 记录找出失败节点与原因，并给出可操作结论。
- **规划恢复与重试**：判断该用 resume（增量续跑）、restart（全量重跑）、restart_clean（清缓存从头）还是 execute-node（单节点/下游），并说明清理语义。
- **核对产物完整性**：确认 `cache/`、`output/` 产物是否齐全、是否与节点 succeeded 状态一致。
- **管理批量任务**：理解批量创建、限流投递、同步工作流、子任务重跑机制。

不负责：不自行直接改动控制平面 DB；不在没有依据时臆测任务失败原因；不修改节点实现本身。

---

## 2. 核心概念

### 2.1 任务（Task）

统一存于控制平面 DB（`Task` 表），按 `payload` 字段区分三种类型：

| 类型 | 判定字段 | 说明 |
|---|---|---|
| 全局调试任务 | `payload.is_debug=True`（且无 `detached`/`batch`） | 与全局工作流 `wf_id` 一一绑定（`_find_debug_task` 按 `is_debug=True` 精确查询），跨会话保留节点 succeeded 进度，调试执行写回同一任务，避免反复新建任务浪费磁盘 |
| 一般任务 | `payload.detached=True`（无 `batch`） | 从画布快照独立出来的历史任务，与全局解耦；创建时复制画布快照到私有 `workflow.json`，此后任务内保存只改私有副本 |
| 批量子任务 | `payload.batch.batch_id` 非空 | 批量工作台派生；创建时复制全局 `workflow.json` 到子任务目录，忠于全局文件快照 |

历史兼容：`payload.detached=True` 的旧任务视为一般/历史任务，不会被 `_find_debug_task` 误选。

### 2.2 工作流（workflow）

DAG 定义：`nodes`（节点）+ `edges`（连线）+ `id`/`name`/`description`。三层存储：

| 层 | 位置 | 内容 | 写入方 |
|---|---|---|---|
| 全局工作流定义 | `backend/config/workflows/{wf_id}.json` | 节点+连线+name/description | 前端「保存」/「另存为」 |
| 任务 DB 快照 | `Task.payload.workflow` | 该任务自己的工作流字典 | `submit_workflow` |
| 任务私有文件 | `control_plane_workspaces/{task_id}/workflow.json` | 与 DB 快照一致 | 执行前 `_prepare_workspace`/`_write_workspace_files`/任务内保存 |

隔离规则（关键）：全局调试任务执行时 `workflow` 以**画布当前快照**为准，节点状态（succeeded 等）保留在 `TaskNode.payload.result`；一般任务只改私有副本不碰全局；「另存为全局」（`save-as-global`）才写新全局文件。

### 2.3 执行目录（workspace）

任务私有文件根目录 `control_plane_workspaces/`（可用环境变量 `CONTROL_PLANE_WORKSPACE_ROOT` 覆盖；旧版 `backend/tasks/{task_id}` 兼容，定位时优先控制平面）。旧版调度器 `create_task_env` 也会按 `TASKS_ROOT` 建 `{task_id}/cache`、`{task_id}/output`，两套目录格式一致。

### 2.4 产物

- **cache/**：中间产物，含用户输入源文件（`input_*`，如 `input_video.webm`）、各步骤中间文件、断点缓存。`restart_clean` 清空该目录。
- **output/**：最终产物，节点输出带 `_{node_id}` 后缀（如 `xxx_abc123def.json`）。
- **task.json**：任务元数据 + 节点状态落盘（详见 §4）。
- 安全约束：产物清理**只删带节点 id 后缀的文件，绝不删 `input_*` 用户源文件、`output/` 目录本身与 `workflow.json`**。

### 2.5 缓存（checkpoint）

- `TaskNode.checkpoint_key = f"{node_id}:{digest}"`，digest 基于节点输入计算；输入变化 → digest 变化 → 该节点重跑。
- `_node_artifact_ok(node, workspace)`：节点 succeeded **且** `artifacts` 声明的产物文件存在时才跳过重跑；产物缺失视为需重跑。
- 中间进度落盘限流：每 ≥5% 或 100% 写一次 `task.json`，避免频繁 IO；子进程通过 `@PROGRESS@|pct|msg` 行协议回报进度。

---

## 3. 任务执行目录结构

```
control_plane_workspaces/{task_id}/
├── workflow.json        # 任务私有工作流快照（与 DB 快照一致）
├── task.json            # 任务信息：id/task_name/workflow_id/batch_id/status/input/
│                        #   nodes(节点状态)/edges/created_at/started_at/finished_at；含中间进度
├── cache/               # 中间产物；input_* 用户源文件；步骤中间文件
├── output/              # 最终产物，文件名带 _{node_id} 后缀
└── editor/              # （如存在）编辑器项目数据：project.json/assets.json/characters.json
```

- `task.json` 是排查首要文件：`status` 为任务总体状态；`nodes.{node_id}.status/outputs/error` 为节点级状态与结果；`input` 为实际输入配置（批量任务真实输入在此，工作流文件里可能为空路径）。
- 任务删除时整个 `{task_id}/` 文件夹（含 cache/output/workflow.json/task.json）被移除，日志打印 `已删除任务文件夹 …`；文件被占用删不干净时打印黄色警告。

---

## 4. 执行流程与状态

### 4.1 投递链路

1. 前端调用 `POST /api/workflows/{wf_id}/execute`（mode 见下）或 `POST /api/workflows/{wf_id}/execute-node`。
2. `submit_workflow` 归一化工作流 → 定位任务（见 4.3）→ 建/重建 `TaskNode` 记录（status=pending，resource_class 与 queue 按节点类型分配）→ 置 `queued`。
3. 通过 Celery 投递 `videolingo.workflow.execute` 到 `videolingo_io` 队列；`send_task` 失败时任务置 `failed`（error_class=`queue_unavailable`）。
4. Worker 执行前 `_prepare_workspace` 落盘 `workflow.json` + `task.json`，按 DAG 拓扑调度节点：内置 `process` 节点走 `step_worker` 子进程，`thread` 节点在运行时线程执行；自定义节点由 `custom_node_runtime.py` 按定义执行。
5. 完成/失败/取消后任务进入终态。

### 4.2 状态机

- 任务（TaskStatus）：`created → queued → running → paused/stopping → succeeded/failed/cancelled → deleting → deleted`。
  - 终态：`succeeded/failed/cancelled/deleted`。
  - `running → stopping → cancelled` 为协作式停止（置 stopping 让 Worker 在进度回调处退出，同时收集子进程 pid 硬杀进程树，不误杀同 worker 其他任务）。
  - `deleted → queued` 合法：删除任务可被重新投递。
- 节点（NodeStatus）：`pending → queued → running → succeeded/failed/cancelled/interrupted/paused`。
  - 节点终态：`succeeded/failed/cancelled`；`interrupted/paused` 可恢复。
- 状态校验用 `transition()`，非法迁移抛 `InvalidTransition`。

### 4.3 任务定位规则（execute 的 mode）

| mode | 行为 | 产物清理 |
|---|---|---|
| `debug` | 写回 wf_id 固定调试任务（无则自动创建），workflow 以画布快照为准，**增量重建**保留 succeeded 节点 | 不清 |
| `resume` | 复用 `task_id` 任务（缺省落到固定调试任务），**增量重建**，`resume_from` 断点续跑 | 不清 |
| `restart` | 复用任务，**全量重建**所有节点重跑 | 不清 |
| `restart_clean` | 同 restart，但先**清空任务 `cache/`** 全新开始（对应前端「从头执行」） | 清 cache |
| `new` | 新建 **detached 一般任务**并投递，与全局调试任务解耦 | 新任务天然干净 |

- `debug`：`_find_debug_task(session, wf_id)` 定位固定调试任务。
- `resume/restart/restart_clean`：优先用请求 `task_id`（须存在、未删除、`workflow.id` 与 wf_id 匹配）；为空则回退固定调试任务 → 旧绑定任务。
- `new`：忽略 `task_id`，强制新建 detached 一般任务。
- **单飞保护**：任务处于非终态（非 paused）且 `enqueue=True` 时直接返回（幂等），避免重复投递；终态/暂停任务才走重建分支。
- **身份标记保留**：复用提交（execute-node / debug 写回）通过 `_merge_task_payload` 保留 `is_debug`/`detached`/`batch`，调试任务不会被冲掉身份导致总是新建 task_id。

### 4.4 节点执行（execute-node）边界（重要）

`POST /api/workflows/{wf_id}/execute-node`：

- **必须携带 `task_id`**，且必须是存在、未删除、`workflow.id` 与 wf_id 匹配的任务；否则返回 400（`节点执行必须指定任务` / `任务与工作流不匹配`）。
- **绝不新建任务**：节点执行只能在当前任务边界内进行，不跨边界跳转。
- `scope=node`：仅执行该节点。**始终提交完整工作流**，用 `payload.exec_only=[node_id]` 收窄执行范围（worker 的 `exec_set ∩ exec_only`），**不裁剪任务私有 workflow**——历史加载时画布仍保留完整节点。
- `scope=downstream`：执行该节点及其连线下游（`_resume_reset_set` 可达集）。
- 兼容旧字段 `run_downstream: true` ⇔ `scope=downstream`。

### 4.5 关键 API 速查

| 方法 | 路径 | 用途 |
|---|---|---|
| GET/POST | `/api/workflows/{wf_id}/debug-task` | 返回/创建固定调试任务（POST 用 body 传画布快照，避免超长 URL） |
| POST | `/api/workflows/{wf_id}/execute` | 执行（mode: debug/resume/restart/restart_clean/new） |
| POST | `/api/workflows/{wf_id}/execute-node` | 节点执行（task_id 必传，scope=node/downstream） |
| POST | `/api/workflows/{wf_id}/spawn-task` | 新建一般任务（detached，写私有 workflow.json，不执行） |
| POST | `/api/workflows/{wf_id}/save-as-global` | 一般任务另存为全局 |
| PUT | `/api/tasks/{task_id}/workflow` | 任务内保存（只改私有副本） |
| GET | `/api/workflows/{wf_id}/status` | 任务/节点状态 |
| DELETE | `/api/tasks/{task_id}` | 删除任务（历史项目单个/批量） |
| POST | `/api/batch/create` | 创建批量任务 |
| POST | `/api/batch/{id}/sync-workflow` | 批量同步全局工作流到子任务 |
| POST | `/api/batch/{id}/add` | 批量追加子任务 |
| DELETE | `/api/batch/{batch_id}` / `/api/batch/{batch_id}/tasks` | 删整批 / 删批内选中任务 |

调试任务初始化时机：前端点击工作流加载画布时调 `POST /api/workflows/{wf_id}/debug-task`（body 传 nodes/edges 画布快照）；无则用当前画布快照初始化（`submit_workflow(mode="debug_init", enqueue=False)`），有则直接返回；`debug_init` 幂等，不重复初始化。

---

## 5. 定位失败原因的方法

### 5.1 按顺序排查

1. **后端运行日志（rich 控制台）**：
   - 执行前打印工作流名称/描述/ID/节点数/连线数/模式/输入节点配置（紧凑表格 + Panel）。
   - 节点执行前 `» 执行节点 <label> (<node_type> · <domain>)`；完成后 `√ 节点完成 <label> 用时 Xs`。
   - 工作流成功（绿 Panel）/取消（黄）/失败（红，含 error_class + message）总结。**失败根因优先看这里**。
   - Windows GBK 控制台使用 `»/√` 等 GBK 兼容字符，编码兜底 errors=replace，不会因编码崩溃。
2. **任务目录** `control_plane_workspaces/{task_id}/task.json`：看 `status`、`nodes.{id}.status`、`outputs`、`error`；确认 `workflow.json` 快照与预期一致。
3. **产物完整性**：succeeded 节点对应 `output/`、`cache/` 产物是否真实存在（`_node_artifact_ok` 的判定逻辑）；产物缺失说明状态与磁盘不一致，需要重跑该节点。
4. **DB 记录**（Task/TaskNode 表）：`status/error_class/worker_id/worker_pid/checkpoint_key/retry_count/cancel_reason` 提供权威状态。
5. **Celery 健康**：确认 Celery worker 存活（5 队列 `videolingo_cpu/gpu/llm/tts/io`，`--pool=threads`）；Celery 不可用会以 `queue_unavailable` 失败；批量投递遇 `RuntimeError`（Celery 不可用）停止投递。

### 5.2 任务"卡住"专项排查

任务状态在 `queued/running` 停留过久时按以下顺序定位：

1. **是否在批量限流中**：`_deliver_loop` 按 `max_concurrent_tasks`（活跃 queued/running/stopping 数达到上限则等待）+ `task_start_interval` 间隔投递；若属批量场景且其他子任务仍在跑，属预期排队。
2. **对应资源队列是否拥塞**：`_queue_depth(resource)` 读 Redis 中 `videolingo_{resource}` 队列长度，`_queue_limit` 默认 100（`CELERY_QUEUE_LIMIT` 可调）；队列打满时新任务会滞留。
3. **worker 是否存活**：`celery_app.control.inspect().stats()` 可查 worker 心跳；worker 死亡时任务停留在 queued 不会自动转失败，需人工介入。
4. **是否为 paused 挂起**：paused 任务在 Worker `_wait_until_runnable` 处等待，属正常暂停；恢复后重新 queued。
5. **任务/节点是否 interrupted**：节点 interrupted 后可重新 queued 继续；长期中断状态应主动重投或取消。

### 5.3 常见现象对照表

| 现象 | 原因 | 处理 |
|---|---|---|
| 执行报 `节点执行必须指定任务` | execute-node 未传 task_id | 节点执行必须在当前任务边界内，先打开/接管调试任务 |
| 每次打开工作流都新建任务 | 前端未走 debug-task 接管 / 调试任务身份（is_debug）被冲掉 | 打开时调用 debug-task 拿固定 taskid；复用提交保留 is_debug |
| 从头执行没清干净 | 使用了 `restart` 而非 `restart_clean` | 前端「从头执行」应传 `mode=restart_clean` |
| 单节点执行却重跑了下游 | execute-node 未传 `scope=node` | scope=node 用 exec_only 仅执行该节点；scope=downstream 才含下游 |
| 单节点执行后历史加载画布只剩该节点 | 旧版把任务 workflow 裁剪成单节点（已修复） | 单节点执行始终提交完整工作流（exec_only 收窄），不覆盖任务私有 workflow |
| 历史任务打开「工作流编排」却显示为一般任务 | 前端未识别调试任务（已修复） | 任务 API 返回 `is_debug`，前端对调试任务切到全局工作流模式加载 |
| 批量子任务重跑结果与全局不一致 | 未 sync-workflow | 批量页「同步工作流」重新读全局文件覆盖子任务快照 |
| 任务卡在 queued 不动 | 队列限流（批量 max_concurrent_tasks）或 Celery worker 未存活 | 检查 worker 状态；等待或排查 Redis/Celery |
| 任务状态 succeeded 但产物缺失 | 产物被删/清理不完整 | 定位到节点后重跑该节点（execute-node scope=node） |

---

## 6. 恢复与重试

### 6.1 选择正确的执行模式

| 目标 | 用哪个 | 效果 |
|---|---|---|
| 断点续跑（保留已完成节点） | `execute` mode=resume，或 execute-node scope=downstream 指定节点 | 增量重建，已 succeeded 节点跳过；`resume_from` 指定断点 |
| 全部重跑 | mode=restart | 全量重建所有节点重跑，**不清 cache**（旧中间产物仍在） |
| 彻底从头（含清中间产物） | mode=restart_clean | 先 `_clear_workspace_cache` 清空 cache/ 再全量重跑（「从头执行」） |
| 只重跑一个节点 | execute-node `scope=node` | 仅该节点，先清该节点产物再执行 |
| 重跑某节点及其下游 | execute-node `scope=downstream` | 该节点+连线可达集，清这些节点产物后执行 |
| 全新独立副本 | mode=new / `POST /api/workflows/{wf_id}/spawn-task` | 新建 detached 一般任务，与全局调试任务解耦（spawn 只建不跑） |

### 6.2 清理语义（用户明确要求）

| 操作 | 清理范围 | 实现 |
|---|---|---|
| 端点「从头执行」（restart_clean） | 清空任务 `cache/` 目录内容（保留目录本身） | `_clear_workspace_cache` |
| 单节点执行（scope=node） | 仅该节点产物 | `_clear_nodes_artifacts([node_id])` |
| 节点「往后执行」（scope=downstream） | 该节点 + 连线下游所有节点产物 | `_clear_nodes_artifacts(downstream_set)` |
| 批量页「从头执行」（retry） | 清该子任务 `cache/` | `_clear_workspace_cache` |
| 批量页「继续执行」（resume） | 不清（保留已完成节点/产物） | `_enqueue(task_id, "resume")` |

`_clear_nodes_artifacts` 三步：① 每节点取步骤实例调 `BaseStep.clear_artifact(task_dir)`（删 `artifacts` 声明文件，等价 rollback）；② 兜底删 `output/`、`cache/` 下带 `_{node_id}` 后缀的文件；③ 重置节点 `status=pending`、清空 `result`、`checkpoint_key=None`，确保重跑不被 `_node_artifact_ok` 跳过。

### 6.3 取消/暂停

- 取消：`request_cancel(task_id)`——running 任务置 `stopping` 并杀子进程树（协作式停止优先）；非 running 直接置 `cancelled`；终态任务幂等返回。
- 暂停：`request_pause(task_id)`——running → `paused`，Worker 在 `_wait_until_runnable` 处等待；恢复即重新 `queued`。
- 重试（Celery 层）：`unified_task` 装饰器 `max_retries=3`；`classify_error` 判定 `retryable` 时指数退避（countdown=min(60, 2^retries)）；`TaskCancelledError`/`TaskTimeoutError` 不自动重试。

### 6.4 删除

- 删任务：统一 `request_delete(task_id)` → DB 置 `deleted` + 删除任务工作区文件夹。入口：`DELETE /api/tasks/{task_id}`（历史项目单个/批量）、`DELETE /api/batch/{batch_id}`（整批）、`DELETE /api/batch/{batch_id}/tasks`（批内选中）。
- 删工作流：`DELETE /api/workflows/{wf_id}` 删全局 `config/workflows/{wf_id}.json` + 旧 `backend/tasks/flow_{wf_id}` 目录，并**级联删除所有 `payload.workflow.id == wf_id` 的绑定任务**（每个走 `request_delete`）。
- **运行中/停止中任务禁止删除**（返回 409 / blocked），文件夹保留；删除工作流时运行中的绑定任务同样跳过，须先停止再删。

---

## 7. 批量任务说明

- **创建**：`POST /api/batch/create` → `_load_workflow(workflow_id)` 读**全局工作流文件** → 每子任务 `submit_workflow(mode="batch", enqueue=False)` → 写 `payload.batch`（batch_id/batch_name/workflow_id/…）+ `legacy_key="batch:{id}:{task_id}"` → **复制全局 `workflow.json` 到子任务目录**。
- **启动/继续**：`_start_delivery`（幂等，已有活跃投递线程不重复启动）→ `_deliver_loop` 后台投递循环：按 `max_concurrent_tasks` 限流（活跃 queued/running/stopping 任务数达到上限则等待）+ `task_start_interval` 启动间隔（config 可配）；跳过已在队列/运行/成功/已删除的任务；遇 Celery 不可用停止投递。投递 `_enqueue(task_id, mode)` 复用**任务自身 payload 工作流快照**。
- **同步**：`POST /api/batch/{id}/sync-workflow` 重新读全局文件并覆盖所有子任务 `payload.workflow`（子任务重跑结果与全局不一致时用它）。
- **追加**：`POST /api/batch/{id}/add` 复用批次首任务工作流快照。
- **可见性**：批量列表/详情排除 `deleted`/`deleting` 状态任务——删除后条目立即消失；历史遗留的 stuck `deleting` 残留（无文件夹的幽灵条目）不再显示。批量任务只有达到 `succeeded`/`failed` 终态才会出现在历史项目页。
- **子任务画布重跑**：批量页「编辑工作流」跳转 `/?task={task_id}` → 前端以一般任务身份加载该子任务 → 画布执行走 `api/workflows`（单任务 execute），与批次投递解耦，遵循 §4.4 边界与 §6.2 清理语义。

---

## 8. 注意与禁忌

- **不编造接口**：本文档列出的 API/函数/目录均有真实实现（`submit_workflow`、`_prepare_workspace`、`_clear_workspace_cache`、`_clear_nodes_artifacts`、`request_delete`、`_deliver_loop`、`videolingo.workflow.execute` 等）；引用时用真实路径核实后再下结论。
- **不清用户源文件**：`cache/` 下的 `input_*`（`input_video.webm` 等）是用户输入，任何清理（restart_clean/节点清理/手动清理）都不许碰；`output/` 目录本身与 `workflow.json` 同样保护。
- **不跨任务边界执行**：execute-node 必须指定合法 task_id，绝不新建任务、不跳到别的任务执行。
- **单飞保护语义**：非终态非 paused 任务重复提交会被幂等返回——「任务点了执行没反应」先查是否已在 running/queued，而非重复投递。
- **restart 与 restart_clean 的区别**：前者不清 cache（旧中间产物可能影响结果判断），后者才对应「从头执行」。
- **is_debug 身份不可丢**：调试任务的 is_debug 标记靠 `_merge_task_payload` 保留；排查「每次打开都新建任务」时先确认身份标记与后端是否已重启。
- **任务删除不可恢复**：`request_delete` 同时删 DB 记录与磁盘文件夹（含全部产物），确认后再删；运行中任务删不掉属预期行为。
- **批量子任务忠于全局快照**：子任务从创建那一刻的快照执行；要跟随全局变更必须先 sync-workflow。
- **worker 资源队列**：节点按类型分配到 `videolingo_cpu/gpu/llm/tts/io` 五队列（可用 `CELERY_QUEUE_{RESOURCE}` 覆盖），队列深度/上限可经 `CELERY_QUEUE_LIMIT` 控制；排查排队卡顿先看对应队列与 worker 存活。
- **路径解析**：所有相对路径相对 PROJECT_ROOT 解析；`CONTROL_PLANE_WORKSPACE_ROOT` 可重定向工作区根目录；旧 `backend/tasks/` 目录为兼容遗留，新任务一律落控制平面工作区。
