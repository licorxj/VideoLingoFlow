# 多任务 / GPU 管理优化计划

> 版本：v1（2026-10-13 定稿）
> 背景：多任务运行时混乱、无限等待、前后端进度不一致、无法顺畅停止任务。
> 本文是修改计划与清单；每项含锚点、改法、验收、回滚。实施按批次推进，每批完成后单独验证再进下一批。

---

## 0. 目标与总体原则

| 目标 | 衡量标准 |
|---|---|
| 停得掉 | 任何非终态任务点停止后，process 域 ≤5s 杀子进程，thread 域 ≤30s 在下一个检查点退出；取消接口语义真实（不再假成功） |
| 等不死 | 所有等待循环（资源令牌 / paused / GPU lane / 引擎调用）有超时或取消检查点；worker 线程不被 paused 任务永久占用 |
| 看得齐 | REST / WS 事件流 / task.json / 矩阵 UI 四个进度源一致；排队中、进行中、停止中、已暂停在前端可区分 |
| 跑不乱 | 同一格子无法并发重复提交；并发下不产生双份资产；失败角标反映最近一次真实结果 |
| GPU 不撞 | GPU 服务不可用时自动降级到令牌管控；lane 崩溃/退出不丢任务、不永久占卡 |

原则：**小步快跑、每批可独立上线、每批可回滚**；不重写架构，优先在现有控制平面上补等待治理与取消链路。

---

## 1. 问题清单与编号（与调查报告对应）

已复核锚点（2026-10-13 逐条 read 确认）：

| 编号 | 问题 | 锚点 | 严重度 |
|---|---|---|---|
| P0-1 | 驾驶舱提交 scope 带 uuid4，单飞保护失效，同格可无限重复并发提交 | `backend/api/creation_tasks.py:109`；`workflow_runtime.py:1185-1195` | P0 |
| P0-2 | 步骤内判重 read-then-act，并发双跑双登记资产 | `backend/steps/s_agi_comic.py:2842/2988/3141/3269`；`backend/creation/store.py:716-731` | P0 |
| P0-3 | paused 任务 `_wait_until_runnable` 永久自旋占死 worker 线程 | `backend/control_plane/workflow_runtime.py:1309-1319` | P0 |
| P0-4 | 资源令牌默认无限排队，排队循环内无取消检查；节点先标 running 再排队 | `workflow_runtime.py:180-192, 1743-1763, 1859-1863`；`control_plane/runtime.py:444-472` | P0 |
| P0-5 | 四个进度源互不同意：TaskEvent / payload.progress(5%节流) / task.json / REST 硬编码 0/100 | `api/tasks.py:65`；`workflow_runtime.py:1915-1935, 2042-2055`；前端补丁注释 `WorkflowEditor.tsx:1520-1526` | P0 |
| P0-6 | SQLite 连接池 5/overflow 0，扛不住逐行/0.25s 高频会话 → 进度丢失 | `control_plane/database.py:81`；`workflow_runtime.py:2042-2080, 2094-2109` | P0 |
| P0-7 | 驾驶舱取消调 `request_delete`，对 running/stopping 静默 no-op 却返回 success；前端无取消入口 | `api/creation_tasks.py:162-171`；`workflow_runtime.py:1366-1385`（对比 `request_cancel:1275-1296`） | P0 |
| P0-8 | thread 域长任务无取消检查点：`cancel_callback` 16 处签名接收、0 处调用；引擎轮询期无检查 | `s_agi_comic.py` 各 run() 签名（1219/1306/1446/1770/1908/2030/2144/2308/2442/2531/2681/2792/2938/3109/3241/3379）；`steps/s_ai_videogen.py:167-330` | P0 |
| P1-1 | queued/running 卡死无自愈：worker 挂、Celery 1h 硬杀后 DB 停 running，仅 worker 重启复位 | `celery_runtime.py:40-41, 64-68`；`workflow_runtime.py:808-883` | P1 |
| P1-2 | GPU lane 死亡无检测（service_alive 不查 lane 心跳），调用方干等 3600s | `gpu_service/jobs.py:27-39, 154-158` | P1 |
| P1-3 | GPU manager 重排队用 lpush（队头），消费 BRPOP 取最旧 → 派不出的任务被饿死 | `gpu_service/manager.py:179`（正确写法见同文件 166-167 rpush） | P1 |
| P1-4 | lane 退出时 `clear_lane` 删除整个 lane 队列 → 任务静默丢弃 | `manager.py:57-62`；`gpu_service/jobs.py:201-208` | P1 |
| P1-5 | 驾驶舱任务列表扫全局最近 500 条 + Python 过滤，繁忙时本项目任务跌出窗口 → 前端停轮询、矩阵停刷新 | `api/creation_tasks.py:124-159`；前端 `CreationMatrixPanel.tsx:441-473` | P1 |
| P1-6 | 矩阵与任务态两套语义：失败角标只增不减；台账漏 chapter_id 致失败数恒 0；吞异常仍报 succeeded | `api/creation_selects.py:648-654`；`s_agi_comic.py:1553/1841/1983/2095/1634/2001/2111/612-637` | P1 |
| P1-7 | 杀 PID 竞态：先收集 pid 再置态再杀；pid 在 Popen 之后才写入 | `workflow_runtime.py:1287-1295, 2035-2038` | P1 |
| P2-1 | 引擎调用无超时（LLM/生图/生视频/TTS 同步阻塞） | `s_agi_comic.py:547/686/724/760` | P2 |
| P2-2 | ~~取消/超时被当故障回退重跑~~ **已修复**：asr_factory/separation_factory 现有代码已有 `GpuServiceUnavailableError` 守卫 | `asr/asr_factory.py:156-159`；`separation/separation_factory.py:79-83` | 关闭 |
| P2-3 | `_gpu_service_active()` 只读环境变量不探存活 → manager 挂时无令牌无 lane 裸跑 CUDA | `workflow_runtime.py:113-119` | P2 |
| P2-4 | GPU 文件锁路径依赖 cwd；Redis 挂掉降级进程内信号量（跨进程限流失效） | `control_plane/runtime.py:395, 455-458` | P2 |
| P2-5 | 线程池乘法膨胀：层内池 × 迭代池(4/5) × 迭代内层无界池 × 子工作流，worker 并发仅 2、GPU 容量 1 | `workflow_runtime.py:2278`；`loop_runtime.py:715, 509` | P2 |
| P2-6 | 前端调并发只写 config.yaml，worker 启动时冻结 → 用户以为生效 | `api/batch.py:67-73`；`manager.py:1615` | P2 |
| P2-7 | task.json 跨进程丢更新（`_legacy_lock` 仅进程内） | `workflow_runtime.py:126, 546-590`；`api/tasks.py:113-121` | P2 |
| P2-8 | lane 内无 job 执行超时；VRAM 用 3s 前陈旧采样起 lane；只读第一块 GPU | `gpu_service/lane.py`（无 watchdog）；`manager.py:51, 67`；`gpu_service/monitor.py:21` | P2 |
| P2-9 | 瞬态 DLL 重试期间 `time.sleep(20)` 不查取消，最坏 60s 停不掉 | `workflow_runtime.py:2135-2138` | P2 |

