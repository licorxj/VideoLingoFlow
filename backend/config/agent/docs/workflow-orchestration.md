# 工作流编排（Workflow Orchestration）

指导 agent 理解 VideoLingoFlow（中文：流连视听）的工作流（workflow）数据模型、运行引擎、节点连接语义，以及如何新增/修改一个工作流。工作流是用户在前端用可视化编辑器搭建的"任务流水线"，由后端运行引擎按拓扑执行。

> 本文档基于 `backend/control_plane/workflow_runtime.py`、`backend/api/workflows.py`、`backend/config/workflows/*.json`、`frontend/src/components/workflow/*` 的**当前实现**。

---

## 1. 工作流数据模型（JSON 结构）

工作流是一份 JSON，顶层含 `id` / `name` / `nodes[]` / `edges[]`。模板存放于 `backend/config/workflows/*.json`。

### 1.1 节点（node）

```json
{
  "id": "node_1_1780590163157",    // 全局唯一（前端用 `<seq>_<时间戳>` 生成）
  "type": "asr",                    // 必须是 builtin_node_types 或自定义节点中的 id
  "position": { "x": 100, "y": 200 },
  "data": {
    "label": "语音识别",
    "config": { "model": "whisperx", "device": "cuda" },   // 表单字段值
    "inputs":  { "video": "..." },   // 可选静态输入
    "outputs": { "subtitle": "..." } // 可选静态输出覆盖
  }
}
```

### 1.2 边（edge）

```json
{
  "id": "xy-edge__nodeAout-subtitle-nodeBin-subtitle",
  "source": "node_1_...",            // 源节点 id
  "target": "node_2_...",            // 目标节点 id
  "sourceHandle": "out-subtitle",    // 源输出 pin：out-<pin_name>
  "targetHandle": "in-subtitle",     // 目标输入 pin：in-<pin_name>
  "type": "xy-edge"
}
```

**pin 命名规则**：输出 `out-<name>`，输入 `in-<name>`，`<name>` 须与节点定义中 `inputs[].name` / `outputs[].name` 一致。引擎据此把上游 `outputs[name]` 注入下游 `inputs[name]`。

---

## 2. 运行引擎

入口：`backend/control_plane/workflow_runtime.py`（类 `WorkflowRuntime`）。

执行流程：
1. 加载工作流 JSON，构建节点图；
2. 拓扑排序，确定执行顺序（含 `condition`/`loop`/`merge` 等控制流）；
3. 装入 `ThreadScheduler`（线程池，`max_workers` 默认 3）或 Celery（异步/重型）；
4. 逐节点执行 `BaseStep.execute()`，按 edge 注入输入、收集输出；
5. 资源令牌：按 `RESOURCE_BY_NODE_TYPE` / `RESOURCE_FREE_NODE_TYPES` 限流（见 capability-index）；
6. GPU 类节点（`GPU_SERVICE_MANAGED_NODE_TYPES`）若启用 GPU 服务层则转交 lane；
7. 进度经 WebSocket 推前端；状态写入 `task.json` 与 `data/control-plane.db`。

状态机：`runtime.transition()` 实现 `pending→running→success/failed/cancelled/timeout`，非法转换抛 `InvalidTransition`；取消抛 `TaskCancelledError`，超时抛 `TaskTimeoutError`。

### 2.1 控制流节点

- `workflow`：嵌套子工作流
- `condition`：条件分支（按表达式决定走哪条边）
- `loop`：循环
- `merge`：汇聚多分支
- `delay` / `run_wait`：延时/等待
- `input` / `output`：工作流级变量
- `comment`：仅注释

---

## 3. 服务端口与接口

- 主后端（业务 API / WebSocket）：**11001**
  - 工作流/任务路由：`backend/api/workflows.py`（含 `TASKS_ROOT = tasks/`，调试任务目录前缀 `flow_`）
  - 实时进度 WebSocket：`/ws`（`backend/api/ws.py`，`@router.websocket("/tasks/{task_id}")`）
- Manager 控制面：**18001**
- 前端 dev server（Vite）代理 `/api`→11001、`/ws`→11001

> 不要假设 8000 或 5173 为主后端端口。前端编辑器本身在 Vite dev server 运行，但其 API 调用都打到 11001。

---

## 4. 内置/示例工作流

`backend/config/workflows/` 下存放若干已保存工作流（如 `335a15de09bc.json`、`55c6efda5e76.json`、`7032ce81b6df.json`）。这些可作为搭建新流水线的参考。新增工作流建议：
- 复制一份相近模板，改 `id` / `name` / 节点与边；
- 通过前端编辑器可视化校验后再保存；
- 或在 `backend/api/workflows.py` 提供的保存接口中提交。

---

## 5. 新增/修改工作流 Checklist

- [ ] 节点 `type` 必须存在于 `builtin_node_types.py` 或 `backend/config/node_types/*.json`
- [ ] 边 `sourceHandle`/`targetHandle` 的 pin 名与节点 `inputs/outputs` 一致
- [ ] 每个非根节点有入边；避免环（控制流节点除外）
- [ ] `data.config` 字段与节点 `form_schema` 对齐
- [ ] 资源占用节点按 `RESOURCE_BY_NODE_TYPE` 受控（GPU→服务层，TTS→tts 令牌）
- [ ] 保存后在 11001 跑一次最小验证（见 task-execution.md）

---

## 6. 常见错误

1. **端口错**：把 API 当成 8000，实际 11001。
2. **pin 名拼错**：edge handle 与节点 io 名不一致 → 输入缺失。
3. **用了不存在的节点 type**：未在 `builtin_node_types` 或自定义节点注册。
4. **绕过资源登记**：新增 GPU/TTS 节点未登记 → 并发压垮本地资源。
5. **手写 JSON 漏字段**：优先用前端编辑器生成，再导出/保存。
