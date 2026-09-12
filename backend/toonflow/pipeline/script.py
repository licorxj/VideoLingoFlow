# -*- coding: utf-8 -*-
"""剧本阶段：剧本生成（事件→草稿，P3 换三层 Agent）与手动导入 / 资产提取。

资产提取使用 o_prompt 的 scriptAssetExtraction 模板——原文要求"必须经 resultTool 返回"，
单发调用时在 system 附加"以 JSON 输出替代 resultTool"的适配说明（隐式契约的显式化）。
"""
import json

from sqlalchemy import select

from backend.toonflow.pipeline import common, submit
from backend.toonflow.core.models import TfAsset, TfNovel, TfProject, TfScript, TfScriptAsset

_VALID_TYPES = ("role", "scene", "tool")


def add_script(project_id: int, title: str, script_data: str) -> int:
    """手动导入剧本。"""
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        row = TfScript(projectId=project_id, title=title or "未命名剧本", scriptData=script_data or "")
        session.add(row)
        session.flush()
        return row.id


def _events_text(session, project_id: int, limit_chars: int = 24000) -> str:
    rows = session.scalars(select(TfNovel).where(TfNovel.projectId == project_id)).all()
    parts = [f"{r.chapter}：{r.event}" for r in rows if (r.event or "").strip()]
    return "\n".join(parts)[:limit_chars]


def generate_script_draft(project_id: int, title: str = "") -> dict:
    """按项目事件列表生成剧本草稿（同步；P3 由三层 Agent 替代）。"""
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        events = _events_text(session, project_id)
        system = common.skill_body("script_execution_script.md")
        if not events:
            raise ValueError("项目还没有事件提取结果，请先完成事件提取")
    prompt = f"请根据以下事件线，输出完整剧本：\n\n{events}"
    text = common.llm(prompt, system=system, json_mode=False, project_id=project_id)
    return {"script_id": add_script(project_id, title or "Agent 剧本草稿", str(text))}


def extract_assets(script_id: int) -> dict:
    """触发资产提取（异步）：剧本 → role/scene/tool 资产清单。"""
    submit(_extract_assets_job, script_id)
    return {"queued": 1}


def _extract_assets_job(script_id: int) -> None:
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        script = session.get(TfScript, script_id)
        if script is None:
            return
        project_id = script.projectId
        script_text = script.scriptData or ""
        project = session.get(TfProject, project_id)
        style_prefix = common.art_style_prefix(project) if project else ""
        template = common.prompt_by_type(session, "scriptAssetExtraction")
        script.extractState = 2  # 提取中（沿用源"进行中"语义：非0非1）

    system = (template
              + "\n\n## 输出方式适配（重要）\n本次运行没有 resultTool 工具。"
                "请直接输出 JSON 对象：{\"assetsList\": [{\"name\", \"desc\", \"prompt\", \"type\"}]}，"
                "type 取值 role/scene/tool，一次性给出全部资产，不要分批。")
    prompt = f"剧本内容：\n\n{script_text[:30000]}"
    data = common.parse_json(common.llm(prompt, system=system, json_mode=True, project_id=project_id))
    assets = data.get("assetsList") or []
    if not assets:
        with session_scope() as session:
            row = session.get(TfScript, script_id)
            if row:
                row.extractState = -1
        return

    created = 0
    with session_scope() as session:
        existing = {(a.name, a.type) for a in session.scalars(
            select(TfAsset).where(TfAsset.projectId == project_id)).all()}
        for item in assets:
            name = str(item.get("name") or "").strip()
            atype = str(item.get("type") or "").strip().lower()
            if not name or atype not in _VALID_TYPES or (name, atype) in existing:
                continue
            prompt_txt = str(item.get("prompt") or "").strip()
            if atype == "scene" or atype == "tool":
                # 场景/道具：英文提示词，画风前缀以注释形态并入（源 generateAssets.buildPrompt 语义）
                prompt_txt = (style_prefix + "\n" + prompt_txt).strip() if style_prefix else prompt_txt
            row = TfAsset(projectId=project_id, name=name, type=atype,
                          describe=str(item.get("desc") or ""), prompt=prompt_txt)
            session.add(row)
            session.flush()
            session.add(TfScriptAsset(scriptId=script_id, assetId=row.id))
            existing.add((name, atype))
            created += 1
        script_row = session.get(TfScript, script_id)
        if script_row:
            script_row.extractState = 1 if created or assets else -1
    print(f"[toonflow:script] extract_assets script={script_id} created={created}")


def asset_state(script_id: int) -> dict:
    """轮询：{state, assets:[...]}。"""
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        script = session.get(TfScript, script_id)
        state = script.extractState if script else 0
        asset_ids = session.scalars(select(TfScriptAsset.assetId).where(
            TfScriptAsset.scriptId == script_id)).all()
        assets = []
        for aid in asset_ids:
            a = session.get(TfAsset, aid)
            if a:
                assets.append({"id": a.id, "name": a.name, "type": a.type,
                               "describe": a.describe, "prompt": a.prompt,
                               "imageId": a.imageId})
    return {"state": state, "assets": assets}
