"""sherpa-onnx 本地 ASR 引擎（SenseVoice / Paraformer）。

以 C++ 实现的 sherpa-onnx（onnxruntime 推理，不依赖 torch）为后端，首个
"零 torch" 的本地 ASR 引擎，适合 CPU 机器与低显存环境。

流水线：
  音源 --ffmpeg--> 16k 单声道 WAV --(可选)Silero VAD 分段--> 逐段 SenseVoice 识别
      --> token 级时间戳 --> 项目统一的 segments 结构

模型由 backend.asr.sherpa_models 自动下载（默认 hf-mirror 镜像）。

实测结论（sherpa-onnx 1.13.8 / sense-voice int8）：
  * VoiceActivityDetector 只给语音段**起始**样本索引，SpeechSegment.samples 为空，
    因此按 "本段起点 → 下段起点" 自行切片，末段取到音频末尾。
  * SenseVoice 结果带 token 级 timestamps（相对该段起点），可构造字级 words。
  * provider 传 "cuda" 但 wheel 未启用 GPU 时，sherpa 内部打印告警并自动回退 cpu，
    不抛异常 —— 因此 CPU/GPU 可统一按 "cuda 优先、自动降级" 配置。
"""
import os
import gc
import json
import shutil
import tempfile
import subprocess
from typing import Callable, Dict, List, Optional

import numpy as np

from backend.asr.asr_base import ASRBase
from backend.asr import sherpa_models

DEFAULT_MODEL = sherpa_models.DEFAULT_MODEL
DEFAULT_VAD_MODEL = sherpa_models.DEFAULT_VAD_MODEL

# <|zh|> / <|en|> ... -> ISO 码
_LANG_TAG_MAP = {
    "zh": "zh", "en": "en", "ja": "ja", "ko": "ko", "yue": "yue",
}


def _normalize_lang(value: Optional[str]) -> str:
    """把 '<|zh|>' / 'zh' / '中文' 之类的输入统一成 sherpa 接受的语种码。"""
    if not value:
        return "auto"
    v = str(value).strip().strip("<>|").lower()
    if v in ("auto", ""):
        return "auto"
    return _LANG_TAG_MAP.get(v, v)


def _strip_tag(value: Optional[str]) -> str:
    return (value or "").strip().strip("<>|")


def _simplify_chinese(text: str) -> str:
    """繁体转简体（whisper 中文输出为繁体）。

    zhconv 缺失时原样返回，绝不因转换失败影响识别结果。
    """
    if not text:
        return text
    try:
        import zhconv
    except ImportError:
        return text
    try:
        return zhconv.convert(text, "zh-cn")
    except Exception:
        return text


