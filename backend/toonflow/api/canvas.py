# -*- coding: utf-8 -*-
"""创作画布 API：项目全量快照 + 流水线阶段操作（触发/轮询/删除/重生）。

快照返回"实体集合"（非 React Flow 节点），前端负责布局成画布节点；
所有产物路径经 /api/files/stream?path= 预览（本项目统一媒体出口）。
"""
import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from urllib.parse import quote

from backend.toonflow.core.models import (
    TfAsset, TfAssetRoleAudio, TfImage, TfNovel, TfProject, TfScript,
    TfStoryboard, TfTask, TfVideo, TfVideoTrack,
)

router = APIRouter()


def _media(path: str) -> str:
    if not path:
        return ""
    from backend.toonflow.core.paths import from_rel

    ap = from_rel(path)
    if ap.is_file():
        return f"/api/files/stream?path={quote(str(ap))}"
    return ""


def _require_project(session, project_id: int) -> TfProject:
    p = session.get(TfProject, project_id)
    if p is None:
        raise HTTPException(404, f"项目不存在: {project_id}")
    return p


@router.get("/canvas/{project_id}")
def canvas_snapshot(project_id: int):
    """项目全量快照：章节/事件、剧本、资产(含图)、分镜(含图/视频提示词)、轨道视频、音色绑定。"""
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        project = _require_project(session, project_id)
        out = {
            "project": {"id": project.id, "name": project.name, "introduce": project.introduce,
                        "artStyle": project.artStyle, "videoRatio": project.videoRatio,
                        "imageQuality": project.imageQuality, "mode": project.mode,
                        "videoResolution": getattr(project, "videoResolution", "") or "720P",
                        "directorManual": project.directorManual,
                        "storyStyle": getattr(project, "storyStyle", "") or ""},
            "chapters": [], "scripts": [], "assets": [], "storyboards": [],
            "videos": [], "bindings": [],
            # 后台活动：type(文本/图片/视频/语音合成…) → 生成中任务数（前端执行状态条数据源）
            "activities": {},
        }
        for n in session.scalars(select(TfNovel).where(TfNovel.projectId == project_id)).all():
            out["chapters"].append({"id": n.id, "reel": n.reel, "chapter": n.chapter,
                                    "event": n.event, "eventState": n.eventState,
                                    "chars": len(n.chapterData or "")})
        for s in session.scalars(select(TfScript).where(TfScript.projectId == project_id)).all():
            out["scripts"].append({"id": s.id, "title": s.title, "extractState": s.extractState,
                                   "chars": len(s.scriptData or ""),
                                   "preview": (s.scriptData or "").strip().replace("\n", " ")[:120]})
        for a in session.scalars(select(TfAsset).where(TfAsset.projectId == project_id)).all():
            image_url = ""
            if a.imageId:
                img = session.get(TfImage, a.imageId)
                image_url = _media(img.filePath) if img else ""
            out["assets"].append({"id": a.id, "name": a.name, "type": a.type,
                                  "describe": a.describe, "prompt": a.prompt,
                                  "assetsId": a.assetsId, "imageId": a.imageId,
                                  "imageUrl": image_url})
        for b in session.scalars(select(TfStoryboard).where(
                TfStoryboard.projectId == project_id).order_by(TfStoryboard.orderNo)).all():
            video_url = ""
            track = session.scalars(select(TfVideoTrack).where(
                TfVideoTrack.projectId == project_id,
                TfVideoTrack.storyboardId == b.id)).first()
            if track and track.selectVideoId:
                v = session.get(TfVideo, track.selectVideoId)
                video_url = _media(v.filePath) if v else ""
            out["storyboards"].append({
                "id": b.id, "orderNo": b.orderNo, "videoDesc": b.videoDesc,
                "prompt": b.prompt, "videoPrompt": b.videoPrompt,
                "assetIds": json.loads(b.assetIds or "[]"),
                "duration": b.duration, "track": b.track,
                "imageUrl": _media(b.filePath), "state": b.state,
                "shouldGenerateImage": b.shouldGenerateImage,
                "videoUrl": video_url,
            })
        for t in session.scalars(select(TfVideoTrack).where(
                TfVideoTrack.projectId == project_id)).all():
            vids = [{"id": v.id, "url": _media(v.filePath), "state": v.state,
                     "duration": v.duration, "selected": t.selectVideoId == v.id}
                    for v in session.scalars(select(TfVideo).where(
                        TfVideo.videoTrackId == t.id)).all()]
            out["videos"].append({"id": t.id, "storyboardId": t.storyboardId,
                                  "prompt": t.prompt, "candidates": vids})
        for r in session.scalars(select(TfAssetRoleAudio).where(
                TfAssetRoleAudio.projectId == project_id)).all():
            a = session.get(TfAsset, r.assetId)
            out["bindings"].append({"id": r.id, "assetId": r.assetId,
                                    "assetName": a.name if a else "", "audioId": r.audioId})
        for t in session.scalars(select(TfTask).where(
                TfTask.state == "生成中", TfTask.projectId == project_id)).all():
            key = t.type or "other"
            out["activities"][key] = out["activities"].get(key, 0) + 1
    return out


