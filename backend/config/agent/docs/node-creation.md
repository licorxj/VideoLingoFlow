# 节点创建（Node Creation）

本章说明如何为 VideoLingoFlow 新增一个**节点（node）**。节点分两类：

1. **内置节点（built-in）**：在仓库源码里定义（前端展示元数据 + 后端 Step 实现），需改代码并重启后端。
2. **自定义节点（custom）**：通过 `POST/PUT /api/node-types` 写入 `backend/config/node_types/<id>.json`，无需改源码、无需重启，运行时由 `control_plane/custom_node_runtime.py` 执行。

两类节点都复用同一套**节点类型定义**驱动前端编辑器的连线、配置项与运行。

---

## A. 内置节点类型定义

### A.1 入口文件

`backend/config/builtin_node_types.py` 维护一个 Python 列表 `BUILTIN_NODE_TYPES`，每个元素是一个 dict。该文件还提供：

- `get_builtin_node_types() -> list[dict]`：返回全部节点类型（前端 `GET /api/node-types` 数据源之一）。
- `get_builtin_node_type(node_id) -> dict | None`
- `is_builtin_node_type_deleted(node_id) -> bool`：内置节点被软删除后返回 True（隐藏但保留历史引用）。

### A.2 字段规范

```python
{
    "id": "srt_to_json",                       # 节点类型唯一 id（字符串）
    "name": "SRT 字幕转 JSON",                 # 展示名
    "execution_domain": "thread",              # 见 A.4
    "category": "tools",                       # 分组 key（见文件顶部 CATEGORIES）
    "description": "把 SRT 字幕转成 ASR 结果格式 JSON",
    "icon": "...",                             # 前端图标标识
    "color": "...",                            # 前端卡片主题色
    "inputs": [                                # 输入端口（用 id，不是 name）
        {"id": "subtitle", "label": "字幕", "type": "subtitle", "required": True},
    ],
    "outputs": [                               # 输出端口
        {"id": "json", "label": "ASR JSON", "type": "filepath"},
    ],
    "defaultConfig": {                         # 默认配置（key 与 configFields 对应）
        "target_fps": 30,
    },
    "configFields": [                          # 前端设置面板
        {
            "key": "target_fps",
            "label": "目标帧率",
            "type": "number",                  # text/number/slider/select/toggle/textarea 等
            "default": 30,
            "min": 1, "max": 60, "step": 1,
        },
        {
            "key": "mode",
            "label": "模式",
            "type": "select",
            "options": [                       # select 用 options
                {"label": "最长时长", "value": "longest"},
                {"label": "主音轨为准", "value": "main"},
            ],
            "default": "longest",
        },
    ],
}
```

**命名要点（易错点）：**
- 输入/输出端口用 `id`（如 `"subtitle"`），不要写成 `name`。
- 设置面板用 `configFields`，默认值放 `defaultConfig`（不是 `default_config` / `form_schema`）。
- 端口 `type` 用受控类型（`filepath` / `subtitle` / `audio` / `text` / `json` / `video` 等），同类型端口才能连线。

### A.3 后端 Step 实现

Step 写在 `backend/steps/s_*.py`，继承 `backend/steps/base_step.py::BaseStep`。

