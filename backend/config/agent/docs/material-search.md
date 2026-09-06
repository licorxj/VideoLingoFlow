# 素材查询指南(Material Search)

指导 agent 在本项目中**查找与使用本地素材**:图片素材、视频素材、公共角色、创作项目资产、音色与音频素材(音效/背景音乐)。覆盖三种查询方式——`local-material-search` 技能(推荐,终端一条命令)、Python API(`backend/creation`)、CLI(`python -m backend.creation.cli`)。

> 本文档基于当前实现:`backend/creation/`(数据层读写脚本)、`backend/control_plane/models.py`(表定义)、`backend/config/agent/skills/local-material-search/`(搜索技能)。完整表结构见 `PROJECT_ROOT/docs/素材库数据库结构与查询指南.md` 与 `PROJECT_ROOT/docs/AI创作项目数据库结构与查询接口指南.md`。

---

## 1. 素材数据分布

| 素材类 | 数据表 | 所在数据库 | 登记脚本 |
|---|---|---|---|
| 图片素材 | `cp_images` | 控制面库 `data/control-plane.db` | `backend/creation/libraries.py` |
| 视频素材 | `cp_videos` | 控制面库 | 同上 |
| 公共角色 | `cp_characters` | 控制面库 | 同上 |
| 创作项目资产 | `cp_creation_assets` | 控制面库 | `backend/creation/store.py`(`register_asset`) |
| 音色 | `vf_voices` | voiceforge 库 `voiceforge_data/voiceforge.db` | `backend/creation/audio_refs.py` |
| 音频素材(音效/背景音乐) | `vf_assets` | voiceforge 库 | 同上 |

创作项目(章节/分镜/人物)数据本身不属于素材库,但资产明细(`cp_creation_assets`)记录了已生成的场景图、配音、分镜视频、成品等,是素材的重要来源,一并纳入搜索。

## 2. 快捷搜索:`local-material-search` 技能(推荐)

技能脚本:`backend/config/agent/skills/local-material-search/material_search.py`。**必须用项目 venv 的 python 运行**,在 `PROJECT_ROOT` 下执行:

```powershell
venv312\Scripts\python.exe backend\config\agent\skills\local-material-search\material_search.py <参数>
```

四类过滤条件可任意组合:

| 能力 | 参数 | 说明 |
|---|---|---|
| 按类 | `--kind` | `all`(默认)/`image`/`video`/`character`/`asset`/`voice`/`audio` |
| 按分组 | `--group` | 匹配 `group_tags`(仅图片/视频库有分组字段) |
| 按标签 | `--tag` | 匹配各库标签合集(图片/视频=分组+自定义;角色=`tags`;音频=`tags_json`) |
| 按描述模糊查找 | `--query` | 大小写不敏感子串匹配,覆盖名称/描述/路径/别名/引用等全部文本字段 |

```powershell
# 按类:全部音频素材
... material_search.py --kind audio
# 按描述模糊:全库搜"走廊"
... material_search.py --query 走廊
# 按分组:图片库"空间站"分组
... material_search.py --kind image --group 空间站
# 按标签:打了"金属"标签的音效
... material_search.py --kind audio --tag 金属
# 组合:视频库"空镜"分组 + 描述含"夜景",限 10 条
... material_search.py --kind video --group 空镜 --query 夜景 --limit 10
# 统计各库数量
... material_search.py --stats
```

输出为统一 JSON:`results[]` 每条带 `kind`、`id`、`name`、`description`、标签字段;`image`/`video` 带 `abs_path`(已还原为绝对路径);`voice`/`audio` 带 `ref`(`vf:` 引用);`asset` 带 `asset_kind` 与 `paths`。`--stats` 只返回数量统计;voiceforge 库缺失时对应类跳过并写入 `warnings`,不影响其余类型。

## 3. Python API 查询(需要更精确的条件时)

```python
from backend import creation as agi

agi.list_images(group_tag="空间站", custom_tag="", keyword="走廊")     # keyword 匹配 path+description
agi.list_videos(group_tag="空镜", keyword="夜景")
agi.list_characters(tag="主角", keyword="林远", origin_creation_id="")  # keyword 匹配姓名/性格/职业
agi.list_voices(keyword="温柔")                                        # 音色名称/显示名
agi.list_audio_assets(asset_type="sfx", keyword="金属")                 # 音频素材按类型+关键词
agi.list_assets(creation_id, asset_kind="scene_image", chapter_id=..., shot_id=...)
```

写入/登记素材的完整接口(含自动探测尺寸、时长、比例)见 `PROJECT_ROOT/docs/素材库数据库结构与查询指南.md`。

## 4. 路径与引用还原约定(拿到结果后怎么用)

1. **公共素材**:`cp_images`/`cp_videos`/角色 `images_dir` 中记录的是 `data/` 开头的**项目根相对路径**;读取文件时用 `paths.resolve_storage_path()` 还原:
   ```python
   from backend.creation import paths
   abs_path = paths.resolve_storage_path("data/image_library/场景1.png")  # → PROJECT_ROOT/data/...
   ```
2. **项目过程文件**:`cp_creation_assets.paths` 中的绝对路径(运行时项目文件夹内)直接使用,勿再拼接。
3. **音频素材**:`vf:voices:<id>` / `vf:assets:<id>` / `vf:exports:<id>` 是音频类素材在创作数据中的标准引用格式:
   ```python
   row = agi.resolve_audio_ref("vf:assets:abc123...")   # 反查 voiceforge 完整行
   path = agi.audio_ref_abspath("vf:assets:abc123...")  # 直接拿音频文件绝对路径
   ```

## 5. CLI 备选

```bash
python -m backend.creation.cli image list [关键词]
python -m backend.creation.cli video list [关键词]
python -m backend.creation.cli character list [关键词]
python -m backend.creation.cli audio voices [关键词]      # 音色
python -m backend.creation.cli audio assets [asset_type]  # 音频素材
python -m backend.creation.cli audio resolve <vf:引用>
python -m backend.creation.cli creation show <id>          # 含项目资产明细
```

## 6. 扩展约定

新增一类可搜索素材时:① 在 `backend/control_plane/models.py` 定义表并加 alembic 迁移;② 在 `backend/creation/` 提供读写函数;③ 在 `material_search.py` 增加 `_fetch_*` 取数函数并接入 `KINDS`/`collect()`;④ 回写本文档与 `skills/local-material-search/SKILL.md` 的覆盖范围表。
