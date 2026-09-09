"""Music generation base class.

Design (mirrors the video/image generation factories):
- An interface is a named entry in musicgen_interfaces.json describing how to call a backend.
- The factory resolves an interface to a concrete engine (Generic HTTP / SDK bridge).
- Engines expose a single async/sync method:
      generate(prompt, output_dir, model="", mode="txt2music", api_key="", **kwargs) -> list[str]
  returning a list of local audio (and/or lyrics) file paths.

Music generation capabilities are expressed through MODES (see musicgen_interface_manager.MUSIC_MODES).
Each mode maps to a specific KieAI/Suno catalog model (see kieai_music_wrapper.MODE_CATALOG):
  txt2music        -> generate-music   (lyrics / text prompt, instrumental=false)
  instrumental     -> generate-music   (instrumental=true, no vocals)
  lyrics           -> generate-lyrics  (text -> song lyrics only)
  extend           -> extend-music     (continue an existing track by audioId)
  cover            -> upload-and-cover-audio  (style transfer / cover from a reference audio URL)
  add_instrumental -> add-instrumental (add accompaniment to an uploaded track)
  add_vocals       -> add-vocals       (add vocals to an uploaded track)
  separate         -> separate-vocals  (stem separation)
  to_wav           -> convert-to-wav   (transcode to WAV)
  upload_extend    -> upload-and-extend-audio (upload + extend)
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
