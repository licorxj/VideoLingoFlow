# 工作流编排能力

> 本能力文档供工作流编排助手按需读取。所有路径相对 PROJECT_ROOT。
> 产品：VideoLingoFlow（中文名：流连视听）。

---

## 一、目标与职责

本助手负责把用户的**处理需求**转化为一份可执行的**工作流 DAG**，包括：

1. 按需求挑选节点（内置 + 自定义）、规划节点顺序与分支；
2. 书写合法的工作流 JSON（`backend/config/workflows/{wf_id}.json`，顶层 `type: "user"`）；
3. 保证节点连线端口类型匹配、config 的 key 合法；
4. 指导用户保存、校验、执行与断点续跑（涉及 API 时以《backend-api-catalog.md》与代码为准）。

所有约定均以当前代码库真实实现为准：**控制平面（Celery）+ 工作流运行时（`backend/control_plane/workflow_runtime.py`）**，工作流 = 节点 + 连线的有向无环图。不要编造未在代码中出现的接口或字段。

---

## 二、核心概念

### 2.1 工作流 = DAG

- 工作流是一个 **DAG（有向无环图）**：由若干**节点**（node）和**连线**（edge）组成，不允许成环。
- 一句话：**工作流 = 数据从「输入」流向「输出」的处理管线**。
- 执行：从 `input` 节点开始，按依赖顺序依次执行；每个节点读取上游产物、产出新产物，状态实时写入任务。

### 2.2 节点（node）

- 一个节点 = 一个处理步骤，如「音频分离」「语音识别」「逐句翻译」「字幕烧录」。
- 节点定义含 **inputs（输入端口）/ outputs（输出端口）** 列表，每个端口有 `id`、`label`、`type`（端口类型）与 `required`（输入是否必填）。
- 节点分两类：
  - **内置节点**：定义在 `backend/config/builtin_node_types.py`；可用项会受 `backend/config/deleted_builtin_node_ids.json` 过滤。
  - **自定义节点**：由前端「节点管理器」创建/导入，定义在 `backend/config/node_types/{node_id}.json`，执行类型可为 `python` / `shell` / `llm` / 透传。
  - **组合节点**：`kind: "group"`、`category: "group_node"` 的自定义子图定义；编辑期保留内部工作流，运行期展开为普通节点和连线。
- 每个节点有 **执行域**：
  - `thread`：线程内执行，轻量，适用于文件操作、字幕处理等；
  - `process`：子进程隔离执行，适用于重型/网络/音视频任务（如 ASR、TTS、下载、发布），可硬停止。

### 2.3 连线（edge）

- 连线 = 数据从上游节点的**输出端口**流向**下游节点的输入端口**。
- 连线必须引用真实存在的节点与端口，**端口类型必须兼容**（见 2.4）。
- 连线两端通过 `sourceHandle` / `targetHandle` 定位端口，命名规则固定：
  - 输出端口 handle：`out-<输出端口id>`（如 `out-video`、`out-audio`）
  - 输入端口 handle：`in-<输入端口id>`（如 `in-video`、`in-asr_audio`）

### 2.4 端口类型（PortType）

| 类型 | 含义 | 典型来源 |
|---|---|---|
| `video` | 视频文件 | input 节点视频、下载、合成结果 |
| `audio` | 音频文件 | 提取/分离/合并结果 |
| `audio_manifest` | 音频清单 JSON | 配音任务单 |
| `json` | JSON 数据文件 | ASR 结果、翻译结果、任务单等 |
| `pandas` | 表格数据 | TTS 任务表 |
| `subtitle` | 字幕文件 | 字幕生成结果 |
| `text` | 文本文件 | 标题、prompt、LLM 结果 |
| `image` | 图片文件 | 封面、帧图、水印图 |
| `url` | URL 字符串 | input 节点 url、下载输入 |
| `preview` | 预览 | 预览节点内部 |
| `any` | 通用 | 可连接任何类型 |

连线规则（`backend/workflow_validation.py` 中 `_can_connect` 实现）：
- **同类型才能连线**：`video→video`、`audio→audio`、`json→json`、`subtitle→subtitle`、`text→text`…；
- **`any` 是万能端口**：`any` 可连任意类型（源或目标任意一侧为 `any` 即合法）；
- 一个输出端口可连多个下游；**同一输入端口不要连多条边**（后写入的会覆盖）。