```python
# backend/steps/s_srt_to_json.py
import os, json
from backend.steps.base_step import BaseStep
from backend.utils.srt_to_json import parse_srt


class S_SrtToJson(BaseStep):
    step_id = "srt_to_json"                    # 仅用于日志

    def check_artifact(self, task_dir):        # 产物是否已完成
        node_id = getattr(self, "_node_id", "")
        name = f"srt_to_json_{node_id}.json" if node_id else "srt_to_json.json"
        return os.path.isfile(os.path.join(task_dir, "cache", name))

    def validate_inputs(self, task_dir):       # 上游输入是否就绪
        raw = (getattr(self, "_step_inputs", {}) or {}).get("subtitle")
        if isinstance(raw, list):
            raw = raw[0] if raw else None
        path = raw if isinstance(raw, str) else None
        return bool(path) and os.path.isfile(path)

    def run(self, task_dir, callback=None, cancel_callback=None):
        node_id = getattr(self, "_node_id", "")
        cache_dir = os.path.join(task_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)

        raw = (getattr(self, "_step_inputs", {}) or {}).get("subtitle")
        if isinstance(raw, list):
            raw = raw[0] if raw else None
        srt_path = raw if isinstance(raw, str) else None
        if not srt_path or not os.path.isfile(srt_path):
            raise ValueError("SRT 转 JSON 失败：未提供有效的字幕文件路径")

        if callback:
            callback(10, f"读取 SRT：{os.path.basename(srt_path)}")
        with open(srt_path, "r", encoding="utf-8") as f:
            entries = parse_srt(f.read())

        segments = [...]                       # 解析为 segments
        asr_result = {"language": "und", "text": " ".join(...), "segments": segments}

        out_name = f"srt_to_json_{node_id}.json" if node_id else "srt_to_json.json"
        out_path = os.path.join(cache_dir, out_name)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(asr_result, f, ensure_ascii=False, indent=2)

        if callback:
            callback(100, f"完成：{len(segments)} 条字幕")
        return {
            "artifacts": [os.path.join("cache", out_name)],
            "outputs": {"json": os.path.join("cache", out_name)},
        }
```

**BaseStep 接口要点：**
- 方法名是 `check_artifact` / `validate_inputs` / `run`（没有 `_pre_execute` / `_execute` / `_post_execute`）。
- 没有 `StepContext` / `StepResult` 对象。`run` 直接接收 `task_dir`（字符串），返回普通 dict。
- 运行时在调用 `run` 前注入三个实例属性（见 `control_plane/step_worker.py`）：
  - `self._node_id`：节点实例唯一 id（用于产物文件名后缀）。
  - `self._step_config`：节点 `data.config`。
  - `self._step_inputs`：连线解析后的输入，键为输入端口 `id`，值为文件路径字符串或列表。
- 进度上报：在 `run` 内调用 `callback(percent: int, message: str)`（若非 None）。
- 协作取消：按需调用 `cancel_callback()`（若提供），返回 True 表示已取消。
- 产物命名约定：`{base}_{node_id}{ext}`（如 `asr_result_a1b2c3.json`）。读取用模块级函数 `find_artifact(directory, base_name)` 反查（见 `file-management.md`），不要硬编码完整文件名。
- `BaseStep` 另提供 `rollback(task_dir)` / `clear_artifact(task_dir)`（按 `artifacts` 清理）与 `_all_exist(task_dir, files)`。

### A.4 execution_domain（执行域）

- `thread`：在线程池内执行（绝大多数节点）。
- `process`：在独立子进程执行（`control_plane/step_worker.py` 以 `python -m ...` 启动），用于重型/长时推理以释放 GIL、隔离崩溃。
- `llm`：以 LLM 调用方式执行（部分 LLM 类节点）。

GPU 计算**不是**一个执行域。GPU 类节点（`asr` / `vocal_separation` / `track_separation`）仍声明为 `process` 或 `thread`，运行时根据 `GPU_SERVICE_MANAGED_NODE_TYPES` 决定交给 GPU 服务层显存 lane（见 `gpu-service.md`）。

### A.5 注册 Step

当前注册表在 `backend/steps/step_registry.py`：模块级 dict `_STEPS`，把 step id 映射到**实例化后的 Step 对象**。控制平面执行时通过 `get_step_instance(step_id)` 取实例（`step_worker.py`、`workflow_runtime.py` 都走它）。

```python
# backend/steps/step_registry.py 的 _STEPS 末尾追加：
from backend.steps.s_srt_to_json import S_SrtToJson

_STEPS = {
    # ... 既有条目 ...
    "s_srt_to_json": S_SrtToJson(),    # 历史 sNN_* 风格 key（兼容）
    "srt_to_json": S_SrtToJson(),      # 与节点类型 id 一致的主 key（必加）
}
```

必须同时加上 `s_<name>` 与 `<node_type_id>` 两个 key（前者兼容旧引用，后者是节点连线实际使用的）。完成后前端即可连线运行该节点。

`backend/engine/thread_scheduler.py` 里另有一份遗留的 `BUILTIN_STEP_REGISTRY`（节点 id → (module, class)），服务于旧的 ThreadScheduler 线程池路径；控制平面执行路径不需要改它，新增节点只改 `step_registry._STEPS` 即可。

