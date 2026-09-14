"""s_video_concat: 视频拼接节点。

将「主视频 / 片段1~3 / 封面图」按前端配置一次性拼装为单个 ffmpeg 命令并一次性完成：
- segment_order: 视频片段拼接顺序（主视频、片段1/2/3 的排序）
- scale_mode: 片段尺寸缩放方式（stretch 拉伸 / crop 裁切填充）
- cover_position / cover_duration: 封面图插入位置（开头/结尾）与停留时长（none 不插入）
所有视频统一缩放到首个参考视频的分辨率与帧率后拼接，封面图以静帧形式插入，
输出拼接后的单个视频文件。
"""
import json
import os
import shutil
import subprocess
from typing import Callable, Optional

from backend.steps.base_step import BaseStep
from backend.utils.video_ops import run_ffmpeg_with_progress


_FORMAT_EXT = {"mp4": "mp4", "mkv": "mkv", "webm": "webm", "mov": "mov", "avi": "avi"}
_SEGMENT_PORTS = ["main", "segment1", "segment2", "segment3"]
_SEGMENT_LABELS = {
    "main": "主视频",
    "segment1": "片段1",
    "segment2": "片段2",
    "segment3": "片段3",
}


def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def _ffprobe() -> str:
    return shutil.which("ffprobe") or "ffprobe"


def _resolve_path(raw, task_dir: str) -> Optional[str]:
    """支持 str / dict{path} / list[...] → 首个真实存在的文件路径。"""
    candidates: list = []
    if isinstance(raw, str):
        if raw:
            candidates = [raw]
    elif isinstance(raw, dict):
        for k in ("path", "file", "file_path", "url"):
            v = raw.get(k)
            if isinstance(v, str) and v:
                candidates.append(v)
                break
    elif isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, str) and item:
                candidates.append(item)
            elif isinstance(item, dict):
                for k in ("path", "file", "file_path", "url"):
                    v = item.get(k)
                    if isinstance(v, str) and v:
                        candidates.append(v)
                        break
    for cand in candidates:
        p = cand if os.path.isabs(cand) else os.path.join(task_dir, cand)
        if os.path.isfile(p):
            return p
    return None


def _probe(path: str) -> dict:
    """用 ffprobe 获取宽高、时长、帧率、是否含音轨。"""
    info = {"width": 0, "height": 0, "duration": 0.0, "fps": 30.0, "has_audio": False}
    exe = _ffprobe()
    if not exe:
        return info
    try:
        cmd = [exe, "-v", "quiet", "-print_format", "json", "-show_streams", "-show_format", path]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        data = json.loads(res.stdout or "{}")
        if "format" in data and data["format"].get("duration"):
            try:
                info["duration"] = float(data["format"]["duration"])
            except (TypeError, ValueError):
                info["duration"] = 0.0
        vw = vh = 0
        for s in data.get("streams", []):
            if s.get("codec_type") == "video" and vw == 0:
                try:
                    vw = int(s.get("width", 0) or 0)
                except (TypeError, ValueError):
                    vw = 0
                try:
                    vh = int(s.get("height", 0) or 0)
                except (TypeError, ValueError):
                    vh = 0
                r = s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/0"
                try:
                    num, den = r.split("/")
                    fps = float(num) / float(den) if float(den) else 0.0
                    if fps > 0:
                        info["fps"] = fps
                except (ValueError, ZeroDivisionError):
                    pass
            elif s.get("codec_type") == "audio":
                info["has_audio"] = True
        if vw and vh:
            info["width"], info["height"] = vw, vh
    except Exception:
        pass
    return info


