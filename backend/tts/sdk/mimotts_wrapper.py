"""MiMo-V2.5-TTS SDK 封装（sdk 型 TTS 接口）。

按 _backup/mimoTTS接口文档.md 实现，全部走 OpenAI 兼容的【非流式】chat.completions 接口：
    POST https://api.xiaomimimo.com/v1/chat/completions
鉴权使用标准 Authorization: Bearer（与官方 SDK 示例一致）。
返回 choices[0].message.audio.data（base64 编码的 WAV）后解码写入 output_path。

四种模式映射：
  - preset_voice       预置音色   -> model=mimo-v2.5-tts，audio.voice=预置音色ID
  - voice_design       声音设计   -> model=mimo-v2.5-tts-voicedesign，user 消息=音色描述文本
  - clone              声音克隆   -> model=mimo-v2.5-tts-voiceclone，audio.voice=参考音频 base64(data URI)
  - controllable_clone 可控克隆   -> voiceclone 模型 + user 消息携带风格指令（自然语言/音频标签）

说明：使用 requests 直连 OpenAI 兼容端点（而非 openai SDK），以避免低版本 SDK 对
message.audio 字段解析的兼容问题；这仍是标准的非流式 OpenAI 请求。
"""
import base64
import json
import logging
import os

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.xiaomimimo.com/v1"
MODEL_PRESET = "mimo-v2.5-tts"
MODEL_VOICEDESIGN = "mimo-v2.5-tts-voicedesign"
MODEL_VOICECLONE = "mimo-v2.5-tts-voiceclone"

# 预置音色列表（来自文档）
PRESET_VOICES = [
    {"name": "MiMo-默认", "id": "mimo_default", "language": "因集群而异", "gender": "-"},
    {"name": "冰糖", "id": "冰糖", "language": "中文", "gender": "女性"},
    {"name": "茉莉", "id": "茉莉", "language": "中文", "gender": "女性"},
    {"name": "苏打", "id": "苏打", "language": "中文", "gender": "男性"},
    {"name": "白桦", "id": "白桦", "language": "中文", "gender": "男性"},
    {"name": "Mia", "id": "Mia", "language": "英文", "gender": "女性"},
    {"name": "Chloe", "id": "Chloe", "language": "英文", "gender": "女性"},
    {"name": "Milo", "id": "Milo", "language": "英文", "gender": "男性"},
    {"name": "Dean", "id": "Dean", "language": "英文", "gender": "男性"},
]


def _get_api_key(api_key=None):
    if api_key:
        return api_key
    return os.environ.get("MIMO_API_KEY", "")


def _encode_audio_data_uri(ref_audio_path):
    """读取参考音频文件，编码为 data:{mime};base64,... 的 data URI（MiMo 克隆所需）。"""
    ext = os.path.splitext(ref_audio_path)[1].lower()
    mime = "audio/wav" if ext == ".wav" else "audio/mpeg"
    with open(ref_audio_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _speed_to_instruction(speed):
    """将调速倍数(相对 1.0)映射为 MiMo 风格指令，变相实现语速控制。

    MiMo 的 audio 对象无原生语速参数，故把 speed 转成自然语言指令放在 user 消息开头。
    映射(语速值 -> 指令)，与文档口径一致：
        <=0.8  语速非常慢
        <=0.9  语速较慢
        <=1.0  语速偏慢
        <=1.2  语速偏快
        <=1.4  语速较快
        > 1.4  语速非常快
    """
    if speed is None:
        return ""
    if speed <= 0.8:
        return "语速非常慢"
    if speed <= 0.9:
        return "语速较慢"
    if speed <= 1.0:
        return "语速偏慢"
    if speed <= 1.2:
        return "语速偏快"
    if speed <= 1.4:
        return "语速较快"
    return "语速非常快"


def _build_user_content(style, speed):
    """把语速指令前置拼到其他风格指令之前：'语速***，{其它指令}'。"""
    speed_instr = _speed_to_instruction(speed)
    if not style:
        return speed_instr
    if not speed_instr:
        return style
    return f"{speed_instr}，{style}"


def synthesize(
    text,
    output_path,
    voice=None,
    mode=None,
    ref_audio=None,
    voice_design=None,
    controllable_clone=None,
    speed=None,
    model=None,
    api_key=None,
    ref_text=None,
    timeout=120,
    **kwargs,
):
    """调用 MiMo OpenAI 兼容接口合成语音并写入 output_path。"""
    mode = mode or "clone"
    api_key = _get_api_key(api_key)
    if not api_key:
        logger.error(
            "MiMoTTS: API key not configured "
            "(set sdk_extra_args.api_key or env MIMO_API_KEY)"
        )
        return False

    base_url = (kwargs.get("api_url") or BASE_URL).rstrip("/")
    timeout = float(timeout or 120)
    audio_format = "wav"

    messages = []
    audio = {"format": audio_format}

    if mode == "preset_voice":
        model_id = MODEL_PRESET
        audio["voice"] = voice or "mimo_default"
        # 语速指令前置拼到风格指令前，放入 user 消息
        user_content = _build_user_content(controllable_clone or "", speed)
        messages.append({"role": "user", "content": user_content})
        messages.append({"role": "assistant", "content": text})

    elif mode == "voice_design":
        model_id = MODEL_VOICEDESIGN
        design_prompt = voice_design or "A clear, natural, neutral voice."
        # 语速指令前置拼到音色设计描述前（无原生语速参数，用指令变相调速）
        user_content = _build_user_content(design_prompt, speed)
        messages.append({"role": "user", "content": user_content})
        # 直接传入目标文本，不做智能润色（保持字幕文本一致）
        messages.append({"role": "assistant", "content": text})

    elif mode in ("clone", "controllable_clone"):
        model_id = MODEL_VOICECLONE
        if not ref_audio or not os.path.exists(ref_audio):
            logger.error(f"MiMoTTS clone requires a valid ref_audio, got: {ref_audio}")
            return False
        audio["voice"] = _encode_audio_data_uri(ref_audio)
        # 克隆/可控克隆：语速指令前置拼到风格指令前；无指令时仅放语速指令（或空串）
        user_content = _build_user_content(controllable_clone or "", speed)
        messages.append({"role": "user", "content": user_content})
        messages.append({"role": "assistant", "content": text})

    else:
        logger.error(f"MiMoTTS: unsupported mode {mode}")
        return False

    payload = {
        "model": model or model_id,
        "messages": messages,
        "audio": audio,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        # 兼容部分 MiMo 文档使用自定义 api-key 头的部署；多余头对 OpenAI 兼容服务无害
        "api-key": api_key,
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=(10, timeout),
        )
        if resp.status_code != 200:
            logger.error(f"MiMoTTS API error {resp.status_code}: {resp.text[:300]}")
            return False
        data = resp.json()
        msg = data.get("choices", [{}])[0].get("message", {})
        audio_field = msg.get("audio")
        if not audio_field or not audio_field.get("data"):
            logger.error(f"MiMoTTS: no audio in response: {json.dumps(data)[:300]}")
            return False
        audio_bytes = base64.b64decode(audio_field["data"])
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(audio_bytes)
        logger.info(f"MiMoTTS synthesized {len(audio_bytes)} bytes -> {output_path}")
        return os.path.isfile(output_path) and os.path.getsize(output_path) > 0
    except requests.exceptions.RequestException as e:
        logger.error(f"MiMoTTS request failed: {e}")
        return False
    except Exception:
        logger.exception("MiMoTTS synthesis failed")
        return False


def list_voices():
    """返回预置音色列表（id/name/language/gender）。"""
    return PRESET_VOICES