---

## 2. 批次总览

```
第一批 止血（B1-B7）  → 停止链路 + 幂等 + 等待治理 + GPU 饥饿/丢任务 + 查询窗口
第二批 治本（B8-B14） → DB 会话治理 + 进度统一 + stale 回收 + 资产去重 + 角标语义 + GPU 降级
第三批 稳健（B15-B20）→ 并发预算 + 引擎超时 + 取消检查点 + 锁与显存细节 + 配置生效明示
```

每批独立验证上线；任一项可单独回滚（见各项「回滚」）。

---

## 3. 第一批：止血

### B1. 驾驶舱取消改走 request_cancel + 前端停止按钮
- **对应**：P0-7
- **锚点**：`backend/api/creation_tasks.py:162-171`
- **改法**：
  1. `cancel_cockpit_task` 改调 `request_cancel(task_id, "user_requested")`；按返回的任务状态给出真实响应：`running → {"success": true, "result": "stopping"}`、其余非终态 → `cancelled`、终态 → 幂等 `already_finished`。
  2. 前端 `frontend/src/components/creation/CreationMatrixPanel.tsx`：格子悬浮操作与抽屉加「停止」按钮（仅 `isRunning` 时可用），POST `/api/creation/tasks/{task_id}/cancel`；`ACTIVE_TASK_STATUS` 展示区分：queued→「排队中」、running→「进行中」、paused→「已暂停」、stopping→「停止中」。
- **风险**：前端改动涉及 MatrixCellView/抽屉两个渲染点，需保持向后兼容（老后端无该按钮时不渲染）。
- **验收**：运行中点停止 → 任务 3s 内转 `stopping`；process 域子进程被 `taskkill` 消失；接口返回真实状态不再假成功。
- **回滚**：还原 162-171 一行 + 前端按钮隐藏。

### B2. 驾驶舱提交幂等（scope 去 uuid + 在途拦截）
- **对应**：P0-1
- **锚点**：`backend/api/creation_tasks.py:109-111`
- **改法**：
  1. scope 改确定性键：`f"cockpit:{creation_id}:{step_id}:{target}"`，target = `chapter_id` 或 `",".join(sorted(chapter_ids))` 或 `shot_id`。
  2. 依赖 `submit_workflow` 既有单飞保护（`workflow_runtime.py:1185-1195`）：同键非终态任务直接返回 `created=False`。接口响应带 `created` 字段，前端对 `created=False` 提示「该格子已有进行中/排队中的任务」。
  3. `force=True` 时允许对 `queued` 重投（1189 行已有 force 分支）；running/stopping 仍拦截。
