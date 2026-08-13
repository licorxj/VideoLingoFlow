"""Separation base class: extensible interface for vocal/instrument separation."""
from abc import ABC, abstractmethod
from typing import Callable, Optional


class SeparationBase(ABC):
    """Abstract base class for audio separation engines.

    All engines must implement separate(). Optional kwargs allow engines
    to accept extra configuration (model, format, segment, etc.) without
    breaking the base contract.
    """

    @abstractmethod
    def separate(
        self,
        input_path: str,
        output_dir: str,
        callback: Optional[Callable] = None,
        **kwargs,
    ) -> dict:
        """Separate vocals from background music.

        Parameters
        ----------
        input_path : str   Path to input audio file.
        output_dir : str   Directory to write separated audio files.
        callback : callable  (percent: int, message: str) progress callback.
        **kwargs : Extra engine-specific options (model, format, etc.)

        Returns
        -------
        dict  {"vocals": path, "background": path}
        """
        ...
