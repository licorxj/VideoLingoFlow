"""Qwen3-ASR engine: Alibaba Qwen team's speech recognition model.

Wraps the qwen_asr package (pip install qwen-asr).

Qwen3-ASR workflow:
  1. Qwen3ASRModel.from_pretrained(checkpoint, ...) → model
  2. results = model.transcribe(audio, language, ...)  → List[ASRTranscription]
  3. (Optional) Qwen3ForcedAligner for word-level timestamps

Models:
  - Qwen/Qwen3-ASR-0.6B  (lightweight)
  - Qwen/Qwen3-ASR-1.7B  (best quality)

Language names are English: Chinese, English, Japanese, Korean, etc.
"""

import os
import gc
import json
import threading
import warnings
import numpy as np
from typing import Callable, Optional, Dict, List, Any

from backend.asr.asr_base import ASRBase

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_MODEL = "Qwen/Qwen3-ASR-1.7B"
DEFAULT_DTYPE = "bfloat16"
# Qwen3-ASR language name mapping (ISO code -> English name)
_LANG_MAP = {
    "auto": None,
    # === Chinese & dialects ===
    # Qwen3-ASR natively supports "Chinese" and "Cantonese"
    "zh": "Chinese",
    "zh-yue-hk": "Cantonese",
    "zh-yue-gd": "Cantonese",
    "zh-wuu": "Chinese",
    "zh-min": "Chinese",
    "zh-anhui": "Chinese",
    "zh-dongbei": "Chinese",
    "zh-fujian": "Chinese",
    "zh-gansu": "Chinese",
    "zh-guizhou": "Chinese",
    "zh-hebei": "Chinese",
    "zh-henan": "Chinese",
    "zh-hubei": "Chinese",
    "zh-hunan": "Chinese",
    "zh-jiangxi": "Chinese",
    "zh-ningxia": "Chinese",
    "zh-shandong": "Chinese",
    "zh-shaanxi": "Chinese",
    "zh-shanxi": "Chinese",
    "zh-sichuan": "Chinese",
    "zh-tianjin": "Chinese",
    "zh-yunnan": "Chinese",
    "zh-zhejiang": "Chinese",
    # === Major languages ===
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "pt": "Portuguese",
    "ru": "Russian",
    "ar": "Arabic",
    "it": "Italian",
    "nl": "Dutch",
    "pl": "Polish",
    "tr": "Turkish",
    "vi": "Vietnamese",
    "th": "Thai",
    "id": "Indonesian",
    "hi": "Hindi",
    "ms": "Malay",
    # === Nordic ===
    "sv": "Swedish",
    "da": "Danish",
    "fi": "Finnish",
    "no": "Swedish",
    "nb": "Swedish",
    # === Central/Eastern European ===
    "cs": "Czech",
    "el": "Greek",
    "hu": "Hungarian",
    "ro": "Romanian",
    "uk": "Russian",
    "sk": "Czech",
    "hr": "Czech",
    "bg": "Russian",
    "sr": "Russian",
    "sl": "Czech",
    "lt": "Russian",
    "lv": "Russian",
    "et": "Finnish",
    # === Other ===
    "bn": "Hindi",
    "fa": "Persian",
    "tl": "Filipino",
    "mk": "Macedonian",
    "ca": "Spanish",
    "he": "Arabic",
}