class SherpaOnnxASR(ASRBase):
    """sherpa-onnx offline recognizer 引擎。"""

    def __init__(self):
        self._recognizers: Dict[str, object] = {}
        self._last_provider: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # 模型 / 识别器
    # ------------------------------------------------------------------
    @staticmethod
    def _import_sherpa():
        try:
            import sherpa_onnx  # noqa: WPS433
        except ImportError as exc:
            raise RuntimeError(
                "sherpa-onnx 未安装，请执行: pip install sherpa-onnx "
                f"（原始错误: {exc}）"
            ) from exc
        return sherpa_onnx

    def _get_recognizer(
        self,
        sherpa_onnx,
        info: dict,
        *,
        language: str = "auto",
        use_itn: bool = True,
        num_threads: int = 2,
        provider: str = "cpu",
        decoding_method: str = "greedy_search",
        task: str = "transcribe",
        word_timestamps: bool = True,
    ):
        key = "|".join([
            info.get("model_id", ""), str(info.get("model_file", "")),
            language, str(use_itn), str(num_threads), provider,
            decoding_method, task, str(word_timestamps),
        ])
        rec = self._recognizers.get(key)
        if rec is not None:
            return rec

        kind = info.get("kind", "sense_voice")
        common = dict(
            tokens=info["tokens"],
            num_threads=max(1, int(num_threads)),
            provider=provider,
            decoding_method=decoding_method,
            debug=False,
        )
        sample_rate = int(info.get("sample_rate", 16000))
        feature_dim = int(info.get("feature_dim", 80))

        if kind == "sense_voice":
            rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=info["model"],
                language=language,
                use_itn=use_itn,
                sample_rate=sample_rate,
                feature_dim=feature_dim,
                **common,
            )
        elif kind == "paraformer":
            # 注意：from_paraformer 的参数名是 paraformer=（不是 model=）
            rec = sherpa_onnx.OfflineRecognizer.from_paraformer(
                paraformer=info["model"],
                sample_rate=sample_rate,
                feature_dim=feature_dim,
                **common,
            )
        elif kind == "dolphin_ctc":
            rec = sherpa_onnx.OfflineRecognizer.from_dolphin_ctc(
                model=info["model"],
                sample_rate=sample_rate,
                feature_dim=feature_dim,
                **common,
            )
        elif kind == "whisper":
            # whisper 用空字符串表示自动检测语种；task=translate 可直接输出英文
            rec = sherpa_onnx.OfflineRecognizer.from_whisper(
                encoder=info["encoder"],
                decoder=info["decoder"],
                language="" if language in ("", "auto") else language,
                task=task,
                # 官方 whisper decoder 未导出 cross-attention，开启 token 时间戳只会
                # 触发 C++ 告警且拿不到结果 → 由注册表的 token_timestamps 决定。
                enable_token_timestamps=bool(word_timestamps)
                and bool(info.get("token_timestamps", False)),
                enable_segment_timestamps=bool(word_timestamps),
                **common,
            )
        elif kind == "fire_red_asr":
            rec = sherpa_onnx.OfflineRecognizer.from_fire_red_asr(
                encoder=info["encoder"],
                decoder=info["decoder"],
                **common,
            )
        else:
            raise RuntimeError(f"不支持的 sherpa-onnx 模型类型: {kind}")

        self._recognizers[key] = rec
        self._last_provider[key] = provider
        return rec

    def unload(self) -> None:
        """释放识别器（模型）占用，供引擎生命周期管理调用。"""
        self._recognizers.clear()
        self._last_provider.clear()
        gc.collect()

    # ------------------------------------------------------------------
    # 音频
    # ------------------------------------------------------------------
    @staticmethod
    def _to_16k_mono_wav(input_path: str, tmp_dir: str) -> str:
        """用 ffmpeg 转成 16kHz 单声道 wav（sherpa 要求 16k float32 输入）。"""
        out_path = os.path.join(tmp_dir, "audio_16k.wav")
        from backend.utils.ffmpeg_guard import apply_resource_args
        cmd = apply_resource_args([
            "ffmpeg", "-y", "-i", input_path,
            "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", out_path,
        ])
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if proc.returncode != 0 or not os.path.exists(out_path):
            raise RuntimeError(f"ffmpeg 音频转换失败: {proc.stderr[-500:]}")
        return out_path

    @staticmethod
    def _read_samples(wav_path: str) -> np.ndarray:
        import soundfile as sf
        data, sr = sf.read(wav_path, dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1).astype(np.float32)
        if sr != 16000:
            from backend.utils.audio_alignment import resample_audio
            data = resample_audio(data, sr, 16000)
        return np.ascontiguousarray(data, dtype=np.float32)

    # ------------------------------------------------------------------
    # VAD
    # ------------------------------------------------------------------
    def _detect_speech_starts(
        self,
        sherpa_onnx,
        samples: np.ndarray,
        vad_model_path: str,
        *,
        threshold: float = 0.5,
        min_silence_duration: float = 0.4,
        min_speech_duration: float = 0.25,
        max_speech_duration: float = 15.0,
        window_size: int = 512,
        num_threads: int = 1,
        provider: str = "cpu",
    ) -> List[int]:
        """返回语音段起始样本索引列表。"""
        cfg = sherpa_onnx.VadModelConfig(
            silero_vad=sherpa_onnx.SileroVadModelConfig(
                model=vad_model_path,
                threshold=threshold,
                min_silence_duration=min_silence_duration,
                min_speech_duration=min_speech_duration,
                window_size=window_size,
                max_speech_duration=max_speech_duration,
            ),
            sample_rate=16000,
            num_threads=max(1, int(num_threads)),
            provider=provider,
        )
        total_seconds = max(1.0, len(samples) / 16000.0 + 1.0)
        vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=total_seconds)
        for i in range(0, len(samples), window_size):
            vad.accept_waveform(samples[i:i + window_size])
        vad.flush()

        starts: List[int] = []
        while not vad.empty():
            starts.append(int(vad.front.start))
            vad.pop()
        return starts

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def transcribe(
        self,
        input_path: str,
        output_path: str,
        callback: Optional[Callable] = None,
        *,
        model: str = DEFAULT_MODEL,
        model_file: Optional[str] = None,
        variant: Optional[str] = None,
        language: Optional[str] = None,
        use_itn: bool = True,
        task: str = "transcribe",
        simplify_chinese: bool = True,
        provider: str = "cpu",
        num_threads: int = 0,
        vad: bool = True,
        vad_model: str = DEFAULT_VAD_MODEL,
        vad_threshold: float = 0.5,
        vad_min_silence_duration: float = 0.4,
        vad_min_speech_duration: float = 0.25,
        vad_max_speech_duration: float = 15.0,
        word_timestamps: bool = True,
        **kwargs,
    ) -> dict:
        """转录音/视频文件，返回项目统一结构 {"segments": [...], "language": ...}。"""
        sherpa_onnx = self._import_sherpa()

        def _cb(pct, msg):
            if callback:
                try:
                    callback(int(pct), msg)
                except Exception:
                    pass

        _cb(5, "准备 sherpa-onnx ...")
        model_id = model or DEFAULT_MODEL
        if not sherpa_models.is_cached(model_id, model_file):
            _cb(8, f"首次使用，下载模型 {model_id} ...")

        info = sherpa_models.ensure_model(
            model_id, model_file=model_file, variant=variant,
            callback=_cb, progress_range=(8, 45),
        )

        # whisper 中文输出为繁体，需要转简体（其它模型输出本身已是简体）
        simplify = bool(simplify_chinese) and info.get("kind") == "whisper"

        if num_threads <= 0:
            num_threads = min(4, os.cpu_count() or 2)
        provider = (provider or "cpu").lower()
        lang = _normalize_language_hint(language, model_id)

        _cb(50, "加载识别模型 ...")
        recognizer = self._get_recognizer(
            sherpa_onnx, info, language=lang, use_itn=use_itn,
            num_threads=num_threads, provider=provider, task=task,
            word_timestamps=word_timestamps,
        )

        tmp_dir = tempfile.mkdtemp(prefix="sherpa_asr_")
        try:
            _cb(55, "转换音频 (16kHz mono) ...")
            wav_path = self._to_16k_mono_wav(input_path, tmp_dir)
            samples = self._read_samples(wav_path)
            total_dur = len(samples) / 16000.0
            _cb(60, f"音频时长 {total_dur:.1f}s")

            if vad:
                _cb(62, "下载/加载 VAD 模型 ...")
                vad_path = sherpa_models.ensure_vad_model(
                    vad_model, callback=_cb, progress_range=(62, 68))
                _cb(70, "VAD 检测语音段 ...")
                starts = self._detect_speech_starts(
                    sherpa_onnx, samples, vad_path,
                    threshold=vad_threshold,
                    min_silence_duration=vad_min_silence_duration,
                    min_speech_duration=vad_min_speech_duration,
                    max_speech_duration=vad_max_speech_duration,
                    num_threads=max(1, num_threads // 2 or 1),
                    provider=provider,
                )
            else:
                starts = [0]
            if not starts:
                starts = [0]

            _cb(72, f"识别 {len(starts)} 个语音段 ...")
            segments: List[dict] = []
            detected_lang = ""
            # 段 i 的结束取"下一段起点 - min_silence"，把段尾静音让出去，
            # 否则 SenseVoice 的字时间戳会在尾部静音区外漂（实测溢出到下一段）。
            silence_pad = int(max(0.0, vad_min_silence_duration) * 16000)
            n = len(starts)
            for idx, st in enumerate(starts):
                raw_end = starts[idx + 1] if idx + 1 < n else len(samples)
                en = raw_end if idx + 1 == n else max(st + 4800, raw_end - silence_pad)
                en = min(en, len(samples))
                if en <= st:
                    continue
                chunk = samples[st:en]
                stream = recognizer.create_stream()
                stream.accept_waveform(16000, chunk)
                recognizer.decode_stream(stream)
                result = stream.result

                text = (getattr(result, "text", "") or "").strip()
                base = st / 16000.0
                end_t = en / 16000.0
                if not text:
                    continue
                if simplify:
                    text = _simplify_chinese(text)

                words = []
                if word_timestamps:
                    words = _build_words(result, base, end_t)
                    if words and simplify:
                        for w in words:
                            w["word"] = _simplify_chinese(w["word"])

                seg = {
                    "id": len(segments) + 1,
                    "start": round(base, 4),
                    "end": round(end_t, 4),
                    "text": text,
                }
                if words:
                    seg["words"] = words
                segments.append(seg)

                if not detected_lang:
                    detected_lang = _strip_tag(getattr(result, "lang", ""))

                _cb(72 + int(25 * (idx + 1) / n),
                    f"识别 {idx + 1}/{n} 段")
                del stream
            gc.collect()

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        result_dict = {
            "segments": segments,
            "language": detected_lang or ("zh" if lang in ("auto", "zh") else lang),
            "text": "".join(s.get("text", "") for s in segments),
        }
        if output_path:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result_dict, f, ensure_ascii=False, indent=2)
        _cb(100, "识别完成")
        return result_dict


