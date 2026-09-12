# AI 创作项目数据库结构与查询接口指南

> 本文档说明 **AI 剧集创作项目(AGI 项目/漫剧)** 的数据表结构,以及 `backend/creation` 数据层的查询/写入接口使用方法。
> 数据存放在控制面数据库 `data/control-plane.db`(SQLite,WAL 模式),随应用启动自动升级(`alembic`,当前 head `20260909_11`,迁移脚本见 `backend/control_plane/alembic/versions/`)。
> 读写脚本:`backend/creation/store.py`;公共素材库与音频素材见《素材库数据库结构与查询指南》。
>
> 漫剧工作流的节点设置全部落到 cp_creations 体系:项目主表、人物、场景、道具、章节(含分镜与分镜级锁定配置)、资产明细、拼接历史、生成台账与全局风格预设。

---

## 1. 总览

以 `cp_creations` 为主表,向下挂人物、场景、道具、章节(含分镜)、资产明细与生成台账;另有全局风格预设库:

```
cp_creations (AI 剧集创作项目)
├── cp_creation_characters  项目人物    → 可关联公共角色库 cp_characters
├── cp_creation_scenes      场景资产(概念图) ← 被分镜 scene_id 引用
├── cp_creation_props       道具资产(概念图)
├── cp_creation_chapters    章节
│   ├── cp_creation_shots   分镜(镜头设计存 JSON/文本列)
│   ├── cp_creation_assets  资产明细可挂 chapter_id(+shot_id)
│   └── cp_chapter_stitch   章节拼接历史(可重拼复用)
├── cp_creation_assets      项目资产明细(10 类资产,asset_kind 区分)
└── cp_generation_tasks     生成任务台账(生图/生视频/TTS 留痕)
cp_style_presets            风格预设库(全局,立项时复用)
```

| 表名 | 说明 | 模型类(`backend/control_plane/models.py`) |
|---|---|---|
| `cp_creations` | 项目主表:名称、简介、标签、剧本全文 | `Creation` |
| `cp_creation_characters` | 项目人物设定 | `CreationCharacter` |
| `cp_creation_scenes` | 场景资产(顺序/原始与最终提示词/概念图) | `CreationScene` |
| `cp_creation_props` | 道具资产(类型/描述/提示词/参考图) | `CreationProp` |
| `cp_creation_chapters` | 章节内容(含封面与分镜级锁定配置) | `CreationChapter` |
| `cp_creation_shots` | 章节下的分镜 | `CreationShot` |
| `cp_creation_assets` | 已生成的项目资产明细 | `CreationAsset` |
| `cp_chapter_stitch` | 章节拼接历史(导出/重拼各记一条) | `ChapterStitch` |
| `cp_generation_tasks` | 生成任务台账 | `GenerationTask` |
| `cp_style_presets` | 风格预设库(内置 + 用户自定义) | `StylePreset` |

所有表都带公共字段:`id`(32 位 uuid hex 主键)、`version`(乐观锁预留,默认 1)、`created_at`、`updated_at`。除主表外的上述业务表均继承 `SoftDeleteMixin`,另带 `deleted_at`(软删除)列:`backend/control_plane/database.py` 的 `do_orm_select` 全局过滤器让普通查询自动跳过已删除行,删除接口只写 `deleted_at`、不物理删行;需要读取已删除数据时在该 session 上设置 `session.info["include_deleted"] = True`。

---

## 2. 表结构详解

### 2.1 cp_creations(项目主表)

