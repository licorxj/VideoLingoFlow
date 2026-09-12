# AI 漫剧链路改进计划

> 参照 `_backup/Drama`（Huobao Drama，专业短剧生产平台）的流程设计与数据结构报告制定。
> 目标：把当前"能跑通演示"的 AI 漫剧链路，升级为**可工业生产**的链路（支持小说改编、单分镜精准重做、生成可追溯）。

## 一、现状与参照系

| 维度 | Drama（参照） | 我们（现状） | 判断 |
|---|---|---|---|
| 配音 / 音色克隆 / 字幕 | 无 | 完整（agi_voice + SRT + 烧录） | **我们强** |
| 整章批处理 | 无 | 支持（chapter_id 驱动） | **我们强** |
| 生成接口管理 | ai_service_configs | imagegen/videogen/tts interfaces | 等价 |
| 多视角图 / 公共角色库 | 单图 image_url | 多视角 + 发布公共库 | **我们强** |
| 分镜生产字段 / 状态机 | 完整（景别/角度/运镜/时长/status） | 已有四层状态机（项目/章节/分镜/资产 status + 断点续跑） | **已补** |
| 资产来源 | 从格式化剧本**提取**并去重 | LLM 凭空**生成** | **需补** |
| 格式化剧本中间产物 | 有（Agent 改写） | 无 | **需补** |
| 分镜↔角色/场景/道具 | ID 关联表 | JSON 名字数组（弱关联） | **需补** |
| 提示词沉淀 | final_prompt 列，可人工调优 | 运行时现拼，不沉淀 | **需补** |
| 生成任务台账 | sys_task（可追溯/重试） | 无 | **需补** |
| 道具实体 | props 表 | 无 | 需补 |
| 分镜拆解量化规则 | 字数→时长→段落数、节拍、台词时长下限 | 手动指定数量 | 需补 |

---

## 二、改进计划

### P0 — 决定成片质量与改编可用性（先做）

| # | 改进项 | 落地内容 | 涉及 |
|---|---|---|---|
| 1 | **分镜生产字段 + 状态机** ✅已完成 | `cp_creation_shots` 增列 `shot_type / angle / movement / duration_seconds / status / image_prompt / video_prompt`；`agi_shot` 按量化规则产出；媒体节点生成前后回写 status；另补 **四层状态机**：`cp_creation_chapters`/`cp_creation_characters` 增 `status` 列，`agi_chapter`/`agi_shot` 按序幂等复用就绪项、单镜节点已存在资产则跳过（断点续跑），`agi_extract`/`agi_prompt` 也落 status | 模型迁移 + agi_shot + 媒体四件套 + agi_chapter/agi_extract/agi_prompt |
| 2 | **资产提取模式** ✅已完成 | `agi_character / agi_scene` 增加 `mode: 生成/从剧本提取`；提取模式以格式化剧本为输入，同名合并（场景按 地点+时间段）；并新增 `agi_extract` 一次性提取人物/场景/道具 | agi_character / agi_scene / agi_extract |
| 3 | **格式化剧本中间产物** ✅已完成 | `agi_deepen` 产出规范剧本（`## S01 \| 内景·地点 \| 时间` + 动作段 + 对白格式）写入章节 `original_text`；`agi_extract/agi_shot` 以此为规范输入；浏览弹窗（`CreationBrowserDialog`）章节卡展示「格式化剧本」并支持人工审改（`PUT /api/creation/chapters/{id}` 更新标题/摘要/剧本文本） | agi_deepen + 浏览弹窗 + 审改接口 |
| 4 | **提示词模板库** ✅已完成 | Drama 技能提示词改造为本项目 MD 模板，节点调用 LLM 时注入 system prompt | `backend/config/drama_prompts/` + 6 个 LLM 节点 |

### P1 — 可运营性

