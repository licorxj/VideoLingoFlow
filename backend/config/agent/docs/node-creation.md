# 节点创建能力

> 本能力文档供节点创建助手按需读取。所有路径相对 PROJECT_ROOT。

> PROJECT_ROOT = 本机 VideoLingoFlow（中文名：流连视听）安装根目录，本地值如 `Y:\VideoLingoLc`。
> 本文档描述的一切约定均以当前代码库真实实现为准（控制平面 + Celery 架构，方案 C 子进程隔离），
> 执行前请用 read/grep 按需核实具体代码，不要凭记忆编造实现细节。

---

## 1. 目标与职责

本助手负责在 VideoLingoFlow 中**新建节点、注册节点、规范存放节点文件**，并处理节点与「能力接口」（ASR/TTS/生图/人声分离/AIGC）的对接。具体职责：

- 新建一个可运行的节点（节点类型定义 + 步骤执行类 + 注册 + 前端兜底副本）。
- 设计节点的输入/输出端口、配置字段（configFields），端口 type 必须与前端 `PortType` 对齐。
- 让节点消费已配置的能力接口（引擎/模型下拉 + 步骤内参数合并）。
- 排查「未知工作流节点」「下游找不到产物」「节点无进度」等执行期问题。

交付标准：工作流中能放置该节点、执行后产物出现在任务目录、节点状态正常推进（running → completed）、失败有明确错误信息、进度正常上报、可取消。

---

## 2. 核心概念

### 2.1 一个可用节点 = 4 个部分，缺一不可

| 部分 | 文件位置 | 作用 | 是否必须 |
|---|---|---|---|
| ① 节点类型定义 | `backend/config/builtin_node_types.py` | 节点元数据（id/名称/端口/配置项/执行域） | 必须 |
| ② 步骤执行类 | `backend/steps/s_*.py` | 实际执行逻辑（继承 `BaseStep`） | 必须 |
| ③ 步骤注册 | `backend/steps/step_registry.py` | 节点类型 id → 步骤实例的映射 | 必须 |
| ④ 前端兜底副本 | `frontend/src/lib/fallbackNodeTypes.ts` | 后端 API 不可用时的前端注册表副本 | 建议同步 |

> 前端正常运行时会通过 `GET /api/node-types` 从后端拉取节点类型（`NodePalette.tsx` → `listNodeTypes()`），所以 ①②③ 是硬性要求；④ 是后端暂不可用时的兜底副本，新增节点时建议同步追加，保持两端一致。

### 2.2 执行架构（控制平面 + Celery）

- **控制平面**：`backend/control_plane/workflow_runtime.py` 负责工作流 DAG 调度、节点状态机、事件推送（WS）、进度落盘。节点执行时：解析连线输入（`_resolve_step_inputs`）→ 判定执行域（`_execution_domain`）→ `thread` 域直接调 `get_step_instance(node_type)` 执行；`process` 域走 `_run_node_subprocess` 子进程隔离。
- **Celery worker**：`backend/control_plane/celery_runtime.py` + `backend/control_plane/step_worker.py` 支撑执行。`step_worker` 以 `python -m backend.control_plane.step_worker <args.json>` 方式运行单个节点：`get_step_instance(node_type)` → 注入 `_node_id/_node_config/_step_inputs` → 调 `step.run()` → 结果 pickle 写回 `result_path`。
- **资源队列**：节点按 `resource_class` 排队执行，队列满抛 `ResourceLimitError`；超时可通过 `CELERY_TIMEOUT_<RESOURCE>` 环境变量控制。

### 2.3 执行域（execution_domain）判定标准

| 值 | 适用场景 | 说明 |
|---|---|---|
| `"process"` | 本地重型推理（ASR/TTS/生图/人声分离等）、网络请求类（下载/发布/LLM） | 独立子进程运行，可硬停止（kill 进程树），需走 `@PROGRESS@|pct|msg` 行协议 |
| `"thread"` | 轻量、纯 CPU 计算、文件转换、几乎瞬时完成 | 线程内直接执行，无法硬杀，靠协作取消 |

