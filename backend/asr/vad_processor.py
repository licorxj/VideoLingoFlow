"""VAD Processor:独立的语音活动检测模块。

支持多种VAD后端：
- FunASR fsmn-vad (推荐，本地可用)
- WebRTC VAD (轻量级)
- Silero VAD (需要网络下载)

可以独立于ASR引擎运行，用于后处理任何ASR结果。
"""

import os
import numpy as np
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass


@dataclass
class VADSegment:
    """VAD检测到的语音段落"""
    start: float  # 开始时间（秒）
    end: float    # 结束时间（秒）
    confidence: float = 1.0  # 置信度（0-1）


class VADProcessor:
    """VAD处理器基类"""
    
    def __init__(self, **kwargs):
        self.options = kwargs
    
    def detect(self, audio_path: str) -> List[VADSegment]:
        """检测音频中的语音活动区域"""
        raise NotImplementedError


class FSMNVADProcessor(VADProcessor):
    """FSMN VAD处理器（推荐）
    
    使用FunASR的fsmn-vad模型进行语音活动检测，本地可用，无需网络下载。
    """
    
    # 本地已缓存模型的候选路径（与 backend/asr/asr_funasr_nano.py 保持一致）
    _LOCAL_MODEL_CANDIDATES = [
        # 项目内 _model_cache/models/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "_model_cache", "models", "iic",
            "speech_fsmn_vad_zh-cn-16k-common-pytorch",
        ),
        # 旧版 ModelScope 布局
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "_model_cache",
            "speech_fsmn_vad_zh-cn-16k-common-pytorch",
        ),
    ]
    
    def __init__(self, 
                 max_segment_time: int = 30000,
                 model: Optional[str] = None,
                 **kwargs):
        super().__init__(**kwargs)
        self.max_segment_time = max_segment_time
        self.model = model or self._resolve_local_model()
    
    @classmethod
    def _resolve_local_model(cls) -> str:
        """返回本地已缓存的 fsmn-vad 模型路径；找不到时回退到 "fsmn-vad"（需联网下载）。"""
        cache_env = os.environ.get("MODELSCOPE_CACHE", "")
        if cache_env:
            candidate = os.path.join(
                cache_env, "models", "iic",
                "speech_fsmn_vad_zh-cn-16k-common-pytorch",
            )
            if os.path.isdir(candidate):
                return candidate
        for candidate in cls._LOCAL_MODEL_CANDIDATES:
            if os.path.isdir(candidate):
                return candidate
        return "fsmn-vad"
    
    def detect(self, audio_path: str) -> List[VADSegment]:
        """使用FSMN VAD检测语音活动"""
        try:
            from funasr import AutoModel
        except ImportError:
            raise ImportError("funasr package required for FSMN VAD")
        
        print(f"[VAD] Loading FSMN VAD model ({self.model})...")
        
        # 加载VAD模型（优先使用本地缓存，避免联网下载）
        model = AutoModel(
            model=self.model,
            max_single_segment_time=self.max_segment_time,
            disable_update=True
        )
        
        print(f"[VAD] Running FSMN VAD detection on {audio_path}...")
        
        # 运行VAD检测
        result = model.generate(input=audio_path)
        
        # 解析结果
        segments = self._parse_fsmn_result(result)
        
        print(f"[VAD] FSMN VAD detected {len(segments)} segments")
        
        return segments
    
    def _parse_fsmn_result(self, result: list) -> List[VADSegment]:
        """解析FSMN VAD结果。
        
        FunASR fsmn-vad 返回两种格式：
        - 纯VAD: [{"key": "xxx", "value": [[start_ms, end_ms], ...]}]
        - 带文本: [{"text": "[]", "timestamp": [[start_ms, end_ms], ...]}]
        """
        segments = []
        
        if not result:
            return segments
        
        for item in result:
            if not isinstance(item, dict):
                continue
            # fsmn-vad 标准输出：value 字段
            timestamps = item.get("value")
            if timestamps is None:
                # 兼容带文本格式：timestamp 字段
                timestamps = item.get("timestamp")
            if not timestamps:
                continue
            for ts in timestamps:
                if isinstance(ts, (list, tuple)) and len(ts) >= 2:
                    try:
                        start_ms, end_ms = float(ts[0]), float(ts[1])
                    except (TypeError, ValueError):
                        continue
                    if end_ms > start_ms:
                        segments.append(VADSegment(
                            start=start_ms / 1000.0,
                            end=end_ms / 1000.0
                        ))
        
        return segments


