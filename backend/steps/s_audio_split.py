"""s_audio_split: 音频切割 —— 按片段数量或固定时长把音频切成多段，也可按用户指定的
时间段区间截取单段，支持静音点切割。

与「视频切割」（``s_video_split``）同源实现，差别仅在于处理对象是音频：
产物为音频片段（``output/asplit_<node_id>_<序号>.<ext>``），并按需输出该片段的切割信息文本。
"""
import array
import json
import os
import subprocess
import wave
from typing import Callable, Optional

from backend.steps.base_step import BaseStep


def _resolve_path(value, task_dir: str = "") -> str:
    """把连线输入解析为存在的绝对路径（相对路径按 task_dir 解析）。"""
    if not value or not isinstance(value, str):
        return ""
    candidate = value.strip()
    if os.path.isabs(candidate) and os.path.isfile(candidate):
        return candidate
    if task_dir:
        rel = os.path.join(task_dir, candidate)
        if os.path.isfile(rel):
            return rel
    return ""


def _get_duration(file_path: str) -> float:
    """用 ffprobe 读取媒体时长（秒）。"""
    try:
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", file_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=15)
        if result.returncode == 0:
            info = json.loads(result.stdout)
            return float(info.get("format", {}).get("duration", 0))
    except Exception:
        pass
    return 0.0


def _to_analysis_wav(audio_path: str, output_path: str) -> bool:
    """把任意音频转成 16k 单声道 WAV，供静音点分析使用。"""
    from backend.utils.ffmpeg_guard import apply_resource_args
    cmd = apply_resource_args([
        "ffmpeg", "-y", "-i", audio_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        output_path,
    ])
    result = subprocess.run(cmd, capture_output=True, timeout=600)
    return result.returncode == 0 and os.path.isfile(output_path)