| # | 改进项 | 落地内容 |
|---|---|---|
| 5 | 提示词沉淀 ✅已完成 | 人物/场景/分镜增 `final_prompt` 列（`agi_prompt` 节点生成并回写，可人工改）；运行时拼装作初值 |
| 6 | 生成任务台账 ✅已完成 | 新表 `cp_generation_tasks`（kind/目标 id/interface/model/prompt/上游 task_id/结果/错误/耗时）；`_gen_images`/`_gen_video`/`_tts` 统一登记（线程上下文透传目标），失败留 error；`retry_failed` 只重跑失败分镜并串联 `upstream_task_id` |
| 7 | 道具资产 ✅已完成 | 新表 `cp_creation_props` + 提取产出 + 白底单品图 |
| 8 | 风格预设库 ✅已完成 | 新表 `cp_style_presets`（name/art_style/genre_tags/audience_tags/description/is_builtin）+ 内置 **21 种**常见画风（迁移 `20260909_10` 预置 4 个、`20260910_03` 补齐 17 个，含日式/国漫/欧美/3D卡通/美漫/韩漫/水墨/国潮/工笔/写实/黑白/港漫/蒸汽朋克/哥特/像素/黏土/绘本/Q版 等）；立项节点新增「风格预设」下拉（`/api/creation/style-presets`）**＋「自定义画风」文本框**（优先级最高），选中后自动带出题材/受众并写入【画风锁定】，节点显式标签优先 |
| 8.1 | **全链路画风统一** ✅已完成 | 画风唯一来源 = 立项预设/自定义输入 → 项目骨架【画风锁定】（剧本深化仅在未锁定时才产出画风，不再改写）；立绘/场景/道具/分镜关键帧/章节封面等生图 prompt 一律经 `_style_hint()` 取用，**移除各节点写死的"动漫风格"**；章节/分镜 LLM 提示词也注入画风约束（分镜不写画种词）；模板侧同步修订 `project_outline.md`/`deepen_bible.md`/`character_extract.md`；立绘 prompt 补入造型锚点 `visual_anchor`，提升角色区分度与形象稳定性 |
| 9 | 分镜关联结构化 ✅已完成 | shots 增 `scene_id`（已有列，本轮补写入）；`agi_shot` 按人物名/别名解析 id 写出 `{name, id}`，并按 (地点+时间)→地点 解析 `scene_id`；`_normalize_shot_characters` 支持保留 `id`；迁移 `20260909_09` 数据迁移存量分镜（名字数组→对象 + scene_id 回填） |

### P2 — 增强

| # | 改进项 |
|---|---|
| 10 | 按章节锁定生成配置（换模型不重跑全项目） ✅已完成 |
| 11 | 角色图 `seed_value` + `reference_images`（重生成一致性） ✅已完成 |
| 12 | 章节拼接历史表（可重拼、转场） ✅已完成 |
| 13 | 全表软删除 ✅已完成 | 全部创作域模型（含公共素材库）继承 `SoftDeleteMixin`；`database.do_orm_execute` 监听器统一为 `SoftDeleteMixin` 实体附加 `deleted_at IS NULL` 过滤（查询已删除数据用 `session.info["include_deleted"]=True`）；`delete_creation`/`remove_chapter` 级联软删子表，各 `remove_*/delete_*` 改为软删；迁移 `20260909_11` 为 13 张表补 `deleted_at` |

---

## 三、已落地：提示词模板库

位置：`backend/config/drama_prompts/`（详见该目录 `README.md`）

| 模板 | 消费节点 | 说明 |
|---|---|---|
| `project_outline.md` | `agi_project` | 立项与故事骨架（世界观/大纲/总剧本） |
| `deepen_bible.md` | `agi_deepen` | 剧本深化：简介/章节规划（格式化剧本）/人物提炼/画风锁定 |
| `character_extract.md` | `agi_character` | 人物提取与设定（含造型锚点、音色设计） |
| `scene_extract.md` | `agi_scene` | 场景提取（地点/时间/光影/陈设结构化描述） |
| `chapter_plan.md` | `agi_chapter` | 章节内容规划（格式化剧本体例） |
| `storyboard_break.md` | `agi_shot` | 分镜拆解：节拍识别、时长锚定、台词时长下限 |
| `video_prompt.md` | `agi_shot_video` | 视频提示词按 3 秒分段规范（含 @角色/场景 引用） |

运行时注入：`s_agi_comic.py::_load_prompt()` 读取 MD（自动剥离 YAML frontmatter），
拼在节点内置 system 之前；**JSON schema 与字段约束始终由代码追加在最后**，
因此人工改写模板不会破坏入库格式。模板缺失时节点回退到内置提示词，不影响运行。

---

## 四、执行建议

顺序即依赖：格式化剧本（3）→ 资产提取（2）→ 分镜量化拆解（1），
对应 Drama 验证过的"改写 → 提取 → 拆解"主轴；随后做任务台账（6）以支撑失败排查与成本统计。
