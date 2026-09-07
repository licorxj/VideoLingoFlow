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
    "execution_domain": "thread",              # 见 A.4（只有 thread / process 两种有效取值）
    "category": "utility",                     # 分组 key，必须是白名单之一（见 A.2.1）
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
            "type": "number",                  # 见 A.2.1 白名单
            "min": 1, "max": 60, "step": 1,
        },
        {
            "key": "mode",
            "label": "模式",
            "type": "select",
            "options": [                       # select 用 options（必填）
                {"label": "最长时长", "value": "longest"},
                {"label": "主音轨为准", "value": "main"},
            ],
        },
    ],
}
```

#### A.2.1 受控枚举（白名单）

后端校验层 `backend/config/node_schema.py` 定义了三份白名单；**自定义节点（走 API）必须遵守，内置节点也建议遵守**：

| 项 | 合法取值 |
|---|---|
| `category` | `io`、`preview`、`audio`、`video`、`ai_gen`、`translation`、`flow_control`、`network_request`、`aigc`、`asset`、`agent`、`utility`、`file`、`group_node`、`hyperframes` |
| 端口 `type` | `video`、`audio`、`audio_manifest`、`json`、`pandas`、`subtitle`、`text`、`image`、`url`、`filepath`、`preview`、`any` |
| `configFields.type` | `text`、`textarea`、`select`、`multiselect`、`checkbox`、`toggle`、`chips`、`file`、`language-select`、`api-select`、`slider`、`number`、`button` |

前端 `PortType`（`frontend/src/lib/workflowTypes.ts`）比后端多两个：`list`、`filepath` 已在后端白名单，`list` 仅前端/内置节点可用。**连线兼容性**（`canConnect`）：type 相同即可连，`any` 可连任意；另有 `subtitle→json`、`list→json`、`image↔list` 三条兼容规则。

前端渲染还支持 `hotwords`、`voice-select`、`account-select`、`audio-selector`、`datetime-local`、`date`、`time` 等字段类型，但**不在后端白名单**，仅内置节点可用。

**命名要点（易错点）：**
- 输入/输出端口用 `id`（如 `"subtitle"`），不要写成 `name`。
- 设置面板用 `configFields`，默认值**统一放 `defaultConfig`**；`configFields` 项内**不要写 `default`**（前端不读该字段，且自定义节点会因 schema 校验被拒）。
- 端口 `type` 用受控类型（`filepath` / `subtitle` / `audio` / `text` / `json` / `video` 等），同类型端口才能连线；不要用 `file`（历史遗留值，不在任何白名单）。
- `category` 不要写 `tools` / `process` / `input` 等不在白名单的值。
- `colSpan` 等排版属性仅内置节点可用，自定义节点带上会被 schema 拒绝。

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
  - `self._node_config`：节点 `data.config`（`BaseStep` 未预设默认值，用 `getattr(self, "_node_config", {}) or {}` 安全读取）。
  - `self._step_inputs`：连线解析后的输入，键为输入端口 `id`，值为文件路径字符串或列表。
- 进度上报：在 `run` 内调用 `callback(percent: int, message: str)`（若非 None）。
- 协作取消：按需调用 `cancel_callback()`（若提供），返回 True 表示已取消。**注意**：`step_worker` 用 `inspect.signature` 判断，只有 `run` 签名里显式声明了 `cancel_callback` 才会注入；另外 `callback` 内部也会检查取消标记文件，所以耗时循环里定期调用 `callback` 同样能响应取消。
- 子进程域（`process`）下：`callback` 写 `@PROGRESS@|pct|msg` 行协议；步骤内的 `print` 会被包装成 `@LOG@|msg` 转发到任务事件流，**请放心打日志**（排查卡死时是唯一线索）。结果由 `step_worker` 以 **JSON** 写入 `result_path`（旧版 pickle 已废弃，仅读取 `.pkl` 时做兼容），父线程再读取。
- 产物命名约定：`{base}_{node_id}{ext}`（如 `asr_result_a1b2c3.json`）。读取用模块级函数 `find_artifact(directory, base_name)` 反查（见 `file-management.md`），不要硬编码完整文件名。
- `BaseStep` 另提供 `rollback(task_dir)` / `clear_artifact(task_dir)`（按 `artifacts` 清理）与 `_all_exist(task_dir, files)`。

### A.4 execution_domain（执行域）

- `thread`：在线程池内执行（默认，绝大多数节点）。
- `process`：在独立子进程执行（`control_plane/step_worker.py` 以 `python -m backend.control_plane.step_worker <args.json>` 启动），用于重型/长时推理以释放 GIL、隔离崩溃、可被硬停止。

**运行时只认这两个值**（`workflow_runtime._execution_domain()`），取 `process` 走子进程，其余一律按 `thread` 处理。优先级：节点 `data.config.execution_domain` > 环境变量 `PROCESS_DOMAIN_EXTRA` > `builtin_node_types.py` 的定义。

> 历史遗留：仓库中有 2 个节点（`ai_punctuate`、`ai_subtitle_correct`）写着 `execution_domain="llm"`，运行时等价于 `thread`。**新节点不要使用该值**（旧文档说的 `llm` 执行域并不存在）。

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

补充要点：

- 未注册会报 `ValueError: 未知工作流节点: <id>`（`step_worker.py` / `workflow_runtime._run_node`）。
- **正常例外**：`input`、`loop` 不在 `_STEPS` 中，由运行时特殊分支/循环运行时处理。（`aigc_runninghub`、`aigc_jimeng` 此前漏注册，现已补入 `_STEPS`。）
- 并发/循环迭代场景请通过 `new_step_instance(node_type)` 取**独立实例**，不要复用 `_STEPS` 里的单例（单例会被写入 `_node_id`/`_node_config`/`_step_inputs`，并发下互相覆盖）。
- 同步更新前端兜底表 `frontend/src/lib/fallbackNodeTypes.ts`（后端 API 不可用时前端依赖它；当前已有 37 个内置节点缺失）。

`backend/engine/thread_scheduler.py` 里另有一份遗留的 `BUILTIN_STEP_REGISTRY`（节点 id → (module, class)）与 `PROCESS_ISOLATED_NODE_TYPES`（仅 `{asr, vocal_separation, track_separation, http_request}`），服务于旧的 ThreadScheduler 线程池路径；控制平面执行路径不需要改它，新增节点只改 `step_registry._STEPS` 即可。

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
  "category": "utility",
  "inputs":  [{"id": "in",  "label": "输入", "type": "filepath", "required": true}],
  "outputs": [{"id": "out", "label": "输出", "type": "filepath"}],
  "defaultConfig": {},
  "configFields": [{"key": "cmd", "label": "命令", "type": "text"}],
  "execType": "python",
  "execCode": "produced['out'] = os.path.join(cache_dir, 'out.txt')",
  "execFile": "",
  "execTimeout": 300
}
```

