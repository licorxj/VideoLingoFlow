"""IndexTTS-2.5 本地 API 封装（sdk 型 TTS 接口）。

调用 IndexTTS-2.5 的本地 API 服务（默认端口 8858）。
POST /api/tts（JSON）：优先传 output_path 让服务端直接落盘（绝对路径），
落盘失败时降级为不传 output_path，取响应内嵌 audio_base64 本地解码写入。

支持零样本声音克隆、指令式情感控制（controllable_clone → instruct 模式）、
8 维情感向量（extra_args 配置 emo_control_method=vector）与原生语速
（项目 speed > 1 变快 ↔ duration_factor < 1 变快，wrapper 内做倒数换算）。
"""
import base64
import logging
import os

import requests
from backend.tts.tts_interface_manager import finalize_tts_output

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "http://localhost:8858"


def synthesize(
    text,
    output_path,
    ref_audio=None,
    mode=None,
    controllable_clone=None,
    speed=None,
    timeout=600,
    api_url=DEFAULT_API_URL,
    lang="zh",
    emo_control_method="reference",
    emo_vector="",
    emotion_alpha=1.0,
    text_normalization=True,
    **kwargs,
):
    """调用 IndexTTS-2.5 本地 API 合成语音并写入 output_path。"""
    if not ref_audio or not os.path.exists(ref_audio):
        logger.error(f"IndexTTS-2.5 clone requires ref_audio, got: {ref_audio}")
        return False

    base_url = (api_url or DEFAULT_API_URL).rstrip("/")

    body = {
        "input_text": text,
        "speaker_audio_path": ref_audio,
        "lang": lang or "zh",
        "text_normalization": bool(text_normalization),
    }

    # 原生语速：项目 speed>1 变快，index25 duration_factor<1 变快
    if speed is not None and speed > 0 and abs(speed - 1.0) > 0.01:
        body["duration_factor"] = round(1.0 / float(speed), 4)

    # 情感控制：controllable_clone 模式 → instruct 指令；否则按配置的默认方式
    if mode == "controllable_clone" and controllable_clone:
        body["emo_control_method"] = "instruct"
        body["instruct"] = controllable_clone
        body["emotion_alpha"] = float(emotion_alpha)
    elif emo_control_method == "vector" and emo_vector:
        body["emo_control_method"] = "vector"
        body["emo_vector"] = emo_vector
        body["emotion_alpha"] = float(emotion_alpha)
    elif emo_control_method == "instruct" and controllable_clone:
        body["emo_control_method"] = "instruct"
        body["instruct"] = controllable_clone
        body["emotion_alpha"] = float(emotion_alpha)

    try:
        # 主路径：传绝对 output_path 让服务端直接落盘（统一助手先判定是否已落盘）
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
