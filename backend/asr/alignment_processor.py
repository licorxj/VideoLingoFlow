"""Alignment Processor: 独立的词级时间戳对齐模块。

支持多种对齐后端：
- WhisperX phoneme alignment (wav2vec2)
- Qwen3 ForcedAligner

可以独立于ASR引擎运行，用于后处理任何ASR结果，为其添加词级时间戳。
"""

import os
import numpy as np
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass


@dataclass
class WordTimestamp:
    """词级时间戳"""
    word: str
    start: float  # 开始时间（秒）
    end: float    # 结束时间（秒）
    score: float = 0.0  # 置信度


@dataclass
class AlignmentResult:
    """对齐结果"""
    words: List[WordTimestamp]
    language: str = ""


class AlignmentProcessor:
    """对齐处理器基类"""
    
    def __init__(self, **kwargs):
        self.options = kwargs
    
    def align(self, audio_path: str, segments: List[dict], language: str = "") -> AlignmentResult:
        """对ASR结果进行词级时间戳对齐
        
        Parameters
        ----------
        audio_path : str
            音频文件路径
        segments : List[dict]
            ASR结果中的segments列表
        language : str
            语言代码
            
        Returns
        -------
        AlignmentResult
            对齐结果，包含词级时间戳
        """
        raise NotImplementedError


class WhisperXAlignmentProcessor(AlignmentProcessor):
    """WhisperX对齐处理器
    
    使用WhisperX的phoneme alignment功能，基于wav2vec2模型。
    """
    
    def __init__(self, 
                 model_name: Optional[str] = None,
                 model_dir: Optional[str] = None,
                 **kwargs):
        super().__init__(**kwargs)
        self.model_name = model_name
        # 默认使用 HF_HOME；但项目内 _model_cache 往往已缓存好对齐模型，
        # align() 时会依次尝试多个本地目录，优先命中已缓存的模型，避免联网下载。
        self.model_dir = model_dir or os.environ.get(
            "HF_HOME",
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))), "_model_cache"),
        )
    
    def _candidate_model_dirs(self) -> List[str]:
        """返回候选模型目录（按优先级：已包含所需模型的目录优先）。
        
        优先使用本地已缓存的模型目录，避免在 huggingface.co / pytorch.org
        不可达时反复尝试联网下载。
        """
        project_cache = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "_model_cache",
        )
        dirs = []
        for d in (self.model_dir, project_cache):
            if d and os.path.isdir(d) and d not in dirs:
                dirs.append(d)
        # 已包含对齐模型的目录排前面
        dirs.sort(key=lambda d: (0 if self._dir_has_align_model(d) else 1, dirs.index(d)))
        return dirs
    
    def _dir_has_align_model(self, dir_path: str) -> bool:
        """粗略判断目录中是否已缓存了对齐模型（torchaudio .pth 或 HF 快照）。"""
        try:
            entries = os.listdir(dir_path)
        except OSError:
            return False
        for name in entries:
            if name.startswith("wav2vec2") and name.endswith(".pth"):
                return True
            if name.startswith("models--"):
                return True
        return False
    
    def align(self, audio_path: str, segments: List[dict], language: str = "") -> AlignmentResult:
        """使用WhisperX进行phoneme alignment"""
        try:
            import whisperx
            import torch
        except ImportError:
            raise ImportError("whisperx package required for WhisperX alignment")
        
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[Alignment] WhisperX alignment starting, device={device}, language={language}")
        
        # 加载音频
        print("[Alignment] Loading audio...")
        audio = whisperx.load_audio(audio_path)
        print(f"[Alignment] Audio loaded, length={len(audio)}")
        
        # 加载对齐模型：依次尝试本地候选目录，命中已缓存模型即使用，避免联网下载
        print("[Alignment] Loading alignment model...")
        align_model = None
        metadata = None
        last_error = None
        for model_dir in self._candidate_model_dirs():
            try:
                print(f"[Alignment] Trying alignment model dir: {model_dir}")
                align_model, metadata = whisperx.load_align_model(
                    language_code=language,
                    device=device,
                    model_name=self.model_name,
                    model_dir=model_dir,
                    model_cache_only=True,
                )
                print(f"[Alignment] Alignment model loaded from: {model_dir}")
                break
            except Exception as e:
                last_error = e
                print(f"[Alignment] Failed with model dir {model_dir}: {e}")
        if align_model is None:
            raise RuntimeError(f"Failed to load alignment model: {last_error}")
        
        # 确保segments格式正确
        if not segments:
            print("[Alignment] No segments to align")
            return AlignmentResult(words=[], language=language)
        
        # 检查segments是否有有效的时间戳
        has_valid_timestamps = any(
            seg.get("start", 0) > 0 or seg.get("end", 0) > 0 
            for seg in segments
        )
        
        if not has_valid_timestamps:
            # 如果没有有效时间戳，将长文本拆分成多个segment
            print("[Alignment] No valid timestamps, splitting text into segments")
            full_text = " ".join(seg.get("text", "") for seg in segments if seg.get("text"))
            if full_text:
                # 获取音频时长
                audio_duration = len(audio) / 16000  # 假设16kHz采样率
                
                # 按标点符号拆分文本，每个segment不超过50个字符
                import re
                # 按中文标点和英文标点拆分
                parts = re.split(r'[，。！？、；：,.!?;:]', full_text)
                parts = [p.strip() for p in parts if p.strip()]
                
                # 合并短的parts，确保每个segment不超过50个字符
                merged_parts = []
                current = ""
                for part in parts:
                    if len(current) + len(part) < 50:
                        current += part
                    else:
                        if current:
                            merged_parts.append(current)
                        current = part
                if current:
                    merged_parts.append(current)
                
                # 为每个part分配时间
                segments = []
                time_per_char = audio_duration / len(full_text) if full_text else 0
                current_time = 0.0
                
                for part in merged_parts:
                    duration = len(part) * time_per_char
                    segments.append({
                        "start": current_time,
                        "end": current_time + duration,
                        "text": part
                    })
                    current_time += duration
                
                print(f"[Alignment] Created {len(segments)} segments from text")
            else:
                print("[Alignment] No text to align")
                return AlignmentResult(words=[], language=language)
        
        # 执行对齐
        print(f"[Alignment] Starting alignment with {len(segments)} segments...")
        result = whisperx.align(
            segments,
            align_model,
            metadata,
            audio,
            device,
            return_char_alignments=False,
        )
        print("[Alignment] Alignment complete")
        
        # 解析结果
        words = []
        for seg in result.get("segments", []):
            for w in seg.get("words", []):
                word = w.get("word", "").strip()
                if word:
                    words.append(WordTimestamp(
                        word=word,
                        start=w.get("start", 0.0),
                        end=w.get("end", 0.0),
                        score=w.get("score", 0.0),
                    ))
        
        print(f"[Alignment] Extracted {len(words)} words")
        return AlignmentResult(words=words, language=language)


