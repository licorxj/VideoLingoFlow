"""
s15_extract_audio: Extract audio from video using ffmpeg.
"""
import os
import sys
import subprocess
from typing import Callable, Optional
from backend.steps.base_step import BaseStep


class StepExtractAudio(BaseStep):
    step_id = "s15_extract_audio"
    step_name = "音频分离"
    dependencies = []

    # 源音频编码 -> 可流复制写入的容器扩展名
    AUDIO_CODEC_EXT = {
        "aac": "m4a",
        "alac": "m4a",
        "mp3": "mp3",
        "flac": "flac",
        "opus": "opus",
        "vorbis": "ogg",
        "ac3": "ac3",
        "eac3": "eac3",
        "dts": "dts",
        "pcm_s16le": "wav",
        "pcm_s24le": "wav",
        "pcm_s32le": "wav",
        "pcm_f32le": "wav",
    }

    # 目标保存格式 -> ffmpeg 重编码参数（format 设为 auto 时不重编码，直接流复制）
    FORMAT_ENCODE_ARGS = {
        "wav": ["-acodec", "pcm_s16le"],
        "mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
        "m4a": ["-c:a", "aac", "-b:a", "192k"],
        "flac": ["-c:a", "flac"],
        "ogg": ["-c:a", "libvorbis", "-q:a", "6"],
    }

    @property
    def artifacts(self):
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        return [f"output/extracted_audio{node_suffix}.*"]

    def check_artifact(self, task_dir: str) -> bool:
        import os
        output_dir = os.path.join(task_dir, "output")
        if not os.path.isdir(output_dir):
            return False
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        return any(
            name.startswith(f"extracted_audio{node_suffix}") for name in os.listdir(output_dir)
        )

    def _detect_source_audio_ext(self, video_path: str) -> str:
        """探测源视频音频流编码，返回对应容器扩展名（保证 -c:a copy 可写入）。

        探测失败或编码未知时返回空串，由调用方回退为 wav 重编码。
        """
        import json
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_streams", "-select_streams", "a:0", video_path],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                streams = (json.loads(result.stdout) or {}).get("streams") or []
                if streams:
                    codec = str(streams[0].get("codec_name") or "").lower()
                    return self.AUDIO_CODEC_EXT.get(codec, "")
        except Exception as e:
            print(f"[ExtractAudio] ffprobe failed: {e}")
        return ""

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

        # 读取节点配置的保存格式（空/auto = 保持源质量，直接流复制音频流）
        node_config = getattr(self, "_node_config", {}) or {}
        target_fmt = str(node_config.get("format", "") or "").strip().lower()
        if target_fmt and target_fmt != "auto" and target_fmt not in self.FORMAT_ENCODE_ARGS:
            raise ValueError(f"不支持的音频保存格式: {target_fmt}")

        src_fmt = self._detect_source_audio_ext(video_path)
        if target_fmt in ("", "auto"):
            fmt = src_fmt
            stream_copy = bool(fmt)
            if not fmt:
                print(f"[ExtractAudio] 无法识别源音频编码，回退为 wav 重编码")
                fmt = "wav"
        else:
            fmt = target_fmt
            # 目标容器与源编码容器一致时仍可流复制，避免重编码损耗
            stream_copy = bool(src_fmt) and src_fmt == fmt
            if not stream_copy:
                print(f"[ExtractAudio] 按设置重编码为 {fmt}")

        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        # Write to output/ for final artifacts
        output_path = os.path.join(output_dir, f"extracted_audio{node_suffix}.{fmt}")
        # Also write to cache/ with node_id prefix for artifact scanner
        cache_output = os.path.join(task_dir, "cache", f"extract_audio_audio{node_suffix}.{fmt}")

        if callback:
            callback(30, "Extracting audio from video...")

        if stream_copy:
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-vn",
                "-c:a", "copy",
                output_path,
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-vn",
                *self.FORMAT_ENCODE_ARGS.get(fmt, ["-acodec", "pcm_s16le"]),
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
