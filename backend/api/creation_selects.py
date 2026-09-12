"""AI 创作项目骨架查询接口（工作流节点下拉数据源 + 可视化浏览）。

供工作流节点 configFields 的 api-select 消费，前端会以当前节点其他配置值
替换端点中的 ``{creation_id}`` / ``{chapter_id}`` 占位符实现联动：

- ``GET /api/creation/style-presets``               风格预设下拉(立项节点)
- ``GET /api/creation/list``                        项目下拉
- ``GET /api/creation/{creation_id}/chapters``      章节下拉
- ``GET /api/creation/{creation_id}/shots?chapter_id=``  分镜下拉(可按章节过滤)
- ``GET /api/creation/{creation_id}/characters``        人物列表(音色生产「生成对象」表格)
- ``GET /api/creation/{creation_id}/tree``          项目骨架全量树(浏览项目页)
- ``PUT /api/creation/chapters/{chapter_id}``       人工审改章节(标题/摘要/格式化剧本文本)

媒体文件预览统一复用 ``/api/files/stream?path=<绝对路径>``。
"""

import os
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import creation as agi

router = APIRouter(prefix="/api/creation", tags=["creation-selects"])


class AssetReview(BaseModel):
    """资产人工审查：通过 / 打回 / 备注 / 设为主选（N 选 1）。"""
    status: str = ""
    note: str = ""
    primary: Optional[bool] = None


class ChapterUpdate(BaseModel):
    """人工审改章节：浏览弹窗「编辑」保存的字段（任选其一，空串会清空）。"""

    title: Optional[str] = None
    summary: Optional[str] = None
    original_text: Optional[str] = None


class CreationUpdate(BaseModel):
    """项目主信息编辑。"""

    name: Optional[str] = None
    description: Optional[str] = None
    script_text: Optional[str] = None


class CharacterUpdate(BaseModel):
    """人物设定编辑。"""

    name: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[str] = None
    personality: Optional[str] = None
    occupation: Optional[str] = None
    voice_design: Optional[str] = None


class SceneUpdate(BaseModel):
    """场景资产编辑。"""

    name: Optional[str] = None
    location: Optional[str] = None
    time: Optional[str] = None
    lighting: Optional[str] = None
    prompt: Optional[str] = None
    final_prompt: Optional[str] = None
    image_url: Optional[str] = None


class PropUpdate(BaseModel):
    """道具资产编辑。"""

    name: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None
    prompt: Optional[str] = None
    final_prompt: Optional[str] = None
    image_url: Optional[str] = None


class DialogueUpdate(BaseModel):
    """分镜对话条目。"""

    dialogue_id: Optional[str] = None
    character: str
    content: str


class ShotUpdate(BaseModel):
    """分镜信息编辑。"""

    scene_descriptions: Optional[list[str]] = None
    dialogues: Optional[list[DialogueUpdate]] = None
    bgm_design: Optional[str] = None
    sfx_design: Optional[str] = None


@router.put("/chapters/{chapter_id}")
def update_chapter(chapter_id: str, data: ChapterUpdate) -> dict:
    """人工审改：更新章节标题 / 摘要 / 格式化剧本文本（``original_text``）。"""
    fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="没有可更新的字段")
    try:
        return agi.update_chapter(chapter_id, **fields)
    except agi.NotFoundError:
        raise HTTPException(status_code=404, detail=f"章节不存在: {chapter_id}")
    except agi.ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/{creation_id}")
def update_creation(creation_id: str, data: CreationUpdate) -> dict:
    """编辑项目主信息：名称 / 简介 / 剧本全文。"""
    fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="没有可更新的字段")
    _require_creation(creation_id)
    try:
        return agi.update_creation(creation_id, **fields)
    except agi.NotFoundError:
        raise HTTPException(status_code=404, detail=f"创作项目不存在: {creation_id}")
    except agi.ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/characters/{character_id}")
def update_creation_character(character_id: str, data: CharacterUpdate) -> dict:
    """编辑人物设定。"""
    fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="没有可更新的字段")
    try:
        return agi.update_creation_character(character_id, **fields)
    except agi.NotFoundError:
        raise HTTPException(status_code=404, detail=f"人物不存在: {character_id}")
    except agi.ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/scenes/{scene_id}")
