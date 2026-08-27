"""s11_merge_dub_video: Merge audio with video (音视频合成).

支持：原视频静音开关、输入音频响度、淡入淡出。
- 原视频静音=True（默认）：仅使用输入音频替换原视频音轨；
- 原视频静音=False：将原视频音轨与输入音频混合（原视频无音轨时自动回退到仅输入音频）。
"""
import os
import subprocess
from typing import Callable, Optional

from backend.steps.base_step import BaseStep
from backend.config.config_manager import config


class S11MergeDubVideo(BaseStep):
    step_id = "s11_merge_dub_video"
    step_name = "音视频合成"
    dependencies = ["s10_merge_audio"]
    artifacts = ["output/video_dubbed.mp4"]

    def check_artifact(self, task_dir: str) -> bool:
        return self._all_exist(task_dir, self.artifacts)

    def validate_inputs(self, task_dir: str) -> bool:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        video_path = self._resolve(step_inputs.get("video"), task_dir,
                                   os.path.join(task_dir, "cache", "input_video.mp4"))
        audio_path = self._resolve_audio(step_inputs.get("audio"), task_dir)
        return bool(video_path) and bool(audio_path)

    # ───────────────────────── 工具 ─────────────────────────

    @staticmethod
    def _resolve(raw, task_dir, default=None):
        if isinstance(raw, list):
            raw = raw[0] if raw else None
        if not raw or not isinstance(raw, str):
            return default if (default and os.path.isfile(default)) else None
        if os.path.isabs(raw) and os.path.isfile(raw):
            return raw
        rel = os.path.join(task_dir, raw)
        if os.path.isfile(rel):
            return rel
        return raw if os.path.isfile(raw) else None

    @staticmethod
    def _resolve_audio(raw, task_dir):
        path = S11MergeDubVideo._resolve(raw, task_dir, None)
        if path:
            return path
        import glob
        matches = sorted(glob.glob(os.path.join(task_dir, "output", "dub.*")))
        return matches[0] if matches else None

    @staticmethod
    def _has_audio(path):
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "a",
                 "-show_entries", "stream=index", "-of", "csv=p=0", path],
                capture_output=True, text=True, timeout=30,
            )
            return bool(r.stdout.strip())
        except Exception:
            return False

    @staticmethod
    def _num(val, default):
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _bool(val, default):
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.strip().lower() in ("1", "true", "yes", "on")
        return bool(val)

    # ───────────────────────── 主流程 ─────────────────────────

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        video_path = self._resolve(step_inputs.get("video"), task_dir,
                                   os.path.join(task_dir, "cache", "input_video.mp4"))
        audio_path = self._resolve_audio(step_inputs.get("audio"), task_dir)
        if not video_path or not os.path.isfile(video_path):
            raise ValueError("音视频合成失败：未提供有效的视频文件")
        if not audio_path or not os.path.isfile(audio_path):
            raise ValueError("音视频合成失败：未提供有效的音频文件")

        # 前端配置
        video_mute = self._bool(node_config.get("video_mute"), True)
        volume = self._num(node_config.get("audio_volume"), 1.0)
        fade_in = self._num(node_config.get("audio_fade_in"), 0.0)
        fade_out = self._num(node_config.get("audio_fade_out"), 0.0)

        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "video_dubbed.mp4")

        if callback:
            callback(10, "准备视频与音频...")

        # 输入音频处理链：响度 + 淡入淡出（淡出默认作用于末尾）
        audio_chain = f"volume={volume}"
        if fade_in > 0:
            audio_chain += f",afade=t=in:d={fade_in}"
        if fade_out > 0:
            audio_chain += f",afade=t=out:d={fade_out}"

        has_orig_audio = self._has_audio(video_path)

        filter_parts = []
        if video_mute or not has_orig_audio:
            # 仅使用（处理过的）输入音频
            filter_parts.append(f"[1:a:0]{audio_chain}[a]")
            amap = ["-map", "0:v:0", "-map", "[a]"]
        else:
            # 混合原视频音轨与输入音频
            filter_parts.append("[0:a:0]volume=1[a0]")
            filter_parts.append(f"[1:a:0]{audio_chain}[a1]")
            filter_parts.append("[a0][a1]amix=inputs=2:dropout_transition=0[a]")
            amap = ["-map", "0:v:0", "-map", "[a]"]

        cmd = ["ffmpeg", "-y", "-i", video_path, "-i", audio_path]
        if filter_parts:
            cmd += ["-filter_complex", ";".join(filter_parts)]
        cmd += amap + ["-c:v", "copy", "-c:a", "aac", "-shortest", output_path]

        if callback:
            callback(40, "合成音视频...")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            if result.returncode != 0:
                err = result.stderr[-800:] if result.stderr else "Unknown error"
                raise Exception(f"ffmpeg 失败：{err}")
        except subprocess.TimeoutExpired:
            raise Exception("视频合成超时（>1小时）")
        except FileNotFoundError:
            raise Exception("未找到 ffmpeg，请先安装 ffmpeg")

        if callback:
            callback(100, "音视频合成完成")

        self.artifacts = ["output/video_dubbed.mp4"]
        return {
            "artifacts": self.artifacts,
            "outputs": {"video": "output/video_dubbed.mp4"},
        }
