# -*- coding: utf-8 -*-
"""角色音色：设计（voice_design 指令 → TTS 合成 → 入配音谷库 → 自动绑定）与绑定管理。

复用 voiceforge 服务层（synthesize_voice_clip / register_voice_sample）与配音谷 vf_voices；
绑定点沿用源 o_assetsRole2Audio（tf_assets_role_audio）。
"""
import json
import uuid
from pathlib import Path

from sqlalchemy import select

from backend.toonflow.core.models import TfAsset, TfAssetRoleAudio, TfProject


def _pick_voice_design_interface() -> str:
    """挑选首个支持 voice_design 模式的已启用 TTS 接口。"""
    from backend.tts.tts_interface_manager import get_tts_interface_manager

    for iface in get_tts_interface_manager().get_enabled():
        modes = (iface.get("config") or {}).get("modes") or {}
        if (modes.get("voice_design") or {}).get("enabled"):
            return iface["id"]
    raise RuntimeError("没有支持「音色设计」模式的已启用 TTS 接口，请先在「设置 → TTS 接口」中配置")


def bind_role_voice(project_id: int, asset_id: int, audio_id: str) -> dict:
    """手动绑定/换绑角色音色（覆盖旧绑定）。"""
    with session_scope_ctx() as session:
        session.query(TfAssetRoleAudio).filter(
            TfAssetRoleAudio.projectId == project_id,
            TfAssetRoleAudio.assetId == asset_id).delete()
        session.add(TfAssetRoleAudio(projectId=project_id, assetId=asset_id, audioId=audio_id))
    return {"success": True, "assetId": asset_id, "audioId": audio_id}


def unbind_role_voice(asset_id: int) -> dict:
    """解除角色音色绑定。"""
    with session_scope_ctx() as session:
        session.query(TfAssetRoleAudio).filter(
            TfAssetRoleAudio.assetId == asset_id).delete()
    return {"success": True, "assetId": asset_id}


def design_role_voice(asset_id: int) -> dict:
    """为角色设计专属音色（异步）：LLM 生成音色设计指令 → 合成 → 入库 → 绑定。"""
    with session_scope_ctx() as session:
        asset = session.get(TfAsset, asset_id)
        if asset is None:
            raise ValueError(f"角色资产不存在: {asset_id}")
        if asset.type != "role":
            raise ValueError("只有「角色」类型资产可以设计音色")
    submit(_design_job, int(asset_id))
    return {"queued": 1, "assetId": asset_id}


def _design_job(asset_id: int) -> None:
    from backend.toonflow.engines.base import task_record

    with session_scope_ctx() as session:
        asset = session.get(TfAsset, asset_id)
        if asset is None:
            return
        project_id = asset.projectId
        role_name = asset.name or f"角色{asset_id}"
        describe = asset.describe or ""
        project = session.get(TfProject, project_id)
        story_style = getattr(project, "storyStyle", "") or ""

    with task_record("音色设计", "tts", project_id):
        # 1) LLM 生成音色设计指令 + 试听台词（贴合角色与题材）
        system = ("你是资深配音导演。根据角色信息，为其设计一条音色设计指令"
                  "（voice_design，30~60字，描述音色质地/年龄感/语气/能量，不出现角色名），"
                  "并写一句 15~25 字的第一人称试听台词。"
                  '直接输出 JSON：{"voice_design": "...", "sample_text": "..."}')
        prompt = (f"角色名：{role_name}\n角色描述：{describe or '（无）'}\n"
                  f"题材风格：{story_style or '未设定'}")
        data = common.parse_json(common.llm(prompt, system=system, json_mode=True,
                                            project_id=project_id))
        voice_design = str(data.get("voice_design") or "").strip()
        sample_text = str(data.get("sample_text") or "").strip() or f"你好，我是{role_name}。"
        if not voice_design:
            raise RuntimeError("音色设计指令生成失败")

        # 2) 选接口并合成样本（复用 voiceforge 服务层：重试 + 落盘校验）
        interface = _pick_voice_design_interface()
        from backend.voiceforge.services import register_voice_sample, synthesize_voice_clip

        tmp = Path("data") / "toonflow" / "tmp" / f"voice_design_{asset_id}_{uuid.uuid4().hex[:8]}.wav"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        synthesize_voice_clip(interface, sample_text, tmp, "voice_design",
                              voice_design=voice_design)

        # 3) 登记进配音谷音色库
        voice = register_voice_sample(
            name=f"{role_name}·画布音色", interface_id=interface, mode="voice_design",
            sample_text=sample_text, sample_clip=tmp, voice_design=voice_design,
            description=f"画布角色音色设计 · {describe}"[:200],
            tags=["画布角色", "音色设计"])

    # 4) 绑定到角色（覆盖旧绑定）
    bind_role_voice(project_id, asset_id, voice["id"])
    print(f"[toonflow:voice-design] asset={asset_id} voice={voice['id']} "
          f"design={voice_design[:40]}")