当前 process 节点：`platform_download`、`vocal_separation`、`track_separation`、`asr`、`summarize`、`translate`、`tts`、`llm_request`、`image_gen`、`editor_agent`、`video_publish`、`aigc_runninghub`、`aigc_jimeng`。`aigc_comfyui` 为 thread 域。

---

## 3. 关键规范

### 3.1 步骤文件命名（backend/steps/）

- 统一放在 **`backend/steps/`** 目录（一个目录，不分子目录）。
- 命名：`s_<节点类型id>.py`（新节点推荐，如 `s_my_node.py`）；既有编号文件可沿用（如 `s15_extract_audio.py`），**不要重复新建同名文件**。
- 文件顶部写一行模块说明：`"""s_xxx: <一句话描述>"""`。

### 3.2 类命名与继承

- 类名以 `S_` 或 `Step` 开头，语义化命名，如 `S_MyNode` / `StepMyNode`。
- **必须继承 `backend.steps.base_step.BaseStep`**（抽象基类）。
- 类内至少声明 `step_id`、`step_name`；`dependencies` 留空列表（`[]`）。
- 常用注入属性（运行时由框架写入，直接 `getattr` 读取）：
  - `_node_id`：当前节点唯一 id（产物命名必须用它做后缀）
  - `_node_config`：节点 `data.config`（用户在前端填写的配置）
  - `_step_inputs`：按连线从上游注入的输入（key = 上游端口 id）

### 3.3 必须实现的方法（BaseStep 抽象方法）

| 方法 | 签名 | 职责 |
|---|---|---|
| `check_artifact` | `check_artifact(self, task_dir: str) -> bool` | 检查本节点产物是否已存在且有效；用 `find_artifact` 匹配产物，存在则跳过执行 |
| `validate_inputs` | `validate_inputs(self, task_dir: str) -> bool` | 检查必需输入是否存在；优先读 `self._step_inputs`（连线输入），回退扫描缓存 |
| `run` | `run(self, task_dir: str, callback=None, cancel_callback=None) -> dict` | 执行节点逻辑，返回 `{"artifacts": [...], "outputs": {...}}` |

> `BaseStep` 还提供 `rollback` / `clear_artifact`（删除本节点产物，供重跑）与 `_all_exist` 工具方法，可直接复用。

### 3.4 run 的返回结构（重要）

```python
def run(self, task_dir, callback=None) -> dict:
    node_id = getattr(self, "_node_id", "unknown")
    output_path = os.path.join(task_dir, "cache", f"my_result_{node_id}.json")
    # ... 执行逻辑 ...
    return {
        "artifacts": [f"cache/my_result_{node_id}.json"],  # 产物相对路径（相对 task_dir）
        "outputs": {"json": f"cache/my_result_{node_id}.json"},  # 端口 id -> 产物路径
    }
```

- `outputs` 的 **key 必须与 builtin_node_types 里本节点的 outputs 端口 id 一一对应**，下游连线按端口 id 取值；无对应端口的多余值不会被下游消费。
- `artifacts` 用于产物检测（`check_artifact`）/清理（`rollback`），可包含 outputs 之外的辅助文件（如中间文件），路径相对 task_dir。

### 3.5 进度上报与协作取消

`run` 内通过 `callback(percent: int, message: str)` 上报进度（0-100）：

```python
if callback:
    callback(10, "开始处理...")
    callback(100, "完成")
```

