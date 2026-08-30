#!/usr/bin/env python3
"""MiniMax TTS SDK wrapper - bridges MiniMax T2A API to the project TTS SDK interface."""
import os
import requests
import logging
import tempfile

logger = logging.getLogger(__name__)

# 云端 API，不占本地 GPU（与 ASR 的 CLOUD 标记一致）
CLOUD = True

# Default configuration
CONFIG = {
    "api_url": "https://api.minimaxi.com/v1/t2a_v2",
    "model": "speech-2.8-hd",
    "default_voice": "male-qn-qingse",
}


def synthesize(text, output_path, voice=None, speed=None, model=None,
               api_key=None, **kwargs):
    """
    Synthesize speech using MiniMax T2A API.

    Args:
        text: Text to synthesize
        output_path: Output audio file path
        voice: Voice ID (e.g., 'male-qn-qingse')
        speed: Speech speed (0.5-2.0)
        model: Model name (e.g., 'speech-2.8-hd')
        api_key: MiniMax API key
        **kwargs: Additional parameters (vol, pitch, emotion, language_boost, etc.)

    Returns:
        bool: True if synthesis succeeded
    """
    if not api_key:
        api_key = os.environ.get("MINIMAX_API_KEY", "")

    if not api_key:
        logger.error("MiniMax TTS: API key not configured. Set MINIMAX_API_KEY environment variable.")
        return False

    api_url = kwargs.get("api_url", CONFIG["api_url"])
    model = model or CONFIG["model"]
    voice = voice or CONFIG["default_voice"]

    # Build request body
    body = {
        "model": model,
        "text": text,
        "stream": False,
        "voice_setting": {
            "voice_id": voice,
            "speed": speed if speed and 0.5 <= speed <= 2.0 else 1.0,
            "vol": kwargs.get("vol", 1),
            "pitch": kwargs.get("pitch", 0),
        },
        "audio_setting": {
            "sample_rate": kwargs.get("sample_rate", 32000),
            "bitrate": kwargs.get("bitrate", 128000),
            "format": kwargs.get("format", "mp3"),
            "channel": kwargs.get("channel", 1),
        },
        "output_format": "hex",
    }

    # Optional voice setting fields
    emotion = kwargs.get("emotion")
    if emotion:
        body["voice_setting"]["emotion"] = emotion

    text_normalization = kwargs.get("text_normalization")
    if text_normalization is not None:
        body["voice_setting"]["text_normalization"] = text_normalization

    # Optional language boost
    language_boost = kwargs.get("language_boost")
    if language_boost:
        body["language_boost"] = language_boost

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        logger.info(f"MiniMax TTS: synthesizing with model={model}, voice={voice}")
        resp = requests.post(api_url, json=body, headers=headers, timeout=120)

        if resp.status_code != 200:
            logger.error(f"MiniMax TTS: HTTP {resp.status_code} - {resp.text[:300]}")
            return False

        result = resp.json()

        # Check API response status
        base_resp = result.get("base_resp", {})
        status_code = base_resp.get("status_code", -1)
        if status_code != 0:
            logger.error(f"MiniMax TTS: API error {status_code} - {base_resp.get('status_msg', '')}")
            return False

        # Extract audio data
        data = result.get("data", {})
        audio_hex = data.get("audio", "")
        if not audio_hex:
            logger.error("MiniMax TTS: No audio data in response")
            return False

        # Decode hex audio and save
        audio_bytes = bytes.fromhex(audio_hex)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        with open(output_path, "wb") as f:
            f.write(audio_bytes)

        audio_length = result.get("extra_info", {}).get("audio_length", 0)
        logger.info(f"MiniMax TTS: synthesis complete, duration={audio_length}ms, saved to {output_path}")
        return True

    except requests.exceptions.Timeout:
        logger.error("MiniMax TTS: request timeout")
        return False
    except Exception as e:
        logger.error(f"MiniMax TTS error: {e}")
        import traceback
        traceback.print_exc()
        return False


def list_voices(api_key=None):
    """Fetch all voices from MiniMax get_voice API.
    
    Args:
        api_key: MiniMax API key (Bearer token)
    
    Returns:
        list[dict]: Voice objects with voice_id, voice_name, description, gender, age, language
    """
    if not api_key:
        api_key = os.environ.get("MINIMAX_API_KEY", "")
    if not api_key:
        logger.warning("MiniMax list_voices: no API key, returning empty list")
        return []

    url = "https://api.minimaxi.com/v1/get_voice"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {"voice_type": "all"}

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        base_resp = data.get("base_resp", {})
        if base_resp.get("status_code", -1) != 0:
            logger.error(f"MiniMax list_voices: API error - {base_resp.get('status_msg', '')}")
            return []

        voices = []
        # Parse system voices (preset voices with full metadata)
        for v in data.get("system_voice", []):
            desc = v.get("description", [])
            voices.append({
                "voice_id": v.get("voice_id", ""),
                "voice_name": v.get("voice_name", ""),
                "description": desc[0] if isinstance(desc, list) and desc else str(desc) if desc else "",
                "gender": "",
                "age": "",
                "language": "",
            })

        # Parse cloned voices
        for v in data.get("voice_cloning", []):
            voices.append({
                "voice_id": v.get("voice_id", ""),
                "voice_name": "",
                "description": "",
                "gender": "",
                "age": "",
                "language": "",
            })

        # Parse generated voices
        for v in data.get("voice_generation", []):
            voices.append({
                "voice_id": v.get("voice_id", ""),
                "voice_name": "",
                "description": "",
                "gender": "",
                "age": "",
                "language": "",
            })

        logger.info(f"MiniMax list_voices: fetched {len(voices)} voices")
        return voices

    except Exception as e:
        logger.error(f"MiniMax list_voices failed: {e}")
        return []
