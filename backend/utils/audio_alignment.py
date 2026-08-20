import os
from typing import Dict, List, Optional, Tuple

import numpy as np
import soundfile as sf

from backend.utils.audio_speed import resample_audio


def active_rms_dbfs(audio: np.ndarray) -> Optional[float]:
    if audio.size == 0:
        return None
    active = audio[np.abs(audio) > 1e-4]
    if active.size < max(128, audio.size // 100):
        active = audio
    if active.size == 0:
        return None
    rms = float(np.sqrt(np.mean(np.square(active, dtype=np.float64))))
    if rms <= 1e-8:
        return None
    return float(20.0 * np.log10(rms))


def normalize_segment_loudness(
    audio: np.ndarray,
    target_dbfs: float,
    max_boost_db: float = 8.0,
    max_cut_db: float = 8.0,
    peak_ceiling_dbfs: float = -1.0,
) -> Tuple[np.ndarray, float, Optional[float]]:
    current_dbfs = active_rms_dbfs(audio)
    if current_dbfs is None:
        return audio, 0.0, None

    gain_db = max(-max_cut_db, min(target_dbfs - current_dbfs, max_boost_db))
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 1e-8:
        peak_dbfs = 20.0 * np.log10(peak)
        gain_db = min(gain_db, peak_ceiling_dbfs - peak_dbfs)

    if abs(gain_db) < 0.05:
        return audio, gain_db, current_dbfs

    gain = float(10.0 ** (gain_db / 20.0))
    normalized = audio * gain
    peak_ceiling = float(10.0 ** (peak_ceiling_dbfs / 20.0))
    normalized_peak = float(np.max(np.abs(normalized))) if normalized.size else 0.0
    if normalized_peak > peak_ceiling and normalized_peak > 1e-8:
        normalized = normalized * (peak_ceiling / normalized_peak)
    return normalized.astype(np.float32, copy=False), gain_db, current_dbfs


def read_audio_mono(path: str, target_sr: int) -> np.ndarray:
    data, sr = sf.read(path, dtype="float32")
    if data.ndim > 1:
        data = np.mean(data, axis=1).astype(np.float32)
    if sr != target_sr:
        data = resample_audio(data, sr, target_sr)
    return data.astype(np.float32, copy=False)


def analyze_target_loudness(segments: List[Dict], task_dir: str, target_sr: int) -> float:
    loudness_values = []
    for seg in segments:
        audio_rel = seg.get("audio_file_adjusted") or seg.get("audio_file", "")
        audio_path = os.path.join(task_dir, audio_rel)
        if not os.path.exists(audio_path):
            continue
        try:
            loudness = active_rms_dbfs(read_audio_mono(audio_path, target_sr))
            if loudness is not None:
                loudness_values.append(loudness)
        except Exception:
            continue
    if not loudness_values:
        return -20.0
    return max(-24.0, min(float(np.median(loudness_values)), -16.0))


def protect_peak(audio: np.ndarray, peak_ceiling_dbfs: float = -1.0) -> Tuple[np.ndarray, Optional[float]]:
    if audio.size == 0:
        return audio, None
    peak = float(np.max(np.abs(audio)))
    peak_ceiling = float(10.0 ** (peak_ceiling_dbfs / 20.0))
    if peak > peak_ceiling and peak > 1e-8:
        return (audio * (peak_ceiling / peak)).astype(np.float32, copy=False), 20.0 * np.log10(peak)
    return audio, None


def merge_segments_sample_aligned(
    segments: List[Dict],
    task_dir: str,
    target_sr: int,
    tolerance_ms: float = 5.0,
    target_loudness_dbfs: Optional[float] = None,
    progress_callback=None,
) -> Tuple[np.ndarray, Dict]:
    if target_loudness_dbfs is None:
        target_loudness_dbfs = analyze_target_loudness(segments, task_dir, target_sr)

    merged = np.array([], dtype=np.float32)
    drift_log = []
    trim_log = []
    tolerance_samples = int(round(tolerance_ms * target_sr / 1000.0))
    last_merged_seg = None

    for i, seg in enumerate(segments):
        audio_rel = seg.get("audio_file_adjusted") or seg.get("audio_file", "")
        audio_path = os.path.join(task_dir, audio_rel)
        if not os.path.exists(audio_path):
            print(f"  [{seg.get('index', i)}] ⚠ 音频文件不存在: {audio_path}")
            continue

        try:
            seg_data = read_audio_mono(audio_path, target_sr)
        except Exception as e:
            print(f"  [{seg.get('index', i)}] ⚠ 读取失败: {e}")
            continue

        seg_data, gain_db, loudness_dbfs = normalize_segment_loudness(seg_data, target_loudness_dbfs)

        target_start = float(seg.get("target_start", 0) or 0)
        target_start_sample = max(0, int(round(target_start * target_sr)))
        cursor_sample = len(merged)
        drift_samples = cursor_sample - target_start_sample
        drift_ms = drift_samples * 1000.0 / target_sr

        if cursor_sample < target_start_sample:
            silence_samples = target_start_sample - cursor_sample
            if silence_samples > 0:
                merged = np.concatenate([merged, np.zeros(silence_samples, dtype=np.float32)])
        elif drift_samples > tolerance_samples:
            # 游标超前：前序段实际音频超出了规划槽位。只告警不修正会让漂移
            # 单调累积（可达数十秒）；截掉已合并音频的尾部超量，使本段从
            # 目标起点重新对齐，同时回写上一段的结束时间戳保持字幕一致
            merged = merged[:target_start_sample]
            seg["align_warning"] = f"cursor ahead by {drift_ms:.1f}ms, trimmed tail to re-align"
            trim_log.append(drift_ms)
            if last_merged_seg is not None:
                corrected_end = target_start_sample / target_sr
                if corrected_end < float(last_merged_seg.get("new_end", 0.0)):
                    last_merged_seg["new_end"] = round(corrected_end, 4)
                    last_merged_seg["actual_audio_duration"] = round(
                        corrected_end - float(last_merged_seg.get("new_start", 0.0)), 4
                    )

        actual_start_sample = len(merged)
        merged = np.concatenate([merged, seg_data])
        actual_end_sample = len(merged)

        seg["new_start"] = round(actual_start_sample / target_sr, 4)
        seg["new_end"] = round(actual_end_sample / target_sr, 4)
        seg["actual_audio_duration"] = round((actual_end_sample - actual_start_sample) / target_sr, 4)
        seg["audio_drift_ms"] = round(drift_ms, 3)
        last_merged_seg = seg

        drift_log.append(abs(drift_ms))
        loudness_label = ""
        if loudness_dbfs is not None:
            loudness_label = f", 响度: {loudness_dbfs:.1f}→{target_loudness_dbfs:.1f} dBFS, 增益: {gain_db:+.1f}dB"
        print(
            f"  [{seg.get('index', i)}] 实际: {seg['new_start']:.3f}-{seg['new_end']:.3f}s "
            f"(漂移: {drift_ms:+.1f}ms, 音频时长: {seg['actual_audio_duration']:.3f}s{loudness_label})"
        )

        if progress_callback:
            progress_callback(i + 1, len(segments))

    merged, clipped_peak = protect_peak(merged)
    stats = {
        "target_loudness_dbfs": target_loudness_dbfs,
        "max_drift_ms": max(drift_log) if drift_log else 0.0,
        "avg_drift_ms": sum(drift_log) / len(drift_log) if drift_log else 0.0,
        "trim_corrections": len(trim_log),
        "max_trim_ms": max(trim_log) if trim_log else 0.0,
        "duration": len(merged) / target_sr if target_sr > 0 else 0.0,
        "clipped_peak_dbfs": clipped_peak,
    }
    return merged, stats
