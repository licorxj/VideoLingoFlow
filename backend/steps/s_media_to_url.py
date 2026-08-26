"""s_media_to_url: 上传本地媒体文件（视频/图片）到腾讯云 VOD，返回 URL 及完整媒体详情。

Logic:
  1. 解析输入：从节点连线获取视频/图片文件路径
  2. （可选）标准化视频：勾选后将视频用 h264 重编码为 mp4，>1080p 降分辨率
  3. 视频按前端设置的分段时长（分钟，默认 30）探测时长；超长时用 ffmpeg 分段
  4. 逐段调用腾讯云 VOD 上传接口（upload_to_tencent_vod_with_details）
  5. 将 URL + 尺寸/时长/码率等详情保存为 JSON 文件到 task_dir/cache/
     多段时顶层兼容保留 url/duration，并以 segments 列表写入每段详情
  6. 输出 json 端口（JSON 文件路径，下游可读取结构化媒体信息）
"""
import json
import math
import os
import subprocess
from typing import Callable, Optional

from backend.steps.base_step import BaseStep, find_artifact


# 支持的输入文件扩展名
_VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".avi", ".mov", ".wmv", ".flv", ".m4v", ".mpg", ".mpeg")
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff", ".tif")

# 标准化视频的分辨率上限（短边/长边均不超过此值）
_MAX_RESOLUTION = 1080


def _probe_video_dimensions(video_path: str) -> tuple[int, int]:
    """用 ffprobe 获取视频宽高，失败返回 (0, 0)。"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0:s=x",
             video_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            w_str, h_str = result.stdout.strip().split("x")
            return int(w_str), int(h_str)
    except Exception:
        pass
    return 0, 0


def _normalize_video(video_path: str, output_path: str, callback=None) -> str:
    """
    将视频标准化：重编码为 h264 mp4，分辨率 >1080p 时等比缩小至 1080p。

    Args:
        video_path: 原始视频路径
        output_path: 输出 mp4 路径
        callback: 可选进度回调（仅日志用途）

    Returns:
        标准化后的视频路径（即 output_path）
    """
    width, height = _probe_video_dimensions(video_path)

    # 判断是否需要缩放
    scale_filter = ""
    if width > 0 and height > 0:
        max_dim = max(width, height)
        if max_dim > _MAX_RESOLUTION:
            # 等比缩小，长边限制为 1080，短边自动按比例，保证偶数
            scale_filter = f"scale='min(1080,iw)':'min(1080,ih)':force_original_aspect_ratio=decrease,pad=ceil(iw/2)*2:ceil(ih/2)*2"
            if callback:
                callback(20, f"标准化视频: {width}x{height} -> 缩小至 ≤1080p")
        else:
            if callback:
                callback(20, f"标准化视频: {width}x{height} 分辨率合规，仅重编码")
    else:
        if callback:
            callback(20, "标准化视频: 无法探测分辨率，仅重编码")

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
    ]
    if scale_filter:
        cmd.extend(["-vf", scale_filter])
    cmd.append(output_path)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            error_msg = result.stderr[-500:] if result.stderr else "Unknown error"
            raise RuntimeError(f"ffmpeg 标准化视频失败: {error_msg}")
    except FileNotFoundError:
        raise RuntimeError("未找到 ffmpeg，请确保已安装并添加到 PATH")
    except subprocess.TimeoutExpired:
        raise RuntimeError("ffmpeg 标准化视频超时（600 秒）")

    return output_path


def _probe_video_duration(video_path: str) -> float:
    """用 ffprobe 获取视频时长（秒），失败返回 0。"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", video_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass
    return 0.0


def _split_video_by_duration(video_path: str, segment_seconds: float, output_dir: str,
                             node_id: str, callback=None) -> list[str]:
    """
    将视频按指定秒数分段（重编码为 h264 mp4，保证每段独立可播、可无缝拼接）。

    Args:
        video_path: 源视频绝对路径
        segment_seconds: 每段时长（秒）
        output_dir: 分段输出目录
        node_id: 节点 id（用于生成分段文件名）
        callback: 可选进度回调

    Returns:
        分段文件路径列表（按顺序）。探测失败或无需分段时返回 [video_path]。
    """
    total = _probe_video_duration(video_path)
    if total <= 0:
        return [video_path]  # 无法探测时长，整体上传
    n = max(1, math.ceil(total / segment_seconds))
    if n <= 1:
        return [video_path]  # 未超过分段阈值，整体上传

    os.makedirs(output_dir, exist_ok=True)
    segment_paths = []
    for i in range(n):
        start = i * segment_seconds
        end = min((i + 1) * segment_seconds, total)
        out_path = os.path.join(output_dir, f"{node_id}_part_{i + 1}.mp4")
        if callback:
            callback(30, f"分段 {i + 1}/{n}: {start:.0f}s - {end:.0f}s")
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", video_path,
            "-t", str(end - start),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            out_path,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg 分段失败（第 {i + 1}/{n} 段）: {result.stderr[-500:]}")
        except FileNotFoundError:
            raise RuntimeError("未找到 ffmpeg，请确保已安装并添加到 PATH")
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"ffmpeg 分段超时（600 秒），第 {i + 1}/{n} 段")
        segment_paths.append(out_path)

    return segment_paths


