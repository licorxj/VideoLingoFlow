"""Speaker Diarization Processor: 独立的说话人识别模块。

支持多种说话人识别后端：
- WhisperX pyannote
- FunASR cam++
- 其他可扩展的说话人识别模型

可以独立于ASR引擎运行，用于后处理任何ASR结果。
"""

import os
import numpy as np
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass

DEFAULT_HF_TOKEN = ""


@dataclass
class SpeakerSegment:
    """说话人识别结果"""
    start: float  # 开始时间（秒）
    end: float    # 结束时间（秒）
    speaker: str  # 说话人标签（如 "SPEAKER_00"）
    confidence: float = 1.0  # 置信度（0-1）


@dataclass
class SpeakerDiarizationResult:
    """说话人识别完整结果"""
    segments: List[SpeakerSegment]
    speakers: List[str]  # 识别到的说话人列表


class SpeakerDiarizationProcessor:
    """说话人识别处理器基类"""
    
    def __init__(self, **kwargs):
        self.options = kwargs
    
    def diarize(self, audio_path: str, 
                num_speakers: Optional[int] = None,
                min_speakers: Optional[int] = None,
                max_speakers: Optional[int] = None) -> SpeakerDiarizationResult:
        """对音频进行说话人识别
        
        Parameters
        ----------
        audio_path : str
            音频文件路径
        num_speakers : int, optional
            预期的说话人数量（如果已知）
        min_speakers : int, optional
            最小说话人数量
        max_speakers : int, optional
            最大说话人数量
            
        Returns
        -------
        SpeakerDiarizationResult
            说话人识别结果
        """
        raise NotImplementedError


class PyannoteDiarizationProcessor(SpeakerDiarizationProcessor):
    """Pyannote说话人识别处理器（从WhisperX提取）
    
    使用pyannote.audio进行说话人识别。
    """
    
    def __init__(self, 
                 model_name: str = "pyannote/speaker-diarization-community-1",
                 hf_token: Optional[str] = None,
                 **kwargs):
        super().__init__(**kwargs)
        self.model_name = model_name
        self.hf_token = hf_token or os.environ.get("HF_TOKEN") or DEFAULT_HF_TOKEN
    
    def diarize(self, audio_path: str, 
                num_speakers: Optional[int] = None,
                min_speakers: Optional[int] = None,
                max_speakers: Optional[int] = None) -> SpeakerDiarizationResult:
        """使用pyannote进行说话人识别"""
        try:
            import whisperx
            from whisperx.diarize import DiarizationPipeline
        except ImportError:
            raise ImportError("whisperx package required for pyannote diarization")
        
        # 加载音频
        audio = whisperx.load_audio(audio_path)
        device = "cuda" if self._is_cuda_available() else "cpu"
        
        diarize_kwargs = {}
        if num_speakers is not None:
            diarize_kwargs["num_speakers"] = num_speakers
        if min_speakers is not None:
            diarize_kwargs["min_speakers"] = min_speakers
        if max_speakers is not None:
            diarize_kwargs["max_speakers"] = max_speakers
        
        # 依次尝试：(model_name, cache_dir)
        # 先使用本地已缓存的 pyannote 模型（离线可用），最后再尝试配置的模型（联网下载）
        last_error = None
        for model_name, cache_dir in self._candidate_models():
            try:
                if cache_dir:
                    # 强制使用本地缓存，避免 huggingface.co 不可达时长时间超时
                    os.environ["HF_HUB_OFFLINE"] = "1"
                print(f"[Diarization] Trying model: {model_name} (cache_dir={cache_dir})")
                pipeline = DiarizationPipeline(
                    model_name=model_name,
                    token=self.hf_token if not cache_dir else None,
                    device=device,
                    cache_dir=cache_dir,
                )
                diarize_df = pipeline(audio, **diarize_kwargs)
                result = self._parse_pyannote_result(diarize_df)
                if result.segments:
                    print(f"[Diarization] Completed with {model_name}: {len(result.speakers)} speaker(s)")
                    return result
                print(f"[Diarization] Model {model_name} returned no segments, trying next")
            except Exception as e:
                last_error = e
                print(f"[Diarization] Model {model_name} failed: {e}")
            finally:
                if cache_dir:
                    os.environ.pop("HF_HUB_OFFLINE", None)
        
        if last_error:
            raise RuntimeError(f"All diarization models failed, last error: {last_error}")
        return SpeakerDiarizationResult(segments=[], speakers=[])
    
    def _candidate_models(self) -> List[Tuple[str, Optional[str]]]:
        """返回 (model_name, cache_dir) 候选列表。
        
        优先本地已缓存的 pyannote 模型（~/.cache/torch/pyannote、HF_HOME/hub），
        最后追加配置的模型名作为联网兜底。
        """
        candidates: List[Tuple[str, Optional[str]]] = []
        seen = set()
        cache_dirs = [
            os.path.join(os.path.expanduser("~"), ".cache", "torch", "pyannote"),
            os.path.join(os.environ.get("HF_HOME", ""), "hub"),
        ]
        for cd in cache_dirs:
            if not cd or not os.path.isdir(cd):
                continue
            try:
                names = os.listdir(cd)
            except OSError:
                continue
            for name in names:
                if not name.startswith("models--pyannote--"):
                    continue
                full = os.path.join(cd, name)
                if not os.path.isdir(full) or not os.path.isdir(os.path.join(full, "snapshots")):
                    continue
                model_name = name.replace("models--", "").replace("--", "/")
                if model_name not in seen:
                    seen.add(model_name)
                    candidates.append((model_name, cd))
        # 配置的模型放最后（作为联网兜底）
        if self.model_name and self.model_name not in seen:
            candidates.append((self.model_name, None))
        return candidates
    
    def _parse_pyannote_result(self, df) -> SpeakerDiarizationResult:
        """解析pyannote结果"""
        segments = []
        speakers_set = set()
        
        if df is not None and len(df) > 0:
            for _, row in df.iterrows():
                speaker = row.get("speaker", "")
                if speaker:
                    segments.append(SpeakerSegment(
                        start=row.get("start", 0.0),
                        end=row.get("end", 0.0),
                        speaker=speaker
                    ))
                    speakers_set.add(speaker)
        
        return SpeakerDiarizationResult(
            segments=segments,
            speakers=sorted(list(speakers_set))
        )
    
    def _is_cuda_available(self) -> bool:
        """检查CUDA是否可用"""
        try:
            import torch
            return torch.cuda.is_available()
        except:
            return False


