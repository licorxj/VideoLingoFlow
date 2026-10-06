# 风格模板资产（画风 / 视频风格）

本目录是**风格模板 json 资产**，供工作流节点「提示词组装」弹窗选择、渲染。

| 文件 | 用途 | 消费方 |
|---|---|---|
| `art_styles.json` | 画风风格模板（生图） | 生图类节点（人物/场景/道具/分镜帧） |
| `video_styles.json` | 视频风格模板（图生视频 / 文生视频） | 分镜视频节点 |

接口（后端 `backend/api/style_templates.py`）：

- `GET  /api/style-templates?kind=art|video&category=&keyword=`
- `GET  /api/style-templates/{kind}/{id}`  模板详情（含变量槽表单）
- `POST /api/style-templates/assemble`     按模板 + 变量值渲染提示词（不调 LLM）
- `POST /api/style-templates/optimize`     用 LLM 模板优化提示词

## 模板结构（源自 AI-Visual-Prompt-Cookbook v2.1，MIT，已简化）

```json
{
  "kind": "art",
  "version": 1,
  "sources": [{"id": "builtin", "name": "项目内置中文漫剧画风", "license": "project"}],
  "common_variables": [
    {"key": "subject", "label": "主体/画面内容", "required": true, "default": "", "placeholder": "..."}
  ],
  "templates": [
    {
      "id": "builtin-japanese-anime",
      "name": "日式动漫",
      "slug": "japanese-anime",
      "category": "动漫",
      "lang": "zh",
      "source": "builtin",
      "tags": ["科幻", "热血"],
      "summary": "经典日式动画质感，少年向热血/科幻",
      "prompt_template": "日式赛璐璐动画风格，清晰线条……，{subject}，{composition}，{lighting}，{extra}",
      "negative_prompt": "低画质，模糊，变形……",
      "variables": [{"key": "composition", "default": "中景"}],
      "fidelity_anchors": ["赛璐璐平涂", "清晰墨线"],
      "avoid": ["写实照片质感"]
    }
  ]
}
```

字段说明：

- `prompt_template`：提示词模板，`{key}` 为变量槽；渲染时未提供值的槽用 `default`，仍为空则
  删除该槽并清理多余分隔符（不会出现 `，，`）
- `common_variables`：文件级公共槽；模板内 `variables` 按 `key` 覆盖 `label`/`default`
- `negative_prompt`：随模板一起带出，前端可编辑后传入生图接口
- `fidelity_anchors` / `avoid`：风格保真锚点与禁忌词（人工维护/LLM 优化时的约束参考）

## 数据来源与许可

| source | 内容 | 许可 |
|---|---|---|
| `builtin` | 项目内置 21 条中文漫剧画风（与 `cp_style_presets` 表内置一致） | 项目自有 |
| `fooocus` / `sai` | Fooocus `sdxl_styles` 风格词条（含 Stability AI SDXL 官方风格集） | 上游仓库 GPL-3.0；**本项目仅取用风格词条文本**，未引入任何代码 |
| `cookbook` | 模板 json 结构规范（变量槽 + prompt_template + negative_prompt） | MIT |
| `self` / `awesome-ai-video-prompts` | 视频风格：镜头语言维度（景别/运镜/光线/色调/节奏）自研，词条素材来自 | MIT |

> 视频风格模板为**自研**：开源界暂无成熟的视频风格 json 库，本文件按镜头语言维度自行组织。

## 提示词优化 LLM 模板

放在 `backend/config/drama_prompts/`：

- `image_prompt_optimize.md` — 生图提示词优化（静态画面，不写运动/运镜）
- `video_prompt_optimize.md` — AI 视频提示词优化（补运动、运镜、景别）

两者均基于 Wan2.1 `wan/utils/prompt_extend.py`（**Apache-2.0**，Alibaba Wan Team）的
`LM_ZH_SYS_PROMPT` 改写，改文件即生效（无需改代码）。

step 映射（LLM 路由按步选模 + 模板正文读取）：

- `backend/steps/s_agi_comic.py:: _STEP_PROMPT_FILES`：`prompt_opt_image` / `prompt_opt_video`
- `backend/config/style_templates.py:: optimize_step_name()`、`load_optimize_system_prompt()`
- 节点实现：`backend/steps/s_prompt_optimize.py`（`prompt_opt_image` / `prompt_opt_video` 两个通用节点）
