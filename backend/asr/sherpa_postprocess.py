"""sherpa-onnx 版后处理组件：VAD / 标点恢复 / 说话人分离。

与 sherpa ASR 引擎共用同一套 C++ 推理后端与模型缓存，替换掉原先依赖
torch / funasr / pyannote 的实现：

  * VAD          -> sherpa Silero VAD（2.2MB onnx）
  * 标点恢复      -> sherpa CT-Transformer（中英）
  * 说话人分离    -> sherpa pyannote 分割 + 3D-Speaker 声纹 + fast clustering

三者均为**可选依赖**：sherpa-onnx 未安装时抛 RuntimeError，由调用方的
失败降级逻辑（asr_base._apply_vad 等）自动回退到其它引擎。
"""
import os
import shutil
import tempfile
from typing import List, Optional

from backend.asr.asr_base import ASRBase  # noqa: F401  (保持与 ASR 侧一致的导入语义)
from backend.asr import sherpa_models
from backend.asr.punctuation_processor import (
    PunctuationProcessor,
    normalize_lang_code,
    _needs_punctuation,
)
from backend.asr.speaker_diarization_processor import (
    SpeakerDiarizationProcessor,
    SpeakerDiarizationResult,
    SpeakerSegment,
)
from backend.asr.vad_processor import VADProcessor, VADSegment


def _import_sherpa():
    try:
        import sherpa_onnx
    except ImportError as exc:
        raise RuntimeError(
            f"sherpa-onnx 未安装，无法使用 sherpa 后处理（pip install sherpa-onnx）：{exc}"
        ) from exc
    return sherpa_onnx


