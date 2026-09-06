# AI 创作项目数据库结构与查询接口指南

> 本文档说明 **AI 剧集创作项目(AGI 项目)** 的数据表结构,以及 `backend/creation` 数据层的查询/写入接口使用方法。
> 数据存放在控制面数据库 `data/control-plane.db`(SQLite,WAL 模式),随应用启动自动迁移(`alembic` revision `20260906_01`)。
> 读写脚本:`backend/creation/store.py`;公共素材库与音频素材见《素材库数据库结构与查询指南》。

---

## 1. 总览

以 `cp_creations` 为主表,向下挂人物、章节、分镜与资产明细:

```
cp_creations (AI 剧集创作项目)
├── cp_creation_characters  项目人物    → 可关联公共角色库 cp_characters
├── cp_creation_chapters    章节
│   └── cp_creation_shots   分镜(对话/场景描述存 JSON 列)
└── cp_creation_assets      项目资产明细(8 类资产,asset_kind 区分)
```

| 表名 | 说明 | 模型类(`backend/control_plane/models.py`) |
|---|---|---|
| `cp_creations` | 项目主表:名称、简介、标签、剧本全文 | `Creation` |
| `cp_creation_characters` | 项目人物设定 | `CreationCharacter` |
| `cp_creation_chapters` | 章节内容 | `CreationChapter` |
| `cp_creation_shots` | 章节下的分镜 | `CreationShot` |
| `cp_creation_assets` | 已生成的项目资产明细 | `CreationAsset` |

所有表都带公共字段:`id`(32 位 uuid hex 主键)、`version`(乐观锁预留,默认 1)、`created_at`、`updated_at`。

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
| `voice_ref` | String(128) | 音色素材引用,格式 `vf:voices:<id>`(见素材库指南) |

### 2.3 cp_creation_chapters(章节)

| 字段 | 类型 | 说明 |
|---|---|---|
| `creation_id` | String,FK→`cp_creations`,级联删除 | 所属项目 |
| `order_no` | Integer,**项目内唯一** | 章节序号(1 开始,缺省自动追加) |
| `title` | String(256) | 章节标题 |
| `original_text` | Text | 章节原文 |
| `summary` | Text | 章节简述 |

### 2.4 cp_creation_shots(分镜)

| 字段 | 类型 | 说明 |
|---|---|---|
| `chapter_id` | String,FK→`cp_creation_chapters`,级联删除 | 所属章节 |
| `order_no` | Integer,**章节内唯一** | 分镜序号(缺省自动追加) |
| `characters` | JSON list | 出场人物:姓名字符串或 `{"name": .., "character_lib_id": ..}` |
| `scene_descriptions` | JSON list | 场景描述(多个),如 `["废弃空间站走廊","应急灯闪烁"]` |
| `dialogues` | JSON list | 对话列表,元素结构见下 |
| `bgm_design` | Text | 背景音乐设计描述 |
| `sfx_design` | Text | 音效设计描述 |

`dialogues` 元素结构(写入时自动归一化,缺省 `dialogue_id` 自动生成 `dlg_` 前缀 id):

```json
[{"dialogue_id": "dlg_1a2b3c4d5e6f", "character": "林远", "content": "这里有生命信号。"}]
```

### 2.5 cp_creation_assets(项目资产明细)

一张表存 8 类资产,由 `asset_kind` 区分:

| asset_kind | 含义 | 字段用法 |
|---|---|---|
| `character` | 人物资产 | `name`=人物名称,`ref_id`=公共角色库 id |
| `scene_image` | 场景图 | `paths`=图片路径列表,挂 `chapter_id`+`shot_id` |
| `voiceover` | 配音片段 | `ref_id`=`vf:` 音频引用(可选),`paths`=片段路径列表,`duration_seconds` |
| `shot_video` | 分镜视频片段 | `paths`=[视频路径],`duration_seconds`=视频时长 |
| `sfx` | 音效片段 | `sequence`=序号,`ref_id`=`vf:assets:<id>`,`description`=音效描述 |
| `bgm` | 背景音乐 | `ref_id`=`vf:assets:<id>`,`duration_seconds`=音乐时长,`description`=音乐描述 |
| `shot_render` | 分镜成品 | `paths`=[成品视频路径],`duration_seconds` |
| `chapter_render` | 章节成品 | 只挂 `chapter_id`,`paths`=[成品视频路径] |