| 字段 | 类型 | 说明 |
|---|---|---|
| `owner_id` | String,可空,FK→`cp_users` | 归属用户,用户删除时置空 |
| `project_id` | String,可空,FK→`cp_projects` | 关联控制面项目(可选) |
| `name` | String(256) | 项目名称 |
| `description` | Text | 简介 |
| `genre_tags` | JSON list | 类型标签,如 `["科幻","冒险"]` |
| `art_style_tags` | JSON list | 画风标签,如 `["赛博朋克"]` |
| `audience_tags` | JSON list | 受众标签 |
| `video_aspect_ratio` | String(16),默认 `16:9` | 立项选择的视频比例(尺寸):`9:16`/`16:9`/`4:3`/`3:4`/`1:1`,作为场景概念图、分镜首尾帧与分镜视频的默认画幅(节点内显式选择仍优先) |
| `status` | String(32),默认 `draft` | 项目状态,可自定义(`draft`/`in_progress`/`done`…) |
| `script_text` | Text | 剧本全文 |

### 2.2 cp_creation_characters(项目人物)

| 字段 | 类型 | 说明 |
|---|---|---|
| `creation_id` | String,FK→`cp_creations`,级联删除 | 所属项目 |
| `character_lib_id` | String,可空,FK→`cp_characters` | 关联公共角色库的角色 id,角色库删除时置空 |
| `name` | String(256),**项目内唯一** | 姓名 |
| `gender` / `age` | String(32) | 性别 / 年龄(字符串,兼容"28""青年"等写法) |
| `personality` | Text | 性格 |
| `occupation` | String(128) | 职业 |
| `aliases` | JSON list | 别名 |
| `relationship_note` | Text | 关系网描述 |
| `voice_design` | Text | 音色设计描述 |
| `voice_ref` | String(128) | 音色素材引用,`vf:voices:<id>`(voiceforge 音色库)或 `vf:assets:<id>`(漫剧"人物音色生产"节点登记的 voice 音色样本),见素材库指南 |
| `final_prompt` | Text | 最终形象提示词(合并画风锁定后的生图提示,漫剧人物节点产出) |
| `seed_value` | Integer,可空 | 生图固定种子(漫剧人物节点配置 `seed` 后写入) |
| `reference_images` | Text | 参考图文本(可空) |
| `status` | String(32),默认 `pending` | 处理状态 |

### 2.3 cp_creation_chapters(章节)

| 字段 | 类型 | 说明 |
|---|---|---|
| `creation_id` | String,FK→`cp_creations`,级联删除 | 所属项目 |
| `order_no` | Integer,**项目内唯一** | 章节序号(1 开始,缺省自动追加) |
| `title` | String(256) | 章节标题 |
| `original_text` | Text | 章节原文 |
| `summary` | Text | 章节简述 |
| `status` | String(32),默认 `draft` | 处理状态 |
| `cover` | String(512) | 章节封面图路径(章节导出时可生成/写入) |
| `gen_config` | Text | **分镜级锁定配置**(JSON 文本):漫剧分镜生图/生视频/分镜配音/分镜导出/章节导出节点,把首跑生效配置(接口/模型/分辨率/提示词等)写入本列;该章节下节点重跑或续跑时优先读取,仅勾选 `force` 强制重跑才改用新参数 |

### 2.4 cp_creation_shots(分镜)

| 字段 | 类型 | 说明 |
|---|---|---|
| `chapter_id` | String,FK→`cp_creation_chapters`,级联删除 | 所属章节 |
| `order_no` | Integer,**章节内唯一** | 分镜序号(缺省自动追加) |
| `scene_id` | String,可空,FK→`cp_creation_scenes` | 关联项目场景资产(复用场景概念图),场景被删时置空 |
| `shot_type` / `angle` / `movement` | String(64) | 景别类型 / 机位角度 / 镜头运动 |
| `atmosphere` | Text | 氛围 |
| `location` / `time` | String | 地点 / 时间(白天/黑夜/具体时刻…) |
| `duration_seconds` | Float,可空 | 建议时长(秒) |
| `image_prompt` | Text | 画面生图提示词 |
| `video_prompt` | Text | 视频生成提示词(图像→视频) |
| `reference_images` | JSON list | 参考图(`data/` 相对路径列表,复用角色/场景图) |
| `status` | String(32),默认 `pending` | 处理状态 |
| `characters` | JSON list | 出场人物:姓名字符串或 `{"name", "id", "character_lib_id"}`(`id` 为项目人物 id,实现分镜↔人物强关联) |
| `scene_descriptions` | JSON list | 场景描述(多个),如 `["废弃空间站走廊","应急灯闪烁"]` |
| `dialogues` | JSON list | 对话列表,元素结构见下 |
| `bgm_design` | Text | 背景音乐设计描述 |
| `sfx_design` | Text | 音效设计描述 |