class Qwen3AlignmentProcessor(AlignmentProcessor):
    """Qwen3对齐处理器
    
    使用Qwen3 ForcedAligner进行强制对齐。
    
    官方用法：
        from qwen_asr import Qwen3ForcedAligner
        
        model = Qwen3ForcedAligner.from_pretrained(
            "Qwen/Qwen3-ForcedAligner-0.6B",
            dtype=torch.bfloat16,
            device_map="cuda:0",
        )
        
        results = model.align(
            audio="audio.wav",
            text="要对齐的文本",
            language="Chinese",
        )
        
        # results[0] 是对齐结果列表
        # results[0][0].text, results[0][0].start_time, results[0][0].end_time
    """
    
    # ISO-639-1 -> Qwen3 language name mapping
    _LANGUAGE_MAP = {
        "zh": "Chinese",
        "en": "English",
        "yue": "Cantonese",
        "ar": "Arabic",
        "de": "German",
        "fr": "French",
        "es": "Spanish",
        "pt": "Portuguese",
        "id": "Indonesian",
        "it": "Italian",
        "ko": "Korean",
        "ru": "Russian",
        "th": "Thai",
        "vi": "Vietnamese",
        "ja": "Japanese",
        "tr": "Turkish",
        "hi": "Hindi",
        "ms": "Malay",
        "nl": "Dutch",
        "sv": "Swedish",
        "da": "Danish",
        "fi": "Finnish",
        "pl": "Polish",
        "cs": "Czech",
        "tl": "Filipino",
        "fa": "Persian",
        "el": "Greek",
        "ro": "Romanian",
        "hu": "Hungarian",
        "mk": "Macedonian",
    }
    
    def __init__(self, 
                 aligner_model: str = "Qwen/Qwen3-ForcedAligner-0.6B",
                 dtype: str = "bfloat16",
                 device_map: str = "auto",
                 **kwargs):
        super().__init__(**kwargs)
        self.aligner_model = aligner_model
        self.dtype = dtype
        self.device_map = device_map
    
    def _map_language(self, language: str) -> Optional[str]:
        """Map ISO-639-1 code to Qwen3 language name."""
        if not language:
            return None
        lang = language.strip().lower()
        # If already a full name, return as-is
        if lang in [v.lower() for v in self._LANGUAGE_MAP.values()]:
            return language
        return self._LANGUAGE_MAP.get(lang, None)
    
    def _resolve_dtype(self, dtype_str: str):
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
    
    # Qwen3-ForcedAligner 最大支持音频时长（秒）
    MAX_AUDIO_DURATION = 300  # 5分钟

    def _get_audio_duration(self, audio_path: str) -> float:
        """获取音频时长（秒）"""
        try:
            import librosa
            duration = librosa.get_duration(path=audio_path)
            return duration
        except Exception:
            # 如果librosa失败，尝试用soundfile
            try:
                import soundfile as sf
                data, sr = sf.read(audio_path)
                return len(data) / sr
            except Exception:
                return 0.0

    def _extract_segment_audio(self, audio_path: str, start: float, end: float, output_path: str) -> str:
        """从音频中提取指定时间段的片段"""
        try:
            import librosa
            import soundfile as sf
            
            # 加载指定时间段的音频
            audio, sr = librosa.load(audio_path, sr=16000, offset=start, duration=end - start)
            
            # 保存到临时文件
            sf.write(output_path, audio, sr)
            return output_path
        except Exception as e:
            print(f"[Qwen3Alignment] Failed to extract segment audio: {e}")
            return None
    
    def _align_single_segment(self, model, audio_path: str, text: str, language: str, 
                              seg_start: float = 0.0) -> List[WordTimestamp]:
        """对单个segment进行对齐"""
        words = []
        try:
            results = model.align(
                audio=audio_path,
                text=text,
                language=language,
            )
            
            # 解析结果，调整时间偏移
            if results and results[0]:
                for item in results[0]:
                    word_text = getattr(item, "text", "").strip()
                    if word_text:
                        words.append(WordTimestamp(
                            word=word_text,
                            start=getattr(item, "start_time", 0.0) + seg_start,
                            end=getattr(item, "end_time", 0.0) + seg_start,
                        ))
        except Exception as e:
            print(f"[Qwen3Alignment] Segment alignment failed: {e}")
        
        return words
    
    def align(self, audio_path: str, segments: List[dict], language: str = "") -> AlignmentResult:
        """使用Qwen3 ForcedAligner进行对齐
        
        Parameters
        ----------
        audio_path : str
            音频文件路径
        segments : List[dict]
            ASR结果中的segments列表
        language : str
            语言代码（如 "zh", "en"）或语言名称（如 "Chinese"）
            
        Returns
        -------
        AlignmentResult
            对齐结果，包含词级时间戳
        """
        try:
            from qwen_asr import Qwen3ForcedAligner
            import torch
        except ImportError:
            raise ImportError("qwen_asr package required for Qwen3 alignment")
        
        # Map language code to Qwen3 format
        qwen_lang = self._map_language(language)
        if not qwen_lang:
            print(f"[Qwen3Alignment] Warning: Unknown language '{language}', using 'Chinese'")
            qwen_lang = "Chinese"
        
        # 检查segments是否有有效的时间戳（来自VAD）
        has_valid_timestamps = any(
            seg.get("start", 0) > 0 or seg.get("end", 0) > 0 
            for seg in segments
        )
        
        # 获取音频总时长
        total_duration = self._get_audio_duration(audio_path)
        print(f"[Qwen3Alignment] Audio duration: {total_duration:.1f}s")
        
        # 解析dtype
        torch_dtype = self._resolve_dtype(self.dtype)
        
        # 确定设备
        device_map = self.device_map
        if device_map == "auto":
            device_map = "cuda" if torch.cuda.is_available() else "cpu"
        
        # 加载 Qwen3ForcedAligner 模型
        print(f"[Qwen3Alignment] Loading model '{self.aligner_model}'...")
        model = Qwen3ForcedAligner.from_pretrained(
            self.aligner_model,
            dtype=torch_dtype,
            device_map=device_map,
        )
        
        all_words = []
        temp_files = []  # 用于清理临时文件
        
        try:
            # 判断是否需要分段处理
            if has_valid_timestamps and total_duration > self.MAX_AUDIO_DURATION:
                # VAD已执行且音频超过5分钟，按segments分段处理
                print(f"[Qwen3Alignment] Audio > {self.MAX_AUDIO_DURATION}s, processing by segments")
                
                for i, seg in enumerate(segments):
                    seg_text = seg.get("text", "").strip()
                    seg_start = seg.get("start", 0.0)
                    seg_end = seg.get("end", 0.0)
                    
                    if not seg_text or seg_end <= seg_start:
                        continue
                    
                    # 检查segment时长是否超过限制
                    seg_duration = seg_end - seg_start
                    if seg_duration > self.MAX_AUDIO_DURATION:
                        print(f"[Qwen3Alignment] Segment {i} too long ({seg_duration:.1f}s), skipping")
                        continue
                    
                    # 提取segment音频
                    import tempfile
                    temp_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                    temp_audio.close()
                    
                    extracted = self._extract_segment_audio(audio_path, seg_start, seg_end, temp_audio.name)
                    if extracted:
                        temp_files.append(temp_audio.name)
                        
                        # 对segment进行对齐
                        print(f"[Qwen3Alignment] Aligning segment {i}: {seg_start:.1f}s-{seg_end:.1f}s")
                        seg_words = self._align_single_segment(model, extracted, seg_text, qwen_lang, seg_start)
                        all_words.extend(seg_words)
            
            elif total_duration > self.MAX_AUDIO_DURATION:
                # 没有VAD结果但音频超过5分钟，需要先分段
                print(f"[Qwen3Alignment] No VAD segments, splitting long audio")
                
                # 按文本长度估算分段点
                full_text = "".join(seg.get("text", "") for seg in segments if seg.get("text"))
                
                # 简单分段：每5分钟一段
                num_chunks = int(total_duration / self.MAX_AUDIO_DURATION) + 1
                chunk_duration = total_duration / num_chunks
                
                for i in range(num_chunks):
                    chunk_start = i * chunk_duration
                    chunk_end = min((i + 1) * chunk_duration, total_duration)
                    
                    # 估算这段对应的文本（按时间比例）
                    text_start = int(len(full_text) * (chunk_start / total_duration))
                    text_end = int(len(full_text) * (chunk_end / total_duration))
                    chunk_text = full_text[text_start:text_end]
                    
                    if not chunk_text.strip():
                        continue
                    
                    # 提取音频片段
                    import tempfile
                    temp_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                    temp_audio.close()
                    
                    extracted = self._extract_segment_audio(audio_path, chunk_start, chunk_end, temp_audio.name)
                    if extracted:
                        temp_files.append(temp_audio.name)
                        
                        print(f"[Qwen3Alignment] Aligning chunk {i}: {chunk_start:.1f}s-{chunk_end:.1f}s")
                        chunk_words = self._align_single_segment(model, extracted, chunk_text, qwen_lang, chunk_start)
                        all_words.extend(chunk_words)
            
            else:
                # 音频在5分钟内，直接处理
                print(f"[Qwen3Alignment] Audio within {self.MAX_AUDIO_DURATION}s limit, processing directly")
                
                full_text = "".join(seg.get("text", "") for seg in segments if seg.get("text"))
                if full_text.strip():
                    all_words = self._align_single_segment(model, audio_path, full_text, qwen_lang)
            
        finally:
            # 清理临时文件
            import os
            for temp_file in temp_files:
                try:
                    os.unlink(temp_file)
                except Exception:
                    pass
            
            # 释放模型
            del model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        
        print(f"[Qwen3Alignment] Extracted {len(all_words)} words total")
        return AlignmentResult(words=all_words, language=language)