> 自定义节点**不需要也不生效** `execution_domain` 字段：控制平面只要 `get_step_instance()` 返回 None 就走 `custom_node_runtime`，不再判断执行域（`workflow_runtime._run_node`）。自定义脚本本身已由 `custom_node_runtime` 用 `subprocess.run` 在子进程执行。

`execType` 取值（`control_plane/custom_node_runtime.py`）：

- `python`：执行内联 `execCode`，或运行 `execFile` 指向的脚本（相对路径按 `codeDir` 解析）。
  - 内联代码会被包裹成脚本：预置 `produced = {}`、`task_dir`、`cache_dir`、`node_id`、`node_config`、`step_inputs`（别名 `config` / `inputs`），执行结束后把 `produced` 以 JSON 写入 `OUTPUTS_JSON_PATH`。
  - **返回端口值要写 `produced['<端口id>'] = <路径或值>`**，不要 `print(json.dumps(...))`（早期文档示例有误，现在不生效）。
- `shell`：执行 `execCode` 里的 shell 命令（`shell=True`，cwd 为任务目录）。
- `llm`：以 `execCode` 为提示词（用 `{key}` 占位符替换 `step_inputs` + `node_config`）发起一次 LLM 调用，结果写入 `cache/<node_id>_llm_output.txt`，输出端口固定为 `text`。

运行时环境变量：`TASK_DIR`、`CACHE_DIR`、`NODE_ID`、`NODE_CONFIG_JSON`、`STEP_INPUTS_JSON`、`OUTPUTS_JSON_PATH`，外加 `INPUT_<端口ID大写>`、`CONFIG_<配置KEY大写>`。`execTimeout` 为秒（缺省 300，且必须 ≥1）；产物默认取 `cache/<node_id>_*` 文件。

**必过的后端校验**（`backend/config/node_schema.py::validate_node_type_data`，create/update/import 都会调用）：