`dialogues` 元素结构(写入时自动归一化,缺省 `dialogue_id` 自动生成 `dlg_` 前缀 id):

```json
[{"dialogue_id": "dlg_1a2b3c4d5e6f", "character": "林远", "content": "这里有生命信号。"}]
```

### 2.5 cp_creation_scenes(场景资产)

| 字段 | 类型 | 说明 |
|---|---|---|
| `creation_id` | String,FK→`cp_creations`,级联删除 | 所属项目 |
| `order_no` | Integer,**项目内唯一** | 顺序(缺省自动追加) |
| `name` | String(256) | 场景名称 |
| `location` | String(256) | 地点 |
| `time` | String(64) | 时间(白天/黑夜/具体时刻…) |
| `lighting` | Text | 光照设计 |
| `prompt` | Text | 原始生成提示词 |
| `final_prompt` | Text | 画风锁定后的最终提示词(生图时优先) |
| `image_url` | Text | 生成的概念图路径(未生图为空) |
| `status` | String(32),默认 `pending` | 处理状态 |

分镜通过 `scene_id` 引用场景;生成的概念图会按 `register_asset(..., "scene_image")` 记入资产明细。

### 2.6 cp_creation_props(道具资产)

| 字段 | 类型 | 说明 |
|---|---|---|
| `creation_id` | String,FK→`cp_creations`,级联删除 | 所属项目 |
| `order_no` | Integer | 顺序(缺省自动追加) |
| `name` | String(256),**项目内唯一** | 道具名称 |
| `type` | String(64) | 类型(武器/信物/机械…) |
| `description` | Text | 描述 |
| `prompt` | Text | 原始生成提示词 |
| `final_prompt` | Text | 画风锁定后的最终提示词 |
| `image_url` | Text | 生成的概念图路径 |
| `reference_images` | JSON list | 参考图(`data/` 相对路径列表) |
| `status` | String(32),默认 `pending` | 处理状态 |

### 2.7 cp_creation_assets(项目资产明细)

一张表存 10 类资产,由 `asset_kind` 区分:

| asset_kind | 含义 | 字段用法 |
|---|---|---|
| `character` | 人物资产 | `name`=人物名称,`ref_id`=公共角色库 id |
| `scene_image` | 场景图 | `paths`=图片路径列表,挂 `chapter_id`+`shot_id` |
| `prop_image` | 道具图 | `paths`=图片路径列表,`name`=道具名称 |
| `voiceover` | 配音片段 | `ref_id`=`vf:` 音频引用(可选),`paths`=片段路径列表,`duration_seconds` |
| `shot_video` | 分镜视频片段 | `paths`=[视频路径],`duration_seconds`=视频时长 |
| `sfx` | 音效片段 | `sequence`=序号,`ref_id`=`vf:assets:<id>`,`description`=音效描述 |
| `bgm` | 背景音乐 | `ref_id`=`vf:assets:<id>`,`duration_seconds`=音乐时长,`description`=音乐描述 |
| `shot_render` | 分镜成品 | `paths`=[成品视频路径],`duration_seconds` |
| `chapter_render` | 章节成品 | 只挂 `chapter_id`,`paths`=[成品视频路径] |
| `chapter_cover` | 章节封面 | 只挂 `chapter_id`,`paths`=[封面图路径] |