- **注意**：同格「失败后重跑」不受影响（终态任务会走重建分支）。
- **验收**：连点 ▶ 5 次只产生 1 个 Task；第二次返回 `created=False`。
- **回滚**：scope 恢复 uuid。

### B3. 资源令牌排队可取消 + 默认获取超时
- **对应**：P0-4
- **锚点**：`backend/control_plane/runtime.py:425-485`（acquire 循环）；`workflow_runtime.py:180-192, 1859-1863`
- **改法**：
  1. `ResourceTokens.acquire()` 增加可选参数 `cancel_check: Callable[[], bool] | None`，Redis 轮询循环（444-472）与本地信号量分支（473-483）每轮调用；为 True 时抛 `TaskCancelledError("cancelled_while_waiting_resource")`。
  2. `workflow_runtime.py:1859-1863` 传入复用 1897-1913 已有的 0.5s 缓存 `cancelled()`（文件优先 + DB 缓存，不增加 DB 压力）。
  3. `_resource_acquire_timeout()`（180-192）默认值 `None` → `900`（保留 `RESOURCE_ACQUIRE_TIMEOUT` 覆盖为 0/空=无限，兼容批量场景）；超时抛 `ResourceLimitError`，`_run_node` 捕获后在节点 payload 写明「等待资源超时(900s)，请重试或提高资源容量」再向上抛（保持现有失败语义，不引入重排复杂度）。
  4. 节点在拿到令牌前保持 `queued` 展示：`node.status="running"`（1751）之前若 `no_token=False`，先写一次 `node_progress` 事件带 `wait_message`（复用 1753-1761 已有 wait_message 机制），并把节点状态语义通过 payload `queued_for_resource=True` 透给前端（B8 消费）。
- **验收**：占满 io 令牌（≥4 任务）后提交第 5 个并停止 → 5s 内 `cancelled`，worker 线程释放；不设取消时 900s 超时给出明确错误而非无限转。
- **回滚**：acquire 参数默认 None 时不改行为；默认超时改回 env 读取逻辑。

### B4. paused 任务超时自动释放 worker 线程
- **对应**：P0-3
- **锚点**：`workflow_runtime.py:1309-1319`
- **改法**：`_wait_until_runnable` 增加 `pause_timeout`（env `WORKFLOW_PAUSE_TIMEOUT`，默认 1800s）；超时后把任务置 `interrupted`（状态机已有，`runtime.py:15-66`），`cancel_reason="pause_timeout"`，抛 `TaskCancelledError("pause_timeout")` 让 `execute_workflow` 收尾。前端对 `interrupted` 展示「已超时暂停，可一键恢复」。
- **验收**：测试环境设 `WORKFLOW_PAUSE_TIMEOUT=60`，paused 任务 60s 后任务变 `interrupted`、worker 线程退出、其他任务可被调度。
- **回滚**：删超时分支。

### B5. GPU manager 重排队端修正 + lane 崩溃不丢任务
- **对应**：P1-3、P1-4
- **锚点**：`backend/gpu_service/manager.py:179`（lpush→rpush）；`manager.py:57-62` + `gpu_service/jobs.py:201-208`（clear_lane 前回收）
- **改法**：
  1. `_dispatch_or_queue` 的 `lpush` 改 `rpush`（与 166-167 注释语义一致：BRPOP 取最旧，rpush 入尾部）。
  2. `_reap` 中 lane 退出时：先把该 lane 专属队列（`jobs.lane_queue_key(lid)`）中所有 job `rpush` 回共享队列，再 `clear_lane`。
  3. `_release_stuck_idle_lanes` 强杀空闲 lane 前同样回收其队列（当前 terminate 后由 `_reap` 统一处理，确认 57-62 覆盖该路径即可，若 terminate 与 reap 之间有窗口则把回收逻辑上移到 terminate 前）。
- **验收**：`kill` 一个 busy lane → 其队列内任务 10s 内回到共享队列并被重新派发，无任务丢失（对比 `wait_result` 3600s 超时日志）。
- **回滚**：两处改回原样。

### B6. lane 存活检测纳入 service_alive
- **对应**：P1-2
- **锚点**：`backend/gpu_service/jobs.py:27-39`
- **改法**：`service_alive()` 在原 manager 状态键新鲜度判断基础上，增加：存在任一 lane 心跳键且新鲜（≤ `heartbeat_ttl`）时也判定存活；仅当「manager 状态键不新鲜 且 无新鲜 lane 心跳」时才不可用。纯查询任务（无 lane 运行时）不应误判——注意空集群场景：manager 刚起、无 lane 时状态键应仍新鲜（确认 `_publish_status` 2s 节流在启动时立即发一次，`manager.py:183-214`）。
- **验收**：manager 存活 → True；kill manager → 60s 内 False；manager 起但无 lane → True。
- **回滚**：还原函数。