class CamPlusDiarizationProcessor(SpeakerDiarizationProcessor):
    """Cam++说话人识别处理器（从FunASR提取）
    
    使用FunASR的cam++模型进行说话人识别。
    """
    
    def __init__(self, 
                 model_name: str = "cam++",
                 **kwargs):
        super().__init__(**kwargs)
        self.model_name = model_name
    
    def diarize(self, audio_path: str, 
                num_speakers: Optional[int] = None,
                min_speakers: Optional[int] = None,
                max_speakers: Optional[int] = None) -> SpeakerDiarizationResult:
        """使用cam++进行说话人识别"""
        try:
            from funasr import AutoModel
        except ImportError:
            raise ImportError("funasr package required for cam++ diarization")
        
        # 创建带说话人识别的模型
        model = AutoModel(
            model="paraformer-zh",  # 基础ASR模型
            vad_model="fsmn-vad",
            punc_model="ct-punc",
            spk_model=self.model_name,
            spk_mode="punc_segment",
            disable_update=True
        )
        
        # 运行识别
        gen_kwargs = {"return_spk_res": True}
        if num_speakers and num_speakers > 0:
            gen_kwargs["preset_spk_num"] = num_speakers
        
        result = model.generate(input=audio_path, **gen_kwargs)
        
        # 解析结果
        parsed = self._parse_cam_result(result)
        
        return parsed
    
    def _parse_cam_result(self, result: list) -> SpeakerDiarizationResult:
        """解析cam++结果"""
        segments = []
        speakers_set = set()
        
        if not result:
            return SpeakerDiarizationResult(segments=[], speakers=[])
        
        r = result[0]
        
        # 处理sentence_info（如果有）
        sentence_info = r.get("sentence_info", [])
        for sent in sentence_info:
            speaker = f"speaker_{sent.get('spk', 0)}"
            segments.append(SpeakerSegment(
                start=sent.get("start", 0) / 1000.0,
                end=sent.get("end", 0) / 1000.0,
                speaker=speaker
            ))
            speakers_set.add(speaker)
        
        # 处理spk_res（如果没有sentence_info）
        if not sentence_info:
            spk_res = r.get("spk_res", "")
            if spk_res:
                for line in spk_res.split("\n"):
                    line = line.strip()
                    if ":" in line:
                        spk_id, _ = line.split(":", 1)
                        speaker = spk_id.strip()
                        speakers_set.add(speaker)
        
        return SpeakerDiarizationResult(
            segments=segments,
            speakers=sorted(list(speakers_set))
        )