- `category`、端口 `type`、`configFields.type` 必须在 A.2.1 的白名单内；`select`/`chips` 必须有 `options`；`api-select` 必须有 `apiEndpoint` 或 `apiUrl`；`slider`/`number` 的 `min`/`max`/`step` 必须是数字；`execTimeout` ≥ 1。
- `python` 节点必须提供 `execCode` 或 `execFile`；`shell`/`llm` 必须提供 `execCode`。
- `kind=group` 的 `category` 必须为 `group_node`（子图 ≥2 节点），`kind=loop` 必须为 `flow_control`（子图 ≥1 节点），两者不得声明 `execType`。
- 坑：`NodeTypeConfig.category` 的**默认值 `"process"` 不在白名单内**，建节点时必须显式传合法分类，否则 400。

**导入/导出（`POST /api/node-types/import`、`/export`）**：

- 与内置节点 ID 同名的包，非重命名导入会被 400 拒绝；应改用 `renameTo` **「重命名导入」**以新 ID 安装。
- 包内 `execFile` 必须是 ZIP 成员（Python 节点缺 `execFile` 且缺 `execCode` 也会被拒）；导出时绝对路径会被规范化为包内相对路径。
- 包内含 `requirements.txt` 会**直接 400 拒绝导入**，依赖必须由部署环境预装。

运行时机：自定义节点在执行工作流时由控制平面派发到 Celery worker，再经 `custom_node_runtime.run_custom_node(...)` 执行，与内置节点共用同一套产物命名、进度与取消机制。

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

1. 在 `builtin_node_types.py` 的 `BUILTIN_NODE_TYPES` 追加节点定义 dict：端口用 `id`（不是 `name`）；`configFields` 描述设置项（不要写 `default`）；默认值放 `defaultConfig`；`category` 与端口 `type` 取 A.2.1 白名单值；`execution_domain` 只取 `thread` / `process`（重型/网络类选 `process`）。
2. 在 `backend/steps/` 新建 `s_<name>.py`，子类化 `BaseStep`，实现 `step_id` / `check_artifact` / `validate_inputs` / `run`。`run(self, task_dir, callback=None, cancel_callback=None)` 通过 `self._step_inputs` / `self._node_config` / `self._node_id` 取运行时数据（均用 `getattr(..., {}) or {}` 安全读取）；产物写入 `os.path.join(task_dir, "cache", ...)`，文件名带 `_<node_id>` 后缀，用 `find_artifact` 反查；返回 `{"artifacts": [...], "outputs": {...}}`（`outputs` 的 key 必须等于输出端口 id）。耗时循环内定期调用 `callback` 以便响应取消。
3. 在 `step_registry.py` 的 `_STEPS` 注册两个 key：`"s_<name>"` 与 `"<node_type_id>"`；并发/循环场景改用 `new_step_instance()` 取独立实例。
4. （建议）同步 `frontend/src/lib/fallbackNodeTypes.ts` 的兜底定义。
5. 若占受限资源，在 `workflow_runtime.py` 的 `RESOURCE_BY_NODE_TYPE` / `RESOURCE_FREE_NODE_TYPES` / `GPU_SERVICE_MANAGED_NODE_TYPES` 补充。
6. 重启后端（manager 守护），前端 `GET /api/node-types` 会带出新节点，可拖拽连线执行。
7. 提交前运行 `python scripts/generate_node_catalog.py` 重新生成 `docs/node_catalog.md`，保持节点名录与代码同步。

---

## E. 前端资源位置

- 工作流编辑器：`frontend/src/components/workflow/`（`WorkflowNode.tsx`、`NodeManager.tsx`、画布等）。
- 节点类型元数据的客户端封装：`frontend/src/api/` 下对应 `node-types` 的 client。
- 节点卡片的分类、端口、设置项完全由 `GET /api/node-types` 返回的 `configFields` / `inputs` / `outputs` 渲染，无需单独改前端即可让新节点出现。

---

## F. 节点名录（Node Catalog）

`docs/node_catalog.md`（相对 `PROJECT_ROOT`）是**所有节点的权威清单**：按分组表格罗列每个节点的 id、名称、描述、执行域与输入/输出接口（含自定义节点）。新增或修改节点后，用它代替手工翻阅 `builtin_node_types.py` 来快速核对现有节点与端口，避免凭记忆使用过时节点 id。

重新生成（在 `PROJECT_ROOT` 下执行，需 venv 已激活、能 import `backend/`）：

```bash
python scripts/generate_node_catalog.py
```

该脚本直接读取后端节点定义（内置 `backend/config/builtin_node_types.py` + 自定义 `backend/config/node_types/*.json`），覆盖写入 `docs/node_catalog.md` 并打印文件绝对路径。当你新增/修改节点并提交前，建议重新生成一次以保持名录与代码同步。
