"""s13_watermark: Add watermark to video."""
import os
import subprocess
from typing import Callable, Optional
from backend.steps.base_step import BaseStep, find_artifact
from backend.config.config_manager import config


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

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        if callback:
            callback(10, "Checking watermark settings...")
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        
        # Check if watermark is enabled
        watermark_config = config.get("video.watermark") or {}
        watermark_enabled = watermark_config.get("enabled", False)
        
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
            
            # Get watermark settings
            watermark_image = step_inputs.get("image") or watermark_config.get("image_path", "")
            if watermark_image and not os.path.isabs(watermark_image):
                watermark_image = os.path.join(task_dir, watermark_image)
            position = watermark_config.get("position", "bottom-right")
            opacity = watermark_config.get("opacity", 0.5)
            
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
                cmd = [
                    "ffmpeg", "-y",
                    "-i", source_video,
                    "-i", watermark_image,
                    "-filter_complex", f"[1]format=rgba,colorchannelmixer=aa={opacity}[wm];[0][wm]overlay={overlay_pos}",
                    "-c:a", "copy",
                    output_path
                ]
                
                try:
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=3600
                    )
                    
                    if result.returncode != 0:
                        # Fallback: copy without watermark
                        import shutil
                        shutil.copy2(source_video, output_path)
                        
                except Exception as e:
                    print(f"Watermark failed: {e}")
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