class DiarizeLibProcessor(SpeakerDiarizationProcessor):
    """diarize 库说话人识别处理器（纯本地 CPU）

    基于已安装的 `diarize` 包（Silero VAD + WeSpeaker ResNet34-LM 嵌入 +
    GMM BIC 自动估计说话人数 + 谱聚类），无需 API Key / HF Token。
    """

    def diarize(self, audio_path: str,
                num_speakers: Optional[int] = None,
                min_speakers: Optional[int] = None,
                max_speakers: Optional[int] = None,
                **kwargs) -> SpeakerDiarizationResult:
        """使用 diarize 库进行说话人识别。

        kwargs 静默忽略 model_name / hf_token 等上游可能注入的无关选项。
        """
        try:
            from diarize import diarize as _lib_diarize
        except ImportError:
            raise ImportError("diarize package required for 'diarize' diarization engine")

        converted = self._ensure_readable_audio(audio_path)
        try:
            call_kwargs: Dict[str, Any] = {}
            if num_speakers:
                call_kwargs["num_speakers"] = int(num_speakers)
            if min_speakers:
                call_kwargs["min_speakers"] = int(min_speakers)
            if max_speakers:
                call_kwargs["max_speakers"] = int(max_speakers)

            print(f"[Diarization] Running local diarize library: {os.path.basename(audio_path)}")
            result = _lib_diarize(converted, **call_kwargs)
        finally:
            if converted != audio_path:
                try:
                    os.unlink(converted)
                except OSError:
                    pass

        parsed = self._parse_result(result)
        print(f"[Diarization] diarize library completed: "
              f"{len(parsed.speakers)} speaker(s), {len(parsed.segments)} segment(s)")
        return parsed

    def _parse_result(self, result: Any) -> SpeakerDiarizationResult:
        """将 diarize 库的 DiarizeResult 映射为项目内数据结构。"""
        segments = [
            SpeakerSegment(start=float(seg.start), end=float(seg.end), speaker=seg.speaker)
            for seg in result.segments
        ]
        return SpeakerDiarizationResult(segments=segments, speakers=list(result.speakers))

    def _ensure_readable_audio(self, audio_path: str) -> str:
        """soundfile 无法读取的格式（mp4/mkv 等视频容器）经 ffmpeg 预转为 16kHz 单声道 WAV。

        可读时原样返回路径；转换后返回临时 WAV 路径（调用方负责清理）。
        """
        try:
            import soundfile as sf
            sf.info(audio_path)
            return audio_path
        except Exception:
            pass

        import shutil
        import subprocess
        import tempfile
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError(
                f"Audio format not readable by soundfile and ffmpeg not found: {audio_path}")

        tmp_path = os.path.join(tempfile.mkdtemp(prefix="diarize_lib_"), "audio.wav")
        cmd = [ffmpeg, "-y", "-i", audio_path, "-vn", "-ac", "1", "-ar", "16000", tmp_path]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg conversion failed: {proc.stderr[-500:]}")
        print(f"[Diarization] Converted to temp WAV for diarize library: {tmp_path}")
        return tmp_path


def _speaker_at(time_point: float, diarization_result: SpeakerDiarizationResult) -> Optional[str]:
    """返回覆盖指定时间点的说话人；无覆盖时取时间上最近的说话人段。"""
    for spk_seg in diarization_result.segments:
        if spk_seg.start <= time_point <= spk_seg.end:
            return spk_seg.speaker
    best_speaker, best_dist = None, float("inf")
    for spk_seg in diarization_result.segments:
        dist = min(abs(time_point - spk_seg.start), abs(time_point - spk_seg.end))
        if dist < best_dist:
            best_dist, best_speaker = dist, spk_seg.speaker
    return best_speaker


