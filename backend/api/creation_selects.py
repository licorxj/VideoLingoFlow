"""AI 创作项目骨架查询接口（工作流节点下拉数据源 + 可视化浏览）。

供工作流节点 configFields 的 api-select 消费，前端会以当前节点其他配置值
替换端点中的 ``{creation_id}`` / ``{chapter_id}`` 占位符实现联动：

- ``GET /api/creation/style-presets``               风格预设下拉(立项节点)
- ``GET /api/creation/list``                        项目下拉
- ``GET /api/creation/{creation_id}/chapters``      章节下拉
- ``GET /api/creation/{creation_id}/shots?chapter_id=``  分镜下拉(可按章节过滤)
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


class ChapterUpdate(BaseModel):
    """人工审改章节：浏览弹窗「编辑」保存的字段（任选其一，空串会清空）。"""

    title: Optional[str] = None
    summary: Optional[str] = None
    original_text: Optional[str] = None


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
            for a in assets_by_shot.get(s["id"], []):
                kind = a.get("asset_kind")
                for p in (a.get("paths") or []):
                    u = _media_url(p)
                    if not u:
                        continue
                    if kind == "scene_image":
                        frames.append(u)
                    elif kind == "shot_video":
                        videos.append(u)
                    elif kind == "voiceover":
                        audios.append(u)
                    elif kind == "shot_render":
                        renders.append(u)
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
            scenes.append({"url": u, "name": sc.get("name", ""),
                           "location": sc.get("location", ""), "time": sc.get("time", ""),
                           "lighting": sc.get("lighting", ""), "prompt": sc.get("prompt", ""),
                           "description": sc.get("prompt") or ""})
    for a in scene_assets:
        for p in (a.get("paths") or []):
            u = _media_url(p)
            if u and u not in seen:
                seen.add(u)
                scenes.append({"url": u, "description": a.get("description") or ""})

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