class WebRTCVADProcessor(VADProcessor):
    """WebRTC VAD处理器
    
    使用WebRTC VAD进行语音活动检测（轻量级，适合实时处理）。
    """
    
    def __init__(self, 
                 aggressiveness: int = 2,
                 frame_duration_ms: int = 30,
                 **kwargs):
        super().__init__(**kwargs)
        self.aggressiveness = aggressiveness
        self.frame_duration_ms = frame_duration_ms
    
    def detect(self, audio_path: str) -> List[VADSegment]:
        """使用WebRTC VAD检测语音活动"""
        try:
            import webrtcvad
        except ImportError:
            raise ImportError("webrtcvad package required for WebRTC VAD")
        
        print(f"[VAD] Running WebRTC VAD detection...")
        
        # 读取音频文件
        audio, sample_rate = self._read_audio(audio_path)
        
        # 创建VAD实例
        vad = webrtcvad.Vad(self.aggressiveness)
        
        # 分帧处理
        frames = self._frame_audio(audio, sample_rate)
        
        # 检测每帧的语音活动
        speech_frames = []
        for frame in frames:
            is_speech = vad.is_speech(frame, sample_rate)
            speech_frames.append(is_speech)
        
        # 合并相邻的语音帧为段落
        segments = self._merge_speech_frames(speech_frames, sample_rate)
        
        print(f"[VAD] WebRTC VAD detected {len(segments)} segments")
        
        return segments
    
    def _read_audio(self, path: str) -> Tuple[np.ndarray, int]:
        """读取音频文件，自动将多声道转换为单声道"""
        try:
            import soundfile as sf
            audio, sr = sf.read(path, dtype='int16')
        except ImportError:
            # 回退使用scipy
            from scipy.io import wavfile
            sr, audio = wavfile.read(path)
        
        # 处理多声道音频：转换为单声道
        if len(audio.shape) > 1:
            print(f"[VAD] Multi-channel audio detected ({audio.shape[1]} channels), converting to mono")
            audio = audio.mean(axis=1).astype(np.int16)
        
        return audio, sr
    
    def _frame_audio(self, audio: np.ndarray, sample_rate: int) -> List[bytes]:
        """将音频分帧"""
        frame_size = int(sample_rate * self.frame_duration_ms / 1000)
        frames = []
        
        for i in range(0, len(audio) - frame_size, frame_size):
            frame = audio[i:i + frame_size]
            # 转换为bytes
            if isinstance(frame, np.ndarray):
                frame = frame.astype(np.int16).tobytes()
            frames.append(frame)
        
        return frames
    
    def _merge_speech_frames(self, speech_frames: List[bool], sample_rate: int) -> List[VADSegment]:
        """合并相邻的语音帧为段落"""
        if not speech_frames:
            return []
        
        frame_duration = self.frame_duration_ms / 1000.0
        segments = []
        in_speech = False
        start = 0.0
        
        for i, is_speech in enumerate(speech_frames):
            if is_speech and not in_speech:
                # 语音开始
                in_speech = True
                start = i * frame_duration
            elif not is_speech and in_speech:
                # 语音结束
                in_speech = False
                end = i * frame_duration
                if end - start > 0.1:  # 最小段落时长100ms
                    segments.append(VADSegment(start=start, end=end))
        
        # 处理最后一段
        if in_speech:
            end = len(speech_frames) * frame_duration
            if end - start > 0.1:
                segments.append(VADSegment(start=start, end=end))
        
        return segments