def _split_segment_by_speakers(seg: dict, diarization_result: SpeakerDiarizationResult) -> List[dict]:
    """按词级时间戳将超长 segment 拆分为单一说话人的子段。

    每个词归属覆盖其时间中点的说话人，相邻同说话人的词合并为一个子段；
    文本按 CJK/拉丁语系自动选择无空格/空格拼接，子段保留对应 words。
    """
    words = [w for w in seg.get("words", []) if w.get("start") is not None]
    if not words:
        return []

    groups: List[Dict[str, Any]] = []
    for w in sorted(words, key=lambda x: x.get("start", 0)):
        mid = (w.get("start", 0.0) + w.get("end", w.get("start", 0.0))) / 2
        speaker = _speaker_at(mid, diarization_result)
        if speaker and groups and groups[-1]["speaker"] == speaker:
            groups[-1]["words"].append(w)
        elif speaker:
            groups.append({"speaker": speaker, "words": [w]})

    if not groups:
        return []

    sub_segments: List[dict] = []
    for g in groups:
        g_words = g["words"]
        text_parts = [w.get("word", "") for w in g_words]
        is_cjk = any('\u4e00' <= c <= '\u9fff' for c in text_parts[0])
        text = "".join(text_parts) if is_cjk else " ".join(text_parts)
        sub_segments.append({
            "start": round(g_words[0].get("start", seg.get("start", 0.0)), 3),
            "end": round(g_words[-1].get("end", seg.get("end", 0.0)), 3),
            "text": text.strip(),
            "words": g_words,
            "speaker": g["speaker"],
        })
    return [s for s in sub_segments if s["text"]]


def assign_speakers_to_segments(asr_segments: List[dict], 
                                 diarization_result: SpeakerDiarizationResult,
                                 overlap_threshold: float = 0.5) -> List[dict]:
    """将说话人标签分配给ASR结果中的segments

    策略：
    1. 单一说话人主导（最大重叠 ≥ overlap_threshold）→ 直接打标签；
    2. 跨说话人的长 segment 且含词级时间戳 → 按说话人边界拆分为子段；
    3. 其余情况兜底取最大重叠说话人，避免长 segment 永远无标签。

    Parameters
    ----------
    asr_segments : List[dict]
        ASR结果中的segments列表
    diarization_result : SpeakerDiarizationResult
        说话人识别结果
    overlap_threshold : float
        重叠时间阈值（0-1），用于判断segment是否由单一说话人主导
        
    Returns
    -------
    List[dict]
        添加了speaker标签的segments（长 segment 可能被拆分为多段）
    """
    if not diarization_result.segments:
        return asr_segments

    result_segments: List[dict] = []

    for seg in asr_segments:
        seg_start = seg.get("start", 0.0)
        seg_end = seg.get("end", 0.0)
        seg_duration = seg_end - seg_start

        # 找到与当前segment重叠最大的说话人
        best_speaker = None
        best_overlap = 0
        speakers_in_seg = set()

        for spk_seg in diarization_result.segments:
            overlap_start = max(seg_start, spk_seg.start)
            overlap_end = min(seg_end, spk_seg.end)
            overlap_duration = max(0, overlap_end - overlap_start)
            if overlap_duration <= 0:
                continue

            speakers_in_seg.add(spk_seg.speaker)

            overlap_ratio = overlap_duration / seg_duration if seg_duration > 0 else 0
            if overlap_ratio > best_overlap:
                best_overlap = overlap_ratio
                best_speaker = spk_seg.speaker

        if best_speaker is None:
            result_segments.append(seg)
            continue

        # 单一说话人主导：直接打标签
        if best_overlap >= overlap_threshold:
            seg["speaker"] = best_speaker
            result_segments.append(seg)
            continue

        # 跨多说话人的长 segment：按词级时间戳拆分
        if len(speakers_in_seg) > 1:
            sub_segments = _split_segment_by_speakers(seg, diarization_result)
            if sub_segments:
                print(f"[Diarization] Segment {seg.get('id')} ({seg_start:.1f}-{seg_end:.1f}s) "
                      f"split into {len(sub_segments)} speaker sub-segments")
                result_segments.extend(sub_segments)
                continue

        # 兜底：取最大重叠说话人，避免无标签
        seg["speaker"] = best_speaker
        result_segments.append(seg)

    # 拆分后重新编号
    for idx, seg in enumerate(result_segments):
        seg["id"] = idx + 1

    return result_segments


def merge_diarization_with_asr(asr_result: dict, 
                                diarization_result: SpeakerDiarizationResult) -> dict:
    """将说话人识别结果合并到ASR结果中
    
    Parameters
    ----------
    asr_result : dict
        ASR结果，格式：{"segments": [...], "language": "xx"}
    diarization_result : SpeakerDiarizationResult
        说话人识别结果
        
    Returns
    -------
    dict
        合并后的结果
    """
    # 复制ASR结果
    merged = asr_result.copy()
    
    # 分配说话人标签
    if "segments" in merged:
        merged["segments"] = assign_speakers_to_segments(
            merged["segments"], 
            diarization_result
        )
    
    # 添加说话人列表
    if diarization_result.speakers:
        merged["speakers"] = diarization_result.speakers
    
    return merged
