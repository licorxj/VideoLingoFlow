"""ASR implementations for cloud engines."""
import os
import json
from typing import Callable, Optional
from backend.asr.asr_base import ASRBase


class WhisperX302(ASRBase):
    """302.ai cloud WhisperX ASR."""
    def transcribe(self, input_path: str, output_path: str, callback: Optional[Callable] = None, **kwargs) -> dict:
        # TODO: Integrate with core/all_whisper_methods/whisperX_302.py
        if callback:
            callback(50, "Cloud ASR not yet integrated")
        from backend.asr.asr_whisperx import WhisperXLocal
        return WhisperXLocal().transcribe(input_path, output_path, callback, **kwargs)