def update_creation_scene(scene_id: str, data: SceneUpdate) -> dict:
    """编辑场景资产。"""
    fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="没有可更新的字段")
    try:
        return agi.update_scene(scene_id, **fields)
    except agi.NotFoundError:
        raise HTTPException(status_code=404, detail=f"场景不存在: {scene_id}")
    except agi.ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/props/{prop_id}")
def update_creation_prop(prop_id: str, data: PropUpdate) -> dict:
    """编辑道具资产。"""
    fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="没有可更新的字段")
    try:
        return agi.update_prop(prop_id, **fields)
    except agi.NotFoundError:
        raise HTTPException(status_code=404, detail=f"道具不存在: {prop_id}")
    except agi.ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/shots/{shot_id}")
def update_creation_shot(shot_id: str, data: ShotUpdate) -> dict:
    """编辑分镜信息：场景描述 / 对话 / 音效 / BGM 设计。"""
    fields = {k: v for k, v in data.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="没有可更新的字段")
    try:
        return agi.update_shot(shot_id, **fields)
    except agi.NotFoundError:
        raise HTTPException(status_code=404, detail=f"分镜不存在: {shot_id}")
    except agi.ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _require_creation(creation_id: str) -> None:
    try:
        agi.get_creation(creation_id)
    except agi.NotFoundError:
        raise HTTPException(status_code=404, detail=f"创作项目不存在: {creation_id}")


@router.get("/style-presets")
def list_style_presets():
    """风格预设列表（立项节点「风格预设」下拉）：内置在前，其余按创建时间。"""
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "art_style": p.get("art_style") or "",
            "genre_tags": p.get("genre_tags") or [],
            "audience_tags": p.get("audience_tags") or [],
            "description": p.get("description") or "",
            "is_builtin": bool(p.get("is_builtin")),
        }
        for p in agi.list_style_presets()
    ]


@router.get("/list")
def list_creations():
    """全部创作项目（项目下拉 + 浏览项目列表页），含进度阶段与资产统计。"""
    items = agi.list_creations()
    out = []
    for c in items:
        cid = c["id"]
        counts = {"characters": 0, "chapters": 0, "shots": 0}
        asset_counts: dict[str, int] = {}
        cover = ""
        stage, percent = "立项完成", 10
        description = ""
        try:
            proj = agi.get_creation(cid, with_detail=True)
            description = proj.get("description") or ""
            chapters = proj.get("chapters") or []
            shots = [s for ch in chapters for s in (ch.get("shots") or [])]
            counts = {"characters": len(proj.get("characters") or []),
                      "chapters": len(chapters), "shots": len(shots),
                      "scenes": len(proj.get("scenes") or []),
                      "props": len(proj.get("props") or [])}
            n_render = 0
            for a in agi.list_assets(cid):
                k = a.get("asset_kind") or ""
                asset_counts[k] = asset_counts.get(k, 0) + 1
                if k == "shot_render":
                    n_render += 1
                if k == "scene_image" and not a.get("shot_id") and not cover:
                    for p in (a.get("paths") or []):
                        u = _media_url(p)
                        if u:
                            cover = u
                            break
            if not cover:
                for sc in proj.get("scenes") or []:
                    u = _media_url(sc.get("image_url"))
                    if u:
                        cover = u
                        break
            n_video = asset_counts.get("shot_video", 0)
            if counts["shots"] > 0:
                if n_render >= counts["shots"]:
                    stage, percent = "分镜成片完成", 95
                elif n_video:
                    stage, percent = "视频生成中", 75
                else:
                    stage, percent = "分镜制作中", 60
            elif counts["chapters"] > 0:
                stage, percent = "章节剧本完成", 45
            elif counts["characters"] > 0:
                stage, percent = "人物资产完成", 30
        except Exception:  # noqa: BLE001
            pass
        out.append({
            "id": cid,
            "name": c.get("name") or cid,
            "description": description,
            "status": c.get("status") or "",
            "updated_at": c.get("updated_at") or "",
            "counts": counts,
            "asset_counts": asset_counts,
            "assets_total": sum(asset_counts.values()),
            "progress": {"stage": stage, "percent": percent},
            "cover": cover,
        })
    return out