其余字段:`creation_id`(FK,级联删除)、`name`、`ref_id`、`paths`(JSON list)、`sequence`、`duration_seconds`、`description`、`metadata`(JSON,模型列名 `metadata_json`)。`chapter_id`/`shot_id` 为数据库级 `SET NULL`——章节或分镜被**物理删除**时资产记录保留,便于追溯(业务删除走软删除,不改资产行)。表上建有 `(creation_id, asset_kind)` 与 `(chapter_id, shot_id)` 索引。

**路径约定**(`backend/creation/paths.py`):`paths` 内允许混用两类路径,写入时自动校验归一化——

- 公共素材:项目根 `data/` 内,**以相对路径记录**(如 `data/image_library/场景1.png`),禁止 `..`;
- 项目过程文件:运行时项目文件夹内,**以绝对路径记录**(如 `D:/runtime/project/shots/s1/img_001.png`)。

### 2.8 cp_chapter_stitch(章节拼接历史)

| 字段 | 类型 | 说明 |
|---|---|---|
| `creation_id` | String,FK→`cp_creations`,级联删除 | 所属项目 |
| `chapter_id` | String,FK→`cp_creation_chapters`,级联删除 | 所属章节 |
| `transition` | String(32),默认 `none` | 转场类型 |
| `transition_duration` | Float,默认 0.4 | 转场时长(秒) |
| `resolution` | String(16),默认 `original` | 分辨率 |
| `aspect_ratio` | String(16),默认 `original` | 画幅比例 |
| `make_cover` | Boolean | 是否制作章节封面片头 |
| `cover_duration` | Float,默认 3.0 | 封面展示时长(秒) |
| `cover_image` | String(1024) | 封面图路径 |
| `sources` | Text | 有序分镜成片源的**绝对路径 JSON 字符串**(重拼时复用,无需重生成分镜视频) |
| `output` | String(1024) | 拼接产物路径 |
| `duration_seconds` | Float,可空 | 产物时长(秒) |

每次章节导出/重拼各记一条,支持"可重拼"——复用历史 `sources` 仅更换转场/封面/分辨率重新拼接。列表按时间倒序(最新在前)。

### 2.9 cp_generation_tasks(生成任务台账)

| 字段 | 类型 | 说明 |
|---|---|---|
| `creation_id` | String,可空,FK→`cp_creations` | 所属项目 |
| `chapter_id` | String(36),可空 | 所属章节(冗余存 id,不建外键) |
| `kind` | String(16) | 生成类型:`image` / `video` / `tts` |
| `target_type` | String(32) | 目标:`shot` / `character` / `scene` / `prop` / `chapter` |
| `target_id` | String(36) | 目标行 id |
| `step_id` | String(64) | 发起的工作流节点 id(如 `agi_shot_frames`) |
| `interface` / `model` / `mode` | String | 调用接口、模型名、模式 |
| `prompt` | Text | 实际请求提示词 |
| `upstream_task_id` | String(36),可空 | 上游任务 id,串联重试链(重试产生的新记录指向被重试的失败记录) |
| `status` | String(16),默认 `success` | `success` / `failed` / `running`… |
| `result` | Text | 产物路径 JSON 字符串 |
| `error` | Text | 失败原因 |
| `duration_ms` | Integer | 耗时(毫秒) |

表上建有 `(creation_id, kind)` 与 `(target_type, target_id)` 索引。供运营排查与"单分镜重试"使用。

### 2.10 cp_style_presets(风格预设库)

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | String(128),**全局唯一** | 预设名 |
| `art_style` | Text | 画风描述(写入项目 `art_style_tags` / 画风锁定) |
| `genre_tags` | JSON list | 题材标签 |
| `audience_tags` | JSON list | 受众标签 |
| `description` | Text | 说明 |
| `is_builtin` | Boolean | 是否内置预设 |

漫剧立项节点下拉选择预设后,把组合写入 `cp_creations` 的标签字段;选中预设的画风还会幂等写入剧本的 `【画风锁定】` 段,供后续各生成节点自动取用。

---

## 3. 查询与写入接口(`backend/creation/store.py`)

推荐导入方式:

```python
from backend import creation as agi          # 包级别统一入口
# 或按需:
from backend.creation import store
```

