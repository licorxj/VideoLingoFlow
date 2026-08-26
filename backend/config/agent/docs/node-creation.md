# 节点创建（Node Creation）

本文件指导 agent 如何**新增一个工作流节点（node）**。节点是工作流的能力单元，分两类：
1. **内置节点**：代码内置的 `S_*` Step（绝大多数能力），需同时改前端展示定义与后端 Step 映射；
2. **自定义节点**：运行时从 `backend/config/node_types/<node_type>.json` 加载，无需写 Python Step，按 `execType` 执行脚本。

> 本文档基于 `backend/config/builtin_node_types.py`、`backend/steps/step_registry.py`、`backend/steps/base_step.py`、`backend/control_plane/custom_node_runtime.py`、`frontend/src/components/workflow/*` 的**当前实现**。节点总数随版本增长（当前约 57 个），不要硬编码旧数字。

---

## A. 内置节点

### A.1 必须改的两处（缺一不可）

| 文件 | 作用 | 不写后果 |
|---|---|---|
| `backend/config/builtin_node_types.py` | 节点的**展示元数据**：名称、分类、图标、输入/输出、表单字段、执行域 | 前端看不到 / 表单缺失 |
| `backend/steps/step_registry.py` | 把节点 id 映射到具体的 `S_*` Step 类（`register_step(id, StepClass, {category, ...})`） | 运行报 "未注册节点" / 节点无法执行 |

> 前端节点核心是**通用**的（`NodeManager.tsx` 用 `node_def` 动态渲染表单与端口），**通常不需要**为内置节点单独写 React 组件——除非你要给它专属 UI（见 A.4）。

### A.2 在 `builtin_node_types.py` 增加定义

每个节点是一个 dict，关键字段：

```python
{
    "id": "my_node",                 # 唯一标识，须与 step_registry 的注册 id 一致
    "name": "我的节点",              # 前端显示名
    "category": "ai",                # 分类（见下方分类枚举）
    "description": "做什么",
    "icon": "🛠️",                    # 展示图标
    "execution_domain": "thread",    # "thread" 或 "process"（无 "gpu" 域；GPU 交服务层）
    "inputs": [
        {"name": "text", "type": "text", "required": True},
    ],
    "outputs": [
        {"name": "result", "type": "text"},
    ],
    "form_schema": [                 # 前端表单字段
        {"key": "model", "label": "模型", "type": "text", "default": "gpt-4o"},
    ],
    "default_config": {},            # 默认配置
    "is_frontend_only": False,       # True=仅前端预览（如 video_preview/image_preview）
    "supported_extensions": [],      # 若处理文件，声明扩展名
}
```

**category 枚举（常用）**：`video` / `audio` / `speech` / `text` / `ai` / `subtitle` / `translate` / `agent` / `workflow` / `io` / `tool` / `publish`。

### A.3 实现 Step 并注册

Step 继承 `backend/steps/base_step.py:BaseStep`，标准三步（`_pre_execute` / `_execute` / `_post_execute`，由 `execute()` 串联）：

```python
from backend.steps.base_step import BaseStep, StepContext, StepResult

class S_MyNode(BaseStep):
    @property
    def name(self) -> str:
        return "我的节点"

    def _pre_execute(self, ctx: StepContext) -> None:
        # 校验输入/配置，缺失则 raise ValueError
        ...

    def _execute(self, ctx: StepContext) -> StepResult:
        # 1. 读输入：ctx.inputs["text"]、ctx.node_inputs
        # 2. 业务处理（可调用 ctx 提供的 model/tts/asr 客户端）
        # 3. 产物落盘：写 file_path，并用 self.find_artifact 或约定 {base}_{node_id}{ext}
        # 4. 返回：
        return StepResult(
            success=True,
            outputs={"result": "..."},
            artifacts=[{"file_path": str(p), "kind": "json", "base_name": "my_out"}],
            progress=100,
        )

    def _post_execute(self, ctx: StepContext, result: StepResult) -> None:
        # 可选：清理/汇总
        ...
```

注册（`step_registry.py`）：

```python
from backend.steps.s_my_node import S_MyNode
register_step("my_node", S_MyNode, {"category": "ai"})
```

**BaseStep 提供给子类的常用能力**（见 `base_step.py`）：
- `self.find_artifact(directory, base_name)`：按 `{base}_{node_id}{ext}` 反查文件；
- `self.log_progress(percent, message)`：上报进度（推前端）；
- 文件读写工具 `read_*_file(path)` / `write_*_file(path, content)`（text/json/srt/str）；
- `ctx.inputs` / `ctx.node_inputs` / `ctx.node_config` / `ctx.workspace`（任务目录）；
- 业务客户端（`ctx.models` / TTS 等），按需通过 `step_base` 提供的工厂获取。

### A.4 何时需要专属前端组件

多数内置节点用通用渲染即可。**仅当**需自定义交互（如可视化编辑器 `json_visual_editor`、`text_editor`、`subtitle_editor`）时，在 `frontend/src/components/workflow/NodeManager.tsx` 用 `TEMPLATE_NODE_COMPONENTS` 注册该 node_type 的专属组件。新增专属组件后，确保它正确读写节点 `config` 并把结果写回 `outputs`。

