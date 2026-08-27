"""Audio splitting utilities for chunked ASR inference.

集中存放"按时长安全切分音频 + 按段偏移时间戳 + 重组装结果"的通用逻辑，
供 ``asr_factory.run_asr``（集中处理切分）与 ``steps/s02_asr.py`` 共用，
避免重复实现与层间循环依赖。

切分策略参考原始项目 ``core/all_whisper_methods/audio_preprocess.py``：
沿 ``max_duration`` 步进，在每个分段末端的静音窗口内寻找静音边界安全下刀，
找不到静音才退回到硬边界。
"""

import os
import json
import shutil
import subprocess
import tempfile
from typing import Dict, List, Tuple


def get_audio_duration(audio_path: str) -> float:
    """Get audio duration in seconds using ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def _detect_silence(audio_path: str, start: float, end: float,
                    threshold_db: float = -30.0, min_duration: float = 0.5) -> List[float]:
    """Detect silence_end points in [start, end] using ffmpeg silencedetect.

    Returns a list of timestamps (in seconds) where silence ends.
    """
    cmd = [
        "ffmpeg", "-y", "-i", audio_path,
        "-ss", str(start), "-to", str(end),
        "-af", f"silencedetect=n={threshold_db}dB:d={min_duration}",
        "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, encoding="utf-8")
        stderr = proc.stderr
    except Exception:
        return []

    silence_ends = []
    for line in stderr.split("\n"):
        if "silence_end" in line:
            try:
                val = float(line.split("silence_end: ")[1].split(" ")[0])
                silence_ends.append(val)
            except (IndexError, ValueError):
                continue
    return silence_ends


def split_audio_at_silence(audio_path: str, max_duration: float,
                           silence_win: float = 60.0) -> List[Tuple[float, float]]:
    """Split audio into segments, cutting at silence boundaries.

    Algorithm (matching original project logic):
    1. Walk through audio in max_duration chunks.
    2. For the last ~silence_win seconds of each chunk, search for silence.
    3. If a silence point is found, cut there; otherwise cut at the boundary.
    4. The remaining tail is a shorter final segment.

    Parameters
    ----------
    audio_path : str     Path to audio file.
    max_duration : float Max segment duration in seconds.
    silence_win : float  Window (seconds) before max_duration to search for silence.

    Returns
    -------
    List[Tuple[float, float]]  List of (start, end) in seconds.
    """
    duration = get_audio_duration(audio_path)
    if duration <= 0:
        return [(0.0, 0.0)]

    if duration <= max_duration:
        return [(0.0, duration)]

    segments: List[Tuple[float, float]] = []
    pos = 0.0

    while pos < duration:
        remaining = duration - pos
        if remaining <= max_duration:
            segments.append((pos, duration))
            break

        # Search window: [pos + max_duration - win, pos + max_duration + win]
        win_start = pos + max_duration - silence_win
        win_end = min(pos + max_duration + silence_win, duration)

        silence_points = _detect_silence(audio_path, win_start, win_end)

        if silence_points:
            # Find the first silence_end that is past the ideal cut point
            ideal_cut = pos + max_duration
            split_at = None
            for t in silence_points:
                if t > ideal_cut - silence_win and t <= ideal_cut + silence_win:
                    split_at = t
                    break
                # Also accept the first one that is close enough
                if t >= ideal_cut:
                    split_at = t
                    break
            # Fallback: pick the closest to ideal_cut
            if split_at is None and silence_points:
                split_at = min(silence_points, key=lambda t: abs(t - ideal_cut))

            if split_at is not None and win_start <= split_at <= win_end:
                segments.append((pos, split_at))
                pos = split_at
                continue

        # No good silence point found: cut at exact boundary
        segments.append((pos, pos + max_duration))
        pos += max_duration

    return segments


def cut_audio_segment(audio_path: str, start: float, end: float,
                      output_path: str) -> str:
    """Extract a segment from audio file using ffmpeg (copy, fallback re-encode)."""
    cmd = [
        "ffmpeg", "-y", "-i", audio_path,
        "-ss", str(start), "-to", str(end),
        "-c", "copy",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        # Fallback: re-encode if copy fails
        cmd = [
            "ffmpeg", "-y", "-i", audio_path,
            "-ss", str(start), "-to", str(end),
            "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to split audio: {result.stderr[:300]}")
    return output_path


def adjust_timestamps(result: dict, time_offset: float) -> dict:
    """Offset all timestamps in an ASR result by time_offset seconds."""
    if not result:
        return result

    for seg in result.get("segments", []):
        if "start" in seg:
            seg["start"] = round(seg["start"] + time_offset, 4)
        if "end" in seg:
            seg["end"] = round(seg["end"] + time_offset, 4)
        for word in seg.get("words", []) or []:
            if "start" in word:
                word["start"] = round(word["start"] + time_offset, 4)
            if "end" in word:
                word["end"] = round(word["end"] + time_offset, 4)

    return result


def merge_results(results: List[dict]) -> dict:
    """Merge multiple ASR results from sequential audio segments.

    组合各分段 segments、去重说话人、重排 segment id，并保留引擎内部
    执行标志（各分段由同一引擎转录时全部分段都带标志才保留，避免长音频
    合并后丢失标志导致下游重复执行 VAD/对齐/说话人识别）。
    """
    if not results:
        return {"segments": [], "language": "auto"}

    merged_segments: List[dict] = []
    all_speakers: set = set()
    detected_language = "auto"

    for r in results:
        lang = r.get("language", "auto")
        if lang and lang != "auto":
            detected_language = lang
            break

    for r in results:
        # Collect speakers (supports both list and dict forms)
        spk = r.get("speakers")
        if isinstance(spk, dict):
            all_speakers.update(spk.keys())
        elif isinstance(spk, (list, tuple, set)):
            all_speakers.update(spk)

        for seg in r.get("segments", []):
            merged_segments.append(seg)

    # Re-number segment IDs
    for idx, seg in enumerate(merged_segments, start=1):
        seg["id"] = idx

    output: Dict[str, any] = {
        "language": detected_language,
        "segments": merged_segments,
    }

    # Include full text if present
    full_text = " ".join(
        seg.get("text", "") for seg in merged_segments if seg.get("text")
    )
    if full_text:
        output["text"] = full_text.strip()

    if all_speakers:
        output["speakers"] = sorted(all_speakers)

    # 保留引擎内部执行标志
    for flag in ("_vad_internally_executed", "_alignment_internally_executed",
                 "_diarization_internally_executed"):
        if all(r.get(flag) for r in results):
            output[flag] = True

    return output
