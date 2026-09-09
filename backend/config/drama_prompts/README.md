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
| `video_prompt.md` | `agi_shot_video` | 视频提示词拼装规范 |

## 运行机制

```
节点 run() → _load_prompt("<模板>.md")  →  剥离 YAML frontmatter
                                        ↓
system_prompt = <模板正文> + "\n\n" + <节点内置的字段/JSON schema 约束>
```

- **模板缺失或为空**时，节点回退到内置 system 提示词，**不会中断流程**；
- **JSON schema 与字段约束始终由代码追加在最后**：人工改写模板不会破坏入库格式，
  但如果模板正文与 schema 冲突，以代码追加的 schema 为准；
- 模板正文可自由调整文风与方法论，但**不要改动示例中的字段名**（如 `synopsis`、`content_plan`），
  节点按这些键解析入库。

## 新增/覆盖

- 覆盖：直接编辑对应 MD（支持中文，UTF-8）；
- 新增：把新 MD 放进本目录，节点侧调用 `_load_prompt("新文件.md")` 即可；
- 禁用某个模板：清空文件内容（或删除），节点自动回退内置提示词。

## 字段契约（与本项目数据库一致）

- 人物：`name / gender / age / personality / occupation / aliases / relationship_note / voice_design / visual_anchor`
  （`visual_anchor` 造型锚点会以 `【造型】` 前缀写入 `personality`）
- 场景：`name / description`（`description` 内按「地点 / 时间 / 陈设 / 光影 / 氛围」结构化成段）
- 章节：`title / original_text / summary`
- 分镜：`characters / scene_descriptions / dialogues[{character, content}] / bgm_design / sfx_design`
  （可选 `camera` / `duration` 会以 `【运镜】`/`【时长】` 标记并入 `scene_descriptions`）
