"""WhisperX local ASR engine – real SDK integration.

WhisperX workflow:
  1. load_model(whisper_arch, device, ...) -> FasterWhisperPipeline
  2. audio = load_audio(file) / load audio numpy array
  3. result = model.transcribe(audio, batch_size, ...)  -> {"segments": [...], "language": "xx"}
  4. align_model, metadata = load_align_model(language, device)
  5. result = align(segments, align_model, metadata, audio, device)
  6. [Optional] diarize: DiarizationPipeline -> assign_word_speakers
  7. Free GPU memory
"""

import os
import gc
import json
import subprocess
import threading
import warnings
import sys
from typing import Callable, Optional, Dict, List

import numpy as np

from backend.asr.asr_base import ASRBase

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "large-v3"
DEFAULT_COMPUTE_TYPE = "float16"
DEFAULT_BATCH_SIZE = 16
DEFAULT_VAD_OPTIONS = {"vad_onset": 0.500, "vad_offset": 0.363}
DEFAULT_ASR_OPTIONS = {"temperatures": [0], "initial_prompt": ""}


class WhisperXLocal(ASRBase):
    """Local WhisperX ASR engine.

    Supports all whisperX parameters: model selection, language, VAD options,
    ASR options, compute type, batch size, alignment, word-level timestamps,
    and speaker diarization.
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
        batch_size: Optional[int] = None,
        compute_type: str = DEFAULT_COMPUTE_TYPE,
        word_timestamps: bool = True,
        vad_options: Optional[dict] = None,
        asr_options: Optional[dict] = None,
        align_model_name: Optional[str] = None,
        diarize: bool = False,
        diarize_model: Optional[str] = None,
        hf_token: Optional[str] = None,
        num_speakers: Optional[int] = None,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
    ) -> dict:
        """Transcribe audio/video and save JSON result.

        Parameters
        ----------
        input_path : str   Path to video or audio file.
        output_path : str  Path to write JSON result.
        callback : callable  (percent: int, message: str) progress callback.
        model : str  Whisper model name or local path.
        language : str | None  Language code, None = auto-detect.
        batch_size : int | None  Inference batch size (auto by GPU mem if None).
        compute_type : str  "float16" / "int8" / "float32".
        word_timestamps : bool  Enable phoneme alignment for word timestamps.
        vad_options : dict  VAD onset/offset overrides.
        asr_options : dict  Extra ASR options passed to load_model.
        align_model_name : str | None  Override alignment model name.
        diarize : bool  Enable speaker diarization.
        diarize_model : str | None  Override diarization model name.
        hf_token : str | None  HuggingFace token for gated pyannote models.
        num_speakers : int | None  Exact number of speakers (if known).
        min_speakers : int | None  Minimum speakers for diarization.
        max_speakers : int | None  Maximum speakers for diarization.
        """
        # --- Suppress non-fatal third-party warnings that confuse users ---
        warnings.filterwarnings("ignore", message="torchcodec is not installed correctly")
        warnings.filterwarnings("ignore", message=".*upgraded your loaded checkpoint.*")
        warnings.filterwarnings("ignore", message=".*TensorFloat-32.*reproducibility.*")

        import whisperx
        import torch

        if callback:
            callback(5, "Preparing WhisperX...")

        device = "cuda" if torch.cuda.is_available() else "cpu"
        if batch_size is None:
            if device == "cuda":
                gpu_mem = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
                batch_size = 16 if gpu_mem > 8 else 2
            else:
                batch_size = 1

        # GPU memory-aware batch_size safety guard (prevent OOM)
        if device == "cuda" and diarize:
            total_mem = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            safe_batch = 8 if total_mem <= 8 else (12 if total_mem <= 12 else 16)
            if batch_size > safe_batch:
                print(f"[WhisperX] Batch size capped: {batch_size} -> {safe_batch} (GPU={total_mem:.1f}GB, diarize enabled)", flush=True)
                batch_size = safe_batch

        # --- Resolve model path (local cache or HuggingFace) ---
        # For Chinese language, use Belle-whisper model with better punctuation
        if language and language.lower() in ("zh", "chinese"):
            belle_model = "Belle-whisper-large-v3-zh-punct-fasterwhisper"
            belle_path = os.path.join(self._model_dir, belle_model)
            if os.path.isdir(belle_path):
                model_name = belle_path
                print(f"[WhisperX] Using Chinese-optimized model: {belle_model}")
            else:
                model_name = self._resolve_model(model)
        else:
            model_name = self._resolve_model(model)

        # --- Step 1: Extract / load audio ---
        if callback:
            callback(10, "Loading audio...")
        audio = self._load_audio(input_path, whisperx)

        # --- Step 2: Build VAD & ASR options ---
        vad_opts = {**DEFAULT_VAD_OPTIONS, **(vad_options or {})}
        asr_opts = {**DEFAULT_ASR_OPTIONS, **(asr_options or {})}
        whisper_language = None if (not language or language == "auto") else language

        # 使用类级别锁确保同一时间只有一个任务使用本地模型进行推理
        # 多个工作流并行运行时，其他任务会在此处排队等待
        with WhisperXLocal._inference_lock:
            # --- Step 3: Load transcription model ---
            if callback:
                callback(20, f"Local model acquired, loading '{model_name}' on {device}...")
            try:
                asr_model = whisperx.load_model(
                    whisper_arch=model_name,
                    device=device,
                    compute_type=compute_type,
                    language=whisper_language,
                    vad_options=vad_opts,
                    asr_options=asr_opts,
                    download_root=self._model_dir,
                )
            except Exception as e:
                raise RuntimeError(f"Failed to load WhisperX model '{model_name}': {e}")

            # --- Step 4: Transcribe ---
            if callback:
                callback(40, "Transcribing audio...")
            result = asr_model.transcribe(
                audio, batch_size=batch_size, print_progress=True
            )

            detected_language = result.get("language", "en")
            if callback:
                callback(60, f"Detected language: {detected_language}")

            # Free transcription model
            del asr_model
            gc.collect()
            self._clear_cuda_cache()

            # --- Step 5: Alignment (word-level timestamps) ---
            if word_timestamps and result.get("segments"):
                if callback:
                    callback(70, "Aligning timestamps...")

                def _do_align():
                    """Load align model and align."""
                    align_lang = detected_language
                    # 复用 alignment_processor 的加载逻辑：先本地 _model_cache/hub 缓存，
                    # 无缓存时自动下载到该目录，避免因 cache_dir 指向错误导致联网卡住
                    from backend.asr.alignment_processor import WhisperXAlignmentProcessor
                    processor = WhisperXAlignmentProcessor(
                        model_name=align_model_name,
                        model_dir=self._model_dir,
                    )
                    align_model, metadata = processor._load_align_model(align_lang, device)
                    aligned = whisperx.align(
                        result["segments"],
                        align_model,
                        metadata,
                        audio,
                        device,
                        return_char_alignments=False,
                    )
                    aligned["language"] = align_lang
                    del align_model
                    gc.collect()
                    self._clear_cuda_cache()
                    return aligned

                _aligned_ok = False
                try:
                    result = _do_align()
                    _aligned_ok = True
                except Exception as e:
                    err_str = str(e)
                    # If the model file is corrupted, delete it and retry once
                    is_corrupt = "PytorchStreamReader" in err_str or "failed finding central directory" in err_str
                    if is_corrupt:
                        corrupted = os.path.join(self._model_dir, "wav2vec2_fairseq_base_ls960_asr_ls960.pth")
                        if os.path.exists(corrupted):
                            os.remove(corrupted)
                            print(f"[WhisperX] Deleted corrupted alignment model: {corrupted}", flush=True)
                        try:
                            result = _do_align()
                            _aligned_ok = True
                        except Exception as e2:
                            warnings.warn(f"Alignment failed after retry (keeping segment-level timestamps): {e2}")
                    else:
                        warnings.warn(f"Alignment failed (keeping segment-level timestamps): {e}")

            # --- Step 6: Speaker diarization ---
            speakers_found: List[str] = []
            if diarize and result.get("segments"):
                if callback:
                    callback(80, "Running speaker diarization...")
                try:
                    diarize_df = self._run_diarization(
                        whisperx, audio, device,
                        diarize_model=diarize_model,
                        hf_token=hf_token,
                        num_speakers=num_speakers,
                        min_speakers=min_speakers,
                        max_speakers=max_speakers,
                    )
                    if diarize_df is not None and len(diarize_df) > 0:
                        result = whisperx.assign_word_speakers(diarize_df, result)
                        # Collect unique speakers
                        speakers_set = set()
                        for seg in result.get("segments", []):
                            spk = seg.get("speaker")
                            if spk:
                                speakers_set.add(spk)
                        speakers_found = sorted(speakers_set)
                        print(f"[WhisperX] Diarization complete - {len(speakers_found)} speaker(s): {speakers_found}")
                    else:
                        warnings.warn("Diarization returned empty result")
                except Exception as e:
                    warnings.warn(f"Diarization failed (proceeding without speaker labels): {e}")

        # --- Step 7: Build output ---
        if callback:
            callback(90, "Saving results...")
        output = self._build_output(result, detected_language, speakers=speakers_found)

        # Mark that VAD was executed internally (integrated in whisper.transcribe)
        # This prevents redundant VAD in post-processing
        output["_vad_internally_executed"] = True
        output["_alignment_internally_executed"] = word_timestamps and bool(result.get("segments"))

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        if callback:
            callback(100, f"ASR done - {len(output['segments'])} segments"
                     + (f", {len(speakers_found)} speakers" if speakers_found else ""))
        return output

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_model(self, model: str) -> str:
        """Return local model path if exists, else the model name for HF download."""
        local_path = os.path.join(self._model_dir, model)
        if os.path.isdir(local_path):
            return os.path.abspath(local_path)
        return model

    @staticmethod
    def _load_audio(input_path: str, whisperx) -> np.ndarray:
        """Load audio from any media file via whisperx.load_audio (uses ffmpeg internally)."""
        return whisperx.load_audio(input_path)

    def _run_diarization(self, whisperx, audio: np.ndarray, device: str,
                         *, diarize_model=None, hf_token=None,
                         num_speakers=None, min_speakers=None,
                         max_speakers=None):
        """Run pyannote speaker diarization via whisperx.diarize.DiarizationPipeline.

        Prefers a locally cached model under _model_cache/hub/ to avoid
        network downloads or gated-model authentication.

        Returns a DataFrame with columns [segment, label, speaker, start, end].
        """
        from whisperx.diarize import DiarizationPipeline

        cache_dir = self._model_dir
        # Check for locally-cached model (HF Hub cache structure)
        local_model = os.path.join(
            cache_dir, "hub", "models--pyannote--speaker-diarization-community"
        )
        if os.path.isdir(local_model) and os.path.isfile(os.path.join(local_model, "config.yaml")):
            diarize_model_name = local_model
            hf_token = None  # no token needed for local files
        else:
            diarize_model_name = diarize_model or os.environ.get(
                "WHISPERX_DIARIZE_MODEL", "pyannote/speaker-diarization-community-1"
            )
            if not hf_token:
                hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")

        diarize_pipeline = DiarizationPipeline(
            model_name=diarize_model_name,
            token=hf_token,
            device=device,
            cache_dir=cache_dir,
        )

        diarize_kwargs = {}
        if num_speakers is not None:
            diarize_kwargs["num_speakers"] = num_speakers
        if min_speakers is not None:
            diarize_kwargs["min_speakers"] = min_speakers
        if max_speakers is not None:
            diarize_kwargs["max_speakers"] = max_speakers

        diarize_df = diarize_pipeline(audio, **diarize_kwargs)
        return diarize_df

    @staticmethod
    def _clear_cuda_cache():
        try:
            import torch as _t
            if _t.cuda.is_available():
                _t.cuda.empty_cache()
        except Exception:
            pass

    @staticmethod
    def _build_output(result: dict, language: str, speakers: Optional[List[str]] = None) -> dict:
        """Normalize whisperX result into a consistent JSON structure.

        Output format:
        {
            "language": "zh",
            "speakers": ["SPEAKER_00", "SPEAKER_01"],
            "segments": [
                {
                    "id": 1,
                    "start": 0.0,
                    "end": 2.5,
                    "text": "Hello world",
                    "speaker": "SPEAKER_00",
                    "words": [
                        {"word": "Hello", "start": 0.0, "end": 1.2, "score": 0.98, "speaker": "SPEAKER_00"},
                        ...
                    ]
                }
            ]
        }
        """
        output: Dict[str, any] = {"segments": [], "language": language}
        if speakers:
            output["speakers"] = speakers

        for idx, seg in enumerate(result.get("segments", []), start=1):
            entry = {
                "id": idx,
                "start": round(float(seg.get("start", 0)), 3),
                "end": round(float(seg.get("end", 0)), 3),
                "text": (seg.get("text") or "").strip(),
            }
            # Include speaker label if diarization was run
            if "speaker" in seg:
                entry["speaker"] = seg["speaker"]

            # Include word-level timestamps if available
            words = seg.get("words", [])
            if words:
                entry["words"] = []
                for w in words:
                    word_entry = {"word": (w.get("word") or "").strip()}
                    if "start" in w:
                        word_entry["start"] = round(float(w["start"]), 3)
                    if "end" in w:
                        word_entry["end"] = round(float(w["end"]), 3)
                    if "score" in w:
                        word_entry["score"] = round(float(w["score"]), 4)
                    if "speaker" in w:
                        word_entry["speaker"] = w["speaker"]
                    entry["words"].append(word_entry)

            output["segments"].append(entry)

        return output