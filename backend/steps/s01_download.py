"""s01_download: Download or import video file."""
import os
import shutil
from typing import Callable, Optional
from backend.steps.base_step import BaseStep
from backend.config.config_manager import config


class S01Download(BaseStep):
    step_id = "s01_download"
    step_name = "下载/导入视频"
    dependencies = []
    artifacts = ["cache/input_video.mp4"]

    def check_artifact(self, task_dir: str) -> bool:
        return self._all_exist(task_dir, self.artifacts)

    def validate_inputs(self, task_dir: str) -> bool:
        """Check if input file is specified."""
        return True

    def _validate_video(self, video_path: str):
        """Validate that the file is a valid video."""
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        file_size = os.path.getsize(video_path)
        if file_size < 1024:
            raise ValueError("Video file is too small or corrupted")

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        if callback:
            callback(5, "Initializing download step...")
        
        # Read task info to get input file
        task_info_path = os.path.join(task_dir, "task.json")
        import json
        with open(task_info_path, "r", encoding="utf-8") as f:
            task_info = json.load(f)
        
        input_files = task_info.get("input_files", {})
        video_source = input_files.get("video", "")
        
        if not video_source:
            raise ValueError("No video file specified in task input")
        
        # Prepare destination
        cache_dir = os.path.join(task_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        dest_path = os.path.join(cache_dir, "input_video.mp4")
        
        # Check if already exists
        if os.path.exists(dest_path):
            if callback:
                callback(100, "Video already exists in cache")
            return {
                "artifacts": ["cache/input_video.mp4"],
                "outputs": {
                    "video": "cache/input_video.mp4",
                },
            }
        
        # Extract filename from video_source path
        video_filename = os.path.basename(video_source)
        
        # Check if source file exists in cache (already copied by task manager)
        source_in_cache = os.path.join(cache_dir, video_filename)
        if os.path.exists(source_in_cache):
            # Rename to input_video.mp4
            if callback:
                callback(50, "Renaming video file...")
            shutil.move(source_in_cache, dest_path)
            if callback:
                callback(100, "Video ready")
            return {
                "artifacts": ["cache/input_video.mp4"],
                "outputs": {
                    "video": "cache/input_video.mp4",
                },
            }
        
        # Try to find the source file elsewhere
        source_path = None
        
        # Check if it's an absolute path
        if os.path.isabs(video_source) and os.path.exists(video_source):
            source_path = video_source
        else:
            # Check relative to task directory
            task_relative = os.path.join(task_dir, video_source)
            if os.path.exists(task_relative):
                source_path = task_relative
            # Check relative to project root
            elif os.path.exists(video_source):
                source_path = video_source
        
        if source_path is None:
            raise FileNotFoundError(f"Source video not found: {video_source}")
        
        # Copy the file
        if callback:
            callback(50, f"Copying video from: {source_path}")
        shutil.copy2(source_path, dest_path)
        
        # Validate the video
        if callback:
            callback(98, "Validating video...")
        self._validate_video(dest_path)
        
        if callback:
            callback(100, "Video ready")
        
        return {
            "artifacts": ["cache/input_video.mp4"],
            "outputs": {
                "video": "cache/input_video.mp4",
            },
        }
