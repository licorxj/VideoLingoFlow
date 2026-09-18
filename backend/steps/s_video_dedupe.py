# -*- coding: utf-8 -*-
"""
视频去重节点（反平台查重变换）。

对输入视频做画面变换以规避平台重复检测，不删除任何内容，只修改画面/音频：

- ``flip_h``：水平镜像翻转（hflip）
- ``zoom_crop``：放大裁切（scale 放大后居中 crop，等效拉近镜头）
- ``speed_change``：调速（视频 setpts + 音频 atempo，轻微变速）
- ``apply_filter``：调色/滤镜（eq/hue/unsharp/gblur 轻量调色）
- ``add_border``：加黑边（pad）

所有变换叠加为一条 ffmpeg -vf/-af 链并重新编码（变换必须重编码）；
编码器由全局设置「视频处理 → 使用显卡加速 (NVIDIA NVENC)」决定（H.264/HEVC 生效）。
输出写入 ``output/video_dedup_{node_id}.{ext}``，沿用 video_scale 的进度/取消机制。
"""
import os
import shutil

from backend.steps.base_step import BaseStep
from backend.utils.video_ops import get_video_duration, run_ffmpeg_with_progress
from backend.utils.video_encoder import build_video_encode_args


def _ensure_disk_space(target_dir: str, needed_bytes: float, margin: float = 1.3) -> None:
    """产物落地前检查磁盘余量，不足时快速失败并给出可执行提示。"""
    if needed_bytes <= 0:
        return
    try:
        free = shutil.disk_usage(target_dir).free
    except OSError:
        return
    if free < needed_bytes * margin:
        raise RuntimeError(
            f"磁盘可用空间不足：本次处理预计需要约 {needed_bytes * margin / 1048576:.0f} MB，"
            f"当前仅剩 {free / 1048576:.0f} MB，已中止以免写坏输出。"
            f"请清理磁盘后重试，或降低视频质量 / 分辨率。"
        )


# 输出格式 -> (视频编码器, 音频编码器)
_FORMAT_CODECS = {
    "mp4": ("libx264", "aac"),
    "mkv": ("libx264", "aac"),
    "mov": ("libx264", "aac"),
    "flv": ("libx264", "aac"),
    "webm": ("libvpx-vp9", "libopus"),
    "avi": ("mpeg4", "libmp3lame"),
}
_FORMAT_EXT = {"mp4": "mp4", "mkv": "mkv", "webm": "webm", "mov": "mov", "avi": "avi", "flv": "flv"}
_CRF_CODECS = ("libx264", "libx265", "libvpx-vp9")
_QUALITY_CRF = {"high": 18, "medium": 23, "low": 28}
_QUALITY_QSCALE = {"high": 2, "medium": 5, "low": 8}

# 调色/滤镜预设 -> ffmpeg 滤镜串
_FILTER_PRESETS = {
    "color": "eq=brightness=0.02:contrast=1.04:saturation=1.05",
    "brightness": "eq=brightness=0.03:contrast=1.02",
    "hue": "hue=h=18",
    "sharpen": "unsharp=5:5:1.2:5:5:0.0",
    "blur": "gblur=sigma=0.8",
}


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _coerce_bool(val, default: bool = False) -> bool:
    if val is None or val == "":
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _build_dedup_filters(cfg: dict):
    """根据配置构建 (vf, af) 滤镜串；均未启用时 vf/af 为空串。

    Returns:
        (vf, af)：视频滤镜串与音频滤镜串，未设置则为 ""。
    """
    vf_parts: list = []

    # 1. 水平镜像翻转
    if _coerce_bool(cfg.get("flip_h"), False):
        vf_parts.append("hflip")

    # 2. 放大裁切（拉近镜头）
    if _coerce_bool(cfg.get("zoom_crop"), False):
        z = _as_float(cfg.get("zoom_factor"), 1.08)
        z = max(1.01, min(z, 2.0))  # 限制 1.01~2.0 倍
        vf_parts.append(f"scale=trunc(iw*{z}*2)/2:trunc(ih*{z}*2)/2,crop=iw/{z}:ih/{z}")

    # 3. 调色/滤镜
    if _coerce_bool(cfg.get("apply_filter"), False):
        preset = str(cfg.get("filter_preset") or "color").strip()
        if preset in _FILTER_PRESETS:
            vf_parts.append(_FILTER_PRESETS[preset])

    # 4. 加黑边
    if _coerce_bool(cfg.get("add_border"), False):
        b = max(1, _as_int(cfg.get("border_size"), 20))
        vf_parts.append(f"pad=iw+2*{b}:ih+2*{b}:{b}:{b}:color=black")

    vf = ",".join(vf_parts)

    # 5. 调速（视频 setpts + 音频 atempo）
    af = ""
    if _coerce_bool(cfg.get("speed_change"), False):
        r = _as_float(cfg.get("speed_ratio"), 1.04)
        r = max(0.5, min(r, 2.0))  # atempo 仅支持 0.5~2.0
        # ratio>1 表示加速：setpts=1/r*PTS，atempo=r
        vf = f"setpts={1.0 / r:.4f}*PTS" + ("," + vf if vf else "")
        af = f"atempo={r:.4f}"

    return vf, af


