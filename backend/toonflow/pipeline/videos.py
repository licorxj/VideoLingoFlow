# -*- coding: utf-8 -*-
"""视频阶段：视频提示词（videoPromptGeneration 19757字模板）/ 视频生成与重生 / 选定。

模式路由（对齐源 videoPromptGeneration 技能）：本项目 videogen 按参考图数自动路由，
提示词模板输出什么格式由 LLM 按项目配置的模型风格决定（Seedance2.0/Wan2.6/通用），此处透传。
"""
import json

from sqlalchemy import select

from backend.toonflow.pipeline import common, submit, session_scope_ctx
from backend.toonflow.core.models import TfAsset, TfImage, TfProject, TfStoryboard, TfVideo, TfVideoTrack
from backend.toonflow.core.paths import copy_into_oss


def generate_video_prompts(project_id: int, storyboard_ids: list[int] | None = None) -> dict:
    """为分镜生成视频提示词（异步；模板要求逐镜整合输出，这里按单镜调用保证对齐）。"""
    with session_scope_ctx() as session:
        stmt = select(TfStoryboard).where(TfStoryboard.projectId == project_id)
        if storyboard_ids:
            stmt = stmt.where(TfStoryboard.id.in_([int(i) for i in storyboard_ids]))
        boards = [b.id for b in session.scalars(stmt).all()]
    for bid in boards:
        submit(_video_prompt_job, project_id, bid)
    return {"queued": len(boards)}


def _build_storyboard_xml(board: TfStoryboard) -> str:
    return (f"<storyboardItem videoDesc='{board.videoDesc}' prompt='{board.prompt[:400]}' "
            f"track='{board.track}' duration='{board.duration}' "
            f"associateAssetsIds=\"{board.assetIds}\" "
            f"shouldGenerateImage=\"{'true' if board.shouldGenerateImage else 'false'}\"></storyboardItem>")


def _video_prompt_job(project_id: int, board_id: int) -> None:
    with session_scope_ctx() as session:
        board = session.get(TfStoryboard, board_id)
        project = session.get(TfProject, project_id)
        if board is None or project is None:
            return
        assets = session.scalars(select(TfAsset).where(TfAsset.projectId == project_id)).all()
        assets_text = "资产信息" + ", ".join(f"[A{a.id}, {a.type}, {a.name}]" for a in assets)
        xml = _build_storyboard_xml(board)
        system = common.prompt_by_type(session, "videoPromptGeneration")

    prompt = (f"模型：{project.mode or '通用多参模式'}\n{assets_text}\n{xml}\n"
              "请按匹配模式输出该分镜的视频提示词（仅输出提示词文本）。")
    text = str(common.llm(prompt, system=system, json_mode=False, project_id=project_id)).strip()
    if not text:
        raise RuntimeError(f"分镜 {board_id} 视频提示词为空")

    with session_scope_ctx() as session:
        board = session.get(TfStoryboard, board_id)
        if board is None:
            return
        board.videoPrompt = text
        # 建/复用轨道并写入 prompt
        track = session.scalars(select(TfVideoTrack).where(
            TfVideoTrack.projectId == project_id,
            TfVideoTrack.storyboardId == board_id)).first()
        if track is None:
            track = TfVideoTrack(projectId=project_id, storyboardId=board_id)
            session.add(track)
            session.flush()
        track.prompt = text
        board.track = board.track or "main"


def generate_videos(project_id: int, storyboard_ids: list[int] | None = None,
                    force: bool = False) -> dict:
    """为分镜生成视频候选（异步；referenceList=[分镜图]）。"""
    with session_scope_ctx() as session:
        stmt = select(TfStoryboard).where(TfStoryboard.projectId == project_id)
        if storyboard_ids:
            stmt = stmt.where(TfStoryboard.id.in_([int(i) for i in storyboard_ids]))
        boards = session.scalars(stmt).all()
        targets = []
        for b in boards:
            if not (b.videoPrompt or "").strip():
                continue
            if not force and (b.filePath or b.state == "已完成"):
                continue
            targets.append(b.id)
    for bid in targets:
        submit(_video_job, project_id, bid)
    return {"queued": len(targets)}


def _video_job(project_id: int, board_id: int) -> None:
    from backend.toonflow.engines import Ai

    with session_scope_ctx() as session:
        board = session.get(TfStoryboard, board_id)
        project = session.get(TfProject, project_id)
        if board is None or project is None:
            return
        refs = []
        if board.filePath:
            refs.append(board.filePath)
        for aid in json.loads(board.assetIds or "[]"):
            asset = session.get(TfAsset, int(str(aid).lstrip("Aa")))
            if asset and asset.imageId:
                img = session.get(TfImage, asset.imageId)
                if img and img.filePath:
                    refs.append(str(img.filePath))
        track = session.scalars(select(TfVideoTrack).where(
            TfVideoTrack.projectId == project_id,
            TfVideoTrack.storyboardId == board_id)).first()
        track_id = track.id if track else None

    out = Ai.video.run({
        "prompt": board.videoPrompt or board.videoDesc,
        "referenceList": refs,
        "duration": board.duration,
        "aspectRatio": project.videoRatio or "16:9",
        "resolution": (getattr(project, "videoResolution", "") or "") or "720P",
    }, project_id=project_id)

    with session_scope_ctx() as session:
        oss_path = copy_into_oss(out.first, project_id, "videos")
        video = TfVideo(projectId=project_id, videoTrackId=track_id,
                        state="生成成功", prompt=board.videoPrompt or "",
                        filePath=str(oss_path), duration=board.duration)
        session.add(video)
        session.flush()
        track = session.get(TfVideoTrack, track_id) if track_id else None
        if track and not track.selectVideoId:
            track.selectVideoId = video.id
        print(f"[toonflow:videos] board={board_id} video={video.id}")


def select_video(track_id: int, video_id: int) -> dict:
    """选定轨道视频。"""
    with session_scope_ctx() as session:
        track = session.get(TfVideoTrack, track_id)
        video = session.get(TfVideo, video_id)
        if track is None or video is None:
            raise ValueError("轨道或视频不存在")
        track.selectVideoId = video_id
    return {"success": True}


def delete_video(video_id: int) -> None:
    with session_scope_ctx() as session:
        v = session.get(TfVideo, video_id)
        if v:
            session.delete(v)