---

## 三、存放位置

| 项 | 位置 | 说明 |
|---|---|---|
| 用户工作流文件 | `backend/config/workflows/{wf_id}.json` | 顶层 `type: "user"`，本助手的主要产出物 |
| 内置节点定义（只读） | `backend/config/builtin_node_types.py` | 节点清单的唯一权威来源 |
| 自定义节点定义 | `backend/config/node_types/{node_id}.json` | 节点管理器创建/导入，前端可见 |
| 自定义节点代码目录 | `backend/nodes/{node_id}/` | python 类型节点的 run.py 等 |
| 任务私有工作流快照 | `control_plane_workspaces/{task_id}/workflow.json` | 执行/保存时自动写入，**不要手写**；实际根目录由环境变量 `CONTROL_PLANE_WORKSPACE_ROOT` 决定 |
| 全局工作流固定调试任务 | 控制平面 DB（`payload.is_debug=True`） | 由 `debug-task` 接口自动接管，**不要手写** |

要点：

- **工作流文件是 JSON，文件名即工作流 id**（不含 `.json`）。前端「工作流编排」页面加载的就是这些文件。
- **任务与工作流解耦**：全局工作流绑定一个固定调试任务（`is_debug`），一般任务/批量子任务各自持有私有工作流快照，互不影响。
- 保存时只写**用户工作流文件**，任何任务目录下的 `workflow.json`、`task.json` 一律由系统自动维护。

---

## 四、工作流 JSON 书写格式

### 4.1 顶层结构

```json
{
  "id": "my_workflow_id",
  "name": "我的工作流",
  "description": "一句话描述",
  "type": "user",
  "nodes": [ ...节点数组... ],
  "edges": [ ...连线数组... ],
  "createdAt": "2026-08-09T00:00:00.000Z",
  "updatedAt": "2026-08-09T00:00:00.000Z"
}
```

- `type` 必须是 `"user"`（`"task"` 是任务内部快照类型，**不要手写**）。
- `id` 全局唯一，建议小写字母/数字/下划线。
- `createdAt` / `updatedAt` 为 ISO 时间字符串，可省略（保存接口会规范化）。

### 4.2 节点定义

```json
{
  "id": "n_001",
  "type": "workflow",
  "position": { "x": 0, "y": 0 },
  "data": {
    "nodeType": "extract_audio",
    "label": "音频分离",
    "config": { "format": "wav", "sample_rate": "44100" }
  }
}
```

| 字段 | 说明 |
|---|---|
| `id` | **画布内唯一**节点 id（建议 `n_` 前缀，供连线引用） |
| `type` | 固定 `"workflow"` |
| `position` | 画布坐标，仅排版用，任意值即可（缺失时后端按网格自动补） |
| `data.nodeType` | **节点类型 id**（必须是节点清单中的 id，见第 5 节） |
| `data.label` | 画布显示名 |
| `data.config` | 节点配置字典，**key 必须来自该节点定义 `configFields`**（未知 key 会被忽略，不报错但无效） |

### 4.3 连线定义

```json
{
  "id": "e_001",
  "source": "n_001",
  "target": "n_002",
  "sourceHandle": "out-audio",
  "targetHandle": "in-video",
  "data": { "sourcePort": "audio", "targetPort": "video" }
}
```

| 字段 | 说明 |
|---|---|
| `source` / `target` | 上游 / 下游节点 id，必须存在于 nodes |
| `sourceHandle` | `"out-" + 上游节点的输出端口 id` |
| `targetHandle` | `"in-" + 下游节点的输入端口 id` |
| `data.sourcePort` / `data.targetPort` | 端口 id 冗余字段（前端写入，后端校验时重新规范化） |

### 4.4 端口匹配（校验与规范化）

保存/执行时后端调用 `normalize_workflow`（`backend/workflow_validation.py`）校验每条边：

