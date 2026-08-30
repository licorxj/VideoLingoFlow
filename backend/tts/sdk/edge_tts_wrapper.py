"""Edge TTS SDK wrapper for voice listing."""
import asyncio
import logging

logger = logging.getLogger(__name__)

# 云端 API，不占本地 GPU（与 ASR 的 CLOUD 标记一致）
CLOUD = True


def list_voices(api_key=None):
    """Fetch all available voices from Edge TTS.
    
    Returns:
        list[dict]: Voice objects with voice_id, voice_name, description, gender, age, language
    """
    try:
        import edge_tts
        raw = asyncio.run(edge_tts.list_voices())
    except Exception as e:
        logger.error(f"Edge TTS list_voices failed: {e}")
        return []

    voices = []
    for v in raw:
        short_name = v.get("ShortName", "")
        gender = v.get("Gender", "").lower()  # "Male" / "Female"
        locale = v.get("Locale", "")  # "zh-CN", "en-US", etc.
        friendly_name = v.get("FriendlyName", "")

        voices.append({
            "voice_id": short_name,
            "voice_name": friendly_name,
            "description": "",
            "gender": gender,
            "age": "",
            "language": locale,
        })

    logger.info(f"Edge TTS list_voices: fetched {len(voices)} voices")
    return voices