@router.get("/{creation_id}/chapters")
def list_chapters(creation_id: str):
    """指定项目的章节列表（章节下拉），按 order_no 升序。"""
    _require_creation(creation_id)
    out = []
    for ch in agi.list_chapters(creation_id):
        out.append(
            {
                "id": ch["id"],
                "order_no": ch.get("order_no"),
                "title": ch.get("title") or f"第{ch.get('order_no')}章",
                "summary": ch.get("summary") or "",
            }
        )
    return out


@router.get("/{creation_id}/shots")
def list_shots(creation_id: str, chapter_id: str = ""):
    """指定项目的分镜列表（分镜下拉），可按章节过滤，按 order_no 升序。"""
    _require_creation(creation_id)
    proj = agi.get_creation(creation_id, with_detail=True)
    out = []
    for ch in proj.get("chapters", []):
        if chapter_id and ch["id"] != chapter_id:
            continue
        for s in ch.get("shots", []):
            scenes = s.get("scene_descriptions") or []
            desc = (scenes[0] if scenes else "").strip()[:24]
            out.append(
                {
                    "id": s["id"],
                    "chapter_id": ch["id"],
                    "order_no": s.get("order_no"),
                    "label": f"#{s.get('order_no')} {desc}".strip(),
                }
            )
    out.sort(key=lambda x: x["order_no"] or 0)
    return out


@router.get("/{creation_id}/scenes")
def list_scenes(creation_id: str):
    """指定项目的场景列表（场景下拉），按 order_no 升序。"""
    _require_creation(creation_id)
    out = []
    for s in agi.list_scenes(creation_id):
        out.append({
            "id": s["id"],
            "order_no": s.get("order_no"),
            "name": s.get("name") or f"场景{s.get('order_no')}",
            "location": s.get("location") or "",
            "time": s.get("time") or "",
            "image_url": _media_url(s.get("image_url")),
        })
    out.sort(key=lambda x: x["order_no"] or 0)
    return out


@router.get("/{creation_id}/props")
def list_props(creation_id: str):
    """指定项目的道具列表（道具下拉），按 order_no 升序。"""
    _require_creation(creation_id)
    out = []
    for p in agi.list_props(creation_id):
        out.append({
            "id": p["id"],
            "order_no": p.get("order_no"),
            "name": p.get("name") or f"道具{p.get('order_no')}",
            "type": p.get("type") or "",
            "image_url": _media_url(p.get("image_url")),
        })
    out.sort(key=lambda x: x["order_no"] or 0)
    return out


@router.get("/{creation_id}/characters")
def list_characters(creation_id: str):
    """项目人物列表（「人物音色生产」节点生成对象表格的数据源）。

    除人物属性外，额外带上 ``voice_design``（音色设计）与 ``voice_url``
    （已生成音色的可播放地址，未生成则为空串，前端表现為不可播放）。
    """
    _require_creation(creation_id)
    proj = agi.get_creation(creation_id, with_detail=True)
    out = []
    for c in proj.get("characters", []):
        voice_url = ""
        if c.get("voice_ref"):
            try:
                ap = agi.audio_ref_abspath(c["voice_ref"])
                if ap and os.path.isfile(ap):
                    voice_url = _media_url(ap)
            except Exception:  # noqa: BLE001
                voice_url = ""
        out.append({
            "id": c.get("id"),
            "name": c.get("name") or "",
            "gender": c.get("gender") or "",
            "age": c.get("age") or "",
            "personality": c.get("personality") or "",
            "occupation": c.get("occupation") or "",
            "voice_design": c.get("voice_design") or "",
            "voice_ref": c.get("voice_ref") or "",
            "voice_url": voice_url,
        })
    return out


@router.put("/assets/{asset_id}/review")
def review_asset(asset_id: str, data: AssetReview):
    """审查一条资产：status=approved|rejected|""（空串=撤销审查），primary 设定 N 选 1 主选。"""
    try:
        return agi.review_asset(asset_id, data.status or "", note=data.note or "", primary=data.primary)
    except agi.NotFoundError as exc:
        raise HTTPException(404, str(exc))
    except agi.ValidationError as exc:
        raise HTTPException(400, str(exc))