1. `source` / `target` 必须在 nodes 中存在，且 `sourceHandle` 以 `out-` 开头、`targetHandle` 以 `in-` 开头；
2. 端口 id 必须存在于对应节点定义的 outputs/inputs 中；
3. 两端端口类型必须满足 `_can_connect`（相同类型或任一侧为 `any`）；
4. **端口不存在或类型不匹配的边会被直接删除**（保存后边数可能减少，这是正常现象）；
5. 历史遗留 handle 会被自动迁移（下表），迁移后回写规范化 handle：

| 节点 | 方向 | 旧 handle | 迁移为 |
|---|---|---|---|
| `asr` | 输入 | `in-audio` | `in-asr_audio` |
| `asr` | 输出 | `out-asr_result` | `out-subtitle` |

> 注意 `asr` 的输出端口类型是 `json`（ASR 结果 JSON），不要误以为 `subtitle` 端口是字幕文件。

### 4.5 组合节点

- 组合仅允许封装连通的普通节点，内部禁止嵌套组合。
- 实例数据在 `data.groupMeta`，含 `internalWorkflow`、`inputMappings`、`outputMappings`；节点类型库中的可复用定义使用 `groupDefinition`。
- 外部输入映射到内部目标端口；输出由映射中 `enabled !== false` 的内部输出显式暴露。
- 编排时可保持组合结构；提交执行时必须经过 `expandGroupNodesForExecution` 或后端 `normalize_workflow(..., expand_groups=True)` 展平。不要为组合节点创建 `BaseStep` 或 `step_registry` 注册。
- 组合成员配置位于 `internalWorkflow.nodes[].data.config`，可在前端组合卡片内直接编辑；修改时必须保留内部 edges 和映射。

---

## 五、可用节点清单获取方式

任何时候需要**完整、最新**的节点清单，按以下顺序获取（不要凭记忆）：

1. 直接读取 `backend/config/builtin_node_types.py` 并通过 `get_builtin_node_types()` 获取有效内置节点；
2. 调用 `GET /api/node-types`（返回内置 + 自定义全部节点，自定义带 `isBuiltIn: false`）；
3. 自定义节点也可读 `backend/config/node_types/*.json`。

每个节点定义中你需要关注的字段：

| 字段 | 用途 |
|---|---|
| `id` | 即 `data.nodeType` 的值 |
| `name` | 节点中文名 |
| `execution_domain` | `thread` / `process`（决定执行环境） |
| `inputs[].id/.type/.required` | 输入端口 id 与类型（连线 `in-<id>`、同类型匹配） |
| `outputs[].id/.type` | 输出端口 id 与类型（连线 `out-<id>`） |
| `defaultConfig` | 默认配置（可省略不写） |
| `configFields[].key` | 合法的 config key；`type: select` / `chips` 的 `options` 给出可选值 |

### 5.1 内置节点总表（41 个，来自 builtin_node_types.py）

> 分类对应前端节点面板；`输入 → 输出` 中的名称即端口 id（`out-`/`in-` 前缀即为 handle）；`config` 只列关键项，全部可选字段以 `configFields` 为准。

**输入 / 输出 / 预览**

| 节点 id | 名称 | 执行域 | 输入 → 输出 | 关键 config |
|---|---|---|---|---|
| `input` | 输入 | thread | （无）→ `video`/`audio`/`subtitle`/`url` | `selectedTypes`(chips: video/audio/subtitle/url)、`videoPath`/`audioPath`/`subtitlePath`/`url`、`source_language`/`target_language`、`copyInputs`、`var1`/`var2`(+`var1Required`/`var2Required`) |
| `output` | 输出 | thread | `any` → （无） | `outputDir`、`fileName`、`suffix`、`autoIncrement` |
| `video_preview` | 视频预览器 | thread | `video`/`subtitle`/`original`/`bilingual` → （无） | 仅预览，无执行 |
| `image_preview` | 图片预览器 | thread | `image` → （无） | 仅预览，无执行 |

**下载 / 工具类**