# ---------------- 流水线操作 ----------------

class ChaptersPayload(BaseModel):
    chapters: list[dict]
    generate_events: bool = True


class TextPayload(BaseModel):
    title: str = ""
    text: str


class IdsPayload(BaseModel):
    ids: list[int] = []
    force: bool = False


@router.post("/projects/{project_id}/novels")
def add_novels(project_id: int, payload: ChaptersPayload):
    from backend.control_plane.database import session_scope
    from backend.toonflow.pipeline import novel as pipe

    with session_scope() as session:
        _require_project(session, project_id)
    ids = pipe.add_novel(project_id, payload.chapters)
    queued = pipe.generate_events(project_id, ids) if payload.generate_events else {"queued": 0}
    return {"success": True, "ids": ids, "eventsQueued": queued["queued"]}


@router.post("/projects/{project_id}/scripts/draft")
def make_script_draft(project_id: int):
    """事件 → 剧本草稿（同步调用，P3 换 Agent 链）。"""
    from backend.toonflow.pipeline import script as pipe

    try:
        return pipe.generate_script_draft(project_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/scripts/{script_id}/extract-assets")
def extract_script_assets(script_id: int):
    from backend.toonflow.pipeline import script as pipe

    return pipe.extract_assets(script_id)


# ---------------- 卡片编辑 / 删除 / 单条重跑（画布用户手动控制入口） ----------------

@router.get("/novels/{novel_id}")
def get_novel(novel_id: int):
    from backend.control_plane.database import session_scope
    from backend.toonflow.core.models import TfNovel

    with session_scope() as session:
        row = session.get(TfNovel, novel_id)
        if row is None:
            raise HTTPException(404, f"章节不存在: {novel_id}")
        return {"id": row.id, "reel": row.reel, "chapter": row.chapter,
                "chapterData": row.chapterData, "event": row.event,
                "eventState": row.eventState}


class NovelUpdate(BaseModel):
    chapter: Optional[str] = None
    chapterData: Optional[str] = None
    reel: Optional[str] = None


@router.put("/novels/{novel_id}")
def update_novel(novel_id: int, payload: NovelUpdate):
    from backend.control_plane.database import session_scope
    from backend.toonflow.core.models import TfNovel

    with session_scope() as session:
        row = session.get(TfNovel, novel_id)
        if row is None:
            raise HTTPException(404, f"章节不存在: {novel_id}")
        for field, value in payload.model_dump(exclude_none=True).items():
            setattr(row, field, value)
        # 正文被改写后事件失效，需重新提取
        if payload.chapterData is not None:
            row.event = ""
            row.eventState = 0
    return {"success": True}


@router.post("/novels/{novel_id}/extract-event")
def extract_novel_event(novel_id: int):
    from backend.toonflow.pipeline import novel as pipe

    return pipe.extract_event_single(novel_id)


@router.delete("/novels/{novel_id}")
def delete_novel(novel_id: int):
    from backend.control_plane.database import session_scope
    from backend.toonflow.core.models import TfNovel

    with session_scope() as session:
        row = session.get(TfNovel, novel_id)
        if row is None:
            raise HTTPException(404, f"章节不存在: {novel_id}")
        session.delete(row)
    return {"success": True}


@router.get("/scripts/{script_id}")
def get_script(script_id: int):
    from backend.control_plane.database import session_scope
    from backend.toonflow.core.models import TfScript

    with session_scope() as session:
        row = session.get(TfScript, script_id)
        if row is None:
            raise HTTPException(404, f"剧本不存在: {script_id}")
        return {"id": row.id, "title": row.title, "scriptData": row.scriptData,
                "extractState": row.extractState}


class ScriptUpdate(BaseModel):
    title: Optional[str] = None
    scriptData: Optional[str] = None


@router.put("/scripts/{script_id}")
def update_script(script_id: int, payload: ScriptUpdate):
    from backend.control_plane.database import session_scope
    from backend.toonflow.core.models import TfScript

    with session_scope() as session:
        row = session.get(TfScript, script_id)
        if row is None:
            raise HTTPException(404, f"剧本不存在: {script_id}")
        for field, value in payload.model_dump(exclude_none=True).items():
            setattr(row, field, value)
    return {"success": True}


@router.delete("/scripts/{script_id}")
def delete_script(script_id: int):
    from backend.control_plane.database import session_scope
    from backend.toonflow.core.models import TfScript, TfScriptAsset

    with session_scope() as session:
        row = session.get(TfScript, script_id)
        if row is None:
            raise HTTPException(404, f"剧本不存在: {script_id}")
        session.execute(delete(TfScriptAsset).where(TfScriptAsset.scriptId == script_id))
        session.delete(row)
    return {"success": True}


class AssetUpdate(BaseModel):
    name: Optional[str] = None
    describe: Optional[str] = None
    prompt: Optional[str] = None


@router.put("/assets/{asset_id}")
def update_asset(asset_id: int, payload: AssetUpdate):
    from backend.control_plane.database import session_scope
    from backend.toonflow.core.models import TfAsset

    with session_scope() as session:
        row = session.get(TfAsset, asset_id)
        if row is None:
            raise HTTPException(404, f"资产不存在: {asset_id}")
        for field, value in payload.model_dump(exclude_none=True).items():
            setattr(row, field, value)
    return {"success": True}


class StoryboardUpdate(BaseModel):
    videoDesc: Optional[str] = None
    prompt: Optional[str] = None
    videoPrompt: Optional[str] = None
    duration: Optional[int] = None


@router.put("/storyboards/{storyboard_id}")
def update_storyboard(storyboard_id: int, payload: StoryboardUpdate):
    from backend.control_plane.database import session_scope
    from backend.toonflow.core.models import TfStoryboard

    with session_scope() as session:
        row = session.get(TfStoryboard, storyboard_id)
        if row is None:
            raise HTTPException(404, f"分镜不存在: {storyboard_id}")
        for field, value in payload.model_dump(exclude_none=True).items():
            setattr(row, field, value)
    return {"success": True}


@router.get("/scripts/{script_id}/assets")
def script_assets_state(script_id: int):
    from backend.toonflow.pipeline import script as pipe

    return pipe.asset_state(script_id)


@router.post("/projects/{project_id}/assets/images")
def generate_asset_images(project_id: int, payload: IdsPayload):
    from backend.toonflow.pipeline import assets as pipe

    return pipe.generate_asset_images(payload.ids)


@router.post("/assets/{asset_id}/images/regenerate")
def regenerate_asset_image(asset_id: int):
    from backend.toonflow.pipeline import assets as pipe

    return pipe.regenerate_asset_image(asset_id)


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: int):
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        a = session.get(TfAsset, asset_id)
        if a is None:
            raise HTTPException(404, f"资产不存在: {asset_id}")
        session.execute(delete(TfAssetRoleAudio).where(TfAssetRoleAudio.assetId == asset_id))
        session.delete(a)
    return {"success": True}


