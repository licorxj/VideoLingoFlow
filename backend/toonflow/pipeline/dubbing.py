# -*- coding: utf-8 -*-
"""配音阶段：角色-音色绑定（audioBindPrompt 模板 + 配音谷音色库 list_voices）。"""
from sqlalchemy import select

from backend.toonflow.pipeline import common, submit, session_scope_ctx
from backend.toonflow.core.models import TfAsset, TfAssetRoleAudio


def _candidates(project_id: int) -> list[dict]:
    """候选音色：配音谷音色库（vf_voices）。"""
    from backend.creation import list_voices as vf_list_voices

    try:
        rows = vf_list_voices()
    except Exception:  # noqa: BLE001
        rows = []
    return [{"audioId": v["id"], "desc": "；".join(
        x for x in (v.get("display_name") or v.get("name"), v.get("gender") or "",
                    v.get("description") or "") if x)} for v in rows]


def bind_character_audios(project_id: int) -> dict:
    """为全部 role 资产匹配音色（异步）。"""
    with session_scope_ctx() as session:
        roles = session.scalars(select(TfAsset).where(
            TfAsset.projectId == project_id, TfAsset.type == "role")).all()
        count = len(roles)
    if count:
        submit(_bind_job, project_id)
    return {"queued": 1 if count else 0, "roles": count}


def _bind_job(project_id: int) -> None:
    from backend.control_plane.database import session_scope

    with session_scope_ctx() as session:
        roles = session.scalars(select(TfAsset).where(
            TfAsset.projectId == project_id, TfAsset.type == "role")).all()
        pairs = [{"assetId": r.id, "name": r.name, "desc": r.describe} for r in roles]
        system = common.prompt_by_type(session, "audioBindPrompt")

    candidates = _candidates(project_id)
    if not candidates:
        print("[toonflow:dubbing] 音色库为空，跳过绑定")
        return

    prompt = (f"候选音频列表(JSON)：\n{json.dumps(candidates, ensure_ascii=False)}\n\n"
              f"角色列表(JSON)：\n{json.dumps(pairs, ensure_ascii=False)}\n\n"
              '请输出 JSON：{"bindings": [{"assetId": <id>, "audioId": "<音色id>"}]}，'
              "无合适音色的角色不要输出。")
    data = common.parse_json(common.llm(prompt, system=system, json_mode=True, project_id=project_id))
    bindings = {int(b["assetId"]): str(b["audioId"]) for b in (data.get("bindings") or [])
                if b.get("assetId") and b.get("audioId")}
    if not bindings:
        print("[toonflow:dubbing] 无绑定结果")
        return

    with session_scope_ctx() as session:
        session.query(TfAssetRoleAudio).filter(TfAssetRoleAudio.projectId == project_id).delete()
        for asset_id, audio_id in bindings.items():
            session.add(TfAssetRoleAudio(projectId=project_id, assetId=asset_id, audioId=audio_id))
    print(f"[toonflow:dubbing] project={project_id} bound={len(bindings)}")


def bindings_of(project_id: int) -> list[dict]:
    with session_scope_ctx() as session:
        rows = session.scalars(select(TfAssetRoleAudio).where(
            TfAssetRoleAudio.projectId == project_id)).all()
        out = []
        for r in rows:
            asset = session.get(TfAsset, r.assetId)
            out.append({"id": r.id, "assetId": r.assetId,
                        "assetName": asset.name if asset else "", "audioId": r.audioId})
        return out


def unbind(binding_id: int) -> None:
    with session_scope_ctx() as session:
        row = session.get(TfAssetRoleAudio, binding_id)
        if row:
            session.delete(row)