- **process 节点**：callback 由 `step_worker._progress_callback` 实现，写 stdout 行 `@PROGRESS@|<pct>|<msg>`，父线程（`workflow_runtime._run_node_subprocess`）逐行解析并转发 WS 事件；中文不乱码依赖 step_worker 强制 UTF-8。**步骤内 `print` 也会进 stdout，请勿输出非 `@PROGRESS@` 前缀的关键信息**（父线程只解析该前缀）。
- **thread 节点**：callback 由 `workflow_runtime` 直接注入，同步写事件并限流落盘（每 ≥5% 或 100% 写一次 task.json，刷新页面进度不丢）；callback 内部会检查超时与取消，抛 `TaskTimeoutError` / `TaskCancelledError`。
- **协作取消**：耗时循环内**必须定期调用 callback**（`step_worker` 侧 callback 检查 `cancel_file` 存在即抛 `TaskCancelledError`；thread 侧检查 `_cancel_requested`）。不回调的阻塞型节点只能靠父进程 kill 进程树兜底（能停但不算优雅）。
- 取消异常从 `backend.control_plane.runtime` 导入：`from backend.control_plane.runtime import TaskCancelledError`。

### 3.6 注册映射（backend/steps/step_registry.py）

`_STEPS` dict 把 **节点类型 id** 映射到 **步骤实例**，import 语句放在文件顶部：

```python
from backend.steps.s_my_node import S_MyNode

_STEPS = {
    # ...既有注册...
    "my_node": S_MyNode(),      # 节点类型 id -> 实例（get_step_instance 用它解析）
    "s_my_node": S_MyNode(),    # 步骤 id -> 实例（兼容 step_id 引用）
}
```

- **每个新节点必须注册**，否则执行时报 `ValueError: 未知工作流节点: <id>`（`workflow_runtime._run_node` / `step_worker` 中 `get_step_instance` 返回 None）。
- 建议同时注册**节点类型 id** 和**步骤 id** 两个 key（与现有节点保持一致），保证新旧引用都能解析。
- 完成后验证：`get_step_instance("<id>")` 不返回 None。

### 3.7 节点类型定义（backend/config/builtin_node_types.py）

在 `BUILTIN_NODE_TYPES` 列表末尾追加一个 dict：

```python
{
    "id": "my_node",            # 唯一节点类型 id（前端 palette、连线、step_registry 都用它）
    "name": "我的节点",          # 显示名称
    "execution_domain": "thread",  # "process"（子进程隔离）或 "thread"（线程内，默认）
    "category": "process",      # 分类：input/process/ai/ai_gen/utility/output/preview/publish/flow_control（前端另有 aigc/network_request）
    "description": "一句话描述",
    "icon": "Wrench",           # lucide-react 图标名
    "color": "#6366f1",         # 主题色
    "inputs": [
        {"id": "json", "label": "JSON输入", "type": "json", "required": True},
        # type 必须是前端 PortType 之一（见 3.8）
    ],
    "outputs": [
        {"id": "json", "label": "结果", "type": "json"},
    ],
    "defaultConfig": {"key": "默认值"},   # 节点默认配置（前端表单初值）
    "configFields": [                     # 前端表单字段定义
        {"key": "key", "label": "配置项", "type": "text"},
    ],
}
```

### 3.8 端口 type 必须与前端 PortType 对齐

前端 `frontend/src/lib/workflowTypes.ts` 的 `PortType` 枚举：

`video | audio | audio_manifest | json | pandas | subtitle | text | image | url | any | preview`

连线规则（`canConnect`）：要求端口 type 相同；`any` 可连任何类型。

### 3.9 configFields 常用字段类型与辅助字段

- 字段类型：`text | textarea | select | checkbox | toggle | chips | file | hotwords | language-select | api-select | voice-select | slider | number | datetime-local | account-select | audio-selector | date | time`。
- 常用辅助字段：`placeholder`、`description`、`dependsOn`（联动）、`dependsValue`/`dependsAnyValues`（联动显示条件）、`fileFilter`（文件选择过滤）、`options`（select/chips 选项，`{value, label}`）、`colSpan`（"half"/"third"/"full" 布局）。
- 接口联动下拉用 `api-select` + `apiEndpoint`（见第 4 节）。

### 3.10 前端兜底副本（frontend/src/lib/fallbackNodeTypes.ts）