def _normalize_language_hint(language: Optional[str], model_id: str) -> str:
    """把项目语种参数映射到该模型支持的语种；不支持时退回 auto。"""
    lang = _normalize_lang(language)
    if lang == "auto":
        return "auto"
    supported = sherpa_models.model_languages(model_id)
    if supported and lang not in supported:
        return "auto"
    return lang


def _build_words(result, base: float, seg_end: float) -> List[dict]:
    """用 token 级 timestamps 构造 word 列表（中文即字级）。"""
    tokens = list(getattr(result, "tokens", None) or [])
    stamps = list(getattr(result, "timestamps", None) or [])
    if not tokens or len(stamps) < 1:
        return []
    if len(stamps) < len(tokens):
        tokens = tokens[:len(stamps)]

    seg_span = max(0.0, seg_end - base)
    words: List[dict] = []
    for i, tok in enumerate(tokens):
        w_start = float(stamps[i])
        if i + 1 < len(stamps):
            w_end = float(stamps[i + 1])
        else:
            # 末字：用前一个字的时长外推，不超过段末
            prev = w_start - float(stamps[i - 1]) if i > 0 else 0.1
            w_end = w_start + max(0.02, min(prev, max(0.02, seg_span - w_start)))
        # 钳制：SenseVoice 的时间戳会在段尾静音区外漂，必须框在本段内
        s_abs = min(max(base + w_start, base), max(base, seg_end))
        e_abs = min(max(base + w_end, s_abs + 0.01), max(base, seg_end))
        words.append({
            "word": tok,
            "start": round(s_abs, 4),
            "end": round(e_abs, 4),
        })
        prev_end = e_abs

    # 时间戳完全退化（全落在段首/零时长）时按文本长度均匀铺开，避免下游对齐误判
    if words and all(w["end"] - w["start"] < 1e-3 for w in words) and seg_span > 1e-3:
        slot = seg_span / len(words)
        t = base
        for w in words:
            w["start"] = round(t, 4)
            w["end"] = round(min(t + slot, base + seg_span), 4)
            t += slot
    return words
