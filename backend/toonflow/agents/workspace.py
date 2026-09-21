# -*- coding: utf-8 -*-
"""工作区（FlowData）—— 源系统存于前端缓存的五类工作区数据，改为服务端直接读库：

    script          剧本正文（最新）
    scriptPlan      拍摄计划（Agent 产出的计划文本，存 tf_settings）
    assets          资产清单（含衍生资产与出图状态）
    storyboardTable 分镜表（文本行视图）
    storyboard      分镜面板/产物（逐镜详情）

key 契约与源 productionAgent/tools.ts 的 flowDataSchema 一致，Agent 提示词无需改动。
"""
import json

from sqlalchemy import select

from backend.toonflow.core.models import (
    TfAsset, TfImage, TfNovel, TfProject, TfScript, TfSetting, TfStoryboard, TfVideoTrack,
)


def _project(session, project_id: int) -> TfProject | None:
    return session.get(TfProject, project_id)


def get_flow_data(project_id: int, key: str):
    """按 key 返回工作区数据；未知 key 抛 ValueError。"""
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        if key == "script" or key.startswith("script:"):
            # key 支持 "script"（最新）与 "script:<id>"（指定剧本，前端会话绑定剧本用）
            script_id = int(key.split(":", 1)[1]) if key.startswith("script:") and key.split(":", 1)[1].isdigit() else None
            if script_id:
                target = session.get(TfScript, script_id)
                if target is None or target.projectId != project_id:
                    raise ValueError(f"剧本不存在: {script_id}")
                return target.scriptData or ""
            script = session.scalars(select(TfScript).where(
                TfScript.projectId == project_id).order_by(TfScript.id.desc())).first()
            return script.scriptData if script else ""

        if key == "scriptPlan":
            row = session.get(TfSetting, f"scriptPlan:{project_id}")
            return row.value if row else ""

        if key == "assets":
            rows = session.scalars(select(TfAsset).where(
                TfAsset.projectId == project_id).order_by(TfAsset.id)).all()
            out = []
            for a in rows:
                has_image = bool(a.imageId and session.get(TfImage, a.imageId))
                out.append({"id": a.id, "assetsId": a.assetsId, "name": a.name,
                            "type": a.type, "describe": a.describe, "prompt": a.prompt,
                            "imageId": a.imageId, "hasImage": has_image,
                            "isDerived": a.assetsId is not None})
            return out

        if key == "storyboardTable":
            boards = session.scalars(select(TfStoryboard).where(
                TfStoryboard.projectId == project_id).order_by(TfStoryboard.orderNo)).all()
            lines = [f"{b.orderNo}. {b.videoDesc}（时长:{b.duration}s 资产:{b.assetIds or '无'}）"
                     for b in boards]
            return "\n".join(lines)

        if key == "storyboard":
            boards = session.scalars(select(TfStoryboard).where(
                TfStoryboard.projectId == project_id).order_by(TfStoryboard.orderNo)).all()
            return [{"id": b.id, "orderNo": b.orderNo, "videoDesc": b.videoDesc,
                     "prompt": b.prompt, "videoPrompt": b.videoPrompt,
                     "filePath": b.filePath, "duration": b.duration,
                     "assetIds": json.loads(b.assetIds or "[]"),
                     "shouldGenerateImage": b.shouldGenerateImage} for b in boards]

        if key == "novelEvents":
            rows = session.scalars(select(TfNovel).where(TfNovel.projectId == project_id)).all()
            return "\n".join(f"{r.chapter}：{r.event}" for r in rows if (r.event or "").strip())

    raise ValueError(f"未知工作区 key: {key}（可选 script/scriptPlan/assets/storyboardTable/storyboard/novelEvents）")


def save_script_plan(project_id: int, plan: str) -> None:
    """保存拍摄计划到工作区（tf_settings KV）。"""
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        row = session.get(TfSetting, f"scriptPlan:{project_id}")
        if row is None:
            row = TfSetting(key=f"scriptPlan:{project_id}", value=plan)
            session.add(row)
        else:
            row.value = plan


def project_summary(project_id: int) -> dict:
    """项目概要（注入决策层 system）。"""
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        p = _project(session, project_id)
        if p is None:
            raise ValueError(f"项目不存在: {project_id}")
        assets = session.scalars(select(TfAsset).where(TfAsset.projectId == project_id)).all()
        boards = session.scalars(select(TfStoryboard).where(
            TfStoryboard.projectId == project_id)).all()
        script = session.scalars(select(TfScript).where(
            TfScript.projectId == project_id).order_by(TfScript.id.desc())).first()
        all_scripts = session.scalars(select(TfScript).where(
            TfScript.projectId == project_id).order_by(TfScript.id.desc())).all()
        return {
            "projectId": project_id, "name": p.name,
            "scripts": [{"id": s.id, "title": s.title, "chars": len(s.scriptData or "")}
                        for s in all_scripts],
            "introduce": p.introduce or "",
            "artStyle": p.artStyle or "未设定",
            "storyStyle": getattr(p, "storyStyle", "") or "未设定",
            "directorManual": p.directorManual or "",
            "videoRatio": p.videoRatio,
            "videoResolution": getattr(p, "videoResolution", "") or "720P",
            "imageQuality": p.imageQuality or "1K",
            "mode": p.mode or "纯文本多参模式",
            "stats": {
                "scripts": 1 if script else 0,
                "assets": len(assets),
                "assetsWithImage": sum(1 for a in assets if a.imageId),
                "storyboards": len(boards),
                "storyboardsWithPrompt": sum(1 for b in boards if (b.prompt or "").strip()),
                "storyboardsWithImage": sum(1 for b in boards if (b.filePath or "").strip()),
                "storyboardsWithVideoPrompt": sum(1 for b in boards if (b.videoPrompt or "").strip()),
            },
        }
