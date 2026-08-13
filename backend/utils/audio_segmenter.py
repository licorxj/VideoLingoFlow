"""Audio segmentation utilities for TTS reference audio extraction.

Provides functions to split audio into segments based on timestamps,
with optimized cut points at waveform silences and noise reduction.
"""

import os
import yaml
import numpy as np


def find_optimal_cut_point(audio_data: np.ndarray, sample_rate: int, window_seconds: float = 1.0) -> int:
    """在指定时间点附近的窗口内找到音频波形能量最低的点作为切割点
    
    Args:
        audio_data: 音频数据 (numpy array)
        sample_rate: 采样率
        window_seconds: 搜索窗口大小（秒），默认1秒
    
    Returns:
        最优切割点的采样索引（相对于 audio_data 的偏移）
    """
    if len(audio_data) == 0:
        return 0
    
    # 使用短时能量（short-term energy）作为静音检测指标
    window_size = max(1, int(window_seconds * sample_rate))
    window_size = min(window_size, len(audio_data) // 4)
    
    if window_size <= 0:
        return len(audio_data) // 2
    
    # 滑动窗口计算能量，找到能量最低的位置
    best_idx = len(audio_data) // 2
    best_energy = float('inf')
    
    for i in range(0, len(audio_data) - window_size, window_size):
        segment = audio_data[i:i + window_size]
        # 计算归一化能量
        energy = np.mean(np.abs(segment) ** 2)
        
        if energy < best_energy:
            best_energy = energy
            best_idx = i + window_size // 2
    
    return best_idx


def get_audio_cut_settings():
    """从配置文件读取音频切割全局参数"""
    try:
        from backend.config.config_manager import config
        return {
            "extend_time": config.get("audio.cut_extend_time") or 0.1,
            "peak_cut_enabled": config.get("audio.peak_cut_enabled") is not False,
            "peak_cut_window": config.get("audio.peak_cut_window") or 1.0,
            "denoise_enabled": config.get("audio.denoise_enabled") is True,
        }
    except Exception:
        return {
            "extend_time": 0.1,
            "peak_cut_enabled": True,
            "peak_cut_window": 1.0,
            "denoise_enabled": False,
        }


def get_audio_output_settings():
    """从配置文件读取音频输出质量全局参数"""
    try:
        from backend.config.config_manager import config
        return {
            "format": config.get("audio.output_format") or "wav",
            "bitrate": config.get("audio.bitrate") or 320,
            "sample_rate": config.get("audio.sample_rate") or 48000,
            "bit_depth": config.get("audio.bit_depth") or 16,
        }
    except Exception:
        return {
            "format": "wav",
            "bitrate": 320,
            "sample_rate": 48000,
            "bit_depth": 16,
        }


def split_audio_by_timestamps(
    audio_path: str,
    segments: list,
    output_dir: str,
) -> dict:
    """按句子时间段切割音频并保存
    
    参数从全局配置读取（通过 get_audio_cut_settings()）
    
    Args:
        audio_path: 原始音频文件路径
        segments: 段落列表，每个元素包含 {'index': int, 'start': float, 'end': float}
        output_dir: 输出目录
    
    Returns:
        Dict[int, str]: {segment_index: output_file_path}
    """
    # 读取全局配置
    settings = get_audio_cut_settings()
    extend_time = settings["extend_time"]
    peak_cut_enabled = settings["peak_cut_enabled"]
    cut_window_seconds = settings["peak_cut_window"]
    apply_denoise = settings["denoise_enabled"]
    try:
        import soundfile as sf
    except ImportError:
        print("[AudioSegmenter] 警告: soundfile 未安装，无法切割音频")
        return {}
    
    # 读取原始音频
    try:
        audio_data, sr = sf.read(audio_path)
        # 转为单声道
        if len(audio_data.shape) > 1:
            audio_data = np.mean(audio_data, axis=1)
    except Exception as e:
        print(f"[AudioSegmenter] 读取音频失败: {e}")
        return {}
    
    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)
    
    ref_map = {}
    
    for seg in segments:
        idx = seg.get("index", 0)
        start = seg.get("start", 0)
        end = seg.get("end", 0)
        
        # 计算基础切割点（带延展）
        base_start_sample = max(0, int((start - extend_time) * sr))
        base_end_sample = min(len(audio_data), int((end + extend_time) * sr))
        
        if base_end_sample <= base_start_sample:
            print(f"[AudioSegmenter] 跳过无效段落: idx={idx}, start={start}, end={end}")
            continue
        
        # 在基础切割点附近找到最优静音点（如果启用了波谷切割）
        optimal_start = base_start_sample
        optimal_end = base_end_sample
        
        if peak_cut_enabled:
            # 起点优化：在 base_start_sample 附近找能量最低点
            search_start = max(0, base_start_sample - int(cut_window_seconds * sr))
            search_end = min(len(audio_data), base_start_sample + int(cut_window_seconds * sr))
            search_region = audio_data[search_start:search_end]
            optimal_offset = find_optimal_cut_point(search_region, sr, cut_window_seconds)
            optimal_start = search_start + optimal_offset
            
            # 终点优化：在 base_end_sample 附近找能量最低点，但必须在起点之后
            search_start = max(optimal_start + int(0.05 * sr), base_end_sample - int(cut_window_seconds * sr))
            search_end = min(len(audio_data), base_end_sample + int(cut_window_seconds * sr))
            if search_end > search_start and search_start < len(audio_data):
                search_region = audio_data[search_start:search_end]
                optimal_offset = find_optimal_cut_point(search_region, sr, cut_window_seconds)
                optimal_end = search_start + optimal_offset
            else:
                optimal_end = base_end_sample
        
        # 确保起点 < 终点
        if optimal_end <= optimal_start:
            optimal_end = min(optimal_start + int(0.1 * sr), len(audio_data))
        
        # 截取音频段
        segment_data = audio_data[optimal_start:optimal_end]
        
        if len(segment_data) == 0:
            print(f"[AudioSegmenter] 跳过空段落: idx={idx}")
            continue
        
        # 保存音频
        out_file = os.path.join(output_dir, f"{idx:04d}.wav")
        try:
            if apply_denoise:
                segment_data = _apply_noise_reduction(segment_data, sr)
            
            sf.write(out_file, segment_data, sr)
            ref_map[idx] = out_file
        except Exception as e:
            print(f"[AudioSegmenter] 保存第 {idx} 段失败: {e}")
    
    print(f"[AudioSegmenter] 音频切割完成，共 {len(ref_map)} 段")
    return ref_map


