"""Music generation base class.

Design (mirrors the video/image generation factories):
- An interface is a named entry in musicgen_interfaces.json describing how to call a backend.
- The factory resolves an interface to a concrete engine (Generic HTTP / SDK bridge).
- Engines expose a single async/sync method:
      generate(prompt, output_dir, model="", mode="txt2music", api_key="", **kwargs) -> list[str]
  returning a list of local audio (and/or lyrics) file paths.

Music generation capabilities are expressed through MODES (see musicgen_interface_manager.MUSIC_MODES).
Each mode maps to a KieAI/Suno official "ai-music-api/*" operation (unified
createTask/recordInfo flow, see kieai_music_wrapper.MODE_OPS + kieai/suno.py):
  txt2music        -> ai-music-api/generate               (custom_mode / lyrics)
  instrumental     -> ai-music-api/generate               (instrumental=true)
  lyrics           -> ai-music-api/generate-lyrics        (text -> lyrics only)
  extend           -> ai-music-api/extend                 (continue by audio_id)
  cover            -> ai-music-api/upload-and-cover-audio (style transfer from audio/task)
  add_instrumental -> ai-music-api/add-instrumental       (add accompaniment)
  add_vocals       -> ai-music-api/add-vocals             (add vocals)
  separate         -> ai-music-api/separate-vocals        (stem separation)
  to_wav           -> ai-music-api/convert-to-wav-format  (transcode to WAV)
  upload_extend    -> ai-music-api/upload-and-extend-audio(upload + extend)
"""
from typing import List


class MusicGenBase:
    """Abstract base for all music generation engines."""

    def __init__(self, config: dict):
        self.config = config or {}

    def generate(
        self,
        prompt: str,
        output_dir: str,
        model: str = "",
        mode: str = "txt2music",
        api_key: str = "",
        **kwargs,
    ) -> List[str]:
        """Generate music and return a list of local file paths.

        Args:
            prompt: textual description / lyrics / theme.
            output_dir: directory to write output files into.
            model: backend model identifier (e.g. "V5_5" for Suno).
            mode: one of MUSIC_MODES (txt2music, instrumental, lyrics, extend,
                  cover, add_instrumental, add_vocals, separate, to_wav, upload_extend).
            api_key: provider API key override.
            **kwargs: mode-specific params (style, title, instrumental, negative_tags,
                      vocal_gender, duration, audio_id, task_id, upload_url, audio_path,
                      continue_at, stem_type, persona_id, weights...).
        """
        raise NotImplementedError("Subclasses must implement generate()")