---

## B. 自定义节点（无需写 Step）

运行时从磁盘加载定义，由 `backend/control_plane/custom_node_runtime.py` 在**独立子进程**执行。

### B.1 定义文件位置

`backend/config/node_types/<node_type>.json`

### B.2 定义结构

```json
{
  "id": "my_custom_node",
  "name": "我的自定义节点",
  "category": "tool",
  "icon": "🧩",
  "execution_domain": "process",
  "inputs":  [{"name": "text", "type": "text", "required": true}],
  "outputs": [{"name": "result", "type": "text"}],
  "form_schema": [{"key": "model", "label": "模型", "type": "text", "default": "gpt-4o"}],
  "execType": "python",             // "python" | "shell" | "node"
  "execCode": "produced['result'] = inputs['text']",   // 内联代码
  "codeDir": "",                    // 入口文件相对根（execFile 模式）
  "execFile": ""                    // 入口文件（替代 execCode）
}
```

### B.3 执行环境（运行时注入的环境变量）

`custom_node_runtime.run_custom_node` 会为子进程注入：

- `TASK_DIR`：任务目录
- `CACHE_DIR`：缓存目录
- `NODE_ID`：当前节点 id
- `NODE_CONFIG_JSON`：节点配置（JSON 字符串）
- `STEP_INPUTS_JSON`：上游输入（JSON 字符串）
- `OUTPUTS_JSON_PATH`：要求把结果 dict 写入此路径（`{"outputs": {...}, "artifacts": [...]}`）

**Python 内联模板**（运行时自动包裹）：

```python
import json, os
task_dir = os.environ['TASK_DIR']
cache_dir = os.environ['CACHE_DIR']
node_id = os.environ['NODE_ID']
node_config = json.loads(os.environ['NODE_CONFIG_JSON'])
step_inputs = json.loads(os.environ['STEP_INPUTS_JSON'])
config = node_config
inputs = step_inputs
produced = {}
# <你的 execCode 写这里，向 produced 赋值>
with open(os.environ['OUTPUTS_JSON_PATH'], 'w', encoding='utf-8') as _f:
    json.dump(produced, _f, ensure_ascii=False)
```

> **shell / node** 类型也支持：shell 直接用 `command`；node 类似 python。详见 `custom_node_runtime.py`。

### B.4 自定义 vs 内置的选择

- 简单脚本/外部工具封装 → **自定义节点**（改 JSON 即可，无需重启后端注册）；
- 需要复用内部客户端（asr/tts/models）、复杂 UI、或被其它内置节点依赖 → **内置节点**。

---

## C. 资源与并发登记（重要）

如果新节点消耗 GPU / TTS 等本地稀缺资源，务必在 `backend/control_plane/workflow_runtime.py` 登记，否则会破坏统一限流：

- `RESOURCE_BY_NODE_TYPE`：加 `"my_gpu_node": "gpu"` 或 `"my_tts_node": "tts"`；
- 若交由 GPU 服务层调度：`GPU_SERVICE_MANAGED_NODE_TYPES` 加入该节点 id（见 `gpu-service.md`）；
- 纯网络/API 节点：无需登记资源，反而会进入 `RESOURCE_FREE_NODE_TYPES` 允许并发。

---

## D. 新节点接入 Checklist

- [ ] `builtin_node_types.py` 增加节点定义（id 唯一、category 合法、io 与表单完整）
- [ ] `step_registry.py` 用 `register_step` 映射 `S_*` 类
- [ ] `S_*` 继承 `BaseStep`，实现 `_pre_execute`/`_execute`/`_post_execute`
- [ ] 输入缺失时 `_pre_execute` 抛 `ValueError`（前端显示校验错误）
- [ ] 产物用 `{base}_{node_id}{ext}` 命名或用 `find_artifact` 反查
- [ ] 进度用 `log_progress` 上报
- [ ] 若耗 GPU/TTS：登记 `RESOURCE_BY_NODE_TYPE` 与（可选）`GPU_SERVICE_MANAGED_NODE_TYPES`
- [ ] 若需专属 UI：在 `NodeManager.tsx: TEMPLATE_NODE_COMPONENTS` 注册
- [ ] 自定义节点：写 `backend/config/node_types/<id>.json`，确认 `execType` 与 `OUTPUTS_JSON_PATH` 写入格式
- [ ] 跑一个最小工作流验证（`task-execution.md`），`read_lints` 无错

---

## E. 常见新增节点示例（当前版本已存在，供参考命名风格）

- 智能体：`agent`（pi_agent）
- 媒体获取：`media_to_url`、`platform_download`
- 字幕处理：`subtitle_theme`（主题）、`reorder_subtitles`（重排）、`subtitle_position_search`、`subtitle_recognition`
- 控制流：`run_wait`（运行等待）、`condition`、`loop`、`merge`、`delay`
- 发布：`publish`、`social_publish`、`xiaopai_publish`
- 去水印：`lcwr_watermark_removal`、`online_watermark_removal`

命名风格：小写 + 下划线，动词/名词组合，与既有节点一致。