class S_VideoConcat(BaseStep):
    step_id = "video_concat"
    step_name = "视频拼接"
    dependencies = []

    # ------------------------------------------------------------------
    # 断点 / 输入校验
    # ------------------------------------------------------------------
    def check_artifact(self, task_dir: str) -> bool:
        output_dir = os.path.join(task_dir, "output")
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        prefix = f"video_concat{node_suffix}."
        return os.path.isdir(output_dir) and any(
            name.startswith(prefix) for name in os.listdir(output_dir)
        )

    def validate_inputs(self, task_dir: str) -> bool:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        for port in _SEGMENT_PORTS + ["cover"]:
            if _resolve_path(step_inputs.get(port), task_dir):
                return True
        return False

    # ------------------------------------------------------------------
    # filter_complex 拼装
    # ------------------------------------------------------------------
    @staticmethod
    def _scale_expr(scale_mode: str, w: int, h: int) -> str:
        if scale_mode == "crop":
            return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
        return f"scale={w}:{h}:force_original_aspect_ratio=disable"

    def _build_filter(self, clips: list, scale_mode: str, w: int, h: int, fps: float) -> str:
        """根据 clips（已含 idx 顺序）生成 filter_complex 字符串。"""
        parts: list = []
        vlabels: list = []
        alabels: list = []
        scale_expr = self._scale_expr(scale_mode, w, h)
        for c in clips:
            idx = c["idx"]
            if c["kind"] == "video":
                parts.append(
                    f"[{idx}:v]{scale_expr},setsar=1,fps={fps},format=yuv420p[v{idx}]"
                )
                if c["has_audio"]:
                    parts.append(
                        f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo[a{idx}]"
                    )
                else:
                    parts.append(
                        f"anullsrc=r=48000:cl=stereo:d={c['duration']:.3f}[a{idx}]"
                    )
            else:  # 封面静帧
                parts.append(
                    f"[{idx}:v]{scale_expr},setsar=1,fps={fps},format=yuv420p,"
                    f"trim=duration={c['duration']:.3f},setpts=PTS-STARTPTS[v{idx}]"
                )
                parts.append(
                    f"anullsrc=r=48000:cl=stereo:d={c['duration']:.3f}[a{idx}]"
                )
            vlabels.append(f"[v{idx}]")
            alabels.append(f"[a{idx}]")
        # concat 滤镜要求输入按「视频0、音频0、视频1、音频1…」交错排列
        interleaved = []
        for i in range(len(vlabels)):
            interleaved.append(vlabels[i])
            interleaved.append(alabels[i])
        n = len(vlabels)
        parts.append("".join(interleaved) + f"concat=n={n}:v=1:a=1[outv][outa]")
        return ";".join(parts)

    # ------------------------------------------------------------------
    # 带进度 / 取消的 ffmpeg 执行
    # ------------------------------------------------------------------
    def _run_ffmpeg(self, cmd, duration, callback, cancel_callback, timeout=86400):
        run_ffmpeg_with_progress(
            cmd, duration, callback, cancel_callback, timeout=timeout, label="拼接"
        )

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def run(self, task_dir, callback=None, cancel_callback=None):
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        order = node_config.get("segment_order") or list(_SEGMENT_PORTS)
        if not isinstance(order, list):
            order = list(_SEGMENT_PORTS)
        scale_mode = node_config.get("scale_mode") or "stretch"
        cover_position = node_config.get("cover_position") or "none"
        try:
            cover_duration = float(node_config.get("cover_duration", 3) or 3)
        except (ValueError, TypeError):
            cover_duration = 3.0
        cover_duration = max(0.1, min(60.0, cover_duration))
        output_format = (node_config.get("output_format") or "mp4").strip().lower() or "mp4"
        ext = _FORMAT_EXT.get(output_format, "mp4")

        # 1) 解析视频片段（按排序）
        video_clips = []
        for port in order:
            if port not in _SEGMENT_PORTS:
                continue
            p = _resolve_path(step_inputs.get(port), task_dir)
            if p:
                meta = _probe(p)
                video_clips.append({"path": p, "meta": meta})

        # 2) 解析封面图
        cover_path = (
            _resolve_path(step_inputs.get("cover"), task_dir)
            if cover_position in ("start", "end") else None
        )

        if not video_clips and not cover_path:
            raise FileNotFoundError("未找到任何有效输入：请连接主视频/片段/封面图中的至少一个")

        # 3) 探测目标分辨率与帧率（首个视频，否则封面图）
        target = None
        for vc in video_clips:
            m = vc["meta"]
            if m["width"] and m["height"]:
                target = m
                break
        if target is None and cover_path:
            target = _probe(cover_path)
        if target is None or not target["width"] or not target["height"]:
            raise RuntimeError("无法探测参考视频/图片尺寸，无法确定输出分辨率")
        out_w, out_h = target["width"], target["height"]
        fps = target.get("fps") or 30.0

        # 4) 组装最终 clips 顺序（含封面插入）
        clips: list = []
        for vc in video_clips:
            m = vc["meta"]
            clips.append({
                "kind": "video",
                "path": vc["path"],
                "duration": m["duration"] or 1.0,
                "has_audio": m["has_audio"],
            })
        if cover_path and cover_position in ("start", "end"):
            cover_clip = {
                "kind": "image",
                "path": cover_path,
                "duration": cover_duration,
                "has_audio": False,
            }
            if cover_position == "start":
                clips.insert(0, cover_clip)
            else:
                clips.append(cover_clip)

        for i, c in enumerate(clips):
            c["idx"] = i

        total_dur = sum(c["duration"] for c in clips)

        # 5) 拼装 ffmpeg 命令（单次执行）
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"video_concat{node_suffix}.{ext}")
        output_rel = f"output/video_concat{node_suffix}.{ext}"

        filter_str = self._build_filter(clips, scale_mode, out_w, out_h, fps)

        cmd = [_ffmpeg(), "-y"]
        for c in clips:
            if c["kind"] == "image":
                cmd += ["-loop", "1"]
            cmd += ["-i", c["path"]]
        cmd += [
            "-filter_complex", filter_str,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "48000",
            output_path,
        ]

        if callback:
            try:
                callback(5, f"开始拼接（{len(clips)} 段，{out_w}x{out_h}，缩放={scale_mode}）")
            except Exception:
                callback(5, "开始拼接")

        self._run_ffmpeg(cmd, total_dur, callback, cancel_callback)

        if not os.path.exists(output_path):
            raise RuntimeError("视频拼接完成但未找到输出文件: " + output_path)

        if callback:
            try:
                callback(100, "视频拼接完成")
            except Exception:
                pass
        return {
            "artifacts": [output_rel],
            "outputs": {"video": output_rel},
        }