| 节点 id | 名称 | 执行域 | 输入 → 输出 | 关键 config |
|---|---|---|---|---|
| `platform_download` | 平台视频下载 | process | `url` → `video`/`subtitle`/`image` | `download_subs`、`download_cover`、`resolution`(best/1080p/720p)、`cookie_file`、`use_as_task_name` |
| `path_to_title` | 路径转标题 | thread | `any` → `text` | `read_from_input`、`template`(占位符 {filename}/{parent}/{grandparent})、`update_task_name` |
| `file_rename` | 文件改名 | thread | `any` → `any` | `rename_mode`(custom/prefix/suffix)、`custom_name`/`prefix`/`suffix` |
| `resolve_path` | 取文件路径 | thread | `any` → `any` | `relative_path`(如 `output/video.mp4`、`cache/subtitle.srt`) |
| `json_to_text` | JSON转文本 | thread | `json` → `text` | `mode`(full/key)、`key_expr`(key0$key1$key2) |
| `json_editor` | JSON编辑 | thread | `json`/`text` → `json` | `key_expr`、`value_source`(auto/input/custom)、`custom_value` |
| `video_split` | 视频切割 | thread | `video`/`audio` → `video`/`text` | `split_mode`(count/duration)、`segment_count`、`segment_duration`、`use_silence` |
| `timed_delay` | 定时执行 | thread | `any` → `any` | `delay_mode`(time_point/countdown)、`target_date`/`target_time`、`countdown_hours/minutes/seconds` |
| `translate_task_name` | 翻译项目名称 | thread | `any` → `text` | `replace_task_name` |
| `http_request` | 网络请求 | process | `input_1`/`input_2`/`input_3`(any)/`request_data`(json) → `result`(any)/`json`/`text`/`status` | `request_client`(requests/httpx/curl)、`url`、`method`、`headers`、`body`(支持 {input_1} 等占位符)、`retry_enabled`/`retry_count`/`retry_interval`、`timeout`、`success_status_codes`、`output_format`、`browser_impersonation`、`ignore_connected_inputs` |

**音频处理**

| 节点 id | 名称 | 执行域 | 输入 → 输出 | 关键 config |
|---|---|---|---|---|
| `extract_audio` | 音频分离 | thread | `video` → `audio` | `format`(wav/mp3/flac/m4a)、`sample_rate`(44100/48000/16000) |
| `vocal_separation` | 人声分离 | process | `audio` → `audio`(人声)/`background`(背景) | `method`(api-select: /api/separation-interfaces/enabled)、`model`、`format` |
| `track_separation` | 音轨分离 | process | `audio` → `vocals`/`bass`/`drums`/`guitar`/`piano`/`other` | `method`(demucs)、`model`(如 htdemucs_6s)、`format` |
| `merge_audio` | 音频合并 | thread | `audio_manifest`/`video` → `audio`/`dub_srt`/`dub_bilingual_srt`/`video_adjusted` | `video_speed_adjust`、`speed_min/max`、`gap_threshold`、`audio_format` |
| `merge_dub` | 配音拼接 | thread | `audio`/`audio_manifest` → `audio`/`dub_srt` | `audio_format`、`audio_bitrate`、`silence_interval`（无时间戳纯文本配音用） |

**AI 处理链（ASR → 翻译 → 字幕）**

| 节点 id | 名称 | 执行域 | 输入 → 输出 | 关键 config |
|---|---|---|---|---|
| `asr` | 语音识别 (ASR) | process | `asr_audio`(必填)/`vocal_audio` → `subtitle`(ASR结果JSON) | `engine`(api-select)、`language`(from_input/auto/zh/en/ja/ko/fr/de/es/pt/ru)、`model`、`word_timestamps`、`hotwords_enabled`/`hotwords`、`vad_onset`/`vad_offset` |
| `sentence_preprocess` | 断句预处理 | thread | `json`/`text` → `subtitle`/`word_index` | `method`(asr/punct/ai)、`split_on_speaker`、`llm_max_chars` |
| `sentence_split` | 句子分割 | thread | `subtitle`(ASR JSON) → `subtitle`/`text` | `max_sentence_length`、`use_llm_split`、`split_sentence_ends`、`split_clause_breaks`、`split_on_speaker`、`merge_min_duration`/`merge_short_enabled`、`merge_max_gap`/`merge_gap_enabled`、`pause_split_threshold`/`pause_split_enabled` |
| `summarize` | 内容总结 | process | `text` → `subtitle`(总结JSON) | `summary_length`、`use_custom_terminology`、`custom_terminology_file` |
| `translate` | 逐句翻译 | process | `subtitle`(必填)/`summary` → `subtitle`(直译)/`reflect`(反思) | `reflect_translate`(follow_global/yes/no)、`translation_style`、`batch_char_limit` |
| `subtitle_align` | 译文断句和双语对齐 | thread | `subtitle` → `subtitle` | `max_subtitle_length` |
| `subtitle_gen` | 字幕生成 | thread | `subtitle`(句子/翻译/对齐JSON) → `subtitle`(译文)/`original`(原文)/`bilingual`(双语) | `file_prefix`、`filter_punctuation` |
| `llm_request` | 通用LLM请求 | process | `text`/`image`/`json` → `result`(JSON)/`text` | `model`、`system_prompt`、`user_prompt`(可用 {input_text}/{input_json}/{source_language}/{target_language} 占位符)、`temperature`、`response_json` |
| `editor_agent` | 剪辑AI Agent | process | `text`(编辑指令) → `project`/`artifacts`/`result` | `instruction`、`expert_role`(auto/general/design/audio/editing/storytelling) |