@router.get("/{creation_id}/review-stats")
def creation_review_stats(creation_id: str, chapter_id: str = ""):
    """审查统计：通过 / 打回 / 未审数量（可限定章节）。"""
    _require_creation(creation_id)
    return agi.review_stats(creation_id, chapter_id=chapter_id)


_IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def _media_url(path) -> str:
    """把资产路径（data/ 相对或运行期绝对路径）转成 /api/files/stream 预览 URL。"""
    if not path:
        return ""
    try:
        ap = agi.resolve_storage_path(path)
        if ap and os.path.isfile(ap):
            return f"/api/files/stream?path={quote(str(ap))}"
    except Exception:  # noqa: BLE001
        pass
    return ""


@router.get("/{creation_id}/tree")
def creation_tree(creation_id: str):
    """项目骨架全量树：故事骨架/人物(多视角图+音色)/场景/章节→分镜(帧/视频/配音/成片)。"""
    _require_creation(creation_id)
    proj = agi.get_creation(creation_id, with_detail=True)

    # 资产按 shot 分组；无 shot 的 scene_image 视为场景资产
    assets_by_shot: dict[str, list] = {}
    scene_assets: list = []
    for a in agi.list_assets(creation_id):
        if a.get("shot_id"):
            assets_by_shot.setdefault(a["shot_id"], []).append(a)
        elif a.get("asset_kind") == "scene_image":
            scene_assets.append(a)

    characters = []
    for c in proj.get("characters", []):
        images: list[str] = []
        if c.get("character_lib_id"):
            try:
                vdir = agi.get_character(c["character_lib_id"]).get("images_dir")
                if vdir:
                    vabs = agi.resolve_public_path(vdir)
                    if os.path.isdir(vabs):
                        images = [_media_url(os.path.join(str(vabs), fn))
                                  for fn in sorted(os.listdir(vabs))
                                  if fn.lower().endswith(_IMG_EXTS)]
                        images = [u for u in images if u]
            except Exception:  # noqa: BLE001
                images = []
        voice_url = ""
        if c.get("voice_ref"):
            try:
                ap = agi.audio_ref_abspath(c["voice_ref"])
                if ap and os.path.isfile(ap):
                    voice_url = _media_url(ap)
            except Exception:  # noqa: BLE001
                voice_url = ""
        characters.append({
            "id": c.get("id"), "name": c.get("name"), "gender": c.get("gender"),
            "age": c.get("age"), "personality": c.get("personality"),
            "occupation": c.get("occupation"), "voice_design": c.get("voice_design"),
            "voice_ref": c.get("voice_ref") or "", "voice_url": voice_url,
            "images": images,
        })

    chapters = []
    for ch in proj.get("chapters", []):
        shots = []
        for s in ch.get("shots", []):
            frames, videos, audios, renders = [], [], [], []
            # 与上面的 URL 列表一一对应的审查元信息（asset_id + 审查态），供驾驶舱逐条审查
            meta = {"frames_meta": [], "videos_meta": [], "audios_meta": [], "renders_meta": []}
            for a in assets_by_shot.get(s["id"], []):
                kind = a.get("asset_kind")
                for p in (a.get("paths") or []):
                    u = _media_url(p)
                    if not u:
                        continue
                    entry = {
                        "asset_id": a.get("id") or "",
                        "url": u,
                        "review_status": a.get("review_status") or "",
                        "review_note": a.get("review_note") or "",
                        "is_primary": bool(a.get("is_primary")),
                    }
                    if kind == "scene_image":
                        frames.append(u)
                        meta["frames_meta"].append(entry)
                    elif kind == "shot_video":
                        videos.append(u)
                        meta["videos_meta"].append(entry)
                    elif kind == "voiceover":
                        audios.append(u)
                        meta["audios_meta"].append(entry)
                    elif kind == "shot_render":
                        renders.append(u)
                        meta["renders_meta"].append(entry)
            scenes_txt = s.get("scene_descriptions") or []
            shots.append({
                "id": s.get("id"), "order_no": s.get("order_no"),
                "label": f"#{s.get('order_no')} {(scenes_txt[0] if scenes_txt else '')[:24]}".strip(),
                "scene_descriptions": scenes_txt,
                "characters": s.get("characters") or [],
                "dialogues": s.get("dialogues") or [],
                "bgm_design": s.get("bgm_design") or "",
                "sfx_design": s.get("sfx_design") or "",
                "frames": frames, "videos": videos,
                "audios": audios, "renders": renders,
                **meta,
            })
        chapters.append({
            "id": ch.get("id"), "order_no": ch.get("order_no"),
            "title": ch.get("title") or f"第{ch.get('order_no')}章",
            "summary": ch.get("summary") or "",
            "original_text": ch.get("original_text") or "",
            "cover": ch.get("cover") or "",
            "gen_config": ch.get("gen_config") or "",
            "shots": shots,
        })

    scenes = []
    seen = set()
    for sc in proj.get("scenes") or []:
        u = _media_url(sc.get("image_url"))
        if u and u not in seen:
            seen.add(u)
            scenes.append({"id": sc.get("id"), "url": u, "name": sc.get("name", ""),
                           "location": sc.get("location", ""), "time": sc.get("time", ""),
                           "lighting": sc.get("lighting", ""), "prompt": sc.get("prompt", ""),
                           "description": sc.get("prompt") or ""})
    for a in scene_assets:
        for p in (a.get("paths") or []):
            u = _media_url(p)
            if u and u not in seen:
                seen.add(u)
                scenes.append({"id": "", "url": u, "description": a.get("description") or ""})

    props = []
    for p in proj.get("props") or []:
        props.append({
            "id": p.get("id"), "name": p.get("name"), "type": p.get("type", ""),
            "description": p.get("description", ""), "url": _media_url(p.get("image_url")),
        })

    return {
        "id": proj.get("id"), "name": proj.get("name"),
        "description": proj.get("description") or "",
        "status": proj.get("status") or "",
        "genre_tags": proj.get("genre_tags") or [],
        "art_style_tags": proj.get("art_style_tags") or [],
        "audience_tags": proj.get("audience_tags") or [],
        "script_text": proj.get("script_text") or "",
        "characters": characters,
        "scenes": scenes,
        "props": props,
        "chapters": chapters,
    }


