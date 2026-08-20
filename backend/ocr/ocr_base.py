"""OCR base class: extensible interface for optical character recognition."""
from abc import ABC, abstractmethod
from typing import Callable, Optional, Union


class OCRBase(ABC):
    """Abstract base class for OCR engines.

    All engines must implement recognize(). Optional kwargs allow engines
    to accept extra configuration (engine_type, ocr_version, model_type, etc.)
    without breaking the base contract.
    """

    @abstractmethod
    def recognize(
        self,
        input_path: Union[str, "np.ndarray"],
        callback: Optional[Callable] = None,
        **kwargs,
    ) -> dict:
        """Recognize text in an image.

        Parameters
        ----------
        input_path : str | np.ndarray
            图片文件路径，或内存中的图片数组（BGR ndarray），
            便于批量流水线直接传入裁剪后的 ROI。
        callback : callable  (percent: int, message: str) progress callback.
        **kwargs : Extra engine-specific options (use_det, use_cls, use_rec, ...).

        Returns
        -------
        dict  {"txts": [...], "boxes": [[[x,y],...], ...], "scores": [...], "elapse": float}
        """
        ...

    def unload(self) -> None:
        """释放引擎实例并归还内存/显存。空闲自动卸载时由注册表调用，子类可覆写。"""
        ...
