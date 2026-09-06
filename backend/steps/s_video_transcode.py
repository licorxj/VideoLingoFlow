# -*- coding: utf-8 -*-
"""
视频转码节点（Step）

使用 ffmpeg 对输入视频进行转码，支持容器格式、视频/音频编码、码率、
分辨率、帧率、编码速度档、像素格式等参数在前端节点卡片上配置。

实现说明：
- 继承真实基类 BaseStep（backend.steps.base_step.BaseStep）。
- 执行域 thread：内部以子进程方式调用 ffmpeg，通过 callback(progress, message)
  上报进度，并通过 cancel_callback 协作取消。
- 返回结构 {"artifacts": [...], "outputs": {port: rel_path}}（相对 task_dir 的路径）。
"""
import os

from backend.steps.base_step import BaseStep
from backend.utils.video_ops import get_video_duration, run_ffmpeg_with_progress


# 视频/音频编码器下拉值 -> ffmpeg 实际编码器名
_VIDEO_CODEC_MAP = {
    "libx264": "libx264",
    "libx265": "libx265",
    "vp9": "libvpx-vp9",
    "mpeg4": "mpeg4",
}
_AUDIO_CODEC_MAP = {
    "aac": "aac",
    "mp3": "libmp3lame",
    "opus": "libopus",
}
# 支持 -crf 的编码器
_CRF_CODECS = ("libx264", "libx265", "libvpx-vp9")
# 支持 -preset 的编码器
_PRESET_CODECS = ("libx264", "libx265")
# 输出格式 -> 文件扩展名
_FORMAT_EXT = {
    "mp4": "mp4",
    "mkv": "mkv",
    "webm": "webm",
    "mov": "mov",
    "avi": "avi",
    "flv": "flv",
}


def _probe_duration(input_path: str) -> float:
    """用 ffprobe 获取视频时长（秒），失败返回 0。"""
    return get_video_duration(input_path)


class S_VideoTranscode(BaseStep):
    step_id = "s_video_transcode"
    step_name = "视频转码"
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
        if os.path.isdir(cache_dir):
            for f in sorted(os.listdir(cache_dir)):
                if f.startswith("input_video") and f.endswith((".mp4", ".mkv", ".webm", ".avi", ".mov")):
                    return os.path.join(cache_dir, f)
            for f in sorted(os.listdir(cache_dir)):
                if f.endswith((".mp4", ".mkv", ".webm", ".avi", ".mov")):
                    return os.path.join(cache_dir, f)
        return ""

    # ------------------------------------------------------------------
    # ffmpeg 命令构建
    # ------------------------------------------------------------------
    def _build_command(self, input_path: str, output_path: str, cfg: dict):
        cmd = ["ffmpeg", "-y", "-i", input_path, "-progress", "pipe:1", "-nostats"]

        video_mode = cfg.get("video_mode", "reencode")
        if video_mode == "none":
            cmd += ["-vn"]
        elif video_mode == "copy":
            cmd += ["-c:v", "copy"]
        else:
            vcodec = _VIDEO_CODEC_MAP.get(cfg.get("video_codec", "libx264"), "libx264")
            cmd += ["-c:v", vcodec]
            crf = cfg.get("crf")
            if vcodec in _CRF_CODECS and crf not in (None, ""):
                try:
                    crf_val = int(crf)
                    cmd += ["-crf", str(crf_val)]
                    if vcodec == "libvpx-vp9":
                        cmd += ["-b:v", "0"]
                except (TypeError, ValueError):
                    pass
            vbitrate = (cfg.get("video_bitrate") or "").strip()
            if vbitrate:
                cmd += ["-b:v", vbitrate]
            resolution = (cfg.get("resolution") or "").strip()
            if resolution:
                cmd += ["-vf", f"scale={resolution}"]
            fps = (cfg.get("fps") or "").strip()
            if fps:
                cmd += ["-r", str(fps)]
            preset = (cfg.get("preset") or "").strip()
            if vcodec in _PRESET_CODECS and preset:
                cmd += ["-preset", preset]
            pix_fmt = (cfg.get("pix_fmt") or "").strip()
            if pix_fmt:
                cmd += ["-pix_fmt", pix_fmt]

        audio_mode = cfg.get("audio_mode", "reencode")
        if audio_mode == "none":
            cmd += ["-an"]
        elif audio_mode == "copy":
            cmd += ["-c:a", "copy"]
        else:
            acodec = _AUDIO_CODEC_MAP.get(cfg.get("audio_codec", "aac"), "aac")
            cmd += ["-c:a", acodec]
            abitrate = (cfg.get("audio_bitrate") or "").strip()
            if abitrate:
                cmd += ["-b:a", abitrate]

        cmd.append(output_path)
        return cmd

    # ------------------------------------------------------------------
    # 带进度/取消的 ffmpeg 执行（公共实现见 backend.utils.video_ops）
    # ------------------------------------------------------------------
    def _run_ffmpeg(self, cmd, duration, callback, cancel_callback, timeout=86400):
        run_ffmpeg_with_progress(
            cmd, duration, callback, cancel_callback, timeout=timeout, label="转码"
        )

    # ------------------------------------------------------------------
    # 断点/产物管理
    # ------------------------------------------------------------------
    def check_artifact(self, task_dir: str) -> bool:
        output_dir = os.path.join(task_dir, "output")
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        prefix = f"transcoded_video{node_suffix}."
        return os.path.isdir(output_dir) and any(
            name.startswith(prefix) for name in os.listdir(output_dir)
        )

    def validate_inputs(self, task_dir: str) -> bool:
        return bool(self._resolve_video_path(task_dir))

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def run(self, task_dir, callback=None, cancel_callback=None):
        node_config = getattr(self, "_node_config", {}) or {}

        input_path = self._resolve_video_path(task_dir)
        if not input_path:
            raise FileNotFoundError("未找到输入视频：请连接视频输入端口，或确保 cache 中存在视频文件")

        output_format = node_config.get("output_format", "mp4")
        ext = _FORMAT_EXT.get(output_format, "mp4")
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"transcoded_video{node_suffix}.{ext}")
        output_rel = f"output/transcoded_video{node_suffix}.{ext}"

        if callback:
            try:
                callback(2, "准备转码命令")
            except Exception:
                pass

        cmd = self._build_command(input_path, output_path, node_config)
        if callback:
            try:
                callback(5, f"开始转码 -> .{ext}")
            except Exception:
                pass

        duration = _probe_duration(input_path)
        self._run_ffmpeg(cmd, duration, callback, cancel_callback)

        if not os.path.exists(output_path):
            raise RuntimeError("转码完成但未找到输出文件: " + output_path)

        if callback:
            try:
                callback(100, "视频转码完成")
            except Exception:
                pass
        return {
            "artifacts": [output_rel],
            "outputs": {"video": output_rel},
        }