- 文件头部注释标明 `Generated from backend/config/builtin_node_types.py as frontend fallback registry`。
- 新增节点时**建议**同步追加对应定义，字段与后端一致：`id/name/category/description/icon/color/inputs/outputs/defaultConfig/configFields`（不包含 `execution_domain`）。
- 结构对应前端 `NodeTypeDef`（见 `frontend/src/lib/workflowTypes.ts`），端口 type 必须是 `PortType` 之一。

### 3.11 产物命名与下游引用（重要）

> 同一节点类型可能在一个工作流中出现多次，为避免文件互相覆盖，**输出文件名必须包含节点 id 后缀**。

- 命名格式：`{base}_{node_id}.{ext}`，例如 `my_result_{node_id}.json`。
- `outputs` 里端口值也用带 `node_id` 的路径。
- `check_artifact` / 下游查找产物统一用 `find_artifact`：

```python
from backend.steps.base_step import find_artifact
path = find_artifact(os.path.join(task_dir, "output"), "extracted_audio.wav")
```

`find_artifact(directory, base_name)` 匹配规则：
- 精确匹配 `base.ext` 或 `base_<任意后缀>.ext`（忽略 `_node_id` 部分）。
- 匹配到多个时取排序后第一个（无 node_id 后缀的优先）。
- 找不到返回 `None`。

目录约定：
- 中间产物 → `task_dir/cache/`
- 最终输出产物 → `task_dir/output/`
- 输入节点复制到任务目录后：`input_video.<ext>` / `input_audio.<ext>` / `input_subtitle.<ext>`

### 3.12 输入注入规范（忠实于连线）

- 运行时 `_resolve_step_inputs(task_id, node_id, workspace)` 从**上游节点在 DB 中的 `result.outputs`** 按端口 id 注入到 `self._step_inputs`；input 节点回退 `task.payload.input`（videoPath/audioPath/...）；上游 outputs 缺失时回退 `workspace/task.json`。
- 步骤内读取连线输入统一用 `self._step_inputs.get("<端口id>", "")`（端口 id = builtin_node_types 里 inputs 的 id）。
- 传入路径可能是相对路径（相对 task_dir）也可能是绝对路径：解析时先判 `os.path.isabs`，否则 `os.path.join(task_dir, raw)`。
- 节点自身多余的输入需求（不来自连线的）按 3.11 的产物约定在任务目录中查找，属于节点内部逻辑，与连线注入互不影响。
- 典型读取模式（参考 `s_video_frame_extract.py` / `s15_extract_audio.py`）：

```python
step_inputs = getattr(self, "_step_inputs", {}) or {}
raw = step_inputs.get("video", "")
if raw:
    p = raw if os.path.isabs(raw) else os.path.join(task_dir, raw)
    if os.path.isfile(p):
        video_path = p
# 无连线时回退扫描 cache/input_video* 或 cache 下视频
```

---

## 4. 接口配置要点（节点如何消费能力接口）

VideoLingoFlow 的「接口」= 设置页里可配置/可开关/可测试的能力提供方，四类接口域完全同构：

| 接口域 | 数据文件 | Manager | API 路由 |
|---|---|---|---|
| ASR 语音识别 | `backend/config/asr_interfaces.json` | `backend/asr/asr_interface_manager.py` | `/api/asr-interfaces` |
| TTS 语音合成 | `backend/config/tts_interfaces.json`（+ `tts_voices.json` 音色） | `backend/tts/tts_interface_manager.py` | `/api/tts-interfaces`、`/api/tts-voices` |
| AI 生图 | `backend/config/imagegen_interfaces.json` | `backend/imagegen/imagegen_interface_manager.py` | `/api/imagegen-interfaces` |
| 人声分离 | `backend/config/separation_interfaces.json` | `backend/separation/separation_interface_manager.py` | `/api/separation-interfaces` |
| AIGC 能力 | `backend/config/config.yaml`（`aigc.*`） | `backend/api/aigc_capabilities.py` 直接读写 | `/api/aigc` |

### 4.1 前端下拉（configFields 用 api-select）

