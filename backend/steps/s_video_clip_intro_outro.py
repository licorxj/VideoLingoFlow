"""s_video_clip_intro_outro: 切割视频片头片尾。

从主视频中裁剪掉片头（开头 N 秒）与片尾，使用 ffmpeg 流拷贝（不重新编码）快速输出三段视频：

- 裁剪后的主视频（main）
- 被切下的片头片段（intro）
- 被切下的片尾片段（outro）

片头：正数秒，从开头切掉 intro_duration 秒。
片尾切割点：正数 N → 在绝对时间 N 处切断（N 之后为片尾）；负数 -N → 从结尾倒数 N 秒处切断。

勾选「片头」/「片尾」执行对应裁剪；两者均未勾选则直接透传输入到输出（不复制）。
产物统一存放于任务目录 cache/video_clip/ 下。
"""
import json
import os
import subprocess
from typing import Callable, Optional

from backend.steps.base_step import BaseStep, find_artifact


def _resolve_path(value, task_dir: str = "") -> str:
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


def _coerce_bool(val, default: bool = False) -> bool:
    if val is None or val == "":
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _get_duration(file_path: str) -> float:
    """使用 ffprobe 获取视频时长（秒）。"""
    try:
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", file_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            info = json.loads(result.stdout)
            return float(info.get("format", {}).get("duration", 0))
    except Exception:
        pass
    return 0.0


def _parse_split_point(raw: str) -> float:
    """解析切割点（带符号）：

    - 纯秒数：正数表示绝对时间戳（从该秒处切断），负数表示倒数（从结尾倒数 |v| 秒处切断）
    - 时间戳 'HH:MM:SS' / 'MM:SS' / 'SS'：视为正数（绝对值）

    返回带符号的秒值。
    """
    if raw is None:
        return 0.0
    text = str(raw).strip()
    if not text:
        return 0.0
    # 时间戳格式（含冒号）→ 正数
    if ":" in text:
        parts = text.split(":")
        try:
            parts_f = [float(p) for p in parts]
        except ValueError:
            return 0.0
        seconds = 0.0
        for p in parts_f:
            seconds = seconds * 60 + p
        return seconds
    try:
        return float(text)
    except ValueError:
        return 0.0


def _get_keyframe_times(video_path: str) -> list:
    """获取视频所有关键帧（I 帧）的时间戳（秒，0 起点）。失败时返回空列表。"""
    try:
        cmd = [
            "ffprobe", "-v", "quiet",
            "-skip_frame", "nokey", "-select_streams", "v:0",
            "-show_entries", "frame=pts_time", "-of", "csv=p=0",
            video_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            times = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if line:
                    try:
                        times.append(float(line))
                    except ValueError:
                        continue
            return sorted(times)
    except Exception:
        pass
    return []


def _first_keyframe_at_or_after(kfs: list, t: float) -> float:
    """返回第一个 >= t 的关键帧时间；不存在则返回 t 本身（交由 ffmpeg 兜底对齐）。"""
    for kf in kfs:
        if kf >= t - 1e-3:
            return kf
    return t


def _clip_video(video_path: str, output_path: str, start: float, end: float) -> bool:
    """使用 ffmpeg 流拷贝裁剪 [start, end] 区间（快速、不重新编码）。"""
    if end <= start:
        return False
    from backend.utils.ffmpeg_guard import apply_resource_args
    cmd = apply_resource_args([
        "ffmpeg", "-y",
        "-ss", f"{start:.3f}",
        "-to", f"{end:.3f}",
        "-i", video_path,
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        output_path,
    ], mux_queue=4096)
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=600)
    except Exception:
        return False
    return result.returncode == 0 and os.path.isfile(output_path)