class S_VideoDedupe(BaseStep):
    step_id = "video_dedupe"
    step_name = "视频去重"
    dependencies = []

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

    def check_artifact(self, task_dir: str) -> bool:
        output_dir = os.path.join(task_dir, "output")
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        prefix = f"video_dedup{node_suffix}."
        return os.path.isdir(output_dir) and any(
            name.startswith(prefix) for name in os.listdir(output_dir)
        )

    def validate_inputs(self, task_dir: str) -> bool:
        return bool(self._resolve_video_path(task_dir))

    def run(self, task_dir, callback=None, cancel_callback=None):
        node_config = getattr(self, "_node_config", {}) or {}

        input_path = self._resolve_video_path(task_dir)
        if not input_path:
            raise FileNotFoundError("未找到输入视频：请把上游视频端口连接到本节点")

        output_format = str(node_config.get("output_format") or "mp4").strip().lower()
        if output_format not in _FORMAT_CODECS:
            raise ValueError(f"不支持的输出格式：{output_format}")
        ext = _FORMAT_EXT.get(output_format, "mp4")

        # 资源保护配置：线程上限（0=自动）、最长时长上限（0=不限制）、编码速度
        ffmpeg_threads = max(0, min(_as_int(node_config.get("ffmpeg_threads"), 0), 64))
        max_duration_minutes = max(0, _as_int(node_config.get("max_duration_minutes"), 0))
        encode_preset = str(node_config.get("encode_preset") or "").strip()

        # 前置预检：时长上限 + 磁盘余量（快速失败，避免处理到一半把机器拖垮）
        try:
            duration = float(get_video_duration(input_path) or 0)
        except Exception:
            duration = 0.0
        if max_duration_minutes > 0 and duration > max_duration_minutes * 60:
            raise RuntimeError(
                f"视频时长约 {duration / 60:.1f} 分钟，超过节点配置的上限 {max_duration_minutes} 分钟。"
                f"如确需处理长视频，请在节点「最长时长上限」中调大或设为 0（不限制）。"
            )
        try:
            input_bytes = os.path.getsize(input_path)
        except OSError:
            input_bytes = 0
        _ensure_disk_space(task_dir, input_bytes * 1.2)

        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"video_dedup{node_suffix}.{ext}")
        output_rel = f"output/video_dedup{node_suffix}.{ext}"

        vf, af = _build_dedup_filters(node_config)
        if callback:
            try:
                callback(2, f"去重滤镜: {'; '.join([p for p in [vf, af] if p]) or '无（直接重编码）'}")
            except Exception:
                pass

        cmd = ["ffmpeg", "-y", "-i", input_path, "-progress", "pipe:1", "-nostats"]
        if vf:
            cmd += ["-vf", vf]
        if af:
            cmd += ["-af", af]

        vcodec, acodec = _FORMAT_CODECS[output_format]
        quality = str(node_config.get("video_quality") or "medium").strip().lower()
        if quality not in _QUALITY_CRF:
            quality = "medium"
        # 全局「使用显卡加速 (NVIDIA NVENC)」开启时，H.264/HEVC 自动改用硬编码
        cmd += build_video_encode_args(vcodec, quality=quality, preset=encode_preset or None)

        cmd += ["-c:a", acodec, "-b:a", "192k",
                # 限制封装队列，避免队列无界增长导致内存暴涨
                "-max_muxing_queue_size", "4096"]
        if ffmpeg_threads > 0:
            # 限制编码与滤镜线程，避免重编码时吃满全部 CPU 导致系统卡顿
            cmd += ["-threads", str(ffmpeg_threads), "-filter_threads", str(ffmpeg_threads)]
        else:
            # 未在节点配置线程上限时，走全局 FFMPEG_MAX_THREADS / CPU 半核默认
            from backend.utils.ffmpeg_guard import resource_args
            cmd += [a for a in resource_args() if a not in ("-max_muxing_queue_size", "4096")]
        cmd.append(output_path)

        if callback:
            try:
                callback(5, f"开始去重变换 -> .{ext}"
                           + (f"（线程上限 {ffmpeg_threads}）" if ffmpeg_threads else "（线程跟随全局限制）"))
            except Exception:
                pass

        # 超时按视频时长自适应：默认 86400s（24h）在 ffmpeg 异常挂起时形同卡死，
        # 这里改用「时长 × 10 + 300s，下限 600s」，超时即终止并抛出可读错误。
        effective_timeout = max(600.0, duration * 10 + 300) if duration > 0 else 1800.0
        run_ffmpeg_with_progress(
            cmd, duration, callback, cancel_callback,
            timeout=effective_timeout, label="去重变换",
        )

        if not os.path.exists(output_path):
            raise RuntimeError("去重变换完成但未找到输出文件: " + output_path)

        if callback:
            try:
                callback(100, "视频去重完成")
            except Exception:
                pass
        return {
            "artifacts": [output_rel],
            "outputs": {"video": output_rel},
        }
