"""TTS base class: extensible interface for text-to-speech."""
from abc import ABC, abstractmethod
from typing import Optional


class TTSBase(ABC):
    """Abstract base class for TTS engines."""

    @abstractmethod
    def synthesize(self, text: str, output_path: str) -> bool:
        """Synthesize text to audio file. Returns True on success."""
        ...
