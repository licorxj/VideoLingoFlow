"""FunASR Nano local ASR engine.

Models:
  - FunAudioLLM/Fun-ASR-Nano-2512    (Chinese, English, Japanese)
  - FunAudioLLM/Fun-ASR-MLT-Nano-2512 (Multi-language, 30+ languages)

Uses funasr.AutoModel with trust_remote_code=True.
Supports: hotwords, VAD, speaker diarization, ITN, sentence timestamps.
Auto-downloads model via modelscope.snapshot_download if not cached.

Speaker diarization requires spk_model="cam++" at construction time.
"""

import os
import gc
import json
import subprocess
import sys
import threading
import time
from typing import Callable, Optional, Dict, List, Any

from backend.asr.asr_base import ASRBase

# ---------------------------------------------------------------------------
# Windows 兼容：funasr 加载模型时若检测到 requirements.txt 会用 PATH 里的裸
# `pip` 启动子进程安装依赖。Windows 上 shutil.which("pip") 常解析到微软商店
# stub（%LOCALAPPDATA%\Microsoft\WindowsApps\pip.exe），CreateProcess 直接
# 报 PermissionError: [WinError 5] 拒绝访问。这里将其改为
# `sys.executable -m pip`（venv 内 pip，必然可执行）。
# ---------------------------------------------------------------------------
_pip_patched = False


def _patch_funasr_pip_install() -> None:
    global _pip_patched
    if _pip_patched:
        return
    try:
        from funasr.utils import install_model_requirements as _imr
        if not getattr(_imr, "_videoLingo_patched", False):
            def pip_install_r_fixed(requirements_path):
                cmd = [sys.executable, "-m", "pip", "install", "-r", str(requirements_path)]
                return subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            _imr.pip_install_r = pip_install_r_fixed
            _imr._videoLingo_patched = True
        _pip_patched = True
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_MODEL = "FunAudioLLM/Fun-ASR-MLT-Nano-2512"
MODELSCOPE_CACHE = os.environ.get(
    "MODELSCOPE_CACHE",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "_model_cache"),
)

# Model ID -> supported language names
_MODEL_LANGUAGES: Dict[str, List[str]] = {
    "FunAudioLLM/Fun-ASR-Nano-2512": ["中文", "英文", "日文"],
    "FunAudioLLM/Fun-ASR-MLT-Nano-2512": [
        "中文", "英文", "粤语", "日文", "韩文", "越南语", "印尼语",
        "泰语", "马来语", "菲律宾语", "阿拉伯语", "印地语", "保加利亚语",
        "克罗地亚语", "捷克语", "丹麦语", "荷兰语", "爱沙尼亚语", "芬兰语",
        "希腊语", "匈牙利语", "爱尔兰语", "拉脱维亚语", "立陶宛语", "马耳他语",
        "波兰语", "葡萄牙语", "罗马尼亚语", "斯洛伐克语", "斯洛文尼亚语", "瑞典语",
    ],
}

# ISO-639-1 -> FunASR language name
_LANG_MAP = {
    "auto": "auto",
    "zh": "中文",
    "en": "英文",
    "ja": "日文",
    "yue": "粤语",
    "ko": "韩文",
    "vi": "越南语",
    "id": "印尼语",
    "th": "泰语",
    "ms": "马来语",
    "tl": "菲律宾语",
    "ar": "阿拉伯语",
    "hi": "印地语",
    "bg": "保加利亚语",
    "hr": "克罗地亚语",
    "cs": "捷克语",
    "da": "丹麦语",
    "nl": "荷兰语",
    "et": "爱沙尼亚语",
    "fi": "芬兰语",
    "el": "希腊语",
    "hu": "匈牙利语",
    "ga": "爱尔兰语",
    "lv": "拉脱维亚语",
    "lt": "立陶宛语",
    "mt": "马耳他语",
    "pl": "波兰语",
    "pt": "葡萄牙语",
    "ro": "罗马尼亚语",
    "sk": "斯洛伐克语",
    "sl": "斯洛文尼亚语",
    "sv": "瑞典语",
}


