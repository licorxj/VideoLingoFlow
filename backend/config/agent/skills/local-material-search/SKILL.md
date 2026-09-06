---
name: local-material-search
description: "本地素材跨库搜索工具:一键检索本项目的图片素材库(cp_images)、视频素材库(cp_videos)、公共角色库(cp_characters)、创作项目资产(cp_creation_assets),以及 voiceforge 的音色库(vf_voices)与音频素材库(vf_assets,音效/背景音乐)。支持按类(--kind image/video/character/asset/voice/audio)、按分组(--group)、按标签(--tag)、按描述/名称模糊查找(--query),可组合过滤,输出统一 JSON。当用户要:找素材、搜图片/视频/音效/音色/角色、按分组或标签筛选素材、按描述找素材、统计素材库数量时使用。"
metadata: { "tags": "素材, 搜索, 图片, 视频, 音效, 音色, 角色, 素材库, 标签, 分组, 模糊搜索" }
---

# 本地素材搜索(Skill)

跨库检索本项目全部本地素材,四类过滤条件可任意组合:**按类、按分组、按标签、按描述模糊查找**。

## 1. 脚本位置与运行方式

| 组件 | 位置(相对 PROJECT_ROOT) |
|---|---|
| 搜索脚本 | `backend/config/agent/skills/local-material-search/material_search.py` |

**必须用项目 venv 的 python 运行**(依赖 sqlalchemy 与项目模块),在 `PROJECT_ROOT` 下执行:

```powershell
venv312\Scripts\python.exe backend\config\agent\skills\local-material-search\material_search.py --kind image --query 走廊
```

## 2. 覆盖的素材范围

| kind | 素材库 | 数据表 | 所在数据库 |
|---|---|---|---|
| `image` | 图片素材库 | `cp_images` | 控制面库 `data/control-plane.db` |
| `video` | 视频素材库 | `cp_videos` | 控制面库 |
| `character` | 公共角色库 | `cp_characters` | 控制面库 |
| `asset` | 创作项目资产 | `cp_creation_assets` | 控制面库(8 类:`scene_image`/`voiceover`/`shot_video`/`sfx`/`bgm`/`shot_render`/`chapter_render`/`character`) |
| `voice` | 音色库 | `vf_voices` | voiceforge 库 `voiceforge_data/voiceforge.db` |
| `audio` | 音频素材 | `vf_assets` | voiceforge 库(音效/背景音乐等) |

## 3. 用法示例

```powershell
# 1) 按类搜索:全部图片素材
python backend/config/agent/skills/local-material-search/material_search.py --kind image

# 2) 按描述模糊查找:在全部素材中搜"走廊"(匹配名称/描述/路径/标签等所有字段,大小写不敏感)
python backend/config/agent/skills/local-material-search/material_search.py --query 走廊

# 3) 按分组搜索:图片库里"空间站"分组的素材
python backend/config/agent/skills/local-material-search/material_search.py --kind image --group 空间站

# 4) 按标签搜索:打了"金属"标签的音频素材
python backend/config/agent/skills/local-material-search/material_search.py --kind audio --tag 金属

# 5) 组合过滤:视频库中"空镜"分组、描述含"夜景"的素材,最多 10 条
python backend/config/agent/skills/local-material-search/material_search.py --kind video --group 空镜 --query 夜景 --limit 10

# 6) 只搜创作项目资产里的配音片段
python backend/config/agent/skills/local-material-search/material_search.py --kind asset --asset-kind voiceover

# 7) 各素材类数量统计
python backend/config/agent/skills/local-material-search/material_search.py --stats

# 8) 结果写入 JSON 文件
python backend/config/agent/skills/local-material-search/material_search.py --kind audio --query 撞击 --output result.json
```

## 4. 参数说明

| 参数 | 说明 |
|---|---|
| `--kind` | 按类:`all`(默认)/`image`/`video`/`character`/`asset`/`voice`/`audio` |
| `--group` | 按分组标签过滤;仅 `image`/`video` 有分组字段(`group_tags`) |
| `--tag` | 按标签过滤,匹配各库标签合集(图片/视频=分组+自定义标签;角色=`tags`;音频=`tags_json`) |
| `--query` | 描述模糊查找:对每条记录的全部文本字段(名称/描述/路径/别名/引用等)做大小写不敏感的子串匹配 |
| `--asset-kind` | 仅 `--kind asset/all` 时生效:过滤创作资产类型,如 `scene_image`、`voiceover`、`bgm` |
| `--limit` | 最多返回条数,默认 50 |
| `--stats` | 只输出各素材类数量统计 |
| `--output` | 结果写入 JSON 文件(UTF-8),默认打印终端 |

## 5. 输出 JSON 结构

```json
{
  "total": 2,
  "returned": 2,
  "results": [
    {
      "kind": "image",
      "id": "8f2a...",
      "name": "场景1.png",
      "description": "废弃空间站走廊",
      "path": "data/image_library/场景1.png",
      "abs_path": "Y:/VideoLingoLc/data/image_library/场景1.png",
      "group_tags": ["场景", "空间站"],
      "custom_tags": ["测试"],
      "tags": ["场景", "空间站", "测试"],
      "width": 1920, "height": 1080, "aspect_ratio": "16:9",
      "created_at": "2026-09-06T04:00:00"
    },
    {
      "kind": "audio",
      "id": "abc1...",
      "name": "金属撞击",
      "ref": "vf:assets:abc1...",
      "asset_type": "sfx",
      "description": "短促金属撞击",
      "tags": ["金属"],
      "storage_key": "assets/xxx/metal_hit.wav",
      "abs_path": "Y:/VideoLingoLc/voiceforge_data/assets/xxx/metal_hit.wav",
      "duration_seconds": 1.5
    }
  ],
  "warnings": []
}
```

各 kind 的关键字段:`image`/`video` 带 `path`+`abs_path`(统一还原为绝对路径);`voice`/`audio` 带 `ref`(`vf:` 音频引用,可直接写入创作项目数据的 `ref_id` 字段);`character` 带 `voice_ref`、`images_dir`;`asset` 带 `asset_kind`、`creation_id`/`chapter_id`/`shot_id`、`paths`。

## 6. 注意事项

- **路径还原**:公共素材库中记录的是 `data/` 开头的项目根相对路径,结果中的 `abs_path` 已按 `PROJECT_ROOT` 还原为绝对路径,可直接读取文件。
- **音频引用**:`ref` 字段(`vf:voices:<id>` / `vf:assets:<id>`)是创作项目数据中引用音频素材的标准格式;反查详情可用 `python -m backend.creation.cli audio resolve <ref>`。
- **voiceforge 缺库容错**:voiceforge 库未初始化时,`voice`/`audio` 两类会跳过并在 `warnings` 中说明,不影响其余类型搜索。
- **空结果排查**:先跑 `--stats` 确认对应库里有没有数据;素材的登记方式见 `docs/material-search.md`(agent 指南)与 `docs/素材库数据库结构与查询指南.md`(完整表结构与 Python API)。