def apply_alignment_to_segments(segments: List[dict], alignment_result: AlignmentResult) -> List[dict]:
    """将对齐结果应用到ASR segments
    
    Parameters
    ----------
    segments : List[dict]
        ASR结果中的segments列表
    alignment_result : AlignmentResult
        对齐结果
        
    Returns
    -------
    List[dict]
        添加了词级时间戳的segments
    """
    if not alignment_result.words:
        return segments
    
    # 创建词列表的副本
    all_words = alignment_result.words.copy()
    word_idx = 0
    
    for seg in segments:
        seg_start = seg.get("start", 0.0)
        seg_end = seg.get("end", 0.0)
        seg_words = []
        
        # 找到属于当前segment的词
        while word_idx < len(all_words):
            w = all_words[word_idx]
            # 如果词的开始时间在segment范围内（允许0.1秒误差以处理VAD边界抖动）
            if w.start >= seg_start - 0.1 and w.start < seg_end:
                seg_words.append({
                    "word": w.word,
                    "start": round(w.start, 3),
                    "end": round(w.end, 3),
                    "score": round(w.score, 4),
                })
                word_idx += 1
            elif w.start >= seg_end:
                # 超出当前segment范围，停止
                break
            else:
                # 在segment之前，跳过
                word_idx += 1
        
        # 如果找到了词，更新segment
        if seg_words:
            seg["words"] = seg_words
            # 更新segment的时间戳为词的范围
            seg["start"] = seg_words[0]["start"]
            seg["end"] = seg_words[-1]["end"]
    
    return segments


def list_alignment_engines() -> List[str]:
    """列出可用的对齐引擎"""
    return ["whisperx", "qwen3"]