# 矩阵列定义：章节 × 生产阶段。level=shot 按分镜计数，level=chapter 整章一个格子。
_MATRIX_STAGES = [
    {"key": "shot", "label": "分镜拆分", "level": "chapter", "step_id": "agi_shot"},
    {"key": "prompt", "label": "分镜提示词", "level": "shot", "step_id": "agi_shot_prompt"},
    {"key": "frame", "label": "首尾帧", "level": "shot", "step_id": "agi_shot_frames"},
    {"key": "video", "label": "分镜视频", "level": "shot", "step_id": "agi_shot_video"},
    {"key": "dub", "label": "分镜配音", "level": "shot", "step_id": "agi_shot_dub"},
    {"key": "render", "label": "分镜成片", "level": "shot", "step_id": "agi_shot_export"},
    {"key": "chapter_render", "label": "章节成片", "level": "chapter", "step_id": "agi_chapter_export"},
]

# 资产类型 → 矩阵阶段（首尾帧历史上登记为 scene_image，靠 shot_id + 描述「帧」兜底识别）
_ASSET_STAGE = {
    "shot_frame": "frame",
    "shot_video": "video",
    "voiceover": "dub",
    "shot_render": "render",
}


def _asset_stage(asset: dict) -> str:
    kind = asset.get("asset_kind") or ""
    stage = _ASSET_STAGE.get(kind)
    if stage:
        return stage if asset.get("shot_id") else ""
    if kind == "scene_image" and asset.get("shot_id"):
        return "frame"
    return ""


def _cell_status(done: int, total: int) -> str:
    if total <= 0 or done <= 0:
        return "empty"
    return "done" if done >= total else "partial"


