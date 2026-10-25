"""s_video_shot_split: 按镜头切换切割视频（PySceneDetect 检测 + ffmpeg 切割）。

按画面「镜头切换点」把一条视频切成多个镜头片段，不依赖字幕/音频：

- 检测：复用 PySceneDetect（https://github.com/Breakthrough/PySceneDetect，BSD-3）的
  场景检测器，逐帧比对画面变化找出切点（content/adaptive/threshold/histogram/hash 五种算法）。
- 切割：按切点区间调用 ffmpeg 输出独立片段文件；默认重编码保证帧精确，
  可切换为流拷贝（秒级完成，但起点会对齐到最近关键帧）。

产物（均带 node_id 后缀，重复运行不会互相覆盖）：
- ``cache/shot_clips_{node_id}/``       ：各镜头片段，按 000、001… 顺序命名
- ``cache/shot_clips_{node_id}.json``   ：切割信息（含检测参数、镜头数与每个镜头的起止/帧号/路径）

输出端口：json（切割信息）/ videos（片段路径列表）/ count（镜头数文本）。
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from typing import Callable, Optional

from backend.steps.base_step import BaseStep
from backend.utils.video_encoder import build_video_encode_args

# 视为视频文件的扩展名（连线输入识别）
_VIDEO_EXTS = (
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".wmv", ".m4v", ".mpg", ".mpeg", ".ts",
)

# 输出格式 -> (扩展名, 视频编码器, 音频编码器, CRF/CQ)
_VIDEO_OUT_FORMATS = {
    "mp4": ("mp4", "libx264", "aac", 23),
    "mkv": ("mkv", "libx264", "aac", 23),
    "mov": ("mov", "libx264", "aac", 23),
    "webm": ("webm", "libvpx-vp9", "libopus", 30),
}

# 检测算法 -> (默认阈值, 面板文案)
_DETECTORS = {
    "content": 27.0,      # ContentDetector：相邻帧 HSV+边缘差异，默认最通用
    "adaptive": 3.0,      # AdaptiveDetector：带滚动窗口，强运镜/快速移动更稳
    "threshold": 12.0,    # ThresholdDetector：亮度阈值，专治淡入淡出转场
    "histogram": 0.2,     # HistogramDetector：颜色直方图差异，抗轻微运动
    "hash": 0.35,         # HashDetector：感知哈希，画面相似度
}

# 检测阶段进度区间（切割阶段接在后面）
_DETECT_PCT_START = 5
_DETECT_PCT_SPAN = 50


def _first_value(raw):
    """连线输入可能是字符串 / 列表 / 多级列表，取第一个非空项。"""
    if isinstance(raw, (list, tuple)):
        for item in raw:
            text = _first_value(item)
            if text:
                return text
        return ""
    return str(raw).strip() if raw is not None else ""


def _as_float(value, default: float) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default: int) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _probe_video(video_path: str) -> dict:
    """用 ffprobe 取时长 / 帧率，拿不到时返回 0（调用方自行兜底）。"""
    info = {"duration": 0.0, "fps": 0.0}
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format", video_path],
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
        )
        data = json.loads(res.stdout or "{}")
        try:
            info["duration"] = float((data.get("format") or {}).get("duration") or 0.0)
        except (TypeError, ValueError):
            pass
        for stream in data.get("streams", []):
            if stream.get("codec_type") != "video":
                continue
            rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/0"
            try:
                num, den = str(rate).split("/")
                fps = float(num) / float(den) if float(den) else 0.0
            except (ValueError, ZeroDivisionError):
                fps = 0.0
            if fps > 0:
                info["fps"] = fps
            break
    except Exception:
        pass
    return info


def _build_detector(kind: str, threshold: Optional[float], min_scene_len: int):
    """按算法名构造 PySceneDetect 检测器（threshold 为空时用该算法默认值）。"""
    from scenedetect.detectors import (
        AdaptiveDetector,
        ContentDetector,
        HashDetector,
        HistogramDetector,
        ThresholdDetector,
    )

    kind = kind if kind in _DETECTORS else "content"
    thr = _DETECTORS[kind] if threshold is None else float(threshold)
    min_len = max(1, int(min_scene_len))

    if kind == "adaptive":
        return AdaptiveDetector(adaptive_threshold=thr, min_scene_len=min_len)
    if kind == "threshold":
        return ThresholdDetector(threshold=thr, min_scene_len=min_len)
    if kind == "histogram":
        return HistogramDetector(threshold=thr, min_scene_len=min_len)
    if kind == "hash":
        return HashDetector(threshold=thr, min_scene_len=min_len)
    return ContentDetector(threshold=thr, min_scene_len=min_len)


def _detect_scenes(video_path: str, detector, frame_skip: int,
                   callback: Optional[Callable], cancel_callback: Optional[Callable]):
    """执行镜头检测，返回 (scenes, total_frames)。

    scenes 为 [(start_sec, end_sec, start_frame, end_frame), ...]，已保证覆盖整段视频
    （没有切点时返回单个覆盖全片的镜头）。
    检测期间由守护线程按 ``video.position`` 上报进度，并在取消时调用 SceneManager.stop()。
    """
    from scenedetect import SceneManager, open_video

    video = open_video(video_path)
    try:
        try:
            total_frames = int(video.duration.frame_num) if video.duration is not None else 0
        except Exception:
            total_frames = 0
        fps = float(video.frame_rate or 0.0)

        manager = SceneManager()
        manager.add_detector(detector)

        stop_evt = threading.Event()
        state = {"cancel": False, "last_pct": -1}

        def _watch():
            """后台进度/取消探针：每 0.5s 读一次解码位置。"""
            while not stop_evt.wait(0.5):
                if cancel_callback is not None:
                    try:
                        if cancel_callback():
                            state["cancel"] = True
                            manager.stop()
                            return
                    except Exception:
                        pass
                if callback is None or total_frames <= 0:
                    continue
                try:
                    current = float(video.position.frame_num)
                except Exception:
                    continue
                pct = _DETECT_PCT_START + int(
                    _DETECT_PCT_SPAN * min(1.0, current / total_frames)
                )
                if pct == state["last_pct"]:
                    continue
                state["last_pct"] = pct
                try:
                    callback(pct, f"镜头检测中 {current:.0f}/{total_frames} 帧")
                except Exception:
                    pass

        watcher = threading.Thread(target=_watch, name="shot-split-watch", daemon=True)
        watcher.start()
        try:
            manager.detect_scenes(video=video, frame_skip=max(0, int(frame_skip)))
        finally:
            stop_evt.set()

        if state["cancel"]:
            from backend.control_plane.runtime import TaskCancelledError

            raise TaskCancelledError("user_requested")

        raw = manager.get_scene_list(start_in_scene=True)
        scenes = []
        for start_tc, end_tc in raw:
            start_sec = float(start_tc.seconds)
            end_sec = float(end_tc.seconds)
            if end_sec - start_sec <= 0:
                continue
            scenes.append((start_sec, end_sec, int(start_tc.frame_num), int(end_tc.frame_num)))

        # 极端情况兜底：检测不到任何镜头时按整段一个镜头处理
        if not scenes and total_frames > 0 and fps > 0:
            scenes = [(0.0, total_frames / fps, 0, total_frames)]
        return scenes, total_frames
    finally:
        try:
            del video
        except Exception:
            pass


class S_VideoShotSplit(BaseStep):
    step_id = "video_shot_split"
    step_name = "按镜头切割视频"
    dependencies: list = []
    artifacts: list = []

    # ------------------------------------------------------------------
    # 路径与产物
    # ------------------------------------------------------------------
    def _nid(self) -> str:
        # 注意：框架会把节点 id 直接写入 self._node_id（实例属性），
        # 因此这里不能用 _node_id 作方法名，否则与注入的属性同名互相覆盖。
        return getattr(self, "_node_id", "") or "node"

    def _result_rel(self) -> str:
        return f"cache/shot_clips_{self._nid()}.json"

    def _clips_rel_dir(self) -> str:
        return f"cache/shot_clips_{self._nid()}"

    def _load_result(self, task_dir: str) -> Optional[dict]:
        path = os.path.join(task_dir, self._result_rel())
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def check_artifact(self, task_dir: str) -> bool:
        data = self._load_result(task_dir)
        if not data:
            return False
        clips = data.get("clips") or []
        return bool(clips) and all(
            os.path.isfile(os.path.join(task_dir, c.get("path", ""))) for c in clips
        )

    def rollback(self, task_dir: str) -> None:
        """清理本节点产物：切割信息 json + 片段目录（重跑前调用）。"""
        import shutil

        path = os.path.join(task_dir, self._result_rel())
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass
        clip_dir = os.path.join(task_dir, self._clips_rel_dir())
        if os.path.isdir(clip_dir):
            shutil.rmtree(clip_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # 输入解析
    # ------------------------------------------------------------------
    def _resolve_video_path(self, task_dir: str) -> str:
        """视频输入：先看 video 端口，再看其它端口里的视频文件，最后回退 cache。"""
        inputs = getattr(self, "_step_inputs", {}) or {}

        def _as_path(raw) -> str:
            text = _first_value(raw)
            if not text:
                return ""
            candidate = text if os.path.isabs(text) else os.path.join(task_dir, text)
            return candidate if os.path.isfile(candidate) else ""

        direct = _as_path(inputs.get("video"))
        if direct:
            return direct
        for key, value in inputs.items():
            if key in ("json", "srt", "subtitle"):
                continue
            hit = _as_path(value)
            if hit and hit.lower().endswith(_VIDEO_EXTS):
                return hit

        cache_dir = os.path.join(task_dir, "cache")
        if not os.path.isdir(cache_dir):
            return ""
        names = sorted(os.listdir(cache_dir))
        for name in names:
            if name.startswith("input_video") and name.lower().endswith(_VIDEO_EXTS):
                return os.path.join(cache_dir, name)
        for name in names:
            if name.lower().endswith(_VIDEO_EXTS):
                return os.path.join(cache_dir, name)
        return ""

    def validate_inputs(self, task_dir: str) -> bool:
        return bool(self._resolve_video_path(task_dir))

    # ------------------------------------------------------------------
    # 切割
    # ------------------------------------------------------------------
    @staticmethod
    def _cut_cmd(video_path: str, out_path: str, start: float, duration: float,
                 cut_mode: str, vid_codec: str, aud_codec: str, crf: int,
                 threads: int) -> list:
        """组装单段切割命令。

        - 重编码：``-ss`` 前置 + 重新编码，帧精确（默认）
        - 流拷贝：``-c copy``，秒级完成但起点对齐到最近关键帧（有轻微偏移）
        """
        from backend.utils.ffmpeg_guard import resource_args

        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{max(0.0, start):.3f}",
            "-i", video_path,
            "-t", f"{max(0.01, duration):.3f}",
            "-map", "0:v:0", "-map", "0:a?",
        ]
        if cut_mode == "copy":
            cmd += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
        else:
            # 全局「使用显卡加速 (NVENC)」开启时自动改用硬编码
            cmd += build_video_encode_args(vid_codec, crf=crf) + ["-c:a", aud_codec]
            if out_path.lower().endswith((".mp4", ".mov", ".m4v")):
                cmd += ["-movflags", "+faststart"]
        cmd += resource_args(threads=threads or None)
        cmd += ["-progress", "pipe:1", "-nostats", out_path]
        return cmd

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def run(self, task_dir, callback=None, cancel_callback=None):
        from backend.utils.ffmpeg_guard import adaptive_timeout, ensure_disk_space
        from backend.utils.video_ops import run_ffmpeg_with_progress

        config = getattr(self, "_node_config", {}) or {}

        try:
            import scenedetect  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "按镜头切割视频需要 PySceneDetect 库：pip install scenedetect"
            ) from exc

        # ---- 1. 配置解析 ----
        detector_kind = str(config.get("detector") or "content").strip().lower()
        if detector_kind not in _DETECTORS:
            detector_kind = "content"

        raw_threshold = config.get("threshold")
        threshold = None
        if raw_threshold not in (None, "", 0, "0"):
            threshold = _as_float(raw_threshold, _DETECTORS[detector_kind])

        min_scene_sec = max(0.0, _as_float(config.get("min_scene_sec"), 1.0))
        frame_skip = max(0, _as_int(config.get("frame_skip"), 0))
        max_clips = max(1, _as_int(config.get("max_clips"), 300))
        cut_mode = str(config.get("cut_mode") or "reencode").strip().lower()
        if cut_mode not in ("reencode", "copy"):
            cut_mode = "reencode"
        output_format = str(config.get("output_format") or "mp4").strip().lower()
        quality = str(config.get("quality") or "medium").strip().lower()
        threads = max(0, _as_int(config.get("ffmpeg_threads"), 0))

        # ---- 2. 输入视频 ----
        video_path = self._resolve_video_path(task_dir)
        if not video_path:
            raise FileNotFoundError(
                "未找到输入视频：请把上游视频端口连接到本节点的「视频」输入"
            )

        probe = _probe_video(video_path)
        video_duration = probe["duration"]
        fps = probe["fps"] or 25.0

        if callback:
            try:
                callback(2, f"输入视频：{os.path.basename(video_path)}"
                            f"（{video_duration:.1f}s @ {fps:.3f}fps）")
            except Exception:
                pass

        # ---- 3. 镜头检测 ----
        min_scene_len = max(1, int(round(min_scene_sec * fps)))
        detector = _build_detector(detector_kind, threshold, min_scene_len)
        effective_threshold = _DETECTORS[detector_kind] if threshold is None else threshold

        if callback:
            try:
                callback(4, f"镜头检测开始（算法 {detector_kind}，阈值 {effective_threshold}，"
                            f"最小镜头 {min_scene_sec:.2f}s）")
            except Exception:
                pass

        scenes, total_frames = _detect_scenes(
            video_path, detector, frame_skip, callback, cancel_callback
        )
        if not scenes:
            raise RuntimeError(
                "未检测到任何镜头区间：请确认输入视频可正常解码（可用其它播放器检查）"
            )
        if len(scenes) > max_clips:
            head = "、".join(f"{s[0]:.1f}s" for s in scenes[:5])
            raise RuntimeError(
                f"检测到 {len(scenes)} 个镜头，超过节点上限 {max_clips} 个。"
                f"可调大「最多镜头数」，或提高「检测阈值」/「最小镜头长度」以减少误切"
                f"（前几个切点：{head}…）。"
            )

        if callback:
            try:
                callback(_DETECT_PCT_START + _DETECT_PCT_SPAN,
                         f"检测完成：共 {len(scenes)} 个镜头，开始切割")
            except Exception:
                pass

        # ---- 4. 准备输出目录（重跑先清空）----
        self.rollback(task_dir)
        clip_dir_abs = os.path.join(task_dir, self._clips_rel_dir())
        os.makedirs(clip_dir_abs, exist_ok=True)

        # ---- 5. 扩展名与编码参数 ----
        src_ext = os.path.splitext(video_path)[1].lower()
        if cut_mode == "copy":
            # 流拷贝必须与源容器兼容，直接沿用源扩展名（非常规容器回退 mp4）
            ext = src_ext.lstrip(".") if src_ext in _VIDEO_EXTS else "mp4"
            vid_codec, aud_codec, crf = "copy", "copy", 0
        else:
            ext, vid_codec, aud_codec, crf = _VIDEO_OUT_FORMATS.get(
                output_format, _VIDEO_OUT_FORMATS["mp4"]
            )
            crf = {"high": 18, "medium": 23, "low": 28}.get(quality, crf)

        # 磁盘余量预检：需要落 N 段近似等长的片段，量级与源文件相当
        try:
            source_bytes = os.path.getsize(video_path)
            if cut_mode != "copy":
                ensure_disk_space(task_dir, source_bytes)
        except OSError:
            pass

        # ---- 6. 逐镜头切割 ----
        clips: list = []
        total = len(scenes)
        for index, (start_sec, end_sec, start_frame, end_frame) in enumerate(scenes):
            if cancel_callback is not None and cancel_callback():
                from backend.control_plane.runtime import TaskCancelledError

                raise TaskCancelledError("user_requested")

            duration = max(0.0, end_sec - start_sec)
            if duration <= 0.01:
                continue

            clip_name = f"{index:03d}.{ext}"
            rel_path = f"{self._clips_rel_dir()}/{clip_name}"
            abs_path = os.path.join(task_dir, rel_path)

            cmd = self._cut_cmd(
                video_path, abs_path, start_sec, duration,
                cut_mode, vid_codec, aud_codec, crf, threads,
            )

            base_pct = _DETECT_PCT_START + _DETECT_PCT_SPAN + 1
            span = (98 - base_pct) / max(1, total)

            def _seg_progress(pct, _msg=None, _idx=index, _base=base_pct, _span=span):
                if not callback:
                    return
                try:
                    callback(int(_base + _span * _idx + _span * pct / 100.0),
                             f"切割镜头 {_idx + 1}/{total}")
                except Exception:
                    pass

            try:
                run_ffmpeg_with_progress(
                    cmd, duration, _seg_progress, cancel_callback,
                    timeout=adaptive_timeout(duration, minimum=300),
                    label=f"切割镜头 {index + 1}",
                )
            except FileNotFoundError:
                raise RuntimeError("未找到 ffmpeg，请先安装 ffmpeg 并确保在 PATH 中")

            if not os.path.isfile(abs_path) or os.path.getsize(abs_path) == 0:
                raise RuntimeError(
                    f"切割第 {index + 1} 个镜头失败：未生成有效片段（{rel_path}）"
                )

            clips.append({
                "id": f"{index:03d}",
                "index": index + 1,
                "start": round(start_sec, 3),
                "end": round(end_sec, 3),
                "duration": round(duration, 3),
                "start_frame": start_frame,
                "end_frame": end_frame,
                "path": rel_path,
            })

        if not clips:
            raise RuntimeError("所有镜头区间时长都过短，未生成任何片段（请调小「最小镜头长度」）")

        # ---- 7. 落盘切割信息 ----
        result = {
            "source": video_path,
            "detector": detector_kind,
            "threshold": effective_threshold,
            "min_scene_sec": min_scene_sec,
            "frame_skip": frame_skip,
            "cut_mode": cut_mode,
            "output_format": ext,
            "fps": round(fps, 4),
            "duration": round(video_duration, 3),
            "total_frames": total_frames,
            "count": len(clips),
            "clips": clips,
        }
        result_abs = os.path.join(task_dir, self._result_rel())
        os.makedirs(os.path.dirname(result_abs), exist_ok=True)
        with open(result_abs, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        if callback:
            try:
                callback(100, f"镜头切割完成：共 {len(clips)} 段")
            except Exception:
                pass

        clip_paths = [c["path"] for c in clips]
        return {
            "artifacts": [self._result_rel(), *clip_paths],
            "outputs": {
                "json": self._result_rel(),
                "videos": clip_paths,
                "count": str(len(clips)),
            },
        }