class S_VideoClipIntroOutro(BaseStep):
    step_id = "s_video_clip_intro_outro"
    step_name = "切割片头片尾"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        clip_dir = os.path.join(task_dir, "cache", "video_clip")
        if not os.path.isdir(clip_dir):
            return False
        return any(f.startswith(f"main_{node_id}.") for f in os.listdir(clip_dir))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        # ── 1. 读取配置 ──
        trim_intro = _coerce_bool(node_config.get("trim_intro"), False)
        trim_outro = _coerce_bool(node_config.get("trim_outro"), False)
        intro_duration = _parse_split_point(node_config.get("intro_duration", "0"))
        outro_duration = _parse_split_point(node_config.get("outro_duration", "0"))

        # ── 2. 解析主视频输入 ──
        raw_video = step_inputs.get("video", "")
        if isinstance(raw_video, list):
            raw_video = raw_video[0] if raw_video else ""
        video_path = _resolve_path(raw_video, task_dir)
        if not video_path:
            raise FileNotFoundError("未连接主视频输入，或主视频文件不存在。")

        # ── 3. 获取时长 ──
        duration = _get_duration(video_path)
        if duration <= 0:
            raise ValueError("无法获取主视频时长，无法切割片头片尾。")
        if callback:
            callback(10, f"主视频时长: {duration:.1f}s（片头={trim_intro}, 片尾={trim_outro}）")

        # ── 3.5 未勾选任何裁剪 → 直接透传输入到输出（不复制） ──
        if not trim_intro and not trim_outro:
            if callback:
                callback(100, "未勾选任何裁剪，直接透传主视频")
            return {
                "artifacts": [],
                "outputs": {"video": raw_video},
            }

        # ── 4. 计算切割点 ──
        # 片头切割点（主视频起点）：正数秒，从开头切掉 intro_duration 秒
        intro_point = min(max(intro_duration, 0.0), duration) if trim_intro else 0.0
        # 片尾切割点（主视频终点）：
        #   正数 v  → 在绝对时间 v 处切断（v 之后为片尾）
        #   负数 -v → 从结尾倒数 v 秒处切断（duration - v 之后为片尾）
        if trim_outro:
            if outro_duration >= 0:
                outro_point = outro_duration
            else:
                outro_point = duration + outro_duration  # duration - |v|
            outro_point = min(max(outro_point, 0.0), duration)
        else:
            outro_point = duration

        # 顺序校验：片头切割点必须早于片尾切割点
        if intro_point >= outro_point:
            raise ValueError(
                f"片头切割点({intro_point:.1f}s) 晚于或等于 片尾切割点({outro_point:.1f}s)，"
                f"请调小片头时长或片尾时长，确保片头在片尾之前。"
            )

        # 关键帧对齐：流拷贝(-c copy)下 -ss/-to 会吸附到关键帧(GOP)。
        # 若主视频结尾与片尾开头落在同一 GOP 内、分属不同关键帧，两段会重叠一部分主视频。
        # 修复：把切割边界统一对齐到「边界处首个关键帧」——主视频结尾 === 片尾开头 === 该片头帧，
        # 片尾从该关键帧「到结尾」，主视频止于该片头帧，消除重叠（也保证主视频与片头片段不重叠）。
        kfs = _get_keyframe_times(video_path)
        intro_kf = _first_keyframe_at_or_after(kfs, intro_point) if (trim_intro and intro_point > 0) else 0.0
        outro_kf = _first_keyframe_at_or_after(kfs, outro_point) if (trim_outro and outro_point < duration) else duration

        main_start = intro_kf
        main_end = outro_kf

        clip_dir = os.path.join(task_dir, "cache", "video_clip")
        os.makedirs(clip_dir, exist_ok=True)
        ext = os.path.splitext(video_path)[1] or ".mp4"

        artifacts = []
        outputs = {}

        # ── 5. 输出裁剪后的主视频 ──
        if callback:
            callback(40, f"生成主视频: {main_start:.1f}s ~ {main_end:.1f}s")
        main_path = os.path.join(clip_dir, f"main_{node_id}{ext}")
        if not _clip_video(video_path, main_path, main_start, main_end):
            raise RuntimeError("ffmpeg 主视频切割失败。")
        rel_main = os.path.relpath(main_path, task_dir).replace("\\", "/")
        artifacts.append(rel_main)
        outputs["video"] = rel_main

        # ── 6. 片头片段（[0, intro_kf]） ──
        if trim_intro and intro_point > 0:
            if callback:
                callback(70, f"生成片头片段: 0.0s ~ {intro_kf:.1f}s")
            intro_path = os.path.join(clip_dir, f"intro_{node_id}{ext}")
            if _clip_video(video_path, intro_path, 0.0, intro_kf):
                rel_intro = os.path.relpath(intro_path, task_dir).replace("\\", "/")
                artifacts.append(rel_intro)
                outputs["intro"] = rel_intro

        # ── 7. 片尾片段（[outro_kf, duration]，从关键帧到结尾） ──
        if trim_outro and outro_point < duration:
            if callback:
                callback(85, f"生成片尾片段: {outro_kf:.1f}s ~ {duration:.1f}s")
            outro_path = os.path.join(clip_dir, f"outro_{node_id}{ext}")
            if _clip_video(video_path, outro_path, outro_kf, duration):
                rel_outro = os.path.relpath(outro_path, task_dir).replace("\\", "/")
                artifacts.append(rel_outro)
                outputs["outro"] = rel_outro

        if callback:
            callback(100, "片头片尾切割完成")

        return {
            "artifacts": artifacts,
            "outputs": outputs,
        }
