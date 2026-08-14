"""
s15_extract_audio: Extract audio from video using ffmpeg.
"""
import os
import sys
import subprocess
from typing import Callable, Optional
from backend.steps.base_step import BaseStep, find_artifact


class StepExtractAudio(BaseStep):
    step_id = "s15_extract_audio"
    step_name = "音频分离"
    dependencies = []

    @property
    def artifacts(self):
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        return [f"output/extracted_audio{node_suffix}.wav"]

    def check_artifact(self, task_dir: str) -> bool:
        return bool(find_artifact(os.path.join(task_dir, "output"), "extracted_audio.wav"))

    def validate_inputs(self, task_dir: str) -> bool:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        # 优先检查上游连线传入的视频路径
        video_input = step_inputs.get("video", "")
        if video_input:
            p = video_input if os.path.isabs(video_input) else os.path.join(task_dir, video_input)
            if os.path.exists(p):
                return True
        # 回退：检查缓存默认路径
        video_path = os.path.join(task_dir, "cache", "input_video.mp4")
        return os.path.exists(video_path)

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        if callback:
            callback(10, "Preparing audio extraction...")

        step_inputs = getattr(self, "_step_inputs", {}) or {}
        cache_dir = os.path.join(task_dir, "cache")

        # 优先使用上游连线传入的视频路径
        video_path = step_inputs.get("video", "")
        if video_path and not os.path.isabs(video_path):
            video_path = os.path.join(task_dir, video_path)
        if video_path and os.path.exists(video_path):
            print(f"[ExtractAudio] Using upstream video: {video_path}")
        else:
            # 回退：扫描 cache 目录
            video_path = ""
            if os.path.exists(cache_dir):
                for f in os.listdir(cache_dir):
                    if f.startswith("input_video") or (f.endswith(('.mp4', '.mkv', '.webm', '.avi', '.mov')) and not f.startswith("input_audio")):
                        video_path = os.path.join(cache_dir, f)
                        break
                if not video_path:
                    for f in os.listdir(cache_dir):
                        if f.endswith(('.mp4', '.mkv', '.webm', '.avi', '.mov')):
                            video_path = os.path.join(cache_dir, f)
                            break
        if not video_path:
            raise FileNotFoundError(
                f"音频分离输入视频不存在。请检查上游连线是否正确连接视频。"
            )

        node_config = getattr(self, '_node_config', {}) or {}
        # 音频质量：节点优先、全局设置兜底（格式/采样率/位深/声道/码率）
        from backend.utils.audio_quality import resolve_audio_quality, ffmpeg_encode_args
        quality = resolve_audio_quality(node_config)
        fmt = quality["format"]

        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        # Write to output/ for final artifacts
        output_path = os.path.join(output_dir, f"extracted_audio{node_suffix}.{fmt}")
        # Also write to cache/ with node_id prefix for artifact scanner
        cache_output = os.path.join(task_dir, "cache", f"extract_audio_audio{node_suffix}.{fmt}")

        if callback:
            callback(30, "Extracting audio from video...")

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vn",
            *ffmpeg_encode_args(quality),
            output_path,
        ]

        if callback:
            callback(50, "Running ffmpeg...")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
            )
            if result.returncode != 0:
                # Filter out ffmpeg version/header info, show actual error
                stderr = result.stderr or ""
                lines = stderr.strip().split("\n")
                # Skip version/config header lines, find actual error
                error_lines = []
                skip_header = True
                for line in lines:
                    if skip_header and (line.startswith("ffmpeg version") or
                                        line.startswith("  built with") or
                                        line.startswith("  configuration:") or
                                        line.startswith("  lib")):
                        continue
                    skip_header = False
                    if line.strip():
                        error_lines.append(line.strip())
                error_msg = "\n".join(error_lines[-5:]) if error_lines else stderr[-300:]
                raise Exception("ffmpeg failed:\n" + error_msg)
        except subprocess.TimeoutExpired:
            raise Exception("Audio extraction timed out after 10 minutes")
        except FileNotFoundError:
            raise Exception("ffmpeg not found. Please install ffmpeg or place ffmpeg.exe in the venv Scripts directory.")

        if callback:
            callback(100, "Audio extraction completed")

        # Copy to cache for artifact scanner
        import shutil
        shutil.copy2(output_path, cache_output)

        return {
            "artifacts": [f"output/extracted_audio{node_suffix}.{fmt}"],
            "outputs": {
                "audio": f"output/extracted_audio{node_suffix}.{fmt}",
            },
            "output_path": output_path,
            "cache_audio": cache_output,
        }
