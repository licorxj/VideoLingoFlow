# -*- coding: utf-8 -*-
"""
按字幕切割视频节点（Step）

输入：
- video : 待切割视频（required；缺失时回退到 cache 中的视频产物）
- srt   : SRT 字幕（可选；提供时先转换为 {segments:[...]} 格式的 json）
- json  : 句子/字幕 JSON（可选；需含 segments 或列表，每段有 start/end）

输出：
- json            : 切割信息 json（含片段 id、路径、起始时间、时长、文本）
- video_segments  : 视频片段清单（json，指向同一 json）

行为：
- 在任务目录 cache 下创建 video_segments_01 文件夹（已存在则 _02、_03...），
  所有视频片段与 segments.json 都放在该文件夹内。
- 片段文件名/编号按 000、001 顺序零填充，封装格式由「输出格式」决定。
- 配置项：输出格式(output_format，默认 mp4)、切割点外扩(expand，默认 0.05s)。
"""
import json
import os
import subprocess

from backend.steps.base_step import BaseStep
from backend.utils.srt_to_json import srt_to_segments


def _ffprobe_duration(video_path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip())
    except Exception:
        pass
    return 0.0


# 输出格式 -> (文件扩展名, ffmpeg 编码参数)
_VIDEO_OUT_FORMATS = {
    "mp4": ("mp4", ["-c:v", "libx264", "-c:a", "aac"]),
    "mkv": ("mkv", ["-c:v", "libx264", "-c:a", "aac"]),
    "mov": ("mov", ["-c:v", "libx264", "-c:a", "aac"]),
    "webm": ("webm", ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "30", "-c:a", "libopus"]),
}


