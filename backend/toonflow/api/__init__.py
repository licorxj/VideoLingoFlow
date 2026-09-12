# -*- coding: utf-8 -*-
"""Toonflow API（挂载于 /api/tf）—— 自定义契约，不复刻源 169 路由。

P0 范围：
    GET  /api/tf/system                  健康检查 + 资产统计（技能/提示词/画风）
    GET  /api/tf/projects                项目列表
    POST /api/tf/projects                新建项目
    GET  /api/tf/projects/{id}           项目详情
    PUT  /api/tf/projects/{id}           更新项目（画风/手册/比例/画质等）
    DELETE /api/tf/projects/{id}         删除项目（级联清理其数据）
    GET  /api/tf/skills                  主技能清单
    GET  /api/tf/skills/libraries        资源库（画风/题材/技法）清单
    GET  /api/tf/prompts                 提示词模板清单（含 effective 正文）
    PUT  /api/tf/prompts/{id}            改写提示词（写 useData）
    GET  /api/tf/agents                  Agent 能力槽位清单
"""
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select

from backend.toonflow.agents import skills_tools
from backend.toonflow.core import seed as tf_seed
from backend.toonflow.core.models import (
    TfAgentDeploy, TfAsset, TfImage, TfNovel, TfPrompt, TfProject,
    TfScript, TfStoryboard, TfVideo, TfVideoTrack,
)

router = APIRouter()

from backend.toonflow.api import canvas as canvas_api  # noqa: E402

router.include_router(canvas_api.router)

try:  # 幂等建表 + 种子（导入即保证 /api/tf 可用；失败不阻塞主应用启动）
    tf_seed.ensure_seeded()
except Exception as _exc:  # noqa: BLE001
    print(f"[toonflow] seed skipped: {_exc}")


class ProjectCreate(BaseModel):
    name: str
    introduce: str = ""
    artStyle: str = ""
    directorManual: str = ""
    mode: str = ""
    videoRatio: str = "16:9"
    imageQuality: str = "1K"
    videoResolution: str = "720P"


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    introduce: Optional[str] = None
    artStyle: Optional[str] = None
    directorManual: Optional[str] = None
    mode: Optional[str] = None
    videoRatio: Optional[str] = None
    imageQuality: Optional[str] = None
    videoResolution: Optional[str] = None


class PromptUpdate(BaseModel):
    useData: str = ""


def _project_dict(p) -> dict:
    return {
        "id": p.id, "name": p.name, "cover": p.cover, "introduce": p.introduce,
        "artStyle": p.artStyle, "directorManual": p.directorManual, "mode": p.mode,
        "videoRatio": p.videoRatio, "imageQuality": p.imageQuality,
        "videoResolution": getattr(p, "videoResolution", "") or "720P",
        "createTime": p.createTime, "updateTime": p.updateTime,
    }


@router.get("/system")
def system_info():
    """健康检查 + 资产统计。"""
    return {
        "ok": True,
        "skills": skills_tools.list_skills(),
        "skillLibraries": skills_tools.list_skill_libraries(),
    }


# ---------------- 项目 ----------------

@router.get("/projects")
def list_projects():
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        rows = session.scalars(select(TfProject).order_by(TfProject.updateTime.desc())).all()
        return {"projects": [_project_dict(p) for p in rows]}


@router.post("/projects")
def create_project(req: ProjectCreate):
    from backend.control_plane.database import session_scope

    if not req.name.strip():
        raise HTTPException(400, "项目名称不能为空")
    with session_scope() as session:
        row = TfProject(name=req.name.strip(), introduce=req.introduce, artStyle=req.artStyle,
                        directorManual=req.directorManual, mode=req.mode,
                        videoRatio=req.videoRatio, imageQuality=req.imageQuality,
                        videoResolution=req.videoResolution or "720P")
        session.add(row)
        session.flush()
        return {"success": True, "project": _project_dict(row)}


def _get_project_or_404(session, project_id: int) -> TfProject:
    row = session.get(TfProject, project_id)
    if row is None:
        raise HTTPException(404, f"项目不存在: {project_id}")
    return row


@router.get("/projects/{project_id}")
def get_project(project_id: int):
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        return {"project": _project_dict(_get_project_or_404(session, project_id))}


@router.put("/projects/{project_id}")
def update_project(project_id: int, req: ProjectUpdate):
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        row = _get_project_or_404(session, project_id)
        for field, value in req.model_dump(exclude_none=True).items():
            setattr(row, field, value)
        row.updateTime = int(time.time() * 1000)
        session.flush()
        return {"success": True, "project": _project_dict(row)}


@router.delete("/projects/{project_id}")
def delete_project(project_id: int):
    """删除项目及其创作数据（资产文件保留在 oss，由后续清理任务处理）。"""
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        _get_project_or_404(session, project_id)
        for table, key in ((TfNovel, "projectId"), (TfScript, "projectId"),
                           (TfAsset, "projectId"), (TfImage, "projectId"),
                           (TfStoryboard, "projectId"), (TfVideo, "projectId"),
                           (TfVideoTrack, "projectId")):
            session.execute(delete(table).where(getattr(table, key) == project_id))
        session.execute(delete(TfProject).where(TfProject.id == project_id))
    return {"success": True}


# ---------------- 资产（技能 / 提示词 / Agent 槽位） ----------------

@router.get("/art-styles")
def list_art_styles():
    """画风选项：skills/art_skills/<画风>/ 目录名（含前缀文件说明首行）。"""
    root = skills_tools.SKILLS_ROOT / "art_skills"
    out = []
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            desc = ""
            for cand in ("prefix.md", "README.md", "art_prompt/prefix.md"):
                p = child / cand
                if p.is_file():
                    for line in p.read_text(encoding="utf-8").split("\n"):
                        line = line.strip().lstrip("#").strip()
                        if line:
                            desc = line[:80]
                            break
                    break
            out.append({"value": child.name, "label": child.name, "desc": desc})
    return {"styles": out}


@router.get("/skills")
def list_skills():
    return {"skills": skills_tools.list_skills()}


@router.get("/skills/libraries")
def list_skill_libraries():
    return {"libraries": skills_tools.list_skill_libraries()}


@router.get("/prompts")
def list_prompts():
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        rows = session.scalars(select(TfPrompt).order_by(TfPrompt.id)).all()
        return {"prompts": [
            {"id": p.id, "name": p.name, "type": p.type,
             "effective": p.effective(), "useData": p.useData or "", "data": p.data}
            for p in rows
        ]}


@router.put("/prompts/{prompt_id}")
def update_prompt(prompt_id: int, req: PromptUpdate):
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        row = session.get(TfPrompt, prompt_id)
        if row is None:
            raise HTTPException(404, f"提示词不存在: {prompt_id}")
        row.useData = req.useData
        session.flush()
        return {"success": True, "id": row.id, "effective": row.effective()}


@router.get("/agents")
def list_agents():
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        rows = session.scalars(select(TfAgentDeploy).order_by(TfAgentDeploy.id)).all()
        return {"agents": [
            {"id": a.id, "key": a.key, "name": a.name, "desc": a.desc,
             "temperature": a.temperature, "maxOutputTokens": a.maxOutputTokens,
             "disabled": a.disabled}
            for a in rows
        ]}
