"""s_video_frame_extract: Extract a single frame from video at a specified time point."""
import json
import os
import subprocess
from typing import Callable, Optional

from backend.steps.base_step import BaseStep


def _parse_srt(srt_path: str) -> list:
    """Parse SRT file into list of {start, end, text} dicts (times in seconds)."""
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read().strip()
    if not content:
        return []

    entries = []
    blocks = content.split("\n\n")
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        if len(lines) < 3:
            continue
        ts = lines[1]
        if " --> " not in ts:
            continue
        start_str, end_str = ts.split(" --> ")

        def _parse_ts(value):
            value = value.replace(",", ".")
            parts = value.strip().split(":")
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])

        entries.append({
            "start": _parse_ts(start_str),
            "end": _parse_ts(end_str),
            "text": "\n".join(lines[2:]).strip(),
        })
    return entries


def _parse_subtitle_json(json_path: str) -> list:
    """Parse subtitle JSON file into list of {start, end, text} dicts (times in seconds).

    Supports both a plain list of entries and wrapper shapes like
    {"segments": [...]} / {"items": [...]} / {"subtitles": [...]}.
    Entry key aliases: start/begin/start_time, end/end_time/finish, text/content/src/translation.
    Returns [] on any parse failure or invalid shape.
    """
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []

    if isinstance(data, dict):
        for key in ("segments", "items", "subtitles", "entries"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            return []
    if not isinstance(data, list):
        return []

    entries = []
    for item in data:
        if not isinstance(item, dict):
            continue
        start = item.get("start", item.get("begin", item.get("start_time")))
        end = item.get("end", item.get("end_time", item.get("finish")))
        if start is None or end is None:
            continue
        try:
            start_f, end_f = float(start), float(end)
        except (ValueError, TypeError):
            continue
        text = item.get("text", item.get("content", item.get("src", item.get("translation", ""))))
        entries.append({"start": start_f, "end": end_f, "text": str(text or "")})
    return entries


def _resolve_subtitles(task_dir: str, step_inputs: dict) -> list:
    """Resolve subtitle entries from the node input or from cache/output artifacts.

    Returns [] when no usable subtitle data is available (never raises), so callers
    can gracefully fall back to frame extraction without subtitle avoidance.
    """
    candidates = []
    raw = step_inputs.get("srt", "") or step_inputs.get("json", "")
    if raw:
        p = raw if os.path.isabs(raw) else os.path.join(task_dir, raw)
        candidates.append(p)

    # 回退扫描任务目录中常见的字幕产物（srt 或 json）
    for folder in ("cache", "output"):
        base = os.path.join(task_dir, folder)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            low = name.lower()
            if low.startswith("input_subtitle") or "subtitle" in low or low.endswith(".srt"):
                candidates.append(os.path.join(base, name))

    seen = set()
    for path in candidates:
        if not os.path.isfile(path) or path in seen:
            continue
        seen.add(path)
        try:
            if path.lower().endswith(".srt"):
                entries = _parse_srt(path)
            elif path.lower().endswith(".json"):
                entries = _parse_subtitle_json(path)
            else:
                entries = _parse_srt(path) or _parse_subtitle_json(path)
        except Exception:
            continue
        if entries:
            return entries
    return []


def _get_video_duration(video_path: str) -> float:
    """Get video duration in seconds using ffprobe, with a plain-text fallback."""
    def _run(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except FileNotFoundError:
            raise RuntimeError("ffprobe not found. Please install ffmpeg.")
        except subprocess.TimeoutExpired:
            raise RuntimeError("ffprobe timed out after 60 seconds")

    result = _run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video_path])
    stdout = result.stdout
    if result.returncode == 0 and stdout and stdout.strip():
        try:
            info = json.loads(stdout)
            duration = info.get("format", {}).get("duration")
            if duration is not None:
                return float(duration)
        except (ValueError, TypeError, json.JSONDecodeError):
            pass

    # 回退：以纯文本形式读取时长（适用于 JSON 输出为空/异常的情况）
    fallback = _run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ])
    text = (fallback.stdout or "").strip()
    if fallback.returncode == 0 and text:
        try:
            return float(text)
        except ValueError:
            pass

    stderr = (result.stderr or fallback.stderr or "").strip()
    detail = stderr or (stdout or "").strip() or "ffprobe 无输出"
    raise RuntimeError(f"无法获取视频时长: {detail[:300]}")