### 3.1 项目主表

```python
# 创建项目(标签支持 list 或逗号分隔字符串)
project = agi.create_creation(
    "星尘旅人",
    description="一艘失联飞船的返乡之旅",
    genre_tags="科幻,冒险",
    art_style_tags=["赛博朋克"],
    audience_tags=["青年"],
    video_aspect_ratio="16:9",     # 立项视频比例:9:16/16:9/4:3/3:4/1:1
    script_text="第一幕……",
)

agi.get_creation(project["id"])                    # 读主表
agi.get_creation(project["id"], with_detail=True)  # 读项目+人物+章节(含分镜)+场景+道具+资产
agi.list_creations(keyword="星尘")                  # 列表,支持 owner_id/project_id/keyword 过滤
agi.update_creation(project["id"], status="in_progress", genre_tags=["科幻", "太空歌剧"])
agi.update_creation(project["id"], video_aspect_ratio="9:16")   # 修改全剧默认画幅(节点内显式选择仍优先)
agi.set_script(project["id"], "新的剧本全文……")      # 专用入口:写剧本全文
agi.export_creation(project["id"])                 # 一次性导出项目全部数据(漫剧取数入口,含场景/道具)
agi.delete_creation(project["id"])                 # 软删除,级联人物/章节/分镜/场景/道具/资产/拼接/任务
```

### 3.2 项目人物

```python
member = agi.add_creation_character(
    project["id"], "林远",
    gender="男", age="28",
    personality="外冷内热", occupation="宇航员",
    aliases=["阿远"],
    relationship_note="与苏晓是多年搭档",
    voice_design="低沉磁性,语速偏慢",
    # 音色引用两种:voiceforge 音色库 vf:voices:<id>;漫剧"人物音色生产"登记的样本 vf:assets:<id>
    voice_ref="vf:assets:e36935a12aa04f9eaca938cc3285cf06",
    character_lib_id=None,                                    # 可关联公共角色库 id
)

agi.update_creation_character(member["id"], personality="沉稳果决",
                              final_prompt="…", seed_value=2026, status="done")
agi.publish_character_to_library(member["id"], tags="主角")  # 发布到公共角色库并自动回写 character_lib_id
agi.remove_creation_character(member["id"])
```

约束:项目内人物**同名拦截**;`voice_ref` 必须是 `vf:` 引用(`vf:voices:` / `vf:assets:` / `vf:exports:`),否则抛 `ValidationError`。

### 3.3 章节与分镜

```python
chapter = agi.add_chapter(project["id"], title="第一章 启航",
                          original_text="舱门缓缓打开……", summary="主角进入空间站")
# order_no 缺省时自动追加到末尾;也可显式指定 order_no=2

shot = agi.add_shot(
    chapter["id"],
    characters=["林远", {"name": "苏晓", "character_lib_id": "xxx"}],  # 两种写法均可
    scene_descriptions=["废弃空间站走廊,应急灯闪烁", "金属门半开"],
    dialogues=[("林远", "这里有生命信号。"),                 # 元组写法,自动生成对话 id
               {"character": "苏晓", "content": "保持警惕。"}],  # 字典写法,可带 dialogue_id
    bgm_design="低频紧张氛围乐",
    sfx_design="金属吱呀声、脚步回声",
)

agi.get_chapter(chapter["id"])                 # 单章节(含分镜)
agi.list_chapters(project["id"], with_shots=True)  # 全部章节
agi.update_shot(shot["id"], bgm_design="改为弦乐铺垫")

dialogue = agi.add_dialogue(shot["id"], "林远", "打开舱门。")   # 追加一条对话
agi.remove_dialogue(shot["id"], dialogue["dialogue_id"])       # 按对话 id 删除

agi.update_chapter(chapter["id"], summary="新简述")

# 分镜级锁定配置:漫剧节点首跑后自动写入该章节,续跑/重跑时优先读取,force 可强制覆盖
agi.update_chapter(chapter["id"], gen_config=json.dumps({
    "agi_shot_frames": {"image_interface": "hunyuan", "art_style_prompt": "赛博朋克"},
    "agi_shot_video": {"video_interface": "kling", "resolution": "720P"},
}))

agi.remove_shot(shot["id"])
agi.remove_chapter(chapter["id"])              # 连同其下全部分镜删除
```