- 节点 configFields 中需要「选引擎/选接口」的字段用 `type: "api-select"` + `apiEndpoint` 指向对应接口 API，前端据此拉列表：
  - `{"key": "engine", "label": "ASR 引擎", "type": "api-select", "apiEndpoint": "/api/asr-interfaces/enabled", "placeholder": "跟随全局配置"}`
  - `{"key": "model", "label": "模型", "type": "api-select", "apiEndpoint": "/api/asr-interfaces/models", "dependsOn": "engine", "placeholder": "默认"}`（`dependsOn` 实现「先选引擎再拉模型」联动）
  - 分离节点：`apiEndpoint: "/api/separation-interfaces/enabled"` + `optionLabel: "name", optionValue: "id"`
  - 生图节点：`apiEndpoint: "/api/imagegen-interfaces/{interface}/models-for-node?mode={mode}"`
  - 端点支持 `{字段名}` 占位符（如 `{tts_engine}`、`{interface}`），前端会先填依赖字段再拉取。

### 4.2 步骤内合并参数（后端消费）

- 节点 `config.engine`（或 `interface`/`method`）存的是**接口 id**；步骤内用对应 Manager 取接口配置作为默认值，任务节点 config 覆盖默认值：

```python
from backend.tts.tts_interface_manager import get_tts_interface_manager
iface_cfg = get_tts_interface_manager().get(engine_id)          # 取接口 config
merged = {**iface_cfg, **node_config}                            # 节点配置覆盖接口默认值
```

- 通用原则：`merged = {**interface_config, **node_config}`；**`engine`/`interface` 本身只做路由用，不要传给引擎**。
- **不要在步骤里硬编码引擎**：新引擎一律通过接口配置注入，避免代码里堆 `if engine == "xxx"`。
- 四类 Manager 均提供单例工厂（`get_xxx_interface_manager()`，惰性初始化）与 `get(id)` / `get_enabled()` 等方法。

### 4.3 接口常见问题

- 新接口没出现在节点下拉 → 接口 `enabled=false` 或 Manager 未 reload：`POST /api/{domain}-interfaces/reload`。
- **不要**手改 `builtin:true` 的内置接口去新增引擎——内置接口用于系统自带引擎，新服务一律在设置页建自定义接口（`builtin:false`）。

---

## 5. 操作步骤（建新节点的完整流程）

假设要新建节点 `my_node`（示例为 thread 轻节点）：

- [ ] **① 判定执行域与输入输出**：先想清楚节点做什么、吃哪些输入（端口 type 对齐 PortType）、产出哪些输出、是否重计算/网络请求（决定 `execution_domain`）。
- [ ] **② 节点类型定义**：在 `backend/config/builtin_node_types.py` 的 `BUILTIN_NODE_TYPES` 列表末尾追加 dict（字段见 3.7），端口 type 严格用 PortType 之一。
- [ ] **③ 新建步骤文件**：在 `backend/steps/` 新建 `s_my_node.py`：
  - 顶部模块说明；类继承 `BaseStep`；声明 `step_id = "s_my_node"`、`step_name`、`dependencies = []`。
  - 实现 `check_artifact`（用 `find_artifact` 或直接拼 `cache/<base>_{node_id}.<ext>` 判断存在）、`validate_inputs`、`run`。
  - 产物命名带 `{node_id}` 后缀；`run` 返回 `{"artifacts": [...], "outputs": {...}}`，outputs key 与端口 id 一一对应。
  - 耗时循环内定期 `callback(pct, msg)`（0-100）。
- [ ] **④ 注册**：在 `backend/steps/step_registry.py` 顶部 import `S_MyNode`，在 `_STEPS` 注册 `"my_node"` 与 `"s_my_node"` 两个 key。
- [ ] **⑤（建议）前端兜底**：在 `frontend/src/lib/fallbackNodeTypes.ts` 的 `FALLBACK_NODE_TYPES` 追加对应定义。
- [ ] **⑥ 验证**：
  - `get_step_instance("my_node")` 非 None；
  - `python -m py_compile backend/steps/s_my_node.py` 通过；
  - 后端启动后 `GET /api/node-types` 返回该节点；前端 palette 出现该节点（无需改前端）。
