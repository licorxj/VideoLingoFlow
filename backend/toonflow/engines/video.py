# -*- coding: utf-8 -*-
"""生视频引擎适配：Toonflow `videoRequest(config, model)` → 本项目 videogen 工厂。

源 VideoConfig：{duration, resolution, aspectRatio:"16:9"|"9:16", prompt, referenceList, audio, mode}
本项目：videogen_engine.generate(prompt, output_dir, mode=txt2video|img2video|flf2video|autovideo,
                                 ref_images=, audio=, resolution=, duration=, ratio=, ...)

模式映射（按参考图数量自动路由，与源"模式路由"语义一致）：
    0 张 → txt2video；1 张 → img2video(首帧)；2 张 → flf2video(首尾帧，按序)；≥3 张 → autovideo(全模态参考)
"""
from pathlib import Path

from backend.toonflow.engines.base import (
    EngineOutput, normalize_refs, pick_enabled, resolve_capability, task_record,
)


def _route_mode(ref_count: int, explicit: str = "") -> str:
    if explicit:
        return explicit
    if ref_count == 0:
        return "txt2video"
    if ref_count == 1:
        return "img2video"
    if ref_count == 2:
        return "flf2video"
    return "autovideo"


def run(config: dict, *, project_id: int | None = None,
        interface: str = "", model: str = "") -> EngineOutput:
    """生成视频并落盘 oss。

    config 键：prompt（必填）、referenceList（首帧/首尾帧/多参参考）、duration(秒)、
               resolution(720P/1080P...)、aspectRatio(16:9/9:16)、audio(True/False/None)、
               negativePrompt、mode(可选显式指定)
    """
    from backend.videogen.videogen_factory import get_videogen_engine
    from backend.videogen.videogen_interface_manager import get_videogen_interface_manager

    prompt = str(config.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("生视频缺少 prompt")
    out_dir = Path(config.get("output_dir") or Path("data") / "toonflow" / "tmp" / f"vid_{uuid_hex()}")
    out_dir.mkdir(parents=True, exist_ok=True)

    refs = normalize_refs(config.get("referenceList"), out_dir)
    mode = _route_mode(len(refs), str(config.get("mode") or ""))
    audio = config.get("audio")
    if isinstance(audio, str):
        audio = {"on": True, "off": False}.get(audio.strip().lower(), audio)

    # 画布设置按模式配置「接口+模型」：txt2video→t2v；img2video/flf2video/autovideo→i2v；显式 v2v→v2v
    prefix = "v2v" if "v2v" in mode else {"txt2video": "t2v"}.get(mode, "i2v")
    cfg_iface, cfg_model = resolve_capability("videogen", prefix)
    iface = pick_enabled(get_videogen_interface_manager, interface or cfg_iface)
    engine = get_videogen_engine(iface)
    with task_record("视频生成", "video", project_id):
        paths = engine.generate(
            prompt, str(out_dir), mode=mode, ref_images=refs or None,
            resolution=str(config.get("resolution") or "720P"),
            duration=int(config.get("duration") or 5),
            ratio=str(config.get("aspectRatio") or config.get("ratio") or "16:9"),
            audio=audio,
            negative_prompt=str(config.get("negativePrompt") or ""),
            model=str(model or config.get("model") or cfg_model),
        ) or []
    if not paths:
        raise RuntimeError(f"生视频未返回结果（接口 {iface}，模式 {mode}）")
    return EngineOutput(paths)


def uuid_hex() -> str:
    import uuid

    return uuid.uuid4().hex[:8]