**AI 生成类**

| 节点 id | 名称 | 执行域 | 输入 → 输出 | 关键 config |
|---|---|---|---|---|
| `dub_task` | 生成配音任务 | thread | `subtitle`(句子时间戳JSON) → `text`(TTS任务单)/`pandas` | `ai_read_tone`、`normalize_chinese_read_text`、`ai_dialect_colloquial`、`dialect_name` |
| `tts` | 语音合成 (TTS) | process | `text`(任务单)/`pandas` → `text`/`pandas` | `tts_mode`、`tts_engine`、`clone_source`、`ref_audio_path`、`voice_role_1..4`、`speed_regenerate` |
| `cover` | AI封面设计 | thread | `json`(内容JSON) → `prompt`(文本) | `design_mode`(ai_design/custom_prompt)、`custom_title`/`custom_subtitle`、`ai_prompt`、`custom_prompt`(占位符 {title}/{subtitle}) |
| `image_gen` | AI生图 | process | `text`/`image` → `images`(JSON列表)/`text`(首张图片) | `mode`(txt2img/img2img)、`interface`、`model`、`resolution`(1K/2K/4K)、`aspect_ratio`、`num_images`、`custom_prompt` |
| `aigc_comfyui` | ComfyUI 生图 | thread | `text`/`reference_video`/`first_frame`/`image2..4`/`last_frame` → `images`/`first`/`files` | `workflow_json`(Z-Image 等)、`mode`(txt2img/img2img)、`resolution_*`（本地/局域网 ComfyUI） |
| `aigc_runninghub` | RunningHub 生成 | process | 同上输入 → `images`/`first`/`files` | 云端 RunningHub 工作流（参数来自「其他能力接口」设置） |
| `aigc_jimeng` | 即梦 CLI 生成 | process | 同上输入 → `images`/`first`/`files` | 即梦 CLI |

**视频合成 / 发布**

| 节点 id | 名称 | 执行域 | 输入 → 输出 | 关键 config |
|---|---|---|---|---|
| `merge_sub_video` | 字幕烧录 | thread | `video`(必填)/`subtitle`(必填)/`audio`(BGM)/`dub`(配音) → `video` | `video_quality`(copy/high/medium/low)、`mute_original`、`bgm_volume`、`dub_volume`、`preset_id`(字幕样式) |
| `merge_dub_video` | 配音视频合成 | thread | `video`/`audio`(配音) → `video` | 无 |
| `watermark` | 水印添加 | thread | `video`/`image`(水印图) → `video` | `enabled`、`position`、`opacity` |
| `video_frame_extract` | 视频抽帧 | thread | `video`/`srt`(字幕) → `image` | `video_source`(input_node/connection)、`time_point`、`time_mode`(positive/negative)、`avoid_subtitles` |
| `cutia` | Cutia 交互剪辑 | thread | `video`/`audio`/`image`/`subtitle` → `video` | 无（手工剪辑，等待成片） |
| `video_publish` | 视频发布 | process | `video`(必填)/`cover_landscape`/`cover_portrait`/`json`(标题描述) → `text`/`result_file` | `account_ids`、`title`/`description`(留空读上游JSON)、`tags`、`publish_mode`(publish/platform_draft/local_draft)、`schedule_enabled`/`schedule_time`、`is_original` |

