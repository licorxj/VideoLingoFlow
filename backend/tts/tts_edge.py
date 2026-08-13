"""Edge TTS engine implementation."""
import asyncio
from backend.tts.tts_base import TTSBase
from backend.config.config_manager import config


class EdgeTTS(TTSBase):
    """Microsoft Edge TTS (free)."""

    def synthesize(self, text: str, output_path: str) -> bool:
        voice = config.get("tts.edge_tts.voice") or "zh-CN-YunjianNeural"
        try:
            import edge_tts
            communicate = edge_tts.Communicate(text, voice)
            asyncio.run(communicate.save(output_path))
            return True
        except ImportError:
            # Fallback: create silence
            from pydub import AudioSegment
            silence = AudioSegment.silent(duration=max(100, len(text) * 50))
            silence.export(output_path, format="wav")
            return True
