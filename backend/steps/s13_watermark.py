"""s13_watermark: Add watermark to video."""
import os
import shutil
import subprocess
from typing import Callable, Optional
from backend.steps.base_step import BaseStep, find_artifact
from backend.config.config_manager import config
from backend.utils.video_encoder import build_video_encode_args


def _ffprobe_width(path: str):
    """返回视频宽度（像素）；失败返回 None。"""
    try:
        exe = shutil.which("ffprobe") or "ffprobe"
        result = subprocess.run(
            [exe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        w = (result.stdout or "").strip()
        return int(w) if w else None
    except Exception:
        return None


def _scale_watermark(src: str, target_width: int, dst: str) -> bool:
    """把水印图片等比缩放到目标宽度（高度自动），成功返回 True。"""
    try:
        exe = shutil.which("ffmpeg") or "ffmpeg"
        subprocess.run(
            [exe, "-y", "-i", src, "-vf", f"scale={int(target_width)}:-1", dst],
            capture_output=True, timeout=60, encoding="utf-8", errors="replace",
        )
        return os.path.isfile(dst) and os.path.getsize(dst) > 0
    except Exception:
        return False


class S13Watermark(BaseStep):
    step_id = "s13_watermark"
    step_name = "水印添加"
    dependencies = ["s11_merge_dub_video"]

    @property
    def artifacts(self):
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        return [f"output/video_final{node_suffix}.mp4"]

    def check_artifact(self, task_dir: str) -> bool:
        return bool(find_artifact(os.path.join(task_dir, "output"), "video_final.mp4"))

    def validate_inputs(self, task_dir: str) -> bool:
        # Check for any video file to add watermark to
        video_paths = [
            find_artifact(os.path.join(task_dir, "output"), "video_dubbed.mp4"),
            find_artifact(os.path.join(task_dir, "output"), "video_with_subs.mp4"),
            os.path.join(task_dir, "cache", "input_video.mp4"),
        ]
        return any(p and os.path.exists(p) for p in video_paths)

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        if callback:
            callback(10, "Checking watermark settings...")
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        
        # 优先读取节点自身配置（前端面板），回退到全局 config.yaml 的 video.watermark
        node_config = getattr(self, "_node_config", {}) or {}
        global_wm = config.get("video.watermark") or {}

        def _wm_get(key, default):
            v = node_config.get(key)
            if v not in (None, ""):
                return v
            return global_wm.get(key, default)

        watermark_enabled = _wm_get("enabled", False)
        
        # Find source video
        source_video = step_inputs.get("video")
        if source_video and not os.path.isabs(source_video):
            source_video = os.path.join(task_dir, source_video)
        for path in [
            find_artifact(os.path.join(task_dir, "output"), "video_dubbed.mp4"),
            find_artifact(os.path.join(task_dir, "output"), "video_with_subs.mp4"),
            os.path.join(task_dir, "cache", "input_video.mp4")
        ]:
            if source_video:
                break
            if path and os.path.exists(path):
                source_video = path
                break
        
        if source_video is None:
            raise FileNotFoundError("No source video found")
        
        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        output_path = os.path.join(output_dir, f"video_final{node_suffix}.mp4")
        
        if not watermark_enabled:
            if callback:
                callback(50, "Watermark disabled, copying video...")
            # Just copy the source video
            import shutil
            shutil.copy2(source_video, output_path)
        else:
            if callback:
                callback(30, "Adding watermark...")
            
            # Get watermark settings（节点配置优先，全局配置回退）
            watermark_image = step_inputs.get("image") or _wm_get("image_path", "")
            if watermark_image and not os.path.isabs(watermark_image):
                watermark_image = os.path.join(task_dir, watermark_image)
            position = _wm_get("position", "bottom-right")
            opacity_raw = _wm_get("opacity", 0.5)
            try:
                opacity = float(opacity_raw)
            except (TypeError, ValueError):
                opacity = 0.5
            # 兼容百分比(>1，如 50 表示 50%)与小数(<=1)两种写法
            if opacity > 1:
                opacity = opacity / 100.0
            opacity = max(0.05, min(1.0, opacity))

            # 水印大小：按「水印宽度 / 视频宽度」比例缩放（size 为 0~1）
            size_raw = _wm_get("size", 0.2)
            try:
                size_ratio = float(size_raw)
            except (TypeError, ValueError):
                size_ratio = 0.2
            size_ratio = max(0.05, min(1.0, size_ratio))
            if size_ratio < 1.0:
                video_w = _ffprobe_width(source_video)
                if video_w:
                    target_w = max(2, int(round(video_w * size_ratio)))
                    cache_dir = os.path.join(task_dir, "cache")
                    os.makedirs(cache_dir, exist_ok=True)
                    scaled_path = os.path.join(cache_dir, f"wm_scaled_{node_suffix or 'x'}.png")
                    if _scale_watermark(watermark_image, target_w, scaled_path):
                        watermark_image = scaled_path
            
            # Map position to ffmpeg overlay coordinates
            position_map = {
                "top-left": "10:10",
                "top-right": "W-w-10:10",
                "bottom-left": "10:H-h-10",
                "bottom-right": "W-w-10:H-h-10",
                "center": "(W-w)/2:(H-h)/2"
            }
            overlay_pos = position_map.get(position, "W-w-10:H-h-10")
            
            if os.path.exists(watermark_image):
                # Add watermark using ffmpeg
                from backend.control_plane.runtime import TaskCancelledError
                from backend.utils.ffmpeg_guard import adaptive_timeout, resource_args
                from backend.utils.video_ops import get_video_duration, run_ffmpeg_with_progress

                cmd = [
                    "ffmpeg", "-y",
                    "-i", source_video,
                    "-i", watermark_image,
                    "-filter_complex", f"[1]format=rgba,colorchannelmixer=aa={opacity}[wm];[0][wm]overlay={overlay_pos}",
                    # 叠加滤镜必须重编码；全局「使用显卡加速 (NVIDIA NVENC)」开启时用 h264_nvenc
                    *build_video_encode_args("libx264", crf=23, preset="medium"),
                    "-c:a", "copy",
                    # 全片重编码：限制线程 / 封装队列
                    *resource_args(),
                    "-progress", "pipe:1", "-nostats",
                    output_path
                ]

                try:
                    try:
                        duration = float(get_video_duration(source_video) or 0)
                    except Exception:
                        duration = 0.0
                    run_ffmpeg_with_progress(
                        cmd, duration, callback, cancel_callback,
                        timeout=adaptive_timeout(duration), label="叠加水印",
                    )
                except TaskCancelledError:
                    raise
                except Exception as e:
                    # 降级为「不加 watermark」但**明确告警**：输出仍产出（不阻断链路），
                    # 但日志与进度都标注未加水印成功，避免此前静默拷贝冒充成功。
                    print(f"[Watermark] 加水印失败，已降级为无水印输出：{e}")
                    if callback:
                        try:
                            callback(90, f"警告：加水印失败，已输出无水印视频（{str(e)[:60]}）")
                        except Exception:
                            pass
                    import shutil
                    shutil.copy2(source_video, output_path)
            else:
                # No watermark image, just copy
                import shutil
                shutil.copy2(source_video, output_path)
        
        if callback:
            callback(100, "Final video ready")
        
        return {
            "artifacts": [f"output/video_final{node_suffix}.mp4"],
            "outputs": {
                "video": f"output/video_final{node_suffix}.mp4",
            },
        }
