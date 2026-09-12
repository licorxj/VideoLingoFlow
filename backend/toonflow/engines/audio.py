# -*- coding: utf-8 -*-
"""TTS 引擎适配：Toonflow `ttsRequest(config, model)` → 本项目 tts 工厂。

源契约：返回音频 base64。本项目：tts_engine.synthesize(text, out_path, mode=, voice=,
voice_design=, controllable_clone=, ref_audio=, speed=, model=)，落盘后经 EngineOutput 兼容 base64。

模式映射：preset_voice(预设音色) / voice_design(音色设计) / clone|controllable_clone(克隆)。
"""
from pathlib import Path

from backend.toonflow.engines.base import EngineOutput, materialize_input, pick_enabled, task_record


def _default_tts_model() -> str:
    """config.yaml 的 tts.default_model（画布设置弹窗写入），未配置返回空串。"""
    try:
        from backend.config.config_manager import config as app_config

        return str(app_config.get("tts.default_model") or "")
    except Exception:  # noqa: BLE001
        return ""


def _default_tts_interface() -> str:
    """config.yaml 的 tts.method（画布设置弹窗写入），未配置返回空串。"""
    try:
        from backend.config.config_manager import config as app_config

        return str(app_config.get("tts.method") or "")
    except Exception:  # noqa: BLE001
        return ""


def run(config: dict, *, project_id: int | None = None,
        interface: str = "", model: str = "") -> EngineOutput:
    """合成一段语音并落盘。

    config 键：text（必填）、mode(preset_voice/voice_design/clone/controllable_clone)、
               voice(预设音色)、voiceDesign(设计指令)、refAudio(克隆参考音频)、speed、model
    """
    from backend.tts.tts_factory import get_tts_engine
    from backend.tts.tts_interface_manager import get_tts_interface_manager

    text = str(config.get("text") or "").strip()
    if not text:
        raise ValueError("TTS 缺少 text")
    mode = str(config.get("mode") or "preset_voice")
    out_path = Path(config.get("output_path")
                    or Path("data") / "toonflow" / "tmp" / f"tts_{__import__('uuid').uuid4().hex[:8]}.wav")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    kwargs = {"mode": mode}
    if mode == "voice_design":
        kwargs["voice_design"] = str(config.get("voiceDesign") or "")
    elif mode in ("clone", "controllable_clone"):
        ref = config.get("refAudio")
        if ref:
            kwargs["ref_audio"] = materialize_input(ref, out_path.parent)
        if mode == "controllable_clone":
            kwargs["controllable_clone"] = str(config.get("cloneInstruct") or config.get("voiceDesign") or "")
    else:
        if config.get("voice"):
            kwargs["voice"] = str(config["voice"])

    iface = pick_enabled(get_tts_interface_manager, interface or _default_tts_interface())
    engine = get_tts_engine(iface)
    with task_record("TTS 合成", "tts", project_id):
        ok = engine.synthesize(
            text, str(out_path),
            speed=config.get("speed"),
            model=str(model or config.get("model") or _default_tts_model()),
            **kwargs,
        )
    if not ok or not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(f"TTS 未返回有效音频（接口 {iface}，模式 {mode}）")
    return EngineOutput([str(out_path)])