def _resolve_hotwords(hotwords) -> List[str]:
    """Parse hotwords from various input formats.

    Supports:
      - List of strings: ["word1", "word2"]
      - Comma/newline separated string: "word1,word2\nword3"
      - File path to .txt (one word per line)
      - None or empty -> empty list
    """
    if not hotwords:
        return []

    # File path
    if isinstance(hotwords, str) and os.path.isfile(hotwords):
        with open(hotwords, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        return lines

    # String: split by comma or newline
    if isinstance(hotwords, str):
        import re
        words = re.split(r"[,\n\r]+", hotwords)
        return [w.strip() for w in words if w.strip()]

    # List
    if isinstance(hotwords, list):
        result = []
        for w in hotwords:
            if isinstance(w, str):
                w = w.strip()
                if w:
                    if os.path.isfile(w):
                        with open(w, "r", encoding="utf-8") as f:
                            for line in f:
                                line = line.strip()
                                if line:
                                    result.append(line)
                    else:
                        result.append(w)
        return result

    return []


class FunASRNanoLocal(ASRBase):
    """FunASR Nano local ASR engine.

    Supports model auto-download via modelscope, hotwords, VAD, and speaker
    diarization via cam++ speaker model.

    Auto-selects model based on language:
    - FunAudioLLM/Fun-ASR-Nano-2512: Chinese, English, Japanese
    - FunAudioLLM/Fun-ASR-MLT-Nano-2512: 30+ languages (default)
    """

    # 类级别锁：确保同一时间只有一个任务使用本地模型进行推理
    _inference_lock = threading.Lock()

    # Languages supported by the smaller Nano model
    _NANO_LANGUAGES = {"zh", "en", "ja", "中文", "英文", "日文"}

    def __init__(self):
        self._model_cache = MODELSCOPE_CACHE
        self._models: Dict[str, Any] = {}

    def _local_submodel(self, path_suffix: str) -> str | None:
        """Resolve a sub-model path under _model_cache/models/iic/.

        Returns the absolute local path if cached and non-empty, or None.
        """
        local = os.path.join(self._model_cache, "models", "iic", path_suffix)
        if os.path.isdir(local) and len(os.listdir(local)) > 0:
            return os.path.abspath(local)
        return None

    def _resolve_model_path(self, model_id: str) -> str | None:
        """Resolve a model's local cache path, checking multiple possible locations.

        ModelScope snapshot_download stores models at ``cache_dir/<org>/<repo>`` in
        newer versions, but older versions used ``cache_dir/models/<org>/<repo>``.
        This method checks both to avoid re-download loops.
        """
        candidates = [
            os.path.join(self._model_cache, model_id),           # new MS path
            os.path.join(self._model_cache, "models", model_id), # old MS path
        ]
        for p in candidates:
            if os.path.isdir(p) and len(os.listdir(p)) > 0:
                return os.path.abspath(p)
        return None

    def _get_model(self, model_id: str, diarize: bool = False, device: str = "cpu"):
        """Get or create a cached FunASR AutoModel instance.

        When diarize=True, the model is created with spk_model="cam++" so it
        can perform speaker diarization.  Non-diarize models are cached
        separately to avoid unnecessary memory usage.
        """
        cache_key = f"{model_id}|{'spk' if diarize else 'nospk'}|{device}"
        if cache_key not in self._models:
            # Windows 兼容：先替换 funasr 的裸 pip 安装逻辑，避免 WinError 5
            _patch_funasr_pip_install()
            from funasr import AutoModel

            # Resolve local model path from cache (check multiple locations)
            local_model_path = self._resolve_model_path(model_id)
            if local_model_path:
                model_id_or_path = local_model_path
            else:
                model_id_or_path = model_id

            model_kwargs = dict(
                model=model_id_or_path,
                device=device,
                vad_model=self._local_submodel("speech_fsmn_vad_zh-cn-16k-common-pytorch") or "fsmn-vad",
                punc_model=self._local_submodel("punc_ct-transformer_cn-en-common-vocab471067-large") or "ct-punc",
                disable_update=True,
            )
            if diarize:
                model_kwargs["spk_model"] = self._local_submodel("speech_campplus_sv_zh-cn_16k-common") or "cam++"
                model_kwargs["spk_mode"] = "punc_segment"

            print(f"[FunASRNano] Building model: {model_id_or_path} (diarize={diarize}, device={device})")
            model = AutoModel(**model_kwargs)
            
            # Handle BFloat16 dtype compatibility
            # If device doesn't support BFloat16, convert model to Float32
            if device == "cuda":
                try:
                    import torch
                    # Check if model has BFloat16 parameters
                    has_bf16 = any(
                        p.dtype == torch.bfloat16 
                        for p in model.model.parameters()
                    )
                    
                    if has_bf16:
                        device_supports_bf16 = torch.cuda.is_bf16_supported()
                        if not device_supports_bf16:
                            # Device doesn't support BFloat16, convert to Float32
                            print("[FunASRNano] Converting model from BFloat16 to Float32 (device doesn't support BF16)")
                            for name, param in model.model.named_parameters():
                                if param.dtype == torch.bfloat16:
                                    param.data = param.data.float()
                            for name, buf in model.model.named_buffers():
                                if buf.dtype == torch.bfloat16:
                                    buf.data = buf.data.float()
                        else:
                            print("[FunASRNano] Model uses BFloat16, device supports BF16")
                except Exception as e:
                    print(f"[FunASRNano] Warning: failed to handle BFloat16: {e}")
            
            self._models[cache_key] = model

        return self._models[cache_key]

    def _select_model_by_language(self, language: Optional[str], default_model: str) -> str:
        """Auto-select the best FunASR model based on language.

        - FunAudioLLM/Fun-ASR-Nano-2512: Chinese, English, Japanese (smaller, faster)
        - FunAudioLLM/Fun-ASR-MLT-Nano-2512: 30+ languages (default)

        Parameters
        ----------
        language : str | None
            Language code (zh/en/ja/...) or FunASR language name (中文/英文/日文).
        default_model : str
            User-configured default model.

        Returns
        -------
        str
            Model ID to use.
        """
        if not language or language == "auto":
            return default_model

        lang = language.strip().lower()
        if lang in self._NANO_LANGUAGES:
            nano_model = "FunAudioLLM/Fun-ASR-Nano-2512"
            print(f"[FunASRNano] Language '{language}' -> using {nano_model}")
            return nano_model

        print(f"[FunASRNano] Language '{language}' -> using {default_model}")
        return default_model

    def transcribe(
        self,
        input_path: str,
        output_path: str,
        callback: Optional[Callable] = None,
        *,
        model: str = DEFAULT_MODEL,
        language: Optional[str] = None,
        hotwords=None,
        diarize: bool = False,
        num_speakers: Optional[int] = None,
        use_itn: bool = True,
        vad_model: str = "fsmn-vad",
        vad_max_segment_time: int = 30000,
        batch_size: int = 1,
        sentence_timestamp: bool = True,
        device: Optional[str] = None,
        **kwargs,
    ) -> dict:
        """Transcribe audio/video via FunASR Nano.

        Parameters
        ----------
        input_path : str   Path to audio/video file.
        output_path : str  Path to write JSON result.
        callback : callable  (percent, message) progress callback.
        model : str  Model ID (e.g. "FunAudioLLM/Fun-ASR-MLT-Nano-2512").
        language : str | None  Language code (zh/en/ja/...) or None for auto.
        hotwords : str | list | None  Hotword list, comma string, or .txt path.
        diarize : bool  Enable speaker diarization (uses cam++ model).
        num_speakers : int | None  Preset number of speakers (0 = auto-detect).
        use_itn : bool  Apply inverse text normalization.
        vad_model : str  VAD model name (None to disable).
        vad_max_segment_time : int  Max segment time in ms for VAD.
        batch_size : int  Batch size.
        sentence_timestamp : bool  Return sentence-level timestamps.
        """
        import torch

        if callback:
            callback(5, "Preparing FunASR Nano...")

        # 设备选择：显式 device > lane 进程广播的 CUDA 可用性 > 自动检测
        # GPU lane 子进程在启动时预热 CUDA 并广播 VIDEOLINGO_LANE_CUDA=1，
        # 避免某些环境下 torch.cuda.is_available() 在推理中途返回 False 导致静默回退 CPU。
        lane_cuda = os.environ.get("VIDEOLINGO_LANE_CUDA") == "1"
        if device is None:
            device = "cuda" if (lane_cuda or torch.cuda.is_available()) else "cpu"
        device = device.lower()
        if device == "cuda" and not torch.cuda.is_available() and not lane_cuda:
            print("[FunASRNano] WARNING: device='cuda' but torch.cuda.is_available()=False, "
                  "falling back to cpu", flush=True)
            device = "cpu"
        print(f"[FunASRNano] device resolved: {device} "
              f"(torch.cuda.is_available={torch.cuda.is_available()}, lane_cuda={lane_cuda})", flush=True)

        # --- Auto-select model based on language ---
        default_model = model or DEFAULT_MODEL
        model_id = self._select_model_by_language(language, default_model)

        # --- Auto-download model via modelscope if not cached ---
        self._ensure_model_downloaded(model_id, callback)

        # --- Get (or create) the FunASR model ---
        asr_model = self._get_model(model_id, diarize=diarize, device=device)

        # --- Prepare generate kwargs ---
        gen_kwargs: Dict[str, Any] = {}
        lang = self._map_language(language)
        if lang and lang != "auto":
            gen_kwargs["language"] = lang
        if use_itn:
            gen_kwargs["use_itn"] = True
        # Note: sentence_timestamp is handled by _build_output (Case 2)
        # because funasr 1.3.9 skips punc segmentation when timestamps are present

        # Hotwords
        resolved_hw = _resolve_hotwords(hotwords)
        if resolved_hw:
            gen_kwargs["hotword"] = resolved_hw

        # Speaker diarization params
        if diarize:
            gen_kwargs["return_spk_res"] = True
            # preset_spk_num: 0 = auto-detect, >0 = fixed number
            spk_num = num_speakers if num_speakers and num_speakers > 0 else None
            if spk_num is not None:
                gen_kwargs["preset_spk_num"] = spk_num

        # FunASR Nano does NOT support batch decoding; force single-segment inference
        gen_kwargs["batch_size_s"] = 0

        # GPU memory-aware VAD max segment time: larger segments = fewer calls = faster
        if device == "cuda":
            try:
                free_mem_gb = torch.cuda.mem_get_info()[0] / (1024 ** 3)
                # ~4GB overhead for model, remaining for audio segments
                if free_mem_gb > 10:
                    max_seg_ms = 300000  # 300s -> ~2 segments for 10min audio
                elif free_mem_gb > 6:
                    max_seg_ms = 180000  # 180s
                elif free_mem_gb > 4:
                    max_seg_ms = 120000  # 120s
                else:
                    max_seg_ms = 60000   # 60s
                gen_kwargs["max_single_segment_time"] = max_seg_ms
                print(f"[FunASRNano] VAD max segment: {max_seg_ms//1000}s (GPU free={free_mem_gb:.1f}GB)", flush=True)
            except Exception:
                pass

        if callback:
            callback(20, f"Transcribing with {model_id} (diarize={diarize})...")

        start_time = time.time()
        # 使用类级别锁确保同一时间只有一个任务使用本地模型进行推理
        # 多个工作流并行运行时，其他任务会在此处排队等待
        with FunASRNanoLocal._inference_lock:
            if callback:
                callback(25, "Local model acquired, starting inference...")
            try:
                results = asr_model.generate(input=input_path, **gen_kwargs)
            except Exception as e:
                raise RuntimeError(f"FunASR Nano failed: {e}")
        elapsed = time.time() - start_time

        if callback:
            callback(80, f"Transcription complete ({elapsed:.1f}s)")

        # --- Build output ---
        # Save raw engine output for debugging
        raw_path = output_path.replace(".json", "_raw.json")
        try:
            os.makedirs(os.path.dirname(raw_path) or ".", exist_ok=True)
            with open(raw_path, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2, default=str)
            print(f"[FunASRNano] Raw engine output saved: {raw_path}")
        except Exception as e:
            print(f"[FunASRNano] Warning: failed to save raw output: {e}")

        output = self._build_output(results, self._map_language(language))

        # Mark that VAD was executed internally (integrated in FunASR model)
        # This prevents redundant VAD in post-processing
        output["_vad_internally_executed"] = True
        # FunASR Nano 转录自带字符级时间戳：有 words 即视为对齐已在内部完成；
        # 启用 diarize 且返回了说话人时，说话人识别也已在内部完成。
        # 这两个标志供下游后处理节点跳过重复阶段，避免浪费与错误叠加。
        output["_alignment_internally_executed"] = any(
            seg.get("words") for seg in output.get("segments", [])
        )
        output["_diarization_internally_executed"] = bool(output.get("speakers")) or any(
            seg.get("speaker_id") or seg.get("speaker")
            for seg in output.get("segments", [])
        )

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        seg_count = len(output.get("segments", []))
        spk_count = len(output.get("speakers", []))
        spk_info = f", {spk_count} speakers" if spk_count else ""
        if callback:
            callback(100, f"ASR done - {seg_count} segments{spk_info} ({elapsed:.1f}s)")
        return output

    # ------------------------------------------------------------------
    # Model management
    # ------------------------------------------------------------------

    def _ensure_model_downloaded(self, model_id: str, callback=None):
        """Download model from ModelScope if not already cached."""
        # Check all possible cache locations first
        if self._resolve_model_path(model_id):
            return

        if callback:
            callback(10, f"Downloading model {model_id}...")

        try:
            from modelscope import snapshot_download
            snapshot_download(model_id, cache_dir=self._model_cache)
            print(f"[FunASRNano] Downloaded {model_id} to {self._model_cache}")
        except Exception as e:
            print(f"[FunASRNano] Model download failed (may already be cached): {e}")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _map_language(language: Optional[str]) -> str:
        if not language or language == "auto":
            return "auto"
        lang = language.strip().lower()
        return _LANG_MAP.get(lang, language)

    @staticmethod
    def _build_output(results: list, language: str) -> dict:
        """Convert FunASR results to standardized output format.

        FunASR returns: [{"text": "...", "timestamp": [[start_ms, end_ms], ...], ...}]
        
        Handles three cases:
          1. sentence_info present (with punc_model) -> sentence-level segments
          2. timestamps only (char-level) -> group into segments by punctuation
          3. text only -> single segment fallback
        """
        if not results:
            return {"segments": [], "language": language, "text": ""}

        r = results[0]
        full_text = r.get("text", "") or r.get("text_tn", "")
        timestamps = r.get("timestamp") or r.get("ctc_timestamps", [])
        sentence_info = r.get("sentence_info", [])
        spk_res = r.get("spk_res", None)

        segments: List[dict] = []
        speakers_set: set = set()

        # --- Case 1: sentence_info present (best quality) ---
        # FunASR sentence_info format:
        #   [{"sentence": "...", "start": ms, "end": ms, "spk": N,
        #     "timestamp": [[start_ms, end_ms], ...]}, ...]
        # The "timestamp" field is character-level within each sentence.
        # We split long sentences at punctuation boundaries.
        if sentence_info:
            _SENT_END_CHARS = set(".!?。！？；;，,、")

            for sent in sentence_info:
                sent_text = (sent.get("sentence") or sent.get("text", "")).strip()
                sent_start_ms = sent.get("start", 0)
                sent_timestamps = sent.get("timestamp", [])
                speaker_label = None
                if "spk" in sent:
                    speaker_label = f"speaker_{sent['spk']}"
                    speakers_set.add(speaker_label)

                if not sent_text:
                    continue

                # Build character list with timestamps
                char_ts_pairs = []
                for j, ts_pair in enumerate(sent_timestamps):
                    if isinstance(ts_pair, (list, tuple)) and len(ts_pair) >= 2:
                        ch = sent_text[j] if j < len(sent_text) else ""
                        char_ts_pairs.append((ch, round(ts_pair[0] / 1000.0, 3), round(ts_pair[1] / 1000.0, 3)))

                # If no timestamps, create a single segment
                if not char_ts_pairs:
                    seg = {
                        "id": len(segments) + 1,
                        "start": round(sent_start_ms / 1000.0, 3),
                        "end": round(sent.get("end", 0) / 1000.0, 3),
                        "text": sent_text,
                    }
                    if speaker_label:
                        seg["speaker_id"] = speaker_label
                    segments.append(seg)
                    continue

                # Split into sub-segments at punctuation or every ~5 seconds
                current_words = []
                current_text_chars = []
                sub_start = char_ts_pairs[0][1]

                for ch, w_start, w_end in char_ts_pairs:
                    current_words.append({"word": ch, "start": w_start, "end": w_end})
                    current_text_chars.append(ch)
                    if speaker_label:
                        current_words[-1]["speaker"] = speaker_label

                    is_end = ch in _SENT_END_CHARS
                    dur_long = (w_end - sub_start) > 5000
                    is_last = (ch, w_start, w_end) == char_ts_pairs[-1]

                    if is_end or dur_long or is_last:
                        seg_text = "".join(current_text_chars)
                        if seg_text.strip():
                            seg = {
                                "id": len(segments) + 1,
                                "start": round(sub_start, 3),
                                "end": round(w_end, 3),
                                "text": seg_text,
                                "words": list(current_words),
                            }
                            if speaker_label:
                                seg["speaker_id"] = speaker_label
                            segments.append(seg)
                        current_words = []
                        current_text_chars = []
                        sub_start = w_end

                # Reset sub_start for next sentence
                if current_words:
                    w = current_words[-1]
                    sub_start = w["end"]

        # --- Case 2: character-level timestamps, no sentence_info ---        # --- Case 2: character-level timestamps, no sentence_info ---
        elif timestamps and full_text:
            char_text = full_text
            seg_words: List[dict] = []
            seg_start = None
            seg_text_chars: List[str] = []

            for i, ts in enumerate(timestamps):
                if not isinstance(ts, (list, tuple)) or len(ts) < 2:
                    continue
                start_ms, end_ms = ts[0], ts[1]
                char = char_text[i] if i < len(char_text) else ""

                if seg_start is None:
                    seg_start = start_ms

                seg_words.append({
                    "word": char,
                    "start": round(start_ms / 1000.0, 3),
                    "end": round(end_ms / 1000.0, 3),
                })
                seg_text_chars.append(char)

                # Split on sentence-ending punctuation or every ~5 seconds
                is_sentence_end = char in ".!?,;:?。！？，；：、"
                dur_long = (end_ms - seg_start) > 5000
                is_last = i == len(timestamps) - 1

                if is_sentence_end or dur_long or is_last:
                    seg_text = "".join(seg_text_chars)
                    if seg_text.strip():
                        segments.append({
                            "id": len(segments) + 1,
                            "start": round(seg_start / 1000.0, 3),
                            "end": round(end_ms / 1000.0, 3),
                            "text": seg_text,
                            "words": list(seg_words),
                        })
                    seg_words = []
                    seg_text_chars = []
                    seg_start = None

        # --- Case 3: text only, no timestamps ---
        elif full_text:
            segments.append({
                "id": 1,
                "start": 0.0,
                "end": 0.0,
                "text": full_text,
            })

        # --- Handle separate speaker diarization result ---
        if spk_res and not sentence_info:
            for line in spk_res.split("\n"):
                line = line.strip()
                if ":" in line:
                    spk_id, spk_text = line.split(":", 1)
                    spk_text = spk_text.strip()
                    if spk_text:
                        speaker_label = spk_id.strip()
                        segments.append({
                            "id": len(segments) + 1,
                            "start": 0.0,
                            "end": 0.0,
                            "text": spk_text,
                            "speaker_id": speaker_label,
                        })
                        speakers_set.add(speaker_label)

        output: Dict[str, any] = {
            "language": language,
            "text": full_text,
            "segments": segments,
        }
        if speakers_set:
            output["speakers"] = sorted(speakers_set)

        return output