### B7. 驾驶舱任务查询下推过滤（去掉 500 条窗口）
- **对应**：P1-5
- **锚点**：`backend/api/creation_tasks.py:124-159`
- **改法**：
  1. SQL 层按 `payload` JSON 过滤：`func.json_extract(Task.payload, "$.input.creation_id") == creation_id`（SQLite JSON1 扩展，WAL 模式可用；实施时先验证一条 SQL）。
  2. `limit` 上限 50 → 200；仍按 `created_at desc`。
  3. 前端轮询逻辑不变（4s），窗口修复后不会再漏。
- **验收**：灌入 ≥600 条非本项目任务后，本项目全部驾驶舱任务仍能列出（对比修复前跌出窗口）。
- **回滚**：还原 Python 过滤。

---

## 4. 第二批：治本

### B8. DB 会话治理（进度丢失根因）
- **对应**：P0-6
- **锚点**：`backend/control_plane/database.py:81`；`workflow_runtime.py:2042-2080, 2094-2109`
- **改法**：
  1. `pool_size=5, max_overflow=0` → `pool_size=20, max_overflow=10`（SQLite WAL 下多连接读无碍，写仍串行但 15s busy_timeout 足够）。
  2. `@LOG@` 行（`_handle_line` 分支）不写 `TaskEvent`，只转发 stdout（日志落文件已有机制）；`node_progress` 事件保持每次写入（细粒度权威源）。
  3. `_run_node_subprocess` 轮询循环（2094-2109）0.25s DB 查询改：取消文件存在性每轮查（本地 stat，无 DB），`_cancel_requested` DB 查询降到每 2s 一次（内存时间戳节流）。
  4. task.json 跨进程写保护（P2-7）：`_write_legacy_task` 的 `_legacy_lock` 从进程内 `threading.Lock` 升级为文件锁（复用 `backend/utils/engine_lifecycle.py` 的 msvcrt/fcntl 模式），API 侧 `_legacy_task_json_lock`（`api/tasks.py:113-121`）指向同一路径。
- **验收**：3 个并发任务 × 每任务 20+ 节点 + 高频 progress 跑完，worker 日志无 `QueuePool limit` / `database is locked`；刷新页面进度不回跳。
- **回滚**：逐项还原；连接池参数可热改。

### B9. 进度源统一（四方一致）
- **对应**：P0-5
- **锚点**：`backend/api/tasks.py:65`；`creation_tasks.py:145-156`；`CreationMatrixPanel.tsx:265/604`；`s_agi_comic.py` 各 `callback`
- **改法**：
  1. `api/tasks.py:65` 硬编码 `100/0` 改读 `node.payload.get("progress", 0)`（缺失时回落 100/0）。
  2. `creation_tasks.py` 列表返回补 `progress`、`wait_message`、`node_label`（从首个 TaskNode.payload 读）。
  3. 前端矩阵：queued/running/paused/stopping 四态分别渲染（排队中/进行中/已暂停/停止中），展示 `wait_message` 或 `progress%`；`WorkflowEditor.tsx:1520-1526` 的兼容补丁在 1 生效后评估移除。
  4. `s_agi_comic.py` 16 个 `run()` 收尾补 `callback(100, "完成")`（当前最高 90/95，`2842-2904` 等）。
- **验收**：同一任务并行对比 `/ws/tasks/{id}` 事件流、`GET /api/tasks/{id}`、`task.json`、矩阵 UI 四者进度一致（允许事件流更细）。
- **回滚**：逐项还原。

### B10. stale 任务周期回收（API 进程 reaper）
- **对应**：P1-1
- **锚点**：新代码 + `main.py:499-506`（现有 recovery 开关旁挂载）；复用 `workflow_runtime.py:808-883` 置态逻辑
- **改法**：API 进程启动时起 daemon 线程，每 60s：
  1. `queued` 且 `dispatch_token==DISPATCH_STALE` 或 `dispatch_token_at` 超过 10 分钟 → 置 `interrupted`（`cancel_reason="dispatch_lost"`），发通知；
  2. `running` 且任意节点 `payload.timings.started_at` 超过 `节点 timeout × 2` → 置 `interrupted`（`cancel_reason="node_timeout"`）。
  3. reaper 只改 DB 状态、不杀进程（真正在跑的由 worker/Celery 时限处理；DB 复位避免前端永久转圈后用户可手动重跑）。
  4. env `CONTROL_PLANE_REAPER=1` 默认开。
- **验收**：全杀 worker 只留 API → 2 分钟内 queued/running 任务变 `interrupted`，前端出现「可重试」；正常跑动的任务不被误判（started_at 在持续更新）。
- **回滚**：env 置 0 即关闭。

