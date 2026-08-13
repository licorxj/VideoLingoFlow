"""s11_merge_dub_video: Merge dubbed audio with video."""
import os
from typing import Callable, Optional
from backend.steps.base_step import BaseStep
from backend.config.config_manager import config


class S11MergeDubVideo(BaseStep):
    step_id = "s11_merge_dub_video"
    step_name = "配音视频合成"
    dependencies = ["s10_merge_audio"]
    artifacts = ["output/video_dubbed.mp4"]

    def check_artifact(self, task_dir: str) -> bool:
        return self._all_exist(task_dir, self.artifacts)

    def validate_inputs(self, task_dir: str) -> bool:
        video_path = os.path.join(task_dir, "cache", "input_video.mp4")
        audio_path = os.path.join(task_dir, "output", "final_audio.wav")
        if not os.path.exists(audio_path):
            # 兼容 s10 实际输出命名 output/dub.{fmt}
            import glob
            matches = sorted(glob.glob(os.path.join(task_dir, "output", "dub.*")))
            audio_path = matches[0] if matches else audio_path
        return os.path.exists(video_path) and os.path.exists(audio_path)

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        if callback:
            callback(10, "Preparing video and audio...")
        
        import subprocess
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        
        # Get paths
        video_path = step_inputs.get("video") or os.path.join(task_dir, "cache", "input_video.mp4")
        default_audio = os.path.join(task_dir, "output", "final_audio.wav")
        if not os.path.exists(default_audio):
            # 兼容 s10 实际输出命名 output/dub.{fmt}
            import glob
            matches = sorted(glob.glob(os.path.join(task_dir, "output", "dub.*")))
            default_audio = matches[0] if matches else default_audio
        audio_path = step_inputs.get("audio") or default_audio
        if not os.path.isabs(video_path):
            video_path = os.path.join(task_dir, video_path)
        if not os.path.isabs(audio_path):
            audio_path = os.path.join(task_dir, audio_path)
        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "video_dubbed.mp4")
        
        if callback:
            callback(30, "Merging audio with video...")
        
        # Build ffmpeg command to replace audio
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            output_path
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600  # 1 hour timeout
            )
            
            if result.returncode != 0:
                error_msg = result.stderr[:500] if result.stderr else "Unknown error"
                raise Exception(f"ffmpeg failed: {error_msg}")
            
        except subprocess.TimeoutExpired:
            raise Exception("Video processing timed out after 1 hour")
        except FileNotFoundError:
            raise Exception("ffmpeg not found. Please install ffmpeg.")
        
        if callback:
            callback(100, "Dubbed video created")
        
        return {
            "artifacts": ["output/video_dubbed.mp4"],
            "outputs": {
                "video": "output/video_dubbed.mp4",
            },
        }