---

## B. 自定义节点（无需改源码）

通过节点类型 REST API 写入 `backend/config/node_types/<id>.json`：

- `POST /api/node-types`：新建。
- `PUT /api/node-types/{id}`：更新。
- `DELETE /api/node-types/{id}`：删除自定义节点（内置节点删除会写隐藏记录，可能使引用它的工作流失效）。

请求体（节选）：

```json
{
  "id": "my_custom_node",
  "name": "我的自定义节点",
  "isBuiltIn": false,
  "execution_domain": "process",
  "category": "tools",
  "inputs":  [{"id": "in",  "label": "输入", "type": "filepath", "required": true}],
  "outputs": [{"id": "out", "label": "输出", "type": "filepath"}],
  "defaultConfig": {},
  "configFields": [{"key": "cmd", "label": "命令", "type": "text"}],
  "execType": "python",
  "execCode": "import os, json\nprint(json.dumps({'outputs': {'out': ...}}))",
  "execFile": ""
}
```

`execType` 取值（`control_plane/custom_node_runtime.py`）：
- `python`：执行内联 `execCode`，或运行 `execFile` 指向的脚本。
- `shell`：执行 `execCode` 里的 shell 命令。
- `llm`：按 `execCode` 作为提示词发起 LLM 调用。

运行时机：自定义节点在执行工作流时由控制平面派发到 Celery worker，再经 `custom_node_runtime.run_custom_node(...)` 在子进程里执行，与内置节点走同一套产物/进度/取消机制。

---

## C. 资源令牌注册（并发控制）

节点若需占用受限本地资源（GPU / TTS / IO 并发），在 `backend/control_plane/workflow_runtime.py` 维护：

- `RESOURCE_BY_NODE_TYPE`：节点类型 → 资源令牌名（`gpu` / `tts` / `io`）。
- `RESOURCE_FREE_NODE_TYPES`：纯网络/API 节点，不占本地计算令牌，可高并发。
- `GPU_SERVICE_MANAGED_NODE_TYPES`：启用 GPU 服务后，这些节点改由 GPU 服务层调度显存 lane，worker 侧不再扣 `gpu` 令牌（避免双重限流）。
- `GPU_SERVICE_LANE`：GPU 服务的 lane 名。

新增 GPU 类节点时按上面约定登记，无需改调度主流程。

---

## D. 新增内置节点 Checklist

1. 在 `builtin_node_types.py` 的 `BUILTIN_NODE_TYPES` 追加节点定义 dict：端口用 `id`（不是 `name`）；`configFields` 描述设置项；默认值放 `defaultConfig`；选对 `execution_domain`（thread/process/llm）与 `category`。
2. 在 `backend/steps/` 新建 `s_<name>.py`，子类化 `BaseStep`，实现 `step_id` / `check_artifact` / `validate_inputs` / `run`。`run(self, task_dir, callback=None, cancel_callback=None)` 通过 `self._step_inputs` / `self._step_config` / `self._node_id` 取运行时数据；产物写入 `os.path.join(task_dir, "cache", ...)`，文件名带 `_<node_id>` 后缀，用 `find_artifact` 反查；返回 `{"artifacts": [...], "outputs": {...}}`。
3. 在 `step_registry.py` 的 `_STEPS` 注册两个 key：`"s_<name>"` 与 `"<node_type_id>"`。
4. 若占受限资源，在 `workflow_runtime.py` 的 `RESOURCE_BY_NODE_TYPE` 等登记表补充。
5. 重启后端（manager 守护），前端 `GET /api/node-types` 会带出新节点，可拖拽连线执行。

---

## E. 前端资源位置

- 工作流编辑器：`frontend/src/components/workflow/`（`WorkflowNode.tsx`、`NodeManager.tsx`、画布等）。
- 节点类型元数据的客户端封装：`frontend/src/api/` 下对应 `node-types` 的 client。
- 节点卡片的分类、端口、设置项完全由 `GET /api/node-types` 返回的 `configFields` / `inputs` / `outputs` 渲染，无需单独改前端即可让新节点出现。