### B11. 资产并发去重（占位台账）
- **对应**：P0-2
- **锚点**：`s_agi_comic.py:2842/2988/3141/3269`（判重）；`creation/store.py:716-731`（register_asset）；`s_agi_comic.py:612-637`（_log_generation）
- **改法**：
  1. 媒体类步骤生成前先插一条 `cp_generation_tasks` 占位行（`status="running"`，带 `chapter_id/step_id/target/kind`）；后到者发现同键 running 行 → 跳过该 target（记 warning）。
  2. 成功/失败更新同一行（不再每次 insert 新行）——同时解决 B12 的「失败角标只增不减」。
  3. `register_asset` 保持 insert，但因 1 的拦截不会双跑；另加一道软保护：`register_asset` 前查同 `(asset_scope, kind, ord)` 是否已有 `is_deleted=0` 行，有则更新而非插入。
- **风险**：台账表结构若缺 target 维度字段需加迁移（alembic，down 指向当前 head）。
- **验收**：绕过 B2 强行并发两次同格 → 第二次秒退，资产表无双份，台账单行状态流转 running→success/failed。
- **回滚**：占位逻辑可配置开关（env 或步骤 config 字段）。

### B12. 失败角标语义 + 台账归属修复
- **对应**：P1-6
- **锚点**：`api/creation_selects.py:648-654`；`s_agi_comic.py:1553/1841/1983/2095/1634/2001/2111`
- **改法**：
  1. 矩阵失败数改为「每个 (chapter, step) 取最近一次台账结果」：failed 仅当最新一行 status=failed；结合 B11 单行更新天然成立。
  2. character/scene/prop/voice 的 `_log_generation` 补 `chapter_id`（无章节的节点传 `""`，前端按 step 归并展示）。
  3. 吞异常节点（1634/2001/2111）：except 内记 failed 台账 + `callback(进度, "跳过原因：...")`，节点最终状态保持 succeeded 但 UI 可见跳过原因（或改 failed——需评估对整章批处理的影响，建议保持 succeeded + 台账 failed + 文案）。
- **验收**：失败一次 → 重跑成功 → 红角标消失；抽屉可见跳过原因。
- **回滚**：还原统计 SQL 与台账补参。

### B13. GPU 服务降级路径加存活探测（manager 挂时不裸跑）
- **对应**：P2-3
- **锚点**：`workflow_runtime.py:113-119`（`_gpu_service_active`）；`asr/asr_factory.py:141-142`；`separation/separation_factory.py:73-74`
- **改法**：
  1. `_gpu_service_active()` 增加 `jobs.service_alive()` 探测结果缓存（5s TTL，避免每节点一次 Redis 查询）。
  2. `gpu_service/client.py` 的 `gpu_service_enabled()` 语义保持（lane 内防递归）；在 `asr_factory`/`separation_factory` 调用处改为「enabled 且 alive」才走服务，否则直接进程内 + 由 `_resource_for` 正常扣 gpu 令牌（现状：ASR/分离节点在 GPU 服务启用时被标 RESOURCE_FREE，`workflow_runtime.py:455-465`；alive 探测失败时该特判不生效 → 自动回到扣令牌路径）。
- **验收**：停掉 gpu manager 后跑 ASR/分离 → 走 `locks/gpu.lock` 令牌路径（日志可见「等待 GPU 资源」），不再无管控并发 CUDA。
- **回滚**：还原探测。

### B14. 杀 PID 竞态收敛
- **对应**：P1-7
- **锚点**：`workflow_runtime.py:1284-1295`；`2035-2038`
- **改法**：
  1. 收集 pid 与置 `stopping` 放同一 `session_scope` 事务内（现为两段）。
  2. `kill_process_tree` 前校验：PID 仍存在且进程启动时间不早于节点 `started_at - 5s`（Windows 用 `psutil` 或 `wmic` 取创建时间；无 psutil 则校验命令行包含 `step_worker` 与 task_id）。
  3. `worker_pid` 写入时机保持 Popen 后立即写（现状可接受），但在写入前若收到取消，下一轮循环（2094-2109）会感知，无遗漏窗口 >0.25s。
- **验收**：任务刚起步即取消 → 无「任务消失但进程还在」；取消后 `taskkill` 日志中的 pid 均对应本任务子进程。
- **回滚**：还原两段式。

---

## 5. 第三批：稳健

### B15. 全局并发预算（收敛线程池乘法膨胀）
- **对应**：P2-5
- **锚点**：`workflow_runtime.py:2274-2295`（层内池）；`loop_runtime.py:509, 715`
- **改法**：新增进程内 `ConcurrencyBudget`（worker 单进程内共享即可，因为 worker 并发=2 已是上限）：层内池与迭代池创建时 `max_workers=min(配置值, budget.acquire(n))`，池退出归还；子工作流展开同样纳入。目标：worker 内活跃线程峰值 ≤ `concurrency × 4`。
- **验收**：压测工作流（loop×5 × 层内 3 节点）时 `threading.active_count()` 峰值 ≤8；GPU 等待日志不刷屏。
- **回滚**：预算开关 env。

### B16. 引擎调用分级超时
- **对应**：P2-1
- **锚点**：`s_agi_comic.py:547`（_llm）、`686`（_gen_images）、`724`（_gen_video）、`760`（_tts）
- **改法**：透传超时参数——LLM 300s、生图 600s、生视频轮询 1800s（沿用 wrapper 已有默认值处仅做显式化）、TTS 300s；超时记 failed 台账并抛出明确错误；单 target 失败不中断整章（现状批处理已有 per-target 容错则保持）。
- **验收**：mock 一个永不返回的引擎端点 → 300s 后该 target failed、章节其余继续。
- **回滚**：超时参数默认关（env 开）。

### B17. thread 域取消检查点补齐
- **对应**：P0-8
- **锚点**：`s_agi_comic.py` 16 个 run()（targets 循环 + 引擎调用前后）；`steps/s_ai_videogen.py:167-330`；`s08_dub_task.py:772`
- **改法**：每个 target 循环迭代首行 + 引擎轮询循环每轮调用 `cancel_callback()`（签名已接收，目前 0 调用）；`cancel_callback` 抛 `TaskCancelledError` 由框架捕获标记 cancelled。`s_ai_videogen` 在 20/40/80 里程碑之间插入轮询期检查（引擎 SDK 轮询循环内）。
- **验收**：thread 域节点（如 agi_chapter/agi_shot）运行中停止 → ≤30s 内退出，DB 状态 cancelled。
- **回滚**：逐步骤还原。

### B18. GPU 文件锁路径固化 + Redis 降级告警
- **对应**：P2-4
- **锚点**：`control_plane/runtime.py:390-398`
- **改法**：`_gpu_lock_path` 的 cwd 回退分支改为固定数据根（`CONTROL_PLANE_DATA_ROOT` 或 `~/.videolingo/locks`），保证 API 进程与 worker 进程（cwd 可能不同）解析同一路径；Redis 降级为进程内信号量时打一条 WARN（每资源一次）。
- **验收**：不同 cwd 启动两个进程抢 gpu 令牌 → 互斥生效（修复前互斥失效）。
- **回滚**：路径函数还原。

### B19. GPU lane 执行超时 watchdog + VRAM 采样修正
- **对应**：P2-8
- **锚点**：`backend/gpu_service/lane.py`；`manager.py:51, 67`；`monitor.py:21`
- **改法**：
  1. lane 执行 job 起 watchdog 线程：超过 `config.job_timeout()` 未返回 → 记录 + 终止当前 job（回报 `TimeoutError` 结果键），lane 自身保持存活继续接任务。
  2. `_spawn_lane` 用当前 `_vram` 前先同步采一次 `gpu_info()`（若上次采样 >1s）；多卡时取「总可用显存最小的一张」或日志明示单卡假设（先做日志）。
- **验收**：mock 一个挂死的 lane job → watchdog 到点杀 job 并回报超时，调用方 3600s 等待缩短为 job_timeout；连续提交 4 个 ASR 不再基于同一陈旧采样起到超额 lane。
- **回滚**：watchdog env 开关。

### B20. 配置生效明示 + DLL 重试期可取消
- **对应**：P2-6、P2-9
- **锚点**：`api/batch.py:67-73`；`manager.py:1615`；`workflow_runtime.py:2135-2138`
- **改法**：
  1. 设置接口保存并发后，若与当前 worker 实际并发不同，响应带 `restart_required: true`，前端提示「重启后生效」。
  2. 瞬态 DLL 重试 `time.sleep(20)` 改 5s，且每次睡前后查取消标记（文件存在即退出重试循环抛 TaskCancelledError）。
- **验收**：设置页改并发出现重启提示；取消一个正在 DLL 重试窗口的任务 → ≤5s 停止。
- **回滚**：还原。

---

## 6. 配置变更清单

| 配置 | 现值 | 新值 | 位置 | 批次 |
|---|---|---|---|---|
| `RESOURCE_ACQUIRE_TIMEOUT` | 未设（=无限） | `900`（代码默认值，env 可覆盖） | `workflow_runtime.py:180-192` | B3 |
| `WORKFLOW_PAUSE_TIMEOUT` | 无 | `1800`（env 可覆盖） | `workflow_runtime.py:1309-1319` | B4 |
| `CONTROL_PLANE_REAPER` | 无 | `1` | 新 reaper | B10 |
| SQLite 连接池 | 5/0 | 20/10 | `database.py:81` | B8 |
| `CELERY_HARD_TIMEOUT` / `CELERY_SOFT_TIMEOUT` | 3600/3300 | 不变（B10 reaper 接管 DB 侧） | `celery_runtime.py:40-41` | — |
| `GPU_SERVICE_JOB_TIMEOUT` | 3600 | 不变（B19 才真正强制执行） | `gpu_service/config.py` | B19 |