其余字段:`creation_id`(FK,级联删除)、`name`、`paths`(JSON list)、`metadata`(JSON,扩展字段)。`chapter_id`/`shot_id` 为 `SET NULL`——章节或分镜被删时资产记录保留,便于追溯。

**路径约定**(`backend/creation/paths.py`):`paths` 内允许混用两类路径,写入时自动校验归一化——

- 公共素材:项目根 `data/` 内,**以相对路径记录**(如 `data/image_library/场景1.png`),禁止 `..`;
- 项目过程文件:运行时项目文件夹内,**以绝对路径记录**(如 `D:/runtime/project/shots/s1/img_001.png`)。

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
    script_text="第一幕……",
)

agi.get_creation(project["id"])                    # 读主表
agi.get_creation(project["id"], with_detail=True)  # 读项目+人物+章节(含分镜)+资产
agi.list_creations(keyword="星尘")                  # 列表,支持 owner_id/project_id/keyword 过滤
agi.update_creation(project["id"], status="in_progress", genre_tags=["科幻", "太空歌剧"])
agi.set_script(project["id"], "新的剧本全文……")      # 专用入口:写剧本全文
agi.export_creation(project["id"])                 # 一次性导出项目全部数据(AI 创作流程取数入口)
agi.delete_creation(project["id"])                 # 级联删除人物/章节/分镜/资产
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
    voice_ref="vf:voices:e36935a12aa04f9eaca938cc3285cf06",  # 音色引用,见素材库指南
    character_lib_id=None,                                    # 可关联公共角色库 id
)

agi.update_creation_character(member["id"], personality="沉稳果决")
agi.publish_character_to_library(member["id"], tags="主角")  # 发布到公共角色库并自动回写 character_lib_id
agi.remove_creation_character(member["id"])
```

约束:项目内人物**同名拦截**;`voice_ref` 必须是 `vf:` 引用格式,否则抛 `ValidationError`。

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

---

## 4. 异常与注意事项

| 异常(`backend.creation.common`) | 触发场景 |
|---|---|
| `NotFoundError` | 项目/人物/章节/分镜/资产 id 不存在;章节不属于该项目;音频引用反查不到 |
| `ValidationError` | 名称/人物为空、同名冲突、序号冲突、`asset_kind` 非法、`voice_ref` 格式错误、对话/人物条目格式错误 |
| `ValueError` | 路径不规范(公共素材不在 `data/` 内、含 `..`,过程文件不是绝对路径) |

- 所有写接口返回**纯 dict**(datetime 已转 ISO 字符串),可直接 `json.dumps`。
- `version` 字段仅保留作乐观锁扩展,本模块更新不做版本校验。
- 分镜删除会级联删除其下资产记录的关联(`shot_id` 置空),资产行本身保留。

## 5. 终端快捷查看(CLI)

```bash
python -m backend.creation.cli creation list [关键词]     # 项目列表
python -m backend.creation.cli creation show <id>         # 项目全量数据(人物/章节/分镜/资产)
python -m backend.creation.cli asset list <id> [asset_kind]
python -m backend.creation.cli character list [关键词]    # 公共角色库
python -m backend.creation.cli image list [关键词]        # 图片素材库
python -m backend.creation.cli video list [关键词]        # 视频素材库
python -m backend.creation.cli audio voices [关键词]      # voiceforge 音色
python -m backend.creation.cli audio assets [asset_type]  # voiceforge 音频素材
python -m backend.creation.cli audio resolve <vf:引用>     # 反查音频素材
```
