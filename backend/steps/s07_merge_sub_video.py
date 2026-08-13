"""s07_merge_sub_video: Video final composition — subtitle burn + audio mix + quality control.

Flow:
  1. Consume the connected subtitle output directly (legacy fallback only)
  2. Load subtitle style preset (from node config or global default)
  3. Convert SRT to ASS using ass_wrapper
  4. Burn subtitles into video with quality settings
  5. If BGM or dubbing provided: mix audio tracks with volume/fade control
  6. Output final video
"""
import json
import os
from typing import Callable, Optional

from backend.steps.base_step import BaseStep
from backend.config.config_manager import config
from backend.utils import audio_processor
from backend.utils.loudnorm import normalize_loudness
from backend.utils.subtitle_style_service import package_subtitles_to_ass


class S07MergeSubVideo(BaseStep):
    step_id = "s07_merge_sub_video"
    step_name = "字幕烧录"
    dependencies = ["s06_subtitle_gen"]
    artifacts = ["output/video_with_subs.mp4", "output/video_with_dub.mp4"]

    # ── Config resolution ──

    def _get_config(self, key: str, default=None):
        """Read from node config first, then global config.yaml."""
        node_cfg = getattr(self, "_node_config", {}) or {}
        val = node_cfg.get(key)
        if val is not None and val != "":
            return val
        # Try video section first, then bgm section, then subtitle section
        return config.get(f"video.{key}", config.get(f"bgm.{key}", config.get(f"subtitle.{key}", default)))

    # ── Subtitle file discovery ──

    @staticmethod
    def _find_subtitles(task_dir: str):
        """Legacy fallback when no explicit subtitle edge is connected."""
        cache = os.path.join(task_dir, "cache")
        bi = os.path.join(cache, "subtitles_bilingual.srt")
        tr = os.path.join(cache, "subtitles.srt")
        orig = os.path.join(cache, "subtitles_original.srt")

        if os.path.exists(tr) and os.path.exists(orig):
            return tr, orig
        if os.path.exists(bi):
            return bi, None
        if os.path.exists(tr):
            return tr, None
        if os.path.exists(orig):
            return orig, None

        raise FileNotFoundError("未找到字幕文件（subtitles.srt / subtitles_original.srt / subtitles_bilingual.srt）")

    # ── Main execution ──

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        # 1. Read config
        preset_id = self._get_config("preset_id") or config.get("subtitle.default_preset", "")
        primary_on_top = self._get_config("primary_on_top", True)
        if isinstance(primary_on_top, str):
            primary_on_top = primary_on_top.lower() in ("true", "1", "yes")
        video_quality = str(self._get_config("default_quality", self._get_config("video_quality", "medium")))
        bgm_path = step_inputs.get("audio") or self._get_config("bgm_path", "")
        dub_path = step_inputs.get("dub") or self._get_config("dub_path", "")
        dub_volume = float(self._get_config("dub_volume", 0.8))
        bgm_volume = float(self._get_config("bgm_volume", 0.3))
        fade_in = float(self._get_config("fade_in", 0.5))
        fade_out = float(self._get_config("fade_out", 0.5))
        target_lufs = float(self._get_config("target_lufs", -16))
        mute_original = self._get_config("mute_original", False)
        if isinstance(mute_original, str):
            mute_original = mute_original.lower() in ("true", "1", "yes")

        if callback:
            callback(5, f"配置: 质量={video_quality}")

        # 2. Find video and subtitles
        video_path = step_inputs.get("video") or os.path.join(task_dir, "cache", "input_video.mp4")
        if not os.path.isabs(video_path):
            video_path = os.path.join(task_dir, video_path)
        if not os.path.exists(video_path):
            video_path = os.path.join(task_dir, "output", "video.mp4")
        if not os.path.exists(video_path):
            raise FileNotFoundError("未找到输入视频文件")

        cache_dir = os.path.join(task_dir, "cache")
        subtitle_input = step_inputs.get("subtitle")
        if subtitle_input:
            # 连线注入的路径可能是相对路径（相对 task_dir），需拼接到任务目录再判断
            if not os.path.isabs(subtitle_input):
                subtitle_input = os.path.join(task_dir, subtitle_input)
        if subtitle_input and os.path.exists(subtitle_input):
            srt_primary = subtitle_input
            srt_secondary = None
        else:
            srt_primary, srt_secondary = self._find_subtitles(task_dir)

        if callback:
            callback(15, f"字幕: {os.path.basename(srt_primary)}" + 
                     (f" + {os.path.basename(srt_secondary)}" if srt_secondary else ""))

        # 3. Load preset and generate ASS
        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        if callback:
            callback(25, "生成 ASS 字幕文件...")

        ass_path = os.path.join(cache_dir, "subtitles.ass")
        package_result = package_subtitles_to_ass(
            primary_srt_path=srt_primary,
            secondary_srt_path=srt_secondary,
            output_ass_path=ass_path,
            preset_id=preset_id,
            primary_on_top=primary_on_top,
        )
        if callback:
            callback(32, f"字幕样式包装: {'双语' if package_result['mode'] == 'dual' else '单语'}")

        # 4. Burn subtitles into video
        if callback:
            callback(40, f"烧录字幕 (质量: {video_quality})...")

        temp_video = os.path.join(output_dir, "video_with_subs_temp.mp4")
        has_dub = dub_path and os.path.exists(dub_path)
        node_suffix = f"_{self._node_id}" if self._node_id else ""
        output_filename = f"video_with_dub{node_suffix}.mp4" if has_dub else f"video_with_subs{node_suffix}.mp4"
        final_output = os.path.join(output_dir, output_filename)

        audio_processor.encode_video_with_quality(
            video_path, ass_path, video_quality, temp_video
        )

        # 5. Audio mixing (if BGM or dubbing provided, or mute_original is enabled)
        has_bgm = bgm_path and os.path.exists(bgm_path)

        if has_bgm or has_dub:
            if callback:
                callback(65, "处理音频混合...")

            # Normalize BGM and dubbing loudness before mixing
            processed_bgm = None
            processed_dub = None

            if has_bgm:
                if callback:
                    callback(70, "准备 BGM...")
                video_dur = audio_processor.get_video_duration(temp_video)
                bgm_prepared = os.path.join(cache_dir, "bgm_prepared.wav")
                audio_processor.prepare_bgm(bgm_path, video_dur, bgm_prepared)
                processed_bgm = os.path.join(cache_dir, "bgm_normalized.wav")
                normalize_loudness(bgm_prepared, target_lufs, processed_bgm)
                if not os.path.exists(processed_bgm):
                    print(f"  ⚠ BGM标准化失败，跳过BGM")
                    has_bgm = False
                    processed_bgm = None

            if has_dub:
                if callback:
                    callback(75, "标准化配音响度...")
                processed_dub = os.path.join(cache_dir, "dub_normalized.wav")
                normalize_loudness(dub_path, target_lufs, processed_dub)
                if not os.path.exists(processed_dub):
                    print(f"  ⚠ 配音标准化失败，跳过配音: {dub_path}")
                    has_dub = False
                    processed_dub = None

            if callback:
                callback(80, "混合音频轨道...")

            audio_processor.mix_audio(
                video_path=temp_video,
                bgm_path=processed_bgm,
                dub_path=processed_dub,
                bgm_vol=bgm_volume,
                dub_vol=dub_volume,
                fade_in=fade_in,
                fade_out=fade_out,
                output_path=final_output,
                mute_original=mute_original,
            )

            # Clean up temp files
            if os.path.exists(temp_video):
                os.remove(temp_video)
        elif mute_original:
            # Only mute original video audio without mixing
            if callback:
                callback(65, "静音原视频...")
            if os.path.exists(final_output):
                os.remove(final_output)
            audio_processor.mute_video_audio(temp_video, final_output)
            if os.path.exists(temp_video):
                os.remove(temp_video)
        else:
            # No audio processing needed, just rename
            if os.path.exists(final_output):
                os.remove(final_output)
            os.rename(temp_video, final_output)

        if callback:
            callback(95, "验证输出...")

        if not os.path.exists(final_output):
            raise RuntimeError("视频合成失败，输出文件不存在")

        if callback:
            callback(100, "视频合成完成")

        return {
            "artifacts": [f"output/{output_filename}"],
            "outputs": {
                "video": f"output/{output_filename}",
            },
            "output_path": final_output,
        }

    def check_artifact(self, task_dir: str) -> bool:
        output_dir = os.path.join(task_dir, "output")
        node_suffix = f"_{self._node_id}" if self._node_id else ""
        return os.path.exists(os.path.join(output_dir, f"video_with_subs{node_suffix}.mp4")) or \
               os.path.exists(os.path.join(output_dir, f"video_with_dub{node_suffix}.mp4"))

    def validate_inputs(self, task_dir: str) -> bool:
        cache = os.path.join(task_dir, "cache")
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        has_video = os.path.exists(os.path.join(cache, "input_video.mp4")) or \
                    os.path.exists(os.path.join(task_dir, "output", "video.mp4"))
        subtitle_input = step_inputs.get("subtitle")
        if subtitle_input:
            # 连线注入的路径可能是相对路径（相对 task_dir），需拼接到任务目录再判断
            if not os.path.isabs(subtitle_input):
                subtitle_input = os.path.join(task_dir, subtitle_input)
        has_srt = (
            bool(subtitle_input and os.path.exists(subtitle_input))
            or os.path.exists(os.path.join(cache, "subtitles.srt"))
            or os.path.exists(os.path.join(cache, "subtitles_original.srt"))
            or os.path.exists(os.path.join(cache, "subtitles_bilingual.srt"))
        )
        return has_video and has_srt

    def rollback(self, task_dir: str):
        node_suffix = f"_{self._node_id}" if self._node_id else ""
        for f in [f"video_with_subs{node_suffix}.mp4", f"video_with_dub{node_suffix}.mp4", "video_with_subs_temp.mp4"]:
            path = os.path.join(task_dir, "output", f)
            if os.path.exists(path):
                os.remove(path)
        for f in ["subtitles.ass", "bgm_prepared.wav", "bgm_normalized.wav", "dub_normalized.wav"]:
            path = os.path.join(task_dir, "cache", f)
            if os.path.exists(path):
                os.remove(path)