> 若新增环境变量，同步更新 `docs/依赖清单.md` / `.runtime/local_env.bat` 注释与安装文档（遵循项目规则：依赖/环境变更同步文档）。

---

## 7. 验证矩阵（每批完成后执行）

| # | 场景 | 操作 | 预期 |
|---|---|---|---|
| V1 | 重复提交 | 矩阵同格连点 ▶ 5 次 | 1 个 Task，第 2~5 次 `created=False` |
| V2 | 取消（process 域） | agi_shot_frames 运行中停止 | ≤5s `stopping`，子进程消失 |
| V3 | 取消（thread 域） | agi_chapter 运行中停止（B17 后） | ≤30s `cancelled` |
| V4 | 排队中取消 | 占满 io 令牌后提交并停止第 5 个 | ≤5s `cancelled`，worker 线程释放 |
| V5 | paused 超时 | `WORKFLOW_PAUSE_TIMEOUT=60`，paused 一个任务 | 60s 后 `interrupted`，其他任务可调度 |
| V6 | lane 崩溃 | busy lane 上 `kill -9` | 队列任务 10s 内重派，不丢 |
| V7 | lane  watchdog | mock 挂死 job | job_timeout 到点回报超时 |
| V8 | GPU 降级 | 停 gpu manager 跑 ASR | 走 gpu 令牌路径，日志「等待 GPU 资源」 |
| V9 | 进度一致 | 跑一整章，四源对比 | REST/WS/task.json/UI 一致 |
| V10 | DB 池 | 3 并发 × 20 节点 | 无 QueuePool / database is locked |
| V11 | 窗口 | 灌 600 条历史任务 | 本项目任务全列出，矩阵持续刷新 |
| V12 | 角标 | 失败一次后重跑成功 | 红角标消失 |
| V13 | 并发去重 | 绕过 UI 强行并发两次同格 | 第二次秒退，无双份资产 |
| V14 | worker 全死 | 杀全部 worker 留 API | 2 分钟内 queued/running → `interrupted` |
| V15 | 冷编译 | `python -m py_compile` 全部改动文件 | 通过 |

---

## 8. 风险与回滚总则

1. **状态机新增值**：B4/B10 使用既有 `interrupted`，不扩状态集；`paused`→`interrupted` 迁移需确认 `runtime.py` `_TRANSITIONS` 放行（先读后改）。
2. **DB 迁移**：B11 若加台账字段，须 alembic 迁移 + down 指向当前 head；上线前 `alembic heads` 单头校验。
3. **每项独立可回滚**：优先 env/配置开关，其次 git 单文件还原；批次间不交叉依赖（B11 依赖 B2 降级体验但不阻塞）。
4. **前端兼容**：新增按钮/状态对旧后端优雅降级（字段缺失时不渲染）。
5. **不动**：Celery 并发默认 2、GPU lane 容量、既有引擎接口签名；这些属运行调优，计划外单独评估。

---

## 9. 进度跟踪

- [x] 调查报告（四路并行探查 + 交叉验证）
- [x] 修改计划与清单（本文）
- [x] 第一批 B1-B7（2026-10-13 完成，自测通过：超时默认值/排队取消/获取超时/lane 回收/存活探测/JSON 下推；前端 tsc 零错误）
  - 实施备注：B4 因 `paused→interrupted` 不在任务迁移表，超时收尾改用 `cancelled + cancel_reason=pause_timeout`；
  - B3 默认获取超时取 1800s（原计划 900s，放宽以避免大章节批处理误判失败；`.runtime/local_env.bat` 已显式设 900，env 优先）；
  - `runtime.py` 本地信号量分支重写为轮询+探针，Redis 降级路径也支持取消（自测覆盖）。