def _compute_rms_values(wav_path: str, window_ms: int = 100,
                        cancel_callback: Optional[Callable] = None) -> list:
    """按窗口（默认 100ms）计算 RMS 能量值，用于寻找静音点。"""
    try:
        with wave.open(wav_path, "rb") as wf:
            if wf.getsampwidth() != 2:
                return []
            sample_rate = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
    except Exception:
        return []

    if not raw or sample_rate <= 0:
        return []

    if cancel_callback is not None:
        cancel_callback()

    # 16bit 采样，按整样本对齐（丢弃可能的半个样本）
    usable_bytes = len(raw) - (len(raw) % 2)
    if usable_bytes <= 0:
        return []
    window_size = max(1, int(sample_rate * window_ms / 1000))

    try:
        import numpy as np
    except Exception:
        np = None

    if np is not None:
        samples = np.frombuffer(raw[:usable_bytes], dtype="<i2").astype("float64")
        frames = (len(samples) // window_size) * window_size
        if frames <= 0:
            return []
        blocks = samples[:frames].reshape(-1, window_size)
        return np.sqrt((blocks ** 2).mean(axis=1)).tolist()

    # 无 numpy 时退回纯 Python 实现
    samples = array.array("h")
    samples.frombytes(raw[:usable_bytes])
    rms_values = []
    for i in range(0, len(samples) - window_size + 1, window_size):
        chunk = samples[i:i + window_size]
        rms_values.append((sum(s * s for s in chunk) / len(chunk)) ** 0.5)
    return rms_values


def _find_silence_point(rms_values: list, target_sec: float, window_ms: int = 100,
                        search_range_sec: float = 10.0) -> float:
    """在 target_sec 附近 ±search_range_sec 内寻找能量最低（最接近静音）的时间点。"""
    if not rms_values:
        return target_sec

    target_idx = int(target_sec * 1000 / window_ms)
    search_range_idx = int(search_range_sec * 1000 / window_ms)
    start_idx = max(0, target_idx - search_range_idx)
    end_idx = min(len(rms_values) - 1, target_idx + search_range_idx)

    if start_idx >= end_idx:
        return target_sec

    min_idx = min(range(start_idx, end_idx + 1), key=lambda i: rms_values[i])
    return min_idx * window_ms / 1000.0


def _monotonic_points(points: list, duration: float, min_gap: float = 0.05) -> list:
    """把切割点规整为严格递增且落在 (0, duration) 内，避免产生零长/负长片段。"""
    result = []
    prev = 0.0
    for point in points:
        point = max(float(point), prev + min_gap)
        if point >= duration - min_gap:
            break
        result.append(point)
        prev = point
    return result


# 时间段区间支持的起止分隔符（半角/全角波浪线、破折号及「至/到」）
_RANGE_SEPARATORS = ("～", "~", "—", "–", "-", "至", "到")


def _parse_time_token(token: str) -> float:
    """解析单个时间值，支持 `90`（秒）与 `1:30`（分:秒）两种写法。"""
    token = str(token).strip()
    if not token:
        raise ValueError("时间段格式错误，请按 起始秒-结束秒 填写，如 30-90。")
    try:
        if ":" in token:
            total = 0.0
            for part in token.split(":"):
                total = total * 60 + float(part)
            return total
        return float(token)
    except ValueError:
        raise ValueError(f"无法解析时间值「{token}」，请按 起始秒-结束秒 填写，如 30-90。")


def _parse_time_range(value, duration: float) -> tuple:
    """把用户输入的时间段区间解析为 (start, end)，并按音频实际时长裁剪。

    支持 `30-90`、`30~90`、`1:30-2:00` 等写法。
    """
    text = str(value or "").strip()
    if not text:
        raise ValueError("请填写时间段，如 30-90（秒）。")

    parts = None
    for sep in _RANGE_SEPARATORS:
        if sep in text:
            parts = text.split(sep, 1)
            break
    if not parts:
        raise ValueError(f"时间段格式错误：「{text}」，请按 起始秒-结束秒 填写，如 30-90。")

    start = _parse_time_token(parts[0])
    end = _parse_time_token(parts[1])
    if start < 0 or end < 0:
        raise ValueError("时间段不能为负数。")
    if start >= duration:
        raise ValueError(f"起始时间 {start:.1f}s 超出音频时长 {duration:.1f}s。")

    end = min(end, duration)
    if end - start < 0.05:
        raise ValueError(f"时间段过短（{end - start:.2f}s），请调整区间。")
    return start, end


# 流复制裁剪失败时按输出扩展名重编码的兜底参数
_AUDIO_CODEC_ARGS = {
    ".mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
    ".m4a": ["-c:a", "aac", "-b:a", "192k"],
    ".aac": ["-c:a", "aac", "-b:a", "192k"],
    ".wav": ["-c:a", "pcm_s16le"],
    ".flac": ["-c:a", "flac"],
    ".ogg": ["-c:a", "libvorbis", "-q:a", "5"],
    ".opus": ["-c:a", "libopus", "-b:a", "128k"],
}


def _cut_audio(audio_path: str, output_path: str, start: float, duration: float) -> bool:
    """裁剪一段音频：优先流复制（快、无损），失败则按扩展名重编码兜底。"""
    from backend.utils.ffmpeg_guard import apply_resource_args

    def _run(codec_args: list) -> bool:
        if os.path.isfile(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass
        cmd = apply_resource_args([
            "ffmpeg", "-y",
            "-ss", f"{start:.3f}",
            "-i", audio_path,
            "-t", f"{duration:.3f}",
            *codec_args,
            "-avoid_negative_ts", "make_zero",
            output_path,
        ])
        result = subprocess.run(cmd, capture_output=True, timeout=600)
        return (
            result.returncode == 0
            and os.path.isfile(output_path)
            and os.path.getsize(output_path) > 0
        )

    if _run(["-c", "copy"]):
        return True
    return _run(_AUDIO_CODEC_ARGS.get(os.path.splitext(output_path)[1].lower(), []))


class S_AudioSplit(BaseStep):
    step_id = "s_audio_split"
    step_name = "音频切割"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        output_dir = os.path.join(task_dir, "output")
        if not os.path.isdir(output_dir):
            return False
        return any(f.startswith(f"asplit_{node_id}_") for f in os.listdir(output_dir))

    def validate_inputs(self, task_dir: str) -> bool:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        return bool(_resolve_path(step_inputs.get("audio", ""), task_dir))

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        # --- 1. 读取配置 ---
        split_mode = node_config.get("split_mode", "count")
        if isinstance(split_mode, list):
            split_mode = split_mode[0] if split_mode else "count"
        try:
            segment_count = max(1, int(float(node_config.get("segment_count", 2) or 2)))
        except (TypeError, ValueError):
            segment_count = 2
        try:
            segment_duration = float(node_config.get("segment_duration", 60) or 60)
        except (TypeError, ValueError):
            segment_duration = 60.0
        use_silence = bool(node_config.get("use_silence", False))
        try:
            output_index = int(float(node_config.get("output_index", 1) or 1))
        except (TypeError, ValueError):
            output_index = 1
        time_range = node_config.get("time_range", "")
        if isinstance(time_range, list):
            time_range = time_range[0] if time_range else ""

        # --- 2. 解析输入 ---
        audio_path = _resolve_path(step_inputs.get("audio", ""), task_dir)
        if not audio_path:
            raise FileNotFoundError("未连接音频输入。")

        # --- 3. 读取时长 ---
        duration = _get_duration(audio_path)
        if duration <= 0:
            raise ValueError("无法获取音频时长。")
        if callback:
            callback(10, f"音频时长: {duration:.1f}秒")

        # --- 4. 计算切割点（时间段模式由用户直接指定区间，无需计算切点）---
        is_range_mode = split_mode == "range"
        if is_range_mode:
            raw_points = []
        elif split_mode == "duration":
            if segment_duration <= 0:
                raise ValueError("每段时长必须大于 0。")
            raw_points = []
            t = segment_duration
            while t < duration:
                raw_points.append(t)
                t += segment_duration
        else:
            raw_points = [i * duration / segment_count for i in range(1, segment_count)]

        # --- 5. 按需吸附到静音点 ---
        if use_silence and raw_points:
            if callback:
                callback(20, "分析音频寻找静音点...")
            analysis_wav = os.path.join(task_dir, "cache", f"_asplit_audio_{node_id}.wav")
            os.makedirs(os.path.dirname(analysis_wav), exist_ok=True)
            if _to_analysis_wav(audio_path, analysis_wav):
                rms_values = _compute_rms_values(analysis_wav, cancel_callback=cancel_callback)
                if rms_values:
                    adjusted = []
                    for pt in raw_points:
                        adj = _find_silence_point(rms_values, pt)
                        adjusted.append(adj)
                        if callback:
                            callback(None, f"  切割点 {pt:.1f}s → {adj:.1f}s (静音)")
                    # 吸附后可能回退或越界，规整为严格递增
                    raw_points = _monotonic_points(adjusted, duration)

        # --- 6. 组装分段边界 ---
        if is_range_mode:
            # 用户指定单个区间，输出唯一一段
            range_start, range_end = _parse_time_range(time_range, duration)
            segments = [(range_start, range_end)]
            output_index = 1
        else:
            boundaries = [0.0] + raw_points + [duration]
            segments = [(boundaries[i], boundaries[i + 1]) for i in range(len(boundaries) - 1)]

        # --- 7. 校验输出序号 ---
        if output_index < 1 or output_index > len(segments):
            raise ValueError(f"序号 {output_index} 超出范围 (共 {len(segments)} 段)。")

        # --- 8. 裁剪指定分段 ---
        start, end = segments[output_index - 1]
        seg_duration = end - start
        if callback:
            if is_range_mode:
                callback(70, f"切割时间段: {start:.1f}s ~ {end:.1f}s")
            else:
                callback(70, f"切割第 {output_index}/{len(segments)} 段: {start:.1f}s ~ {end:.1f}s")

        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        ext = os.path.splitext(audio_path)[1] or ".mp3"
        output_filename = f"asplit_{node_id}_{output_index}{ext}"
        output_path = os.path.join(output_dir, output_filename)

        if cancel_callback is not None:
            cancel_callback()

        if not _cut_audio(audio_path, output_path, start, seg_duration):
            raise RuntimeError("ffmpeg 音频切割失败。")

        if callback:
            callback(100, f"完成: {output_filename}")

        return {
            "artifacts": [f"output/{output_filename}"],
            "outputs": {
                "audio": f"output/{output_filename}",
                "text": (
                    f"时间段 {start:.1f}s ~ {end:.1f}s (时长 {seg_duration:.1f}s)"
                    if is_range_mode
                    else f"第{output_index}/{len(segments)}段 {start:.1f}s ~ {end:.1f}s (时长 {seg_duration:.1f}s)"
                ),
            },
        }
