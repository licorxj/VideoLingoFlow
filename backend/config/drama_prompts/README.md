# AI 漫剧提示词模板库

本目录的 MD 模板在**节点调用 LLM 时作为 system prompt 注入**，用于约束各阶段产出的专业度。

## 模板与节点映射

| 模板文件 | 消费节点 | 阶段 |
|---|---|---|
| `project_outline.md` | `agi_project` | 立项 · 故事骨架 |
| `deepen_bible.md` | `agi_deepen` | 剧本深化（简介/章节规划/人物提炼/画风锁定） |
| `character_extract.md` | `agi_character` | 人物资产 |
| `scene_extract.md` | `agi_scene` | 场景资产 |
| `chapter_plan.md` | `agi_chapter` | 章节剧本 |
| `storyboard_break.md` | `agi_shot` | 分镜拆解 |
| `video_prompt.md` | `agi_shot_video` | 视频提示词拼装规范（**frontmatter 参数运行时生效**，非 system prompt 注入） |

## 运行机制

```
节点 run() → _load_prompt("<模板>.md")  →  剥离 YAML frontmatter
                                        ↓
system_prompt = <模板正文> + "\n\n" + <节点内置的字段/JSON schema 约束>
```

`video_prompt.md` 是**拼装规则**而非 LLM 提示词：`S_AGI_ShotVideo` 通过
`_video_prompt_rules()` 读取其 frontmatter 参数（段长 / 衔接词 / @引用 / 台词模板 /
运镜位置等）驱动确定性拼装，**改文件即生效**；节点显式配置同名项优先，文件缺失或
参数非法时回退内置默认值。

- **模板缺失或为空**时，节点回退到内置 system 提示词，**不会中断流程**；
- **JSON schema 与字段约束始终由代码追加在最后**：人工改写模板不会破坏入库格式，
  但如果模板正文与 schema 冲突，以代码追加的 schema 为准；
- 模板正文可自由调整文风与方法论，但**不要改动示例中的字段名**（如 `synopsis`、`content_plan`），
  节点按这些键解析入库。

## 新增/覆盖

- 覆盖：直接编辑对应 MD（支持中文，UTF-8）；
- 新增：把新 MD 放进本目录，节点侧调用 `_load_prompt("新文件.md")` 即可；
- 禁用某个模板：清空文件内容（或删除），节点自动回退内置提示词。

## 画风一致性（全链路）

- **唯一来源**：立项（`agi_project`）选定的风格预设或「自定义画风」写入项目骨架的
  `【画风锁定】` 段（落库），全项目共用；
- **唯一取用口**：所有节点的生图 / 提示词组装都必须经 `_style_hint()` 取画风
  （节点「画风补充提示词」→ 项目 `【画风锁定】` → 项目画风标签），**禁止在代码或模板里硬编码画种词**
  （早期版本在立绘/场景/道具/关键帧 prompt 里写死过"动漫风格"，已移除）；
- **剧本深化不得改写画风**：`【画风人工指定】` 已给出（立项已锁定）时，`art_style` 只做细化，
  画种与整体调性保持原样；
- **模板写法**：MD 模板中涉及视觉的约束应写成"以【画风/风格】为准"，不要写死具体画种。

## 字段契约（与本项目数据库一致）

- 人物：`name / gender / age / personality / occupation / aliases / relationship_note / voice_design / visual_anchor`
  （`visual_anchor` 造型锚点会以 `【造型】` 前缀写入 `personality`）
- 场景：`name / description`（`description` 内按「地点 / 时间 / 陈设 / 光影 / 氛围」结构化成段）
- 章节：`title / original_text / summary`
- 分镜：`characters / scene_descriptions / dialogues[{character, content}] / bgm_design / sfx_design`
  （可选 `camera` / `duration` 会以 `【运镜】`/`【时长】` 标记并入 `scene_descriptions`）
