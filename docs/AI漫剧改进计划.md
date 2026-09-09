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
| 3 | **格式化剧本中间产物** | `agi_deepen` 产出规范剧本（`## S01 \| 内景·地点 \| 时间` + 动作段 + 对白格式）写入章节，作为提取与拆解的规范输入，浏览页可人工审改 | agi_deepen + 浏览弹窗 |
| 4 | **提示词模板库** ✅已完成 | Drama 技能提示词改造为本项目 MD 模板，节点调用 LLM 时注入 system prompt | `backend/config/drama_prompts/` + 6 个 LLM 节点 |

### P1 — 可运营性

| # | 改进项 | 落地内容 |
|---|---|---|
| 5 | 提示词沉淀 ✅已完成 | 人物/场景/分镜增 `final_prompt` 列（`agi_prompt` 节点生成并回写，可人工改）；运行时拼装作初值 |
| 6 | 生成任务台账 | 新表 `cp_generation_tasks`（kind/目标 id/interface/model/prompt/上游 task_id/结果/错误/耗时）；媒体节点每次生成登记；支持单分镜重试 |
| 7 | 道具资产 ✅已完成 | 新表 `cp_creation_props` + 提取产出 + 白底单品图 |
| 8 | 风格预设库 | `style_presets` 表 + 立项节点选预设 |
| 9 | 分镜关联结构化 | shots 增 `scene_id`；characters 由名字数组升级为 `{name, id}`（含迁移脚本） |

### P2 — 增强

| # | 改进项 |
|---|---|
| 10 | 按章节锁定生成配置（换模型不重跑全项目） ✅已完成 |
| 11 | 角色图 `seed_value` + `reference_images`（重生成一致性） ✅已完成 |
| 12 | 章节拼接历史表（可重拼、转场） ✅已完成 |
| 13 | 全表软删除 |

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