class Qwen3ASRLocal(ASRBase):
    """Local Qwen3-ASR engine.

    Supports model selection (0.6B / 1.7B), language, dtype, forced alignment
    for word-level timestamps.
    """

    # 类级别锁：确保同一时间只有一个任务使用本地模型进行推理
    _inference_lock = threading.Lock()

    def __init__(self):
        self._model_dir = os.environ.get(
            "HF_HOME",
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))), "_model_cache"),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def transcribe(
        self,
        input_path: str,
        output_path: str,
        callback: Optional[Callable] = None,
        *,
        model: str = DEFAULT_MODEL,
        language: Optional[str] = None,
        dtype: str = DEFAULT_DTYPE,
        word_timestamps: bool = True,
        context: str = "",
        device_map: str = "auto",
        aligner_model: Optional[str] = None,
        **kwargs,
    ) -> dict:
        """Transcribe audio/video and save JSON result.

        Parameters
        ----------
        input_path : str   Path to audio/video file.
        output_path : str  Path to write JSON result.
        callback : callable  (percent, message) progress callback.
        model : str  Model name or local path (e.g. "Qwen/Qwen3-ASR-1.7B").
        language : str | None  ISO language code (zh/en/ja/...) or None for auto.
        dtype : str  "bfloat16" / "float16" / "float32".
        word_timestamps : bool  Enable forced alignment for word-level timestamps.
        context : str  Optional context/prompt text.
        device_map : str  Device mapping for model loading.
        aligner_model : str | None  ForcedAligner checkpoint (enables timestamps).
        """
        from qwen_asr import Qwen3ASRModel

        if callback:
            callback(5, "Preparing Qwen3-ASR...")

        # Resolve model path
        model_name = self._resolve_model(model)

        # Map language
        qwen_lang = self._map_language(language)

        # Resolve torch dtype
        import torch
        torch_dtype = self._resolve_dtype(dtype)

        # Build backend kwargs
        backend_kwargs = {
            "device_map": device_map,
            "dtype": torch_dtype,
        }

        # Determine aligner
        use_aligner = word_timestamps
        aligner_ckpt = None
        if use_aligner:
            aligner_ckpt = aligner_model or self._resolve_model("Qwen/Qwen3-ForcedAligner-0.6B")

        if callback:
            callback(15, f"Loading model '{model_name}'...")

        # 使用类级别锁确保同一时间只有一个任务使用本地模型进行推理
        # 多个工作流并行运行时，其他任务会在此处排队等待
        with Qwen3ASRLocal._inference_lock:
            if callback:
                callback(20, "Local model acquired, loading...")

            try:
                asr_model = Qwen3ASRModel.from_pretrained(
                    model_name,
                    forced_aligner=aligner_ckpt if use_aligner else None,
                    **backend_kwargs,
                )
            except Exception as e:
                raise RuntimeError(f"Failed to load Qwen3-ASR model '{model_name}': {e}")

            if callback:
                callback(40, "Transcribing audio...")

            try:
                results = asr_model.transcribe(
                    audio=input_path,
                    language=qwen_lang,
                    context=context,
                    return_time_stamps=use_aligner,
                )
            except Exception as e:
                del asr_model
                gc.collect()
                raise RuntimeError(f"Qwen3-ASR transcription failed: {e}")

            # Free model
            del asr_model
            gc.collect()
            try:
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

        if callback:
            callback(80, "Processing results...")

        # Parse results
        output = self._build_output(results, input_path)

        # Save
        if callback:
            callback(90, "Saving results...")
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        if callback:
            callback(100, f"ASR done - {len(output['segments'])} segments")
        return output

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_model(self, model: str) -> str:
        """Return local model path if exists, else the model name for HF download.
        
        Handles both direct paths and HuggingFace cache directory structure:
        - Direct: _model_cache/Qwen/Qwen3-ASR-0.6B/
        - HF cache: _model_cache/hub/models--Qwen--Qwen3-ASR-0.6B/snapshots/<sha>/
        """
        # 1. Check direct path
        local_path = os.path.join(self._model_dir, model)
        if os.path.isdir(local_path):
            return os.path.abspath(local_path)
        
        # 2. Check HF cache structure: models--repo--name -> snapshots/<sha>/
        # Convert "Qwen/Qwen3-ASR-0.6B" to "models--Qwen--Qwen3-ASR-0.6B"
        parts = model.split("/")
        if len(parts) >= 2:
            hf_dir = os.path.join(self._model_dir, "hub", "models--" + "--".join(parts))
            snapshots = os.path.join(hf_dir, "snapshots")
            if os.path.isdir(snapshots):
                for sha_dir in os.listdir(snapshots):
                    full = os.path.join(snapshots, sha_dir)
                    if os.path.isdir(full) and os.path.isfile(os.path.join(full, "config.json")):
                        return os.path.abspath(full)
        
        return model

    @staticmethod
    def _map_language(language: Optional[str]) -> Optional[str]:
        """Map ISO language code to Qwen3-ASR language name."""
        if not language or language == "auto":
            return None
        lang = language.strip().lower()
        return _LANG_MAP.get(lang, language)

    @staticmethod
    def _resolve_dtype(dtype_str: str):
        """Convert dtype string to torch dtype."""
        import torch
        s = dtype_str.strip().lower()
        if s in ("bf16", "bfloat16"):
            return torch.bfloat16
        if s in ("fp16", "float16", "half"):
            return torch.float16
        if s in ("fp32", "float32"):
            return torch.float32
        return torch.bfloat16

    @staticmethod
    def _build_output(results: list, input_path: str) -> dict:
        """Convert Qwen3-ASR results to standardized output format.

        Output format:
        {
            "language": "Chinese",
            "text": "full text",
            "segments": [
                {
                    "id": 1,
                    "start": 0.0,
                    "end": 2.5,
                    "text": "segment text",
                    "words": [
                        {"word": "token", "start": 0.1, "end": 0.5},
                        ...
                    ]
                }
            ]
        }
        """
        if not results:
            return {"segments": [], "language": "", "text": ""}

        r = results[0]
        full_text = getattr(r, "text", "") or ""
        detected_lang = getattr(r, "language", "") or ""

        segments = []
        words_out = []

        # Extract forced alignment timestamps if available
        ts = getattr(r, "time_stamps", None)
        if ts and hasattr(ts, "items") and ts.items:
            # Group alignment items into segments by sentence boundaries
            current_seg_words = []
            current_start = None

            for item in ts.items:
                word_text = getattr(item, "text", "") or ""
                start_t = getattr(item, "start_time", 0.0)
                end_t = getattr(item, "end_time", 0.0)

                word_entry = {"word": word_text, "start": round(start_t, 3), "end": round(end_t, 3)}
                words_out.append(word_entry)
                current_seg_words.append(word_entry)

                if current_start is None:
                    current_start = start_t

                # Split segment on sentence-ending punctuation
                if word_text and word_text[-1] in ".!?\u3002\uff01\uff1f":
                    seg_text = " ".join(w["word"] for w in current_seg_words)
                    # For CJK, join without spaces
                    if detected_lang and detected_lang.lower() in ("chinese", "japanese", "cantonese"):
                        seg_text = "".join(w["word"] for w in current_seg_words)

                    segments.append({
                        "id": len(segments) + 1,
                        "start": round(current_start, 3),
                        "end": round(end_t, 3),
                        "text": seg_text.strip(),
                        "words": list(current_seg_words),
                    })
                    current_seg_words = []
                    current_start = None

            # Flush remaining words as last segment
            if current_seg_words:
                seg_text = "".join(w["word"] for w in current_seg_words)
                if detected_lang and detected_lang.lower() not in ("chinese", "japanese", "cantonese"):
                    seg_text = " ".join(w["word"] for w in current_seg_words)

                segments.append({
                    "id": len(segments) + 1,
                    "start": round(current_start or 0, 3),
                    "end": round(current_seg_words[-1]["end"], 3),
                    "text": seg_text.strip(),
                    "words": list(current_seg_words),
                })
        else:
            # No timestamps - create a single segment from full text
            segments.append({
                "id": 1,
                "start": 0.0,
                "end": 0.0,
                "text": full_text,
            })

        return {
            "language": detected_lang,
            "text": full_text,
            "segments": segments,
        }