@router.post("/projects/{project_id}/storyboards/table")
def gen_storyboard_table(project_id: int, payload: TextPayload):
    """payload.text 为可选剧本 id；缺省用项目最新剧本。"""
    from backend.control_plane.database import session_scope
    from backend.toonflow.pipeline import storyboard as pipe

    with session_scope() as session:
        _require_project(session, project_id)
        script_id = int(payload.text) if payload.text.strip() else None
        if script_id is None:
            s = session.scalars(select(TfScript).where(
                TfScript.projectId == project_id).order_by(TfScript.id.desc())).first()
            if s is None:
                raise HTTPException(400, "项目还没有剧本")
            script_id = s.id
    pipe.generate_storyboard_table(project_id, script_id)
    return {"success": True}


@router.post("/projects/{project_id}/storyboards/prompts")
def gen_storyboard_prompts(project_id: int):
    from backend.toonflow.pipeline import storyboard as pipe

    return pipe.polish_storyboard_prompts(project_id)


@router.post("/projects/{project_id}/storyboards/images")
def gen_storyboard_images(project_id: int, payload: IdsPayload):
    from backend.toonflow.pipeline import storyboard as pipe

    return pipe.generate_storyboard_images(project_id, payload.ids or None)


@router.post("/storyboards/{storyboard_id}/image/regenerate")
def regenerate_storyboard_image(storyboard_id: int):
    from backend.control_plane.database import session_scope
    from backend.toonflow.pipeline import storyboard as pipe
    from backend.toonflow.core.models import TfStoryboard

    with session_scope() as session:
        board = session.get(TfStoryboard, storyboard_id)
        if board is None:
            raise HTTPException(404, f"分镜不存在: {storyboard_id}")
        project_id = board.projectId
    return pipe.generate_storyboard_images(project_id, [storyboard_id])


@router.delete("/storyboards/{storyboard_id}")
def delete_storyboard(storyboard_id: int):
    from backend.toonflow.pipeline import storyboard as pipe

    pipe.delete_storyboard(storyboard_id)
    return {"success": True}


@router.post("/projects/{project_id}/videos/prompts")
def gen_video_prompts(project_id: int, payload: IdsPayload):
    from backend.toonflow.pipeline import videos as pipe

    return pipe.generate_video_prompts(project_id, payload.ids or None)


@router.post("/projects/{project_id}/videos/generate")
def gen_videos(project_id: int, payload: IdsPayload):
    from backend.toonflow.pipeline import videos as pipe

    return pipe.generate_videos(project_id, payload.ids or None, force=payload.force)


@router.post("/tracks/{track_id}/select")
def select_track_video(track_id: int, payload: IdsPayload):
    from backend.toonflow.pipeline import videos as pipe

    if not payload.ids:
        raise HTTPException(400, "缺少视频 id")
    return pipe.select_video(track_id, payload.ids[0])


@router.delete("/videos/{video_id}")
def delete_video(video_id: int):
    from backend.toonflow.pipeline import videos as pipe

    pipe.delete_video(video_id)
    return {"success": True}


@router.post("/projects/{project_id}/dubbing/bind")
def bind_dubbing(project_id: int):
    from backend.toonflow.pipeline import dubbing as pipe

    return pipe.bind_character_audios(project_id)
