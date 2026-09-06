# -*- coding: utf-8 -*-
"""
视频缩放节点（Step）

使用 ffmpeg 将输入视频缩放到预置分辨率或自定义宽高：

- ``scale_preset``：original / 2160p / 1440p / 1080p / 720p / 480p / 360p / custom。
  预置档按目标高度等比缩放（``scale=-2:H``，宽度自动取偶）；custom 使用精确宽高。
- ``output_format``：mp4 / mkv / webm / mov / avi / flv（编码器随容器自动匹配）。
- ``video_quality``：high(CRF18) / medium(CRF23) / low(CRF28)；mpeg4(avi) 无 CRF，
  按 -q:v 2/5/8 映射。

实现沿用视频转码节点：thread 域、ffmpeg 子进程 + ``-progress`` 进度上报、协作取消，
执行器来自 backend.utils.video_ops。输出写入 ``output/video_scale_{node_id}.{ext}``。
"""
import os

from backend.steps.base_step import BaseStep
from backend.utils.video_ops import get_video_duration, run_ffmpeg_with_progress

# 高度型预置档 -> 目标高度（等比缩放，宽自动取偶）
_HEIGHT_PRESETS = {
    "2160p": 2160,
    "1440p": 1440,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
    "360p": 360,
}

# 输出格式 -> (视频编码器, 音频编码器)
_FORMAT_CODECS = {
    "mp4": ("libx264", "aac"),
    "mkv": ("libx264", "aac"),
    "mov": ("libx264", "aac"),
    "flv": ("libx264", "aac"),
    "webm": ("libvpx-vp9", "libopus"),
    "avi": ("mpeg4", "libmp3lame"),
}

# 输出格式 -> 文件扩展名
_FORMAT_EXT = {"mp4": "mp4", "mkv": "mkv", "webm": "webm", "mov": "mov", "avi": "avi", "flv": "flv"}

# 支持 -crf 的编码器
_CRF_CODECS = ("libx264", "libx265", "libvpx-vp9")
# 质量档 -> CRF
_QUALITY_CRF = {"high": 18, "medium": 23, "low": 28}
# 质量档 -> mpeg4 的 -q:v（1-31，越小质量越高）
_QUALITY_QSCALE = {"high": 2, "medium": 5, "low": 8}


def _as_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _build_scale_filter(cfg: dict) -> str:
    """按缩放设置构建 -vf 参数；保持原始分辨率返回空串。"""
    preset = str(cfg.get("scale_preset") or "1080p").strip()
    if preset == "original":
        return ""
    if preset in _HEIGHT_PRESETS:
        return f"scale=-2:{_HEIGHT_PRESETS[preset]}"
    if preset == "custom":
        width = _as_int(cfg.get("custom_width"))
        height = _as_int(cfg.get("custom_height"))
        if width < 1 or height < 1:
            raise ValueError("自定义缩放需要填写有效的宽与高（像素）")
        return f"scale={width}:{height}"
    raise ValueError(f"不支持的缩放尺寸档位：{preset}")


class S_VideoScale(BaseStep):
    step_id = "video_scale"
    step_name = "视频缩放"
    dependencies = []

    # ------------------------------------------------------------------
    # 输入解析
    # ------------------------------------------------------------------
    def _resolve_video_path(self, task_dir: str) -> str:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        raw = step_inputs.get("video", "")
        if isinstance(raw, (list, tuple)):
            raw = next((item for item in raw if str(item or "").strip()), "")
        raw = str(raw or "").strip()
        if raw:
            p = raw if os.path.isabs(raw) else os.path.join(task_dir, raw)
            if os.path.isfile(p):
                return p
        return ""

    # ------------------------------------------------------------------
    # ffmpeg 命令构建
    # ------------------------------------------------------------------
    def _build_command(self, input_path: str, output_path: str, cfg: dict):
        cmd = ["ffmpeg", "-y", "-i", input_path, "-progress", "pipe:1", "-nostats"]

        vf = _build_scale_filter(cfg)
        if vf:
            cmd += ["-vf", vf]

        output_format = str(cfg.get("output_format") or "mp4").strip().lower()
        if output_format not in _FORMAT_CODECS:
            raise ValueError(f"不支持的输出格式：{output_format}")
        vcodec, acodec = _FORMAT_CODECS[output_format]
        cmd += ["-c:v", vcodec]

        quality = str(cfg.get("video_quality") or "medium").strip().lower()
        if quality not in _QUALITY_CRF:
            raise ValueError(f"不支持的编码质量档位：{quality}")
        if vcodec in _CRF_CODECS:
            cmd += ["-crf", str(_QUALITY_CRF[quality])]
            if vcodec == "libvpx-vp9":
                cmd += ["-b:v", "0"]
        else:  # mpeg4：无 CRF，按 qscale 映射
            cmd += ["-q:v", str(_QUALITY_QSCALE[quality])]

        cmd += ["-c:a", acodec, "-b:a", "192k"]
        cmd.append(output_path)
        return cmd

    # ------------------------------------------------------------------
    # 断点/产物管理
    # ------------------------------------------------------------------
    def check_artifact(self, task_dir: str) -> bool:
        output_dir = os.path.join(task_dir, "output")
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        prefix = f"video_scale{node_suffix}."
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
            raise FileNotFoundError("未找到输入视频：请把上游视频端口连接到本节点")

        output_format = str(node_config.get("output_format") or "mp4").strip().lower()
        ext = _FORMAT_EXT.get(output_format, "mp4")
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"video_scale{node_suffix}.{ext}")
        output_rel = f"output/video_scale{node_suffix}.{ext}"

        if callback:
            try:
                callback(2, "准备缩放命令")
            except Exception:
                pass

        cmd = self._build_command(input_path, output_path, node_config)
        if callback:
            try:
                callback(5, f"开始缩放 -> .{ext}")
            except Exception:
                pass

        duration = get_video_duration(input_path)
        run_ffmpeg_with_progress(cmd, duration, callback, cancel_callback, label="缩放")

        if not os.path.exists(output_path):
            raise RuntimeError("缩放完成但未找到输出文件: " + output_path)

        if callback:
            try:
                callback(100, "视频缩放完成")
            except Exception:
                pass
        return {
            "artifacts": [output_rel],
            "outputs": {"video": output_rel},
        }