### 5.2 自定义节点

- 通过前端「节点管理器」创建或导入的节点自动出现在 `GET /api/node-types` 与节点面板中，id 即 `nodeType`。
- 定义存 `backend/config/node_types/{id}.json`；python 类型节点的代码在 `backend/nodes/{id}/`（或内联 `execCode`），另有 `shell` / `llm` 类型。
- 编排时与内置节点一样按端口类型连线、填 config 即可。若清单中没有用户需要的节点，提示需要先在「节点管理器」创建（详见 `node-creation.md`）。

---

## 六、编排步骤（如何根据需求规划 DAG）

### Step 1 识别输入

用户提供什么？→ 视频文件 / 音频文件 / 字幕文件 / URL / 纯文本。

- 在 `input` 节点设置 `selectedTypes`（chips）与对应 `videoPath`/`audioPath`/`subtitlePath`/`url`；
- 设置 `source_language`、`target_language`（如 `auto`→`zh`）；
- URL 输入时配 `platform_download` 下载成视频/字幕/封面。

### Step 2 识别目标（常见链路）

| 用户目标 | 建议 DAG |
|---|---|
| 翻译配音成片 | input → extract_audio → asr → sentence_split → translate → subtitle_align → subtitle_gen → merge_sub_video；配音分支 → dub_task → tts → merge_audio → merge_dub_video |
| 仅字幕 | input → extract_audio → asr → sentence_split → translate → subtitle_align → subtitle_gen |
| 纯转写/提取文字 | input → extract_audio → asr → sentence_split（→ summarize → llm_request） |
| 视频下载+处理 | input(url) → platform_download → … |
| AI 封面 + 生图 | …json → cover → image_gen → image_preview / output |
| 发布 | … → video_publish（video 必填，封面走 cover_landscape/cover_portrait，标题描述走 json 或手填） |

### Step 3 连线（严格按端口）

- 上游**输出端口 id** → 下游**输入端口 id**，`sourceHandle = "out-" + 上游端口id`、`targetHandle = "in-" + 下游端口id`，**两端类型必须相同**（或任一侧为 `any`）。
- 典型示例：
  - `input.out-video` → `extract_audio.in-video`（video→video）；
  - `extract_audio.out-audio` → `asr.in-asr_audio`（audio→audio，注意 asr 的输入端口叫 `asr_audio` 不叫 `audio`）；
  - `asr.out-subtitle` → `sentence_split.in-subtitle`（json→json）；
  - `sentence_split.out-subtitle` → `translate.in-subtitle`（json→json）；
  - `sentence_split.out-text` → `summarize.in-text`（text→text）。

### Step 4 填 config

- 每个节点填关键配置（见第 5 节），**可省略的默认值不写**；
- 语言、引擎、模型等留空则跟随全局配置；`asr.language` 可设 `from_input` 跟随 input 节点；
- config 的 key 必须来自该节点 `configFields`，未知 key 会被忽略（不报错但无效）。

### Step 5 保存与校验

1. 保存到 `backend/config/workflows/{id}.json`，顶层 `type: "user"`；
2. 用前端「工作流编排」页打开检查（会自动调 `GET /api/workflows/{id}` 详情），或直接读回文件核对；
3. 重点关注：节点 id 是否画布内唯一、连线两端的端口是否真实存在且类型匹配、`data.nodeType` 是否在清单中。

### Step 6 执行与断点（供用户操作，涉及接口以代码为准）

- 打开全局工作流时前端自动调用 `POST /api/workflows/{id}/debug-task`（body 传画布快照）**接管固定调试任务**（`is_debug`，无则用画布快照初始化），后续调试执行都写回该任务、不每次新建。
- 执行模式 `mode`（`POST /api/workflows/{id}/execute`，body: `{nodes, edges, mode, task_id, input}`）：
  - `debug` / `resume`：写回固定调试任务（或指定 `task_id`），**增量重建**，保留已 succeeded 节点（断点续跑）；
  - `restart`：全量重建并重跑；
  - `restart_clean`：**从头执行**，先清空任务 cache 再全量重建（对应前端「从头执行」）；
  - `new`：新建一个 detached 一般任务并投递执行，与全局调试任务解耦。