class S_MediaToUrl(BaseStep):
    step_id = "s_media_to_url"
    step_name = "媒体转链接"
    dependencies = []
    artifacts = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        cache_dir = os.path.join(task_dir, "cache")
        path = os.path.join(cache_dir, f"media_url_{node_id}.json")
        return os.path.exists(path)

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    @staticmethod
    def _resolve_media_path(task_dir: str, step_inputs: dict, node_config: dict) -> Optional[str]:
        """解析媒体文件路径：忠实于节点连线输入，或节点配置中指定的文件路径。"""
        # 1. 连线输入：按端口 id 读取（video / image / any）
        for port_id in ("video", "image", "any", "filepath"):
            raw = step_inputs.get(port_id, "")
            if not raw:
                continue
            p = raw if os.path.isabs(raw) else os.path.join(task_dir, raw)
            if os.path.isfile(p):
                return p

        # 2. 节点配置中直接指定的文件路径
        cfg_path = node_config.get("file_path", "")
        if cfg_path:
            p = cfg_path if os.path.isabs(cfg_path) else os.path.join(task_dir, cfg_path)
            if os.path.isfile(p):
                return p

        return None

    def _upload_with_timeout(self, media_path: str, timeout_sec: int,
                             callback: Optional[Callable] = None,
                             cancel_callback: Optional[Callable] = None,
                             label: str = "上传中") -> dict:
        """调用腾讯云 VOD 上传（内部含上传 + 轮询完整媒体信息），带节点级超时与取消。

        Returns:
            upload_result dict（含 url / meta_data 等）
        """
        from backend.auth.cloud_auth_service import upload_to_tencent_vod_with_details
        import time
        import threading

        result_holder: dict = {"data": None, "error": None}

        def _do_upload():
            try:
                data = upload_to_tencent_vod_with_details(media_path)
                result_holder["data"] = data
            except Exception as e:
                result_holder["error"] = e

        t = threading.Thread(target=_do_upload, daemon=True)
        t.start()

        # 协作等待：定期回调进度 + 检查取消
        start_time = time.time()
        progress = 30
        while t.is_alive():
            elapsed = time.time() - start_time
            if elapsed >= timeout_sec:
                t.join(timeout=1)
                if result_holder["error"] is None and result_holder["data"] is None:
                    result_holder["error"] = TimeoutError(
                        f"上传超时（{timeout_sec} 秒），文件可能过大或网络异常"
                    )
                break
            new_progress = min(90, progress + 1)
            if new_progress != progress:
                progress = new_progress
            if callback and progress % 5 == 0:
                callback(progress, f"{label}... {int(elapsed)}s / {timeout_sec}s")
            if cancel_callback and cancel_callback():
                from backend.control_plane.runtime import TaskCancelledError
                raise TaskCancelledError("用户取消上传")
            t.join(timeout=2)

        if result_holder["error"] is not None:
            raise result_holder["error"]
        if result_holder["data"] is None:
            raise RuntimeError("上传完成但未获取到媒体详情")
        return result_holder["data"]

    @staticmethod
    def _as_segment_duration_min(node_config: dict) -> int:
        """读取前端设置的分段时长（分钟），默认 30。"""
        raw = node_config.get("segment_duration", "30")
        try:
            v = int(raw)
            return v if v > 0 else 30
        except (TypeError, ValueError):
            return 30

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        if callback:
            callback(5, "解析输入媒体文件...")

        # 1. 解析媒体文件路径
        media_path = self._resolve_media_path(task_dir, step_inputs, node_config)
        if not media_path or not os.path.isfile(media_path):
            raise FileNotFoundError(
                "未找到可上传的媒体文件。请通过节点连线传入视频/图片，或在配置中指定文件路径。"
            )

        media_name = os.path.basename(media_path)
        if callback:
            callback(15, f"待上传文件: {media_name}")

        # 2. （可选）标准化视频：勾选后将视频重编码为 h264 mp4，>1080p 降分辨率
        normalize_video = node_config.get("normalize_video", False)
        if isinstance(normalize_video, str):
            normalize_video = normalize_video.lower() in ("true", "1", "yes")

        if normalize_video:
            is_video = media_path.lower().endswith(_VIDEO_EXTS)
            if not is_video:
                if callback:
                    callback(20, "标准化视频已跳过：输入非视频文件")
            else:
                cache_dir = os.path.join(task_dir, "cache")
                os.makedirs(cache_dir, exist_ok=True)
                normalized_path = os.path.join(cache_dir, f"normalized_{node_id}.mp4")
                if callback:
                    callback(18, "开始标准化视频（h264 重编码 + 分辨率检查）...")
                _normalize_video(media_path, normalized_path, callback=callback)
                media_path = normalized_path
                media_name = os.path.basename(media_path)
                if callback:
                    callback(25, f"标准化完成: {media_name}")

        # 3. 读取超时配置（秒）
        raw_timeout = node_config.get("timeout_sec", 300)
        try:
            timeout_sec = int(raw_timeout)
            if timeout_sec <= 0:
                timeout_sec = 300
        except (TypeError, ValueError):
            timeout_sec = 300

        # 3.5 判断是否视频 + 读取分段时长（分钟）
        is_video = media_path.lower().endswith(_VIDEO_EXTS)
        segment_duration_min = self._as_segment_duration_min(node_config)
        segment_seconds = segment_duration_min * 60

        # 4. 视频超过分段阈值：分段后逐段上传，结果以列表形式写入
        cache_dir = os.path.join(task_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)

        if is_video:
            total_duration = _probe_video_duration(media_path)
            if total_duration > segment_seconds:
                if callback:
                    callback(28, f"视频时长 {total_duration:.0f}s > 分段阈值 {segment_seconds:.0f}s，开始分段（每段 {segment_duration_min} 分钟）...")
                segment_dir = os.path.join(cache_dir, "segments")
                seg_paths = _split_video_by_duration(
                    media_path, segment_seconds, segment_dir, node_id, callback=callback
                )
                if len(seg_paths) > 1:
                    seg_results = []
                    total_segs = len(seg_paths)
                    for idx, seg_path in enumerate(seg_paths):
                        if callback:
                            callback(
                                max(30, 32 + int(58 * idx / total_segs)),
                                f"上传分段 {idx + 1}/{total_segs}...",
                            )
                        seg_upload = self._upload_with_timeout(
                            seg_path, timeout_sec, callback=callback,
                            cancel_callback=cancel_callback,
                            label=f"上传分段 {idx + 1}/{total_segs}",
                        )
                        seg_results.append(seg_upload)
                    # 组合：顶层兼容保留第一段 url/meta_data，segments 为列表
                    first = seg_results[0]
                    upload_result = {
                        "url": first.get("url", ""),
                        "file_id": first.get("file_id", ""),
                        "media_name": media_name,
                        "category": "Video",
                        "media_type": first.get("media_type", ""),
                        "storage_region": first.get("storage_region", ""),
                        "create_time": first.get("create_time", ""),
                        "meta_data": first.get("meta_data") or {},
                        "duration": total_duration,
                        "is_segmented": True,
                        "segment_duration_min": segment_duration_min,
                        "segment_count": len(seg_results),
                        "segments": [],
                    }
                    for i, seg_upload in enumerate(seg_results):
                        seg_meta = seg_upload.get("meta_data") or {}
                        start = i * segment_seconds
                        seg_dur = seg_meta.get("duration") or min(segment_seconds, max(0, total_duration - start))
                        upload_result["segments"].append({
                            "index": i + 1,
                            "start": round(start, 1),
                            "end": round(min((i + 1) * segment_seconds, total_duration), 1),
                            "duration": round(float(seg_dur or 0), 1),
                            "url": seg_upload.get("url", ""),
                            "file_id": seg_upload.get("file_id", ""),
                            "meta_data": seg_meta,
                        })
                    if callback:
                        callback(96, f"分段上传完成：共 {len(seg_results)} 段")
                    out_path = os.path.join(cache_dir, f"media_url_{node_id}.json")
                    with open(out_path, "w", encoding="utf-8") as f:
                        json.dump(upload_result, f, ensure_ascii=False, indent=2)
                    if callback:
                        callback(100, "完成")
                    return {
                        "artifacts": [f"cache/media_url_{node_id}.json"],
                        "outputs": {
                            "json": f"cache/media_url_{node_id}.json",
                        },
                    }

        # 5. 单段（图片 / 未超时长视频）：整体上传
        if callback:
            callback(30, "开始上传到腾讯云 VOD...")
        upload_result = self._upload_with_timeout(
            media_path, timeout_sec, callback=callback, cancel_callback=cancel_callback
        )
        upload_result.setdefault("is_segmented", False)
        upload_result.setdefault("segment_duration_min", segment_duration_min)
        upload_result.setdefault("segments", [])

        url = upload_result.get("url", "")
        if callback:
            callback(95, f"上传成功，URL: {url[:60]}...")

        # 6. 保存完整媒体详情为 JSON 文件
        out_path = os.path.join(cache_dir, f"media_url_{node_id}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(upload_result, f, ensure_ascii=False, indent=2)

        if callback:
            callback(100, "完成")

        return {
            "artifacts": [f"cache/media_url_{node_id}.json"],
            "outputs": {
                "json": f"cache/media_url_{node_id}.json",
            },
        }


StepMediaToUrl = S_MediaToUrl