约束:章节序号项目内唯一、分镜序号章节内唯一,冲突抛 `ValidationError`。

### 3.4 项目资产明细

```python
# 场景图:过程文件用绝对路径,公共素材用 data/ 相对路径,可混用
asset = agi.register_asset(
    project["id"], "scene_image",
    chapter_id=chapter["id"], shot_id=shot["id"],
    paths_list=["D:/runtime/project/shots/s1/img_001.png",
                "data/image_library/场景1.png"],
    description="走廊场景图",
)

# 音效:序号 + vf:assets 引用 + 描述
agi.register_asset(project["id"], "sfx", chapter_id=chapter["id"], shot_id=shot["id"],
                   ref_id="vf:assets:abc123...", sequence=1, description="金属吱呀声")

# 背景音乐:vf:assets 引用 + 时长 + 描述
agi.register_asset(project["id"], "bgm", chapter_id=chapter["id"], shot_id=shot["id"],
                   ref_id="vf:assets:def456...", duration_seconds=45.0, description="紧张氛围乐")

# 分镜成品 / 章节成品
agi.register_asset(project["id"], "shot_render", chapter_id=chapter["id"], shot_id=shot["id"],
                   paths_list=["D:/runtime/project/shots/s1/final.mp4"], duration_seconds=8.5)

agi.list_assets(project["id"], asset_kind="scene_image", chapter_id=chapter["id"], shot_id=shot["id"])
agi.append_asset_paths(asset["id"], "D:/runtime/project/shots/s1/img_002.png")  # 追加产物路径
agi.update_asset(asset["id"], description="新描述", paths=["data/image_library/替换.png"])  # 整体替换路径用 paths
agi.remove_asset(asset["id"])
```

注意:`register_asset` 的路径参数名为 `paths_list`,而 `update_asset` 里叫 `paths`,两者都会做同样的路径校验归一化。

### 3.5 场景与道具

```python
# —— 场景 ——
scene = agi.add_creation_scene(
    project["id"], "废弃空间站",
    location="空间站", time="深夜",
    lighting="应急灯冷光",
    prompt="废弃空间站走廊,管线裸露,冷光应急灯",
)
agi.list_scenes(project["id"])                 # 全部场景
agi.get_scene(scene["id"])
# 生图后回写:final_prompt 由漫剧节点写入(合并画风锁定),image_url 记录概念图
agi.update_scene(scene["id"], final_prompt="…", image_url="data/scenes/废弃空间站.png", status="done")

# 分镜绑定场景:概念图复用,下游生图/生视频节点自动带该场景图
agi.update_shot(shot["id"], scene_id=scene["id"])
agi.remove_scene(scene["id"])

# —— 道具 ——
prop = agi.add_creation_prop(
    project["id"], "量子罗盘",
    type="机械道具", description="银灰色圆盘,中央指针悬浮",
    prompt="…", reference_images=["data/ref/罗盘参考.png"],
)
agi.list_props(project["id"])
agi.update_prop(prop["id"], image_url="data/props/量子罗盘.png", status="done")
agi.remove_prop(prop["id"])
```

约束:场景 `order_no` 项目内唯一;道具 `name` 项目内唯一,冲突抛 `ValidationError`。

### 3.6 章节拼接历史