- 「新建一般任务」编辑态：`POST /api/workflows/{id}/spawn-task`（仅建任务+写私有 workflow.json，不执行）。
- 一般任务「另存为全局」：`POST /api/workflows/{id}/save-as-global`。
- 节点级执行：`POST /api/workflows/{id}/execute-node`（`task_id` 必传且必须与当前工作流匹配；`scope=node` 仅执行本节点——始终提交完整工作流、用 `exec_only` 收窄，不覆盖任务私有 workflow；`scope=downstream` 执行本节点及其连线下游）。
- 执行状态：`GET /api/workflows/{id}/status` 返回任务与节点状态（内部 `pending/running/succeeded/failed` 等，降级映射后对外展示 `pending/running/completed/failed/cancelled`）与产物。

---

## 七、校验与常见错误

### 7.1 后端校验行为（normalize_workflow）

| 行为 | 触发条件 |
|---|---|
| 删除非法边 | source/target 不存在；handle 不以 `out-`/`in-` 开头；端口 id 不在节点定义中；端口类型不兼容 |
| 迁移 legacy handle | `asr` 的 `in-audio`→`in-asr_audio`、`out-asr_result`→`out-subtitle` |
| 补全 position | 节点缺 `position` 时按网格自动铺排（防止前端崩溃） |
| 忽略未知 config key | config 中有不在 `configFields` 的 key（不报错但无效） |

### 7.2 常见错误排查

| 错误现象 | 原因 | 修复 |
|---|---|---|
| 保存后边数变少 | 端口 id 或类型不匹配，被 `normalize_workflow` 删除 | 核对 `sourceHandle=out-<id>`、`targetHandle=in-<id>`、端口类型相同 |
| 执行报「未知工作流节点」 | `nodeType` 不在节点注册表 | 确认 id 拼写正确且已注册（内置 41 个 + 自定义） |
| 节点一直 waiting 不执行 | 前置节点未完成或未连线 | 检查依赖边完整、上游已 completed |
| 下游找不到产物 | 上游未产出该端口 / 端口 id 连错 | 核对上游 outputs 端口 id 与 handle |
| input 节点没数据 | `selectedTypes` 未包含对应类型，或路径无效 | 检查 config：videoPath 需为本地绝对路径 |
| 执行节点报「节点执行必须指定任务」 | `execute-node` 未传 `task_id` 或任务与工作流不匹配 | 节点执行必须在当前任务边界内：先打开/接管调试任务或进入一般任务再执行 |
| 调试进度丢失、每次新建任务 | 全局工作流未走固定调试任务 | 打开工作流时前端应调用 `debug-task` 接管；确认前端已更新 |
| config 填了字段但无效 | key 不在 `configFields` | 以节点定义的 `configFields` 为准取 key |

---

## 八、注意与禁忌

1. **一个工作流只用一个 `input` 节点作为数据源**（需要多路输入可复用其 `var1`/`var2` 或再放 input）。
2. **节点 id 画布内唯一**，`data.nodeType` 必须是节点清单中的 id。
3. **连线端口类型必须一致**（`any` 万能）；同一输入端口只连一条边。
4. **config 的 key 必须来自该节点 `configFields`**，未知 key 会被忽略（不报错但无效）。
5. **不要手写 `type: "task"` 的工作流**，那是执行快照；用户工作流文件必须是 `type: "user"`。
6. 大工作流建议分段编排：先验证中间产物（用 `video_preview`/`image_preview`/`output` 节点），再补全下游。
7. **不要手写任务目录下的 `workflow.json` / `task.json`**：任务私有快照由执行/保存自动维护，与全局工作流文件解耦。
8. **节点执行（execute-node）必须在任务边界内**：必须携带与当前工作流匹配的 `task_id`，后端会拒绝空/跨任务的节点执行。
9. 端口命名规则固定为 `out-<端口id>` / `in-<端口id>`，端口 id 以节点定义为准（如 asr 的输入端口是 `asr_audio`，不是 `audio`）。
10. 端口类型以节点定义 `inputs/outputs` 的 `type` 为准，**不要凭端口名猜测类型**（如 asr 的 `subtitle` 输出端口实际类型是 `json`）。
