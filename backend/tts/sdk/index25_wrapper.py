"""IndexTTS-2.5 本地 API 封装（sdk 型 TTS 接口）。

调用 IndexTTS-2.5 的本地 API 服务（默认端口 8858）。
POST /api/tts（JSON）：优先传 output_path 让服务端直接落盘（绝对路径），
落盘失败时降级为不传 output_path，取响应内嵌 audio_base64 本地解码写入。

支持零样本声音克隆、指令式情感控制（controllable_clone → instruct 模式）、
8 维情感向量（extra_args 配置 emo_control_method=vector）与原生语速（speed 参数）。

参数与 IndexTTS-2.5 API 文档完全对齐，与项目 TTS 工厂的请求参数解耦。
"""
import base64
import logging
import os

import requests
from backend.tts.tts_interface_manager import finalize_tts_output

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "http://localhost:8858"

# API 参数硬编码兜底默认值（与 IndexTTS-2.5 API 文档一致）
_HARDCODED_DEFAULTS = {
    "api_url": DEFAULT_API_URL,
    "lang": "zh",
    "speed": 1.0,
    "text_normalization": True,
    "interval_silence": 200,
    "max_text_tokens_per_segment": 120,
    "use_random": False,
    "emo_control_method": "reference",
    "emotion_alpha": 1.0,
    "do_sample": True,
    "top_p": 0.9,
    "top_k": 50,
    "temperature": 1.0,
    "num_beams": 1,
    "repetition_penalty": 1.2,
    "length_penalty": 1.0,
    "max_mel_tokens": 3000,
}


def _resolve(key, arg):
    """解析单个参数的最终取值：显式传入 > 硬编码默认值。"""
    if arg is not None:
        return arg
    return _HARDCODED_DEFAULTS.get(key)


def synthesize(
    text,
    output_path,
    ref_audio=None,
    mode=None,
    controllable_clone=None,
    speed=None,
    timeout=600,
    api_url=None,
    lang=None,
    emo_control_method=None,
    emo_vector=None,
    emotion_alpha=None,
    text_normalization=None,
    interval_silence=None,
    max_text_tokens_per_segment=None,
    use_random=None,
    do_sample=None,
    top_p=None,
    top_k=None,
    temperature=None,
    num_beams=None,
    repetition_penalty=None,
    length_penalty=None,
    max_mel_tokens=None,
    **kwargs,
):
    """调用 IndexTTS-2.5 本地 API 合成语音并写入 output_path。

    参数与 IndexTTS-2.5 API 文档完全对齐。
    情感控制逻辑：
    - 克隆模式（默认）：emo_control_method = reference，情感来自参考音频
    - 可控克隆模式：emo_control_method = instruct，controllable_clone 作为 instruct 文本
    """
    if not ref_audio or not os.path.exists(ref_audio):
        logger.error(f"IndexTTS-2.5 clone requires ref_audio, got: {ref_audio}")
        return False

    base_url = (api_url or _resolve("api_url", None)).rstrip("/")

    # 构建请求体（参数名与 API 文档一致）
    body = {
        "input_text": text,
        "speaker_audio_path": ref_audio,
        "lang": lang or _resolve("lang", None),
        "text_normalization": bool(_resolve("text_normalization", text_normalization)),
        "interval_silence": int(_resolve("interval_silence", interval_silence)),
        "max_text_tokens_per_segment": int(_resolve("max_text_tokens_per_segment", max_text_tokens_per_segment)),
        "use_random": bool(_resolve("use_random", use_random)),
        "do_sample": bool(_resolve("do_sample", do_sample)),
        "top_p": float(_resolve("top_p", top_p)),
        "top_k": int(_resolve("top_k", top_k)),
        "temperature": float(_resolve("temperature", temperature)),
        "num_beams": int(_resolve("num_beams", num_beams)),
        "repetition_penalty": float(_resolve("repetition_penalty", repetition_penalty)),
        "length_penalty": float(_resolve("length_penalty", length_penalty)),
        "max_mel_tokens": int(_resolve("max_mel_tokens", max_mel_tokens)),
    }

    # 语速控制：API 原生支持 speed 参数（>1 加快，<1 放慢）
    speed_val = _resolve("speed", speed)
    if speed_val is not None and abs(float(speed_val) - 1.0) > 0.01:
        body["speed"] = float(speed_val)

    # 情感控制逻辑
    if mode == "controllable_clone" and controllable_clone:
        # 可控克隆模式：使用 instruct 指令情感控制
        body["emo_control_method"] = "instruct"
        body["instruct"] = controllable_clone
        body["emotion_alpha"] = float(_resolve("emotion_alpha", emotion_alpha))
    else:
        # 克隆模式：使用 reference（默认），情感来自参考音频
        emo_method = _resolve("emo_control_method", emo_control_method)
        if emo_method == "vector" and emo_vector:
            # 向量模式
            body["emo_control_method"] = "vector"
            body["emo_vector"] = emo_vector
            body["emotion_alpha"] = float(_resolve("emotion_alpha", emotion_alpha))
        elif emo_method == "instruct" and controllable_clone:
            # instruct 模式（非 controllable_clone 模式但配置了 instruct）
            body["emo_control_method"] = "instruct"
            body["instruct"] = controllable_clone
            body["emotion_alpha"] = float(_resolve("emotion_alpha", emotion_alpha))
        else:
            # 默认 reference 模式
            body["emo_control_method"] = "reference"

    try:
        # 主路径：传绝对 output_path 让服务端直接落盘
        resp = requests.post(
            f"{base_url}/api/tts",
            json={**body, "output_path": os.path.abspath(output_path)},
            timeout=float(timeout or 600),
        )
        resp.raise_for_status()
        if finalize_tts_output(output_path, timeout=timeout):
            data = resp.json()
            logger.info(
                f"IndexTTS-2.5 synthesized to {output_path}, "
                f"duration={data.get('duration')}"
            )
            return True

        # 降级：不传 output_path，取内嵌 base64 本地写入
        logger.warning(
            f"IndexTTS-2.5 server-side save failed, fallback to base64"
        )
        resp = requests.post(f"{base_url}/api/tts", json=body, timeout=float(timeout or 600))
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0 or not data.get("audio_base64"):
            logger.error(f"IndexTTS-2.5 synthesis failed: {str(data)[:300]}")
            return False
        return finalize_tts_output(
            output_path, content=base64.b64decode(data["audio_base64"]), timeout=timeout
        )
    except requests.exceptions.ConnectionError as e:
        logger.error(f"IndexTTS-2.5 service unreachable at {base_url}: {e}")
        return False
    except Exception:
        logger.exception("IndexTTS-2.5 synthesis failed")
        return False


def list_voices():
    """IndexTTS-2.5 为零样本克隆，无预置音色。"""
    return []