```python
stitch = agi.add_chapter_stitch(
    project["id"], chapter["id"],
    transition="fade", transition_duration=0.5,
    resolution="720P", aspect_ratio="16:9",
    make_cover=True, cover_image="data/chapters/第一章_封面.png", cover_duration=3.0,
    sources='["D:/runtime/project/ch1/s1.mp4", "…"]',  # 有序分镜成片绝对路径 JSON(重拼可原样复用)
    output="D:/runtime/project/ch1/final.mp4",
    duration_seconds=60.0,
)
agi.list_chapter_stitches(chapter["id"])   # 最新在前
agi.get_chapter_stitch(stitch["id"])
```

### 3.7 生成任务台账

```python
task = agi.add_generation_task(
    project["id"], kind="image", chapter_id=chapter["id"],
    target_type="shot", target_id=shot["id"],
    step_id="agi_shot_frames", interface="hunyuan", model="hunyuan-image",
    mode="character_ref", prompt="…", status="success",
    result='["D:/runtime/project/shots/s1/img_001.png"]', duration_ms=5230,
)
agi.list_generation_tasks(project["id"], kind="image", target_type="shot",
                          target_id=shot["id"], status="failed")  # 过滤参数均可选
agi.get_generation_task(task["id"])
agi.update_generation_task(task["id"], status="failed", error="timeout")
# 重试:新建任务并把 upstream_task_id 指向被重试的失败任务,即可串起重试链
```

### 3.8 风格预设库

```python
preset = agi.add_style_preset("玄幻修仙", art_style="国风水墨厚涂",
                              genre_tags=["玄幻", "冒险"], audience_tags=["青年"],
                              description="…")
agi.list_style_presets()                  # 立项节点下拉数据:内置 + 用户自定义
agi.get_style_preset(preset["id"])
agi.update_style_preset(preset["id"], art_style="新画风")
agi.delete_style_preset(preset["id"])

# 立项时选用预设 → 自动带入题材/画风/受众标签(参见 3.1)
```

---

## 4. 异常与注意事项

| 异常(`backend.creation.common`) | 触发场景 |
|---|---|
| `NotFoundError` | 项目/人物/场景/道具/章节/分镜/资产/拼接记录/生成任务/风格预设 id 不存在,或子资源不属于该项目;音频引用反查不到 |
| `ValidationError` | 名称/人物为空、同名冲突、序号冲突(章节/分镜/场景)、`asset_kind` 非法、`voice_ref` 格式错误、对话/人物/道具条目格式错误 |
| `ValueError` | 路径不规范(公共素材不在 `data/` 内、含 `..`,过程文件不是绝对路径) |

- 所有写接口返回**纯 dict**(datetime 已转 ISO 字符串),可直接 `json.dumps`。
- `version` 字段仅保留作乐观锁扩展,本模块更新不做版本校验。
- 业务删除(`remove_*`/`delete_*`)均为**软删除**:给 `deleted_at` 打标,数据库层全局过滤后普通查询即不可见;资产行的 `chapter_id`/`shot_id` 为数据库级 `SET NULL`,仅在 ORM 物理删除时触发,软删除不修改资产行。
- 漫剧分镜级节点(生图/生视频/分镜配音/导出/章节导出)执行时会读取章节 `gen_config` 中的**已锁定配置**并写回新锁定值,只有节点勾选 `force` 才绕过锁定——排查"改了参数却不生效"时先查看章节 `gen_config`。
- `register_asset`/`paths` 校验见 §2.7,路径混用规则不变。

## 5. 终端快捷查看(CLI)

```bash
python -m backend.creation.cli creation list [关键词]     # 项目列表
python -m backend.creation.cli creation show <id>         # 项目全量数据(人物/场景/道具/章节/分镜/资产)
python -m backend.creation.cli asset list <id> [asset_kind]
python -m backend.creation.cli character list [关键词]    # 公共角色库
python -m backend.creation.cli image list [关键词]        # 图片素材库
python -m backend.creation.cli video list [关键词]        # 视频素材库
python -m backend.creation.cli audio voices [关键词]      # voiceforge 音色
python -m backend.creation.cli audio assets [asset_type]  # voiceforge 音频素材
python -m backend.creation.cli audio resolve <vf:引用>     # 反查音频素材
```