@router.get("/{creation_id}/matrix")
def creation_matrix(creation_id: str):
    """生产矩阵：行=章节，列=生产阶段，格子=完成度/缺口/失败数。

    状态全部由数据推导（分镜表 + 资产表 + 生成台账），不额外维护第二套状态机。
    """
    _require_creation(creation_id)
    proj = agi.get_creation(creation_id, with_detail=True)
    chapters = sorted(proj.get("chapters") or [], key=lambda c: c.get("order_no") or 0)
    assets = agi.list_assets(creation_id)

    # 分镜维度：shot_id → 阶段 → 数量 / 最近更新时间
    shot_stage: dict[str, dict[str, int]] = {}
    shot_stage_time: dict[str, str] = {}
    chapter_render: set[str] = set()
    for a in assets:
        paths = [p for p in (a.get("paths") or []) if p]
        if not paths:
            continue
        if (a.get("asset_kind") or "") == "chapter_render":
            if a.get("chapter_id"):
                chapter_render.add(a["chapter_id"])
            continue
        stage = _asset_stage(a)
        if not stage:
            continue
        sid = a["shot_id"]
        bucket = shot_stage.setdefault(sid, {})
        bucket[stage] = bucket.get(stage, 0) + 1
        created = str(a.get("created_at") or "")
        if created > shot_stage_time.get(f"{sid}:{stage}", ""):
            shot_stage_time[f"{sid}:{stage}"] = created

    # 失败台账：(章节, 步骤) → 失败次数
    failed: dict[tuple[str, str], int] = {}
    try:
        for t in agi.list_generation_tasks(creation_id, status="failed", limit=500):
            key = (t.get("chapter_id") or "", t.get("step_id") or "")
            failed[key] = failed.get(key, 0) + 1
    except Exception:  # noqa: BLE001
        failed = {}

    step_of = {s["key"]: s.get("step_id") or "" for s in _MATRIX_STAGES}
    rows = []
    for ch in chapters:
        ch_id = ch.get("id") or ""
        shots = sorted(ch.get("shots") or [], key=lambda s: s.get("order_no") or 0)
        total = len(shots)
        cells = {}

        # 分镜拆分：整章一个格子，无分母（done 直接表示已有镜数）
        cells["shot"] = {
            "status": "done" if total else "empty",
            "done": total,
            "total": 0,
            "missing": [],
            "failed": failed.get((ch_id, step_of.get("shot", "")), 0),
            "updated_at": "",
        }

        # 分镜提示词：分镜表字段
        prompt_missing = [i + 1 for i, s in enumerate(shots)
                          if not str(s.get("image_prompt") or "").strip()]
        cells["prompt"] = {
            "status": _cell_status(total - len(prompt_missing), total),
            "done": total - len(prompt_missing),
            "total": total,
            "missing": prompt_missing,
            "failed": failed.get((ch_id, step_of.get("prompt", "")), 0),
            "updated_at": "",
        }

        # 资产驱动的分镜阶段
        for stage in ("frame", "video", "dub", "render"):
            missing, done, latest = [], 0, ""
            for i, s in enumerate(shots):
                sid = s.get("id") or ""
                if shot_stage.get(sid, {}).get(stage, 0) > 0:
                    done += 1
                    latest = max(latest, shot_stage_time.get(f"{sid}:{stage}", ""))
                else:
                    missing.append(i + 1)
            cells[stage] = {
                "status": _cell_status(done, total),
                "done": done,
                "total": total,
                "missing": missing,
                "failed": failed.get((ch_id, step_of.get(stage, "")), 0),
                "updated_at": latest,
            }

        has_render = ch_id in chapter_render
        cells["chapter_render"] = {
            "status": "done" if has_render else "empty",
            "done": 1 if has_render else 0,
            "total": 1,
            "missing": [] if has_render else [1],
            "failed": failed.get((ch_id, step_of.get("chapter_render", "")), 0),
            "updated_at": "",
        }

        rows.append({
            "id": ch_id,
            "order_no": ch.get("order_no") or 0,
            "title": ch.get("title") or f"第{ch.get('order_no')}章",
            "shot_count": total,
            "cells": cells,
        })

    summary = {"chapters": len(rows), "shots": sum(r["shot_count"] for r in rows)}
    for stage in _MATRIX_STAGES:
        key = stage["key"]
        if stage["level"] == "shot":
            done = sum(r["cells"][key]["done"] for r in rows)
            total = sum(r["cells"][key]["total"] for r in rows)
        else:
            done = sum(1 for r in rows if r["cells"][key]["done"] > 0)
            total = len(rows)
        summary[key] = {"done": done, "total": total, "status": _cell_status(done, total)}

    return {
        "id": proj.get("id"),
        "name": proj.get("name"),
        "stages": _MATRIX_STAGES,
        "rows": rows,
        "summary": summary,
    }