class StepVideoCutBySubtitle(BaseStep):
    step_id = "s_video_cut_by_subtitle"
    step_name = "按字幕切割视频"
    dependencies = []

    # ------------------------------------------------------------------
    # 输入解析
    # ------------------------------------------------------------------
    def _resolve_video_path(self, task_dir: str) -> str:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        raw = step_inputs.get("video", "")
        if raw:
            p = raw if os.path.isabs(raw) else os.path.join(task_dir, raw)
            if os.path.isfile(p):
                return p
        cache_dir = os.path.join(task_dir, "cache")
        if not os.path.isdir(cache_dir):
            return ""
        for name in sorted(os.listdir(cache_dir)):
            if name.startswith("input_video") or name.lower().endswith(
                (".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv")
            ):
                return os.path.join(cache_dir, name)
        return ""

    def _resolve_segments(self, task_dir: str):
        """返回 (segments, source_label)。每个 segment 形如
        {"id": int, "text": str, "speaker": str, "start": float, "end": float}。"""
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        srt_raw = step_inputs.get("srt", "")
        json_raw = step_inputs.get("json", "")

        if srt_raw:
            p = srt_raw if os.path.isabs(srt_raw) else os.path.join(task_dir, srt_raw)
            if not os.path.isfile(p):
                raise FileNotFoundError(f"未找到 srt 输入文件: {p}")
            return srt_to_segments(p).get("segments", []), "srt"
        if json_raw:
            p = json_raw if os.path.isabs(json_raw) else os.path.join(task_dir, json_raw)
            if not os.path.isfile(p):
                raise FileNotFoundError(f"未找到 json 输入文件: {p}")
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                segs = data.get("segments", data.get("items", []))
            elif isinstance(data, list):
                segs = data
            else:
                segs = []
            result = []
            for i, item in enumerate(segs, start=1):
                start = item.get("start", item.get("begin", item.get("start_time")))
                end = item.get("end", item.get("end_time", item.get("finish")))
                if start is None or end is None:
                    continue
                result.append({
                    "id": i,
                    "text": str(item.get("text", item.get("content", "")) or ""),
                    "speaker": str(item.get("speaker", "")),
                    "start": float(start),
                    "end": float(end),
                })
            return result, "json"
        raise ValueError("未提供字幕输入：请连接 srt 或 json 输入端口")

    def _next_segments_dir(self, task_dir: str) -> str:
        cache_dir = os.path.join(task_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        existing = []
        for name in os.listdir(cache_dir):
            if name.startswith("video_segments_"):
                try:
                    existing.append(int(name.split("_")[-1]))
                except ValueError:
                    pass
        n = (max(existing) + 1) if existing else 1
        return os.path.join(cache_dir, f"video_segments_{n:02d}")

    # ------------------------------------------------------------------
    # 断点/产物管理
    # ------------------------------------------------------------------
    def check_artifact(self, task_dir: str) -> bool:
        cache_dir = os.path.join(task_dir, "cache")
        if not os.path.isdir(cache_dir):
            return False
        for name in os.listdir(cache_dir):
            if name.startswith("video_segments_") and os.path.isdir(os.path.join(cache_dir, name)):
                return True
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return bool(self._resolve_video_path(task_dir))

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def run(self, task_dir, callback=None, cancel_callback=None):
        node_config = getattr(self, "_node_config", {}) or {}
        output_format = (node_config.get("output_format", "mp4") or "mp4").lower()
        seg_ext, seg_codec_args = _VIDEO_OUT_FORMATS.get(output_format, ("mp4", ["-c:v", "libx264", "-c:a", "aac"]))
        try:
            expand = float(node_config.get("expand", 0.05))
        except (ValueError, TypeError):
            expand = 0.05

        video_path = self._resolve_video_path(task_dir)
        if not video_path:
            raise FileNotFoundError("未找到输入视频：请连接视频输入端口，或确保 cache 中存在视频文件")
        video_duration = _ffprobe_duration(video_path)

        segments, src = self._resolve_segments(task_dir)
        if not segments:
            raise ValueError("字幕解析后没有有效的时间段（需要每段含 start/end）")

        if callback:
            try:
                callback(5, f"解析到 {len(segments)} 段字幕（来源: {src}）")
            except Exception:
                pass

        out_dir = self._next_segments_dir(task_dir)
        os.makedirs(out_dir, exist_ok=True)
        seg_folder = os.path.basename(out_dir)

        info = {"segments": []}
        seg_rel_paths = []

        for i, seg in enumerate(segments):
            if cancel_callback and cancel_callback():
                from backend.control_plane.runtime import TaskCancelledError
                raise TaskCancelledError("用户取消切割")

            start = max(0.0, seg["start"] - expand)
            end = seg["end"] + expand
            if video_duration and end > video_duration:
                end = video_duration
            duration = max(0.0, end - start)
            seg_id = f"{i:03d}"
            rel_video = os.path.join("cache", seg_folder, f"{seg_id}.{seg_ext}")
            abs_video = os.path.join(task_dir, rel_video)

            cmd = [
                "ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", video_path,
                "-t", f"{duration:.3f}",
            ] + list(seg_codec_args) + [abs_video]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
                if r.returncode != 0:
                    raise RuntimeError(f"ffmpeg 切割失败(段 {seg_id}): {r.stderr[-500:]}")
            except FileNotFoundError:
                raise RuntimeError("未找到 ffmpeg，请先安装 ffmpeg")
            seg_rel_paths.append(rel_video)

            info["segments"].append({
                "id": seg_id,
                "path": rel_video,
                "start": round(seg["start"], 3),
                "end": round(seg["end"], 3),
                "duration": round(duration, 3),
                "text": seg.get("text", ""),
                "speaker": seg.get("speaker", ""),
            })

            if callback:
                try:
                    callback(
                        int((i + 1) / len(segments) * 90) + 5,
                        f"已切割 {i + 1}/{len(segments)} 段",
                    )
                except Exception:
                    pass

        rel_json = os.path.join("cache", seg_folder, "segments.json")
        abs_json = os.path.join(task_dir, rel_json)
        with open(abs_json, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)

        if callback:
            try:
                callback(100, "视频切割完成")
            except Exception:
                pass

        return {
            "artifacts": [rel_json] + seg_rel_paths,
            "outputs": {
                "json": rel_json,
                "video_segments": rel_json,
            },
        }