- [ ] **⑦ 端到端**：工作流中放置该节点并执行：产物出现在任务目录、节点状态 running → completed、进度正常、失败有明确错误信息。
- [ ] **⑧（可选）分享到共享社区**：`POST /api/community/pack-node` 生成资源包（node_config + code + 预览图）→ `POST /api/community/publish` 上传到云端 Worker（R2 + D1 元数据）。打包时节点定义会被净化（去掉本地私密信息），发布前请确认 `configFields` 中没有机器相关绝对路径等敏感默认值。

若节点需要消费能力接口，在上述流程中额外：configFields 加 `api-select` 字段（4.1），步骤内用 Manager 合并参数（4.2）。

---

## 6. 常见错误与排查

| 错误现象 | 原因 | 修复 |
|---|---|---|
| `ValueError: 未知工作流节点: xxx` | 节点类型 id 未在 `step_registry._STEPS` 注册 | 按 3.6 注册（并重启 worker） |
| 下游找不到产物 | 产物未带 `_node_id` 后缀 或 命名与 `find_artifact` 约定不符 | 按 3.11 命名，用 `find_artifact` 匹配 |
| 节点执行后无进度/状态不更新 | WS 事件未推送（后端进程崩溃或路由不匹配） | 确认后端存活、`/ws/tasks/{id}` 可连；重启后端 + worker |
| process 节点取消不生效 | 步骤耗时循环未调用 callback | 循环内定期 callback（检查取消标记） |
| 节点引擎下拉没有新接口 | Manager 未 reload / 接口 `enabled=false` | `POST /api/{domain}-interfaces/reload`；确认 enabled |
| 接口测试 401/403 | `api_key` 为空或格式不符 | 填对 key；local 请求头固定 `Authorization: Bearer` |
| 删除接口失败 400 | 接口是 builtin | 内置接口不可删，只可改 description/config |
| 步骤执行仍用旧引擎 | 节点 config 里 `engine` 已写死 | 清空节点 engine（跟随全局/接口默认） |
| 端口连不上线 | 端口 type 与上游不一致（`any` 除外） | 核对两边端口 type 均为 PortType 之一 |
| `(trapped) error reading bcrypt version` | passlib/bcrypt 版本兼容 | 无害警告，已加补丁，忽略 |

排查顺序建议：注册（get_step_instance）→ 语法（py_compile）→ 节点定义（/api/node-types）→ 执行产物（任务目录）→ 状态与进度（WS）。

---

## 7. 注意与禁忌

- **必须继承 `BaseStep` 并实现全部抽象方法**（`check_artifact`/`validate_inputs`/`run`），返回结构必须为 `{"artifacts", "outputs"}`。
- **产物文件名必须带 `_node_id` 后缀**，这是多实例防覆盖的硬性约定；下游查找一律用 `find_artifact`。
- **不要**重复新建已存在的步骤文件（如既有 `s15_extract_audio.py` 就不应再建 `s_extract_audio.py`）。
- **process 节点禁止向 stdout 输出非 `@PROGRESS@|` 前缀的关键信息**（会被父线程忽略，且污染行协议解析）。
- **不要**在步骤里硬编码引擎分支（`if engine == "xxx"`）；引擎统一走接口配置注入。
- **不要**手改 `builtin:true` 接口去新增引擎；新服务一律建自定义接口。
- 进度回调用整数百分比（0-100），消息尽量简短（process 节点消息会做单行化处理）。
- 网络请求/重推理节点标 `process`；轻量计算标 `thread`，并确认 thread 域支持协作取消（回调会抛取消异常）。
- 发布社区包前检查 `configFields` 默认值无机器相关绝对路径等敏感信息。
- 遵守全局约束：不访问 `backend/auth` 及认证/支付相关代码；不破坏数据结构；读取文档后如涉及具体代码，用 read/grep 按需核实再动手。