class SileroVADProcessor(VADProcessor):
    """Silero VAD处理器
    
    使用Silero VAD模型进行语音活动检测（需要网络下载模型）。
    """
    
    def __init__(self, 
                 vad_onset: float = 0.500,
                 vad_offset: float = 0.363,
                 **kwargs):
        super().__init__(**kwargs)
        self.vad_onset = vad_onset
        self.vad_offset = vad_offset
    
    def detect(self, audio_path: str) -> List[VADSegment]:
        """使用Silero VAD检测语音活动"""
        try:
            import torch
        except ImportError:
            raise ImportError("torch package required for Silero VAD")
        
        print(f"[VAD] Loading Silero VAD model...")
        
        # 加载Silero VAD模型：优先使用本地已缓存的repo（torch hub cache），避免联网下载
        try:
            local_repo = self._find_local_repo()
            if local_repo:
                print(f"[VAD] Using locally cached Silero VAD repo: {local_repo}")
                model, utils = torch.hub.load(
                    local_repo,
                    model='silero_vad',
                    trust_repo=True,
                    source='local',
                )
            else:
                model, utils = torch.hub.load(
                    repo_or_dir='snakers4/silero-vad',
                    model='silero_vad',
                    trust_repo=True
                )
        except Exception as e:
            raise RuntimeError(f"Failed to load Silero VAD model: {e}")
        
        # 读取音频
        audio, sr = self._read_audio(audio_path)
        
        # 转换为torch tensor
        audio_tensor = torch.from_numpy(audio).float()
        if sr != 16000:
            # 需要重采样到16kHz
            import torchaudio
            audio_tensor = torchaudio.functional.resample(audio_tensor, sr, 16000)
        
        print(f"[VAD] Running Silero VAD detection...")
        
        # 运行VAD检测
        segments = self._run_silero_vad(model, utils, audio_tensor)
        
        print(f"[VAD] Silero VAD detected {len(segments)} segments")
        
        return segments
    
    def _read_audio(self, path: str) -> Tuple[np.ndarray, int]:
        """读取音频文件，自动将多声道转换为单声道"""
        try:
            import soundfile as sf
            audio, sr = sf.read(path, dtype='float32')
        except ImportError:
            from scipy.io import wavfile
            sr, audio = wavfile.read(path)
            audio = audio.astype(np.float32) / 32768.0
        
        # 处理多声道音频：转换为单声道
        if len(audio.shape) > 1:
            print(f"[VAD] Multi-channel audio detected ({audio.shape[1]} channels), converting to mono")
            audio = audio.mean(axis=1)
        
        return audio, sr
    
    @staticmethod
    def _find_local_repo() -> Optional[str]:
        """查找本地已缓存的 silero-vad 仓库（torch hub cache），避免联网下载。"""
        torch_home = os.environ.get(
            "TORCH_HOME",
            os.path.join(os.path.expanduser("~"), ".cache", "torch"),
        )
        candidate = os.path.join(torch_home, "hub", "snakers4_silero-vad")
        if os.path.isdir(candidate):
            return candidate
        return None
    
    def _run_silero_vad(self, model, utils, audio_tensor) -> List[VADSegment]:
        """运行Silero VAD"""
        (get_speech_timestamps, _, read_audio, _, _) = utils
        
        # 获取语音时间戳
        speech_timestamps = get_speech_timestamps(
            audio_tensor,
            model,
            threshold=self.vad_onset,
        )
        
        # 转换结果
        segments = []
        for ts in speech_timestamps:
            start = ts['start'] / 16000.0  # 转换为秒
            end = ts['end'] / 16000.0
            segments.append(VADSegment(start=start, end=end))
        
        return segments


def get_vad_processor(engine: str = "fsmn", **kwargs) -> VADProcessor:
    """获取VAD处理器实例
    
    Parameters
    ----------
    engine : str
        VAD引擎名称: "fsmn", "webrtc", "silero"
    **kwargs
        传递给处理器的参数
        
    Returns
    -------
    VADProcessor
        VAD处理器实例
    """
    if engine == "fsmn":
        return FSMNVADProcessor(**kwargs)
    elif engine == "webrtc":
        return WebRTCVADProcessor(**kwargs)
    elif engine == "silero":
        return SileroVADProcessor(**kwargs)
    else:
        raise ValueError(f"Unknown VAD engine: {engine}")


def list_vad_engines() -> List[str]:
    """列出可用的VAD引擎"""
    return ["fsmn", "webrtc", "silero"]
