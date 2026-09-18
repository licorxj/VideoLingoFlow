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
import shutil
from typing import Callable, Optional

from backend.steps.base_step import BaseStep
from backend.config.config_manager import config
from backend.utils import audio_processor
from backend.utils.loudnorm import normalize_loudness
from backend.utils.subtitle_style_service import package_subtitles_to_ass


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

    @staticmethod
    def _resolve_input_path(task_dir: str, path: str) -> str:
        if not path or os.path.isabs(path):
            return path
        return os.path.join(task_dir, path)

    # ── Main execution ──

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        # 1. Read config
        preset_id = self._get_config("preset_id") or config.get("subtitle.default_preset", "")
        primary_on_top = self._get_config("primary_on_top", True)
        if isinstance(primary_on_top, str):
            primary_on_top = primary_on_top.lower() in ("true", "1", "yes")
        video_quality = str(self._get_config("default_quality", self._get_config("video_quality", "medium")))
        # 编码速度预设 / 显卡加速 / 超时时间（节点配置优先，其次全局配置）
        encode_preset = str(self._get_config("encode_preset", "medium"))
        gpu_accel = self._get_config("gpu_accel", False)
        if isinstance(gpu_accel, str):
            gpu_accel = gpu_accel.lower() in ("true", "1", "yes")
        ffmpeg_timeout = float(self._get_config("ffmpeg_timeout", 600) or 600)
        # 资源保护：编解码/滤镜线程上限（0=自动）、最长时长上限（0=不限制）
        try:
            ffmpeg_threads = int(self._get_config("ffmpeg_threads", 0) or 0)
        except (TypeError, ValueError):
            ffmpeg_threads = 0
        ffmpeg_threads = max(0, min(ffmpeg_threads, 64))
        try:
            max_duration_minutes = int(self._get_config("max_duration_minutes", 0) or 0)
        except (TypeError, ValueError):
            max_duration_minutes = 0
        max_duration_minutes = max(0, max_duration_minutes)
        bgm_path = step_inputs.get("audio") or self._get_config("bgm_path", "")
        dub_path = step_inputs.get("dub") or self._get_config("dub_path", "")
        bgm_path = self._resolve_input_path(task_dir, bgm_path)
        dub_path = self._resolve_input_path(task_dir, dub_path)
        dub_volume = float(self._get_config("dub_volume", 0.8))
        bgm_volume = float(self._get_config("bgm_volume", 0.3))
        fade_in = float(self._get_config("fade_in", 0.5))
        fade_out = float(self._get_config("fade_out", 0.5))

        # ── 与「音轨混响」节点互补对齐：音量/淡变按轨独立，BGM 循环可关 ──
        def _opt_float(key: str):
            """读取可选浮点配置；未配置返回 None，表示回退到 fade_in/fade_out。"""
            raw = self._get_config(key, None)
            if raw is None or raw == "":
                return None
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None

        bgm_fade_in = _opt_float("bgm_fade_in")
        bgm_fade_out = _opt_float("bgm_fade_out")
        dub_fade_in = _opt_float("dub_fade_in")
        dub_fade_out = _opt_float("dub_fade_out")
        original_volume = float(self._get_config("original_volume", 1.0) or 1.0)
        original_fade_in = float(self._get_config("original_fade_in", 0.0) or 0.0)
        original_fade_out = float(self._get_config("original_fade_out", 0.0) or 0.0)
        bgm_loop = self._get_config("bgm_loop", True)
        if isinstance(bgm_loop, str):
            bgm_loop = bgm_loop.lower() in ("true", "1", "yes")
        target_lufs = float(self._get_config("target_lufs", -16))
        mute_original = self._get_config("mute_original", False)
        if isinstance(mute_original, str):
            mute_original = mute_original.lower() in ("true", "1", "yes")

        if callback:
            callback(5, f"配置: 质量={video_quality}, 编码速度={encode_preset}, 显卡加速={'开' if gpu_accel else '关'}, "
                       f"线程上限={'自动' if ffmpeg_threads == 0 else ffmpeg_threads}, 超时={ffmpeg_timeout:.0f}s")

        # 2. Find video and subtitles
        video_path = self._resolve_input_path(
            task_dir,
            step_inputs.get("video") or os.path.join(task_dir, "cache", "input_video.mp4"),
        )
        if not os.path.exists(video_path):
            video_path = os.path.join(task_dir, "output", "video.mp4")
        if not os.path.exists(video_path):
            raise FileNotFoundError("未找到输入视频文件")

        cache_dir = os.path.join(task_dir, "cache")

        # 资源保护预检：时长上限 + 磁盘余量（快速失败，避免烧录到一半把机器拖垮）
        try:
            video_dur = audio_processor.get_video_duration(video_path)
        except Exception:
            video_dur = 0.0
        if max_duration_minutes > 0 and video_dur > max_duration_minutes * 60:
            raise RuntimeError(
                f"视频时长约 {video_dur / 60:.1f} 分钟，超过节点配置的上限 {max_duration_minutes} 分钟。"
                f"如确需处理长视频，请在节点「最长时长上限」中调大或设为 0（不限制）。"
            )
        try:
            input_bytes = os.path.getsize(video_path)
        except OSError:
            input_bytes = 0
        _ensure_disk_space(task_dir, input_bytes * 1.2)

        subtitle_input = step_inputs.get("subtitle")
        if subtitle_input:
            # 连线注入的路径可能是相对路径（相对 task_dir），需拼接到任务目录再判断
            subtitle_input = self._resolve_input_path(task_dir, subtitle_input)
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
            video_path, ass_path, video_quality, temp_video,
            encode_preset=encode_preset,
            gpu_accel=gpu_accel,
            # 长视频自动放宽超时：烧录是重编码，耗时随分辨率/时长增长；
            # 取「配置值」与「按时长估算值」的较大者，避免长视频必然超时。
            timeout=max(ffmpeg_timeout, video_dur * 10 + 300) if video_dur > 0 else ffmpeg_timeout,
            callback=(lambda pct, msg: callback(int(40 + pct * 0.2), msg)) if callback else None,
            cancel_callback=cancel_callback,
            threads=ffmpeg_threads,
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
                audio_processor.prepare_bgm(bgm_path, video_dur, bgm_prepared, loop=bool(bgm_loop))
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

            if not has_bgm and not has_dub:
                if mute_original:
                    raise RuntimeError("配音和背景音乐均不可用，无法在静音原视频后生成有声视频")
                if callback:
                    callback(80, "外部音频不可用，保留原视频音轨...")

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
                bgm_fade_in=bgm_fade_in,
                bgm_fade_out=bgm_fade_out,
                dub_fade_in=dub_fade_in,
                dub_fade_out=dub_fade_out,
                original_vol=original_volume,
                original_fade_in=original_fade_in,
                original_fade_out=original_fade_out,
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
        output_paths = [
            os.path.join(output_dir, f"video_with_dub{node_suffix}.mp4"),
            os.path.join(output_dir, f"video_with_subs{node_suffix}.mp4"),
        ]
        output_path = next((path for path in output_paths if os.path.exists(path)), None)
        if not output_path:
            return False
        mute_original = self._get_config("mute_original", False)
        if isinstance(mute_original, str):
            mute_original = mute_original.lower() in ("true", "1", "yes")
        return not mute_original or audio_processor._video_has_audio(output_path)

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