def _read_16k_mono(audio_path: str):
    """音频 -> (float32 16k 单声道 samples, 临时目录)。调用方负责清理临时目录。"""
    from backend.asr.asr_sherpa_onnx import SherpaOnnxASR
    import soundfile as sf

    tmp_dir = tempfile.mkdtemp(prefix="sherpa_pp_")
    try:
        wav_path = SherpaOnnxASR._to_16k_mono_wav(audio_path, tmp_dir)
        data, sr = sf.read(wav_path, dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        if sr != 16000:
            from backend.utils.audio_alignment import resample_audio
            data = resample_audio(data, sr, 16000)
        return data.astype("float32"), tmp_dir
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


# ---------------------------------------------------------------------------
# VAD
# ---------------------------------------------------------------------------
class SherpaVADProcessor(VADProcessor):
    """sherpa-onnx Silero VAD：2MB 模型、无 torch 依赖、本地缓存。"""

    def __init__(
        self,
        vad_model: str = sherpa_models.DEFAULT_VAD_MODEL,
        threshold: Optional[float] = None,
        min_silence_duration: Optional[float] = None,
        min_speech_duration: float = 0.25,
        max_speech_duration: float = 20.0,
        window_size: int = 512,
        num_threads: int = 1,
        provider: str = "cpu",
        vad_onset: float = 0.500,
        vad_offset: float = 0.363,
        **kwargs,
    ):
        super().__init__(**kwargs)
        from backend.asr.vad_processor import (
            _coerce_unit_float,
            offset_to_silence_seconds,
        )
        self.vad_model = vad_model
        # 起始阈值 -> sherpa 的 threshold（原生概率门限）
        self.threshold = (
            float(threshold) if threshold is not None
            else _coerce_unit_float(vad_onset, 0.500)
        )
        # sherpa 无原生"退出语音"概率门限，用结束阈值换算静音容忍时长
        self.min_silence_duration = (
            float(min_silence_duration) if min_silence_duration is not None
            else offset_to_silence_seconds(_coerce_unit_float(vad_offset, 0.363))
        )
        self.min_speech_duration = min_speech_duration
        self.max_speech_duration = max_speech_duration
        self.window_size = window_size
        self.num_threads = num_threads
        self.provider = provider

    def detect(self, audio_path: str) -> List[VADSegment]:
        sherpa_onnx = _import_sherpa()
        model_path = sherpa_models.ensure_vad_model(self.vad_model)

        cfg = sherpa_onnx.VadModelConfig(
            silero_vad=sherpa_onnx.SileroVadModelConfig(
                model=model_path,
                threshold=self.threshold,
                min_silence_duration=self.min_silence_duration,
                min_speech_duration=self.min_speech_duration,
                window_size=self.window_size,
                max_speech_duration=self.max_speech_duration,
            ),
            sample_rate=16000,
            num_threads=max(1, int(self.num_threads)),
            provider=self.provider,
        )

        samples, tmp_dir = _read_16k_mono(audio_path)
        try:
            vad = sherpa_onnx.VoiceActivityDetector(
                cfg, buffer_size_in_seconds=max(1.0, len(samples) / 16000.0 + 1.0))
            win = self.window_size
            for i in range(0, len(samples), win):
                vad.accept_waveform(samples[i:i + win])
            vad.flush()

            starts: List[int] = []
            while not vad.empty():
                starts.append(int(vad.front.start))
                vad.pop()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        if not starts:
            return []

        # sherpa 只给语音段起点：本段终点取下一段起点（末段取音频末尾）
        segments: List[VADSegment] = []
        n = len(starts)
        for i, st in enumerate(starts):
            end = starts[i + 1] if i + 1 < n else len(samples)
            if end <= st:
                continue
            segments.append(VADSegment(
                start=round(st / 16000.0, 4),
                end=round(end / 16000.0, 4),
                confidence=1.0,
            ))
        print(f"[VAD] sherpa-onnx detected {len(segments)} segment(s)", flush=True)
        return segments


# ---------------------------------------------------------------------------
# 标点恢复
# ---------------------------------------------------------------------------
class SherpaPunctuationProcessor(PunctuationProcessor):
    """sherpa-onnx CT-Transformer 标点恢复（中英，纯文本、无需音频）。"""

    def __init__(self, num_threads: int = 1, provider: str = "cpu", **options):
        self.options = options or {}
        self.num_threads = max(1, int(num_threads))
        self.provider = provider
        self._model = None

    def _get_model(self):
        if self._model is None:
            sherpa_onnx = _import_sherpa()
            model_path = sherpa_models.ensure_punct_model()
            cfg = sherpa_onnx.OfflinePunctuationConfig(
                model=sherpa_onnx.OfflinePunctuationModelConfig(
                    ct_transformer=model_path,
                    num_threads=self.num_threads,
                    provider=self.provider,
                )
            )
            self._model = sherpa_onnx.OfflinePunctuation(cfg)
        return self._model

    def restore(self, segments: List[dict], language: str = "") -> List[dict]:
        lang = normalize_lang_code(language)
        if lang not in ("zh", "en"):
            print(f"[Punctuation] sherpa 标点不支持语言 '{language or 'unknown'}'（仅 zh/en），跳过",
                  flush=True)
            return segments
        if not _needs_punctuation(segments):
            print("[Punctuation] 文本已有足够标点，跳过", flush=True)
            return segments

        model = self._get_model()
        print(f"[Punctuation] sherpa-onnx 恢复标点：{len(segments)} 段", flush=True)
        for idx, seg in enumerate(segments):
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            try:
                parts = []
                # CT-Transformer 对超长文本有长度上限，按 200 字分块（与 ct-punc 一致）
                for i in range(0, len(text), 200):
                    chunk = text[i:i + 200]
                    if not chunk.strip():
                        continue
                    out = model.add_punctuation(chunk)
                    parts.append(out if isinstance(out, str) and out.strip() else chunk)
                if not parts:
                    continue
                restored = "".join(parts) if lang == "zh" else " ".join(parts)
                if restored:
                    seg["text"] = restored
            except Exception as exc:
                print(f"[Punctuation] 第 {idx} 段标点恢复失败，保留原文: {exc}", flush=True)
                continue
        return segments


# ---------------------------------------------------------------------------
# 说话人分离
# ---------------------------------------------------------------------------
class SherpaDiarizationProcessor(SpeakerDiarizationProcessor):
    """sherpa-onnx 说话人分离：pyannote 分割 + 3D-Speaker 声纹 + fast clustering。"""

    def __init__(
        self,
        # 聚类阈值（余弦距离）：越大越容易把不同说话人合并。
        # 实测官方 4 说话人样本：0.5 -> 7 人（过细）、0.8 -> 5 人、指定 num_speakers=4 -> 4 人。
        threshold: float = 0.75,
        num_threads: int = 2,
        provider: str = "cpu",
        min_duration_on: float = 0.3,
        min_duration_off: float = 0.5,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.threshold = threshold
        self.num_threads = num_threads
        self.provider = provider
        self.min_duration_on = min_duration_on
        self.min_duration_off = min_duration_off

    def diarize(
        self,
        audio_path: str,
        num_speakers: Optional[int] = None,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
    ) -> SpeakerDiarizationResult:
        sherpa_onnx = _import_sherpa()
        models = sherpa_models.ensure_speaker_models()

        # fast clustering 只接受确定的聚类数：优先 num_speakers，其次 max_speakers，
        # 都没有则 -1（自动推断）。
        clusters = num_speakers or max_speakers or -1

        config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                    model=models["segmentation"],
                ),
                num_threads=max(1, int(self.num_threads)),
                provider=self.provider,
            ),
            embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=models["embedding"],
                num_threads=max(1, int(self.num_threads)),
                provider=self.provider,
            ),
            clustering=sherpa_onnx.FastClusteringConfig(
                num_clusters=int(clusters),
                threshold=float(self.threshold),
            ),
            min_duration_on=float(self.min_duration_on),
            min_duration_off=float(self.min_duration_off),
        )
        sd = sherpa_onnx.OfflineSpeakerDiarization(config)

        samples, tmp_dir = _read_16k_mono(audio_path)
        try:
            result = sd.process(samples)
            # 结果对象不可迭代，需通过 sort_by_start_time() 取按时间排序的段列表
            raw = result.sort_by_start_time() if hasattr(result, "sort_by_start_time") else []
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        segments: List[SpeakerSegment] = []
        speakers: List[str] = []
        for item in raw or []:
            spk = f"SPEAKER_{int(getattr(item, 'speaker', 0)):02d}"
            if spk not in speakers:
                speakers.append(spk)
            segments.append(SpeakerSegment(
                start=round(float(getattr(item, "start", 0.0)), 4),
                end=round(float(getattr(item, "end", 0.0)), 4),
                speaker=spk,
                confidence=float(getattr(item, "confidence", 1.0) or 1.0),
            ))

        print(f"[Diarization] sherpa-onnx: {len(segments)} 段 / {len(speakers)} 说话人",
              flush=True)
        return SpeakerDiarizationResult(segments=segments, speakers=speakers)