- [x] 第二批 B8-B14（2026-10-13 完成，自测 A/B/C 全过）
  - B8：连接池 5/0→20/10；`@LOG@` 批量落库（20 条或 1s，前端 node_log 消费不变）；子进程轮询 DB 查询 2s 节流 + 取消标记文件优先；task.json 改「进程内全局锁 + 按任务跨进程文件锁」（含同线程重入防护——自测曾抓到嵌套死锁并修复）。
  - B9：`_task_node_state` 改读 `payload.progress`（终态强制 100，成功块统一写 progress=100）；未逐个改 s_agi_comic 的 16 处 callback（中心修复覆盖全部节点类型，避免 16 处高风险散改）；前端 WorkflowEditor 补丁注释更新。
  - B10：新增 `backend/control_plane/stale_reaper.py`（60s 周期，queued 僵尸 120min / running 卡死 90min 阈值，均 env 可调；置 interrupted/cancelled + 节点复位 pending + dispatch 哨兵；不杀进程防 PID 复用误杀）；main.py 启动挂载。**首跑即在开发库发现并回收 7 个真实僵尸 queued 任务**。
  - B11：`_claim_target` 占位台账（running 行拦截并发双跑，1800s 陈旧自动回收，全程 fail-open）；frames/video/dub 三个生成循环接入；`register_asset` 经评估**不改**（同 shot+kind 多候选是合法重复，去重应放在占位层）。
  - B12：矩阵角标改「同目标最近一次结果」；三个吞异常处补失败台账；`list_generation_tasks` 排序改 `COALESCE(updated_at, created_at) DESC`；顺带修复 `TimestampedVersioned.updated_at` 缺 Python 默认值导致新行插入 NULL 的迁移漂移问题。
  - B13：`_gpu_service_active` 加 `service_alive` 探测（5s TTL 缓存）；引擎侧 `_submit_and_wait` 本就有存活前置检查，无需改 asr_factory。
  - B14：`request_cancel` 落取消标记文件（各检查点第一信号）+ `_kill_pid_safely` psutil 校验命令行（非 step_worker 跳过）；`_run_node` 入口清理遗留标记（修「重跑即取消」潜在缺陷）。
- [x] 第三批 B15-B20（2026-10-14 完成，自测 8 组全过，前端 tsc 零错误）
  - B15：`runtime.py` 新增 `ConcurrencyBudget`（默认 8，env `CONTROL_PLANE_THREAD_BUDGET` 可调；非阻塞申请、保底 1 的软上限）；层内池（workflow_runtime）、循环迭代池与迭代内层池（loop_runtime，ExitStack 接入）统一从预算官道申请。
  - B16：生图 600s / 生视频 1800s / TTS 300s 经 `_call_engine` 签名过滤透传（引擎不支持自动剔除，cfg.*_timeout 可覆盖）；LLM 侧 llm_client 本就有 120s 级超时+重试，无需改。
  - B17：`base_step.step_check_cancel` 共享检查点；s_agi_comic 16 处（7 个 thread 域节点循环头 + 5 处 LLM 调用前 + 媒体循环）；`s_ai_videogen` 增加 `cancel_callback` 参数 + on_progress 取消探针（签名适配多 SDK，取消抛内部异常外层转 TaskCancelledError；agnes 吞回调异常的路径靠进程杀兜底）；`s08_dub_task` 补 72→100 间隙检查点。
  - B18：GPU 锁路径 cwd 兜底改确定性 `<项目根>/data`（自测验证跨 cwd 一致）；Redis 降级进程内信号量时每资源告警一次。
  - B19：lane 执行看门狗（超 `GPU_SERVICE_JOB_TIMEOUT` 回报超时结果后 `os._exit` 释放显存，manager reap 接管）；客户端等待超时默认与看门狗阈值对齐（`config.job_timeout()`）；manager 起 lane 前 1s 陈旧补采显存；monitor 多卡识别（gpu_count + free 取 device 0 + manager 启动告警）。
  - B20：`PUT /api/batch/config` 响应带 `worker_restart_required` 明示；设置页「最大并发任务数」补重启生效提示（BatchWorkshop 原有提示保留）；DLL 重试等待改 4×5s 分片睡 + 取消检查（最坏 60s 停不掉 → 5s）。
- [x] 全量验证矩阵 V1-V15：代码级/单函数级/端到端（合成任务）验证已完成；V3/V5/V7/V9/V10 等需起真实 worker + 真实引擎的场景测试待用户环境执行（见「遗留事项」）。

## 10. 遗留事项（需真实运行环境）

1. **场景测试**：V3（thread 域节点运行中停止，≤30s 退出）、V5（paused 超时收尾）、V7（lane watchdog 强杀挂死 job）、V9（四源进度对比）、V10（3 并发任务无 QueuePool 报错）——需启动完整后端（manager + redis + worker + gpu service）后执行。
2. **配置调优**：`CONTROL_PLANE_THREAD_BUDGET`（默认 8）、`CONTROL_PLANE_STALE_*_MINUTES`（120/90）、`GPU_SERVICE_JOB_TIMEOUT`（3600）按实际机器（显存/核数）调整。
3. **多卡利用**：当前 lane 全部走 device 0；多卡机器如需真并行，需给各 lane 分配 `CUDA_VISIBLE_DEVICES`（已告警提示，未实现）。
4. **agnes 引擎取消**：其包装层吞 on_progress 异常，云轮询期取消仍靠节点超时/进程杀；如常用该引擎，可在 wrapper 内传播取消异常。
5. **git 提交**：三批改动尚未提交；`workflow_runtime.py`/`runtime.py` 按项目规则只在本地（闭源模块），其余文件 + 新文件 `stale_reaper.py` 可入库。
