#!/usr/bin/env python3
"""MiMo TTS SDK wrapper - bridges MiMoTTS API to the project TTS SDK interface."""
import os
import sys
import logging

logger = logging.getLogger(__name__)

_this_dir = os.path.dirname(os.path.abspath(__file__))
if _this_dir not in sys.path:
    sys.path.insert(0, _this_dir)

_mimotts_module = None


def _get_mimotts():
    global _mimotts_module
    if _mimotts_module is None:
        from backend.tts.sdk import mimotts_api
        _mimotts_module = mimotts_api
    return _mimotts_module


def _speed_to_description(speed):
    """将语速数值映射为自然语言描述，拼入提示词控制语速。

    语速区间与描述：
      0.75  → 语速非常慢
      0.9   → 语速较慢
      1.0   → 语速略慢（接近正常）
      1.05+ → 语速略快
      1.1   → 语速略快
      1.15  → 语速较快
      1.2   → 语速很快
    """
    if speed <= 0.82:
        return "语速非常慢"
    elif speed <= 0.92:
        return "语速较慢"
    elif speed <= 0.98:
        return "语速略慢"
    elif speed <= 1.02:
        return ""  # 正常语速，无需额外描述
    elif speed <= 1.12:
        return "语速略快"
    elif speed <= 1.18:
        return "语速较快"
    else:
        return "语速很快"


def synthesize(text, output_path, voice=None, mode=None, ref_audio=None,
               voice_design=None, speed=None, model=None, api_key=None,
               ref_text=None, timeout=120, **kwargs):
    mimotts = _get_mimotts()
    MiMoTTS = mimotts.MiMoTTS
    if not api_key:
        api_key = mimotts.CONFIG.get("api_key") or os.environ.get("MIMO_API_KEY", "")
    if not api_key:
        logger.error("MiMo TTS: API key not configured")
        return False
    try:
        tts = MiMoTTS(api_key=api_key, timeout=timeout)
        # 构建 speed 提示（当 TTS API 不原生支持 speed 时，拼接到描述中）
        speed_hint = ""
        if speed and abs(speed - 1.0) > 0.01:
            speed_desc = _speed_to_description(speed)
            if speed_desc:
                speed_hint = f"{speed_desc}。"

        if mode == "voice_design" or (not mode and voice_design):
            desc = f"{speed_hint}{voice_design or '默认'}" if speed_hint else (voice_design or "default")
            result = tts.synthesize_with_design(
                text=text, voice_description=desc)
        elif mode == "controllable_clone":
            if not ref_audio or not os.path.exists(ref_audio):
                logger.error("ref_audio required for controllable_clone mode")
                return False
            if ref_text:
                logger.info(f"controllable_clone ref_text: {ref_text[:80]}")
            style_desc = kwargs.get("controllable_clone") or voice_design or ""
            if speed_hint:
                style_desc = f"{speed_hint}{style_desc}"
            result = tts.synthesize_with_clone(
                text=text, reference_audio_path=ref_audio,
                style_description=style_desc or None)
        elif mode == "clone":
            if not ref_audio or not os.path.exists(ref_audio):
                logger.error("ref_audio required for clone mode")
                return False
            if ref_text:
                logger.info(f"clone ref_text: {ref_text[:80]}")
            result = tts.synthesize_with_clone(
                text=text, reference_audio_path=ref_audio,
                style_description=speed_hint or None)
        else:
            result = tts.synthesize_with_preset(
                text=text, voice=voice or "mimo_default")
        if result.success:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            success = tts.save_audio(result, output_path)
            tts.shutdown()
            return success
        else:
            tts.shutdown()
            return False
    except Exception as e:
        logger.error("MiMo TTS error: " + str(e))
        import traceback
        traceback.print_exc()
        return False


def list_voices():
    mimotts = _get_mimotts()
    MiMoTTS = mimotts.MiMoTTS
    try:
        tts = MiMoTTS(api_key="dummy")
        voices = list(tts.get_preset_voices().keys())
        tts.shutdown()
        return voices
    except Exception:
        return ["mimo_default"]