class S_VideoFrameExtract(BaseStep):
    step_id = "s_video_frame_extract"
    step_name = "视频抽帧"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        path = os.path.join(task_dir, "cache", f"key_frame_{node_id}.png")
        return os.path.exists(path)

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        # --- 1. Get video path ---
        video_source = node_config.get("video_source", "input_node")
        # chips returns array
        if isinstance(video_source, list):
            video_source = video_source[0] if video_source else "input_node"

        video_path = None
        if video_source == "connection":
            raw = step_inputs.get("video", "")
            if raw:
                if os.path.isabs(raw) and os.path.isfile(raw):
                    video_path = raw
                elif os.path.isfile(os.path.join(task_dir, raw)):
                    video_path = os.path.join(task_dir, raw)

        if not video_path:
            # 回退：优先检查 step_inputs 中的 video，再扫描 cache 目录
            raw = step_inputs.get("video", "")
            if raw:
                p = raw if os.path.isabs(raw) else os.path.join(task_dir, raw)
                if os.path.isfile(p):
                    video_path = p

        if not video_path:
            cache_dir = os.path.join(task_dir, "cache")
            if os.path.isdir(cache_dir):
                for f in sorted(os.listdir(cache_dir)):
                    if f.startswith("input_video") and f.endswith(('.mp4', '.mkv', '.webm', '.avi', '.mov')):
                        video_path = os.path.join(cache_dir, f)
                        break
                if not video_path:
                    for f in sorted(os.listdir(cache_dir)):
                        if f.endswith(('.mp4', '.mkv', '.webm', '.avi', '.mov')):
                            video_path = os.path.join(cache_dir, f)
                            break

        if not video_path or not os.path.isfile(video_path):
            raise FileNotFoundError("No video file found. Connect a video input or ensure input video exists in cache.")

        if callback:
            callback(10, f"Video: {os.path.basename(video_path)}")

        # --- 2. Get video duration and resolve time point ---
        duration = _get_video_duration(video_path)

        raw_time = node_config.get("time_point", 1.0)
        try:
            time_point = float(raw_time)
        except (ValueError, TypeError):
            time_point = 1.0

        # Handle time mode
        time_mode = node_config.get("time_mode", "positive")
        if isinstance(time_mode, list):
            time_mode = time_mode[0] if time_mode else "positive"

        if time_mode == "negative":
            time_point = duration - time_point

        # Clamp to valid range
        time_point = max(0.0, min(time_point, duration - 0.01))

        if callback:
            callback(30, f"Time point: {time_point:.2f}s (duration: {duration:.2f}s)")

        # --- 3. Avoid subtitles if enabled ---
        avoid_subtitles = node_config.get("avoid_subtitles", False)
        if avoid_subtitles:
            try:
                subtitles = _resolve_subtitles(task_dir, step_inputs)
            except Exception as exc:
                subtitles = []
                if callback:
                    callback(40, f"字幕解析失败，回退为不避开字幕：{exc}")

            if subtitles:
                # Check if time_point falls within any subtitle
                for idx, sub in enumerate(subtitles):
                    if sub["start"] <= time_point <= sub["end"]:
                        # Find gap between current subtitle end and next subtitle start
                        gap = 3.0  # default if no next subtitle
                        if idx + 1 < len(subtitles):
                            gap = subtitles[idx + 1]["start"] - sub["end"]
                        # Use min(gap/2, 3.0) as offset, ensure positive
                        offset = min(max(gap, 0) / 2.0, 3.0)
                        new_time = sub["end"] + offset
                        if new_time < duration:
                            if callback:
                                callback(40, f"Subtitle hit [{sub['start']:.1f}-{sub['end']:.1f}], gap={gap:.1f}s, adjusting to {new_time:.2f}s")
                            time_point = new_time
                        else:
                            # Fallback: move to start - 0.1s
                            new_time = max(0, sub["start"] - 0.1)
                            if callback:
                                callback(40, f"Subtitle hit, adjusted end exceeds duration, fallback to {new_time:.2f}s")
                            time_point = new_time
                        break
            elif callback:
                callback(40, "未找到有效字幕数据，跳过避开字幕")

        # --- 4. Extract frame using ffmpeg ---
        cache_dir = os.path.join(task_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        output_path = os.path.join(cache_dir, f"key_frame_{node_id}.png")

        if callback:
            callback(60, f"Extracting frame at {time_point:.2f}s...")

        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{time_point:.3f}",
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", "2",
            output_path,
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                error_msg = result.stderr[:500] if result.stderr else "Unknown error"
                raise RuntimeError(f"ffmpeg frame extraction failed: {error_msg}")
        except FileNotFoundError:
            raise RuntimeError("ffmpeg not found. Please install ffmpeg.")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Frame extraction timed out after 60 seconds")

        if not os.path.exists(output_path):
            raise RuntimeError(f"Frame extraction produced no output file: {output_path}")

        if callback:
            callback(100, f"Frame saved: key_frame_{node_id}.png")

        return {
            "artifacts": [f"cache/key_frame_{node_id}.png"],
            "outputs": {
                "image": f"cache/key_frame_{node_id}.png",
            },
        }