def _apply_noise_reduction(audio_data: np.ndarray, sample_rate: int, 
                           n_fft: int = 512, threshold_factor: float = 0.5) -> np.ndarray:
    """对音频段应用频谱减法去噪
    
    原理：
    1. 使用STFT将音频变换到频域
    2. 估计噪声谱（取能量最低的15%帧作为噪声参考）
    3. 从频谱中减去噪声估计
    4. 逆STFT重构音频
    
    Args:
        audio_data: 音频数据 (numpy array, 归一化到 [-1, 1])
        sample_rate: 采样率
        n_fft: FFT窗口大小
        threshold_factor: 阈值因子（越大去噪越强，0.3-1.0）
    
    Returns:
        去噪后的音频数据
    """
    try:
        from scipy.fft import rfft, irfft
    except ImportError:
        print("[AudioSegmenter] 警告: scipy 未安装，跳过音频去噪")
        return audio_data
    
    if len(audio_data) == 0:
        return audio_data
    
    # 音频太短时跳过去噪（至少需要2帧才能有效估计噪声）
    if len(audio_data) < n_fft * 2:
        return audio_data
    
    hop_length = n_fft // 4
    
    # 填充音频到合适长度
    num_frames = max(1, (len(audio_data) - n_fft) // hop_length + 1)
    padded_length = n_fft + (num_frames - 1) * hop_length
    padded = np.pad(audio_data, (0, max(0, padded_length - len(audio_data))), mode='constant')
    
    # 汉宁窗
    window = np.hanning(n_fft)
    
    # 计算STFT
    stft_magnitude = np.zeros((n_fft // 2 + 1, num_frames))
    stft_phase = np.zeros((n_fft // 2 + 1, num_frames))
    frame_energies = np.zeros(num_frames)
    
    for i in range(num_frames):
        start = i * hop_length
        frame = padded[start:start + n_fft] * window
        spectrum = rfft(frame)
        stft_magnitude[:, i] = np.abs(spectrum)
        stft_phase[:, i] = np.angle(spectrum)
        frame_energies[i] = np.mean(np.abs(spectrum))
    
    # 估计噪声谱：取能量最低的15%帧的中位数
    noise_threshold_idx = max(1, int(num_frames * 0.15))
    noise_indices = np.argsort(frame_energies)[:noise_threshold_idx]
    noise_spectrum = np.median(stft_magnitude[:, noise_indices], axis=1, keepdims=True)
    
    # 计算阈值并应用频谱减法
    threshold = noise_spectrum * threshold_factor
    
    cleaned_magnitude = np.maximum(stft_magnitude - threshold, 0)
    
    # 重建频谱
    cleaned_stft = cleaned_magnitude * np.exp(1j * stft_phase)
    
    # 逆STFT重构音频
    reconstructed = np.zeros(padded_length)
    overlap_sum = np.zeros(padded_length)
    
    for i in range(num_frames):
        start = i * hop_length
        frame = irfft(cleaned_stft[:, i])
        reconstructed[start:start + n_fft] += frame * window
        overlap_sum[start:start + n_fft] += window ** 2
    
    # 归一化重叠
    overlap_sum = np.maximum(overlap_sum, 1e-10)
    reconstructed = reconstructed / overlap_sum
    
    # 截取原始长度
    result = reconstructed[:len(audio_data)]
    
    # 防止溢出
    max_val = np.max(np.abs(result))
    if max_val > 1.0:
        result = result / max_val
    
    return result
