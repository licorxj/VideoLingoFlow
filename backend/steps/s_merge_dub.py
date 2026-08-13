"""s_merge_dub: 配音拼接节点 - 无时间戳纯文本配音片段的顺序合并。

适用于无时间戳要求的纯文本配音：读取配音任务单与各段已生成的配音音频，
按顺序拼接，在片段之间插入设定的静音间隔，按配置的格式/码率导出合并音频，
并生成与合并音频对齐的顺序时间戳配音字幕。
"""
import os
import json
from typing import Callable, Optional, List, Dict

from backend.steps.base_step import BaseStep, find_artifact
from backend.config.config_manager import config
from backend.utils.audio_segmenter import get_audio_output_settings

try:
    import numpy as np
except ImportError:
    np = None

try:
    from pydub import AudioSegment
    HAS_PYDUB = True
except ImportError:
    HAS_PYDUB = False


class S_MergeDub(BaseStep):
    step_id = "merge_dub"
    step_name = "配音拼接"
    dependencies = ["s09_tts"]

    # 支持拼接的音频扩展名
    AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".aac", ".m4a", ".wma", ".amr", ".opus"}

    @staticmethod
    def _load_manifest(task_dir: str, manifest_input: str = "") -> tuple[list, str]:
        """读取配音任务单，返回 (segments, manifest_path)。

        manifest_input 非空时作为任务单路径（绝对/相对 task_dir）；
        为空时回退到任务缓存中的 dub_task.json。
        """
        manifest_path = manifest_input or \
            find_artifact(os.path.join(task_dir, "cache"), "dub_task.json") or \
            os.path.join(task_dir, "cache", "dub_task.json")
        if not os.path.isabs(manifest_path):
            manifest_path = os.path.join(task_dir, manifest_path)
        if not os.path.exists(manifest_path):
            raise FileNotFoundError(f"配音任务单不存在: {manifest_path}")
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("segments", []), manifest_path

    @staticmethod
    def _list_audio_segments(audio_input: str, task_dir: str) -> tuple[list, str]:
        """从音频片段路径（单个文件或目录）构建片段列表。

        - 绝对路径直接使用；相对路径以任务执行目录（task_dir）为基准
        - 目录模式：列出目录下所有音频文件，按文件名升序排序

        Returns:
            (segments, audio_path): segments 每项含 index/text/read_text/audio_file
        """
        audio_path = audio_input if os.path.isabs(audio_input) else os.path.join(task_dir, audio_input)
        if os.path.isfile(audio_path):
            files = [audio_path]
        elif os.path.isdir(audio_path):
            files = sorted(
                os.path.join(audio_path, name)
                for name in os.listdir(audio_path)
                if os.path.splitext(name)[1].lower() in S_MergeDub.AUDIO_EXTS
            )
        else:
            raise FileNotFoundError(f"音频片段路径不存在: {audio_path}")

        if not files:
            raise RuntimeError(f"未在路径下找到任何音频文件: {audio_path}")

        segments = []
        for idx, path in enumerate(files):
            basename = os.path.splitext(os.path.basename(path))[0]
            segments.append({
                "index": idx,
                "text": basename,
                "read_text": basename,
                "audio_file": path,
            })
        return segments, audio_path

    @classmethod
    def _resolve_segments(cls, task_dir: str, step_inputs: dict) -> tuple[list, str, str]:
        """解析配音片段来源，返回 (segments, manifest_path, source_mode)。

        优先级：
        1. 配音任务单 JSON（audio_manifest / text）：两个输入都提供时以 JSON 为准，
           片段的 audio_file 相对路径按 TTS 保存规则基于 task_dir 读取。
        2. 音频片段路径（audio）：目录下所有音频文件按文件名升序排序拼接。
        3. 均未提供：回退到任务缓存中的 dub_task.json。
        """
        manifest_input = step_inputs.get("audio_manifest") or step_inputs.get("text")
        audio_input = step_inputs.get("audio")

        if manifest_input:
            segments, manifest_path = cls._load_manifest(task_dir, manifest_input)
            return segments, manifest_path, "json"
        if audio_input:
            segments, _ = cls._list_audio_segments(audio_input, task_dir)
            return segments, None, "dir"
        # 回退默认
        segments, manifest_path = cls._load_manifest(task_dir)
        return segments, manifest_path, "json"

    def check_artifact(self, task_dir: str) -> bool:
        output_dir = os.path.join(task_dir, "output")
        audio_format = get_audio_output_settings().get("format", "wav")
        return bool(
            find_artifact(output_dir, f"dub_merge.{audio_format}")
            and find_artifact(output_dir, "dub_merge.srt")
        )

    def validate_inputs(self, task_dir: str) -> bool:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        # 提供配音任务单 JSON 或音频片段路径任一输入即可
        if step_inputs.get("audio") or step_inputs.get("audio_manifest") or step_inputs.get("text"):
            return True
        cache_dir = os.path.join(task_dir, "cache")
        return bool(find_artifact(cache_dir, "dub_task.json"))

    # ───────────────────────── 主流程 ─────────────────────────

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        if callback:
            callback(5, "加载配音任务单...")

        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        # 读取设置面板参数
        audio_format_override = (node_config.get("audio_format") or "").strip()
        audio_bitrate_override = node_config.get("audio_bitrate")
        try:
            silence_interval = float(node_config.get("silence_interval", 0.5) or 0.5)
        except (TypeError, ValueError):
            silence_interval = 0.5
        silence_interval = max(0.0, min(10.0, silence_interval))

        segments, manifest_path, source_mode = self._resolve_segments(task_dir, step_inputs)
        total = len(segments)
        if total == 0:
            print("[S_MergeDub] 无配音片段，跳过拼接")
            return {"artifacts": [], "outputs": {}}

        print(f"\n[S_MergeDub] 配音拼接开始，共 {total} 段（来源: {'配音任务单JSON' if source_mode == 'json' else '音频片段路径'}）")
        print(f"[S_MergeDub] 配置: 格式={audio_format_override or '跟随全局'}, "
              f"码率={audio_bitrate_override or '跟随全局'}, 静音间隔={silence_interval}s")

        # 逐段顺序拼接，片段间插入静音
        if callback:
            callback(30, "逐段拼接配音音频...")
        merged_path, dub_srt_path, timings = self._merge_sequential(
            segments, task_dir,
            audio_format_override=audio_format_override,
            audio_bitrate_override=audio_bitrate_override,
            silence_interval=silence_interval,
            callback=callback,
        )
        if not merged_path or not os.path.exists(merged_path):
            raise RuntimeError("配音拼接失败：未生成合并音频")

        # 生成配音字幕（顺序时间戳，与合并音频对齐）
        if callback:
            callback(85, "生成配音字幕...")
        if not dub_srt_path:
            output_dir = os.path.join(task_dir, "output")
            os.makedirs(output_dir, exist_ok=True)
            dub_srt_path = os.path.join(output_dir, "dub_merge.srt")
        self._write_srt(segments, dub_srt_path, timings)

        # 回写任务单（补充合并后的实际时间戳），仅 JSON 来源时回写
        if manifest_path:
            for seg, (start, end) in zip(segments, timings):
                seg["new_start"] = round(start, 4)
                seg["new_end"] = round(end, 4)
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump({"segments": segments}, f, ensure_ascii=False, indent=2)

        if callback:
            callback(100, f"配音拼接完成，总时长 {timings[-1][1] if timings else 0:.3f}s")

        rel_audio = os.path.relpath(merged_path, task_dir).replace("\\", "/")
        rel_srt = os.path.relpath(dub_srt_path, task_dir).replace("\\", "/")
        return {
            "artifacts": [rel_audio, rel_srt],
            "outputs": {
                "audio": rel_audio,
                "dub_srt": rel_srt,
            },
        }

    # ─────────────────── 顺序拼接 ───────────────────

    def _merge_sequential(
        self,
        segments: List[Dict],
        task_dir: str,
        audio_format_override: str = "",
        audio_bitrate_override=None,
        silence_interval: float = 0.5,
        callback: Optional[Callable] = None,
    ) -> tuple[Optional[str], Optional[str], List[tuple]]:
        """逐段读取配音音频，顺序拼接并插入静音，导出合并音频。

        Returns:
            (merged_audio_path, dub_srt_path, timings): timings 为
            [(start, end), ...] 每段的实际起止时间（秒）。
        """
        import soundfile as sf
        from backend.utils.audio_speed import resample_audio

        if np is None:
            print("[S_MergeDub] 警告: numpy 未安装，无法拼接音频")
            return None, None, []

        output_settings = get_audio_output_settings()
        target_sr = int(output_settings.get("sample_rate", 48000))
        target_bit_depth = int(output_settings.get("bit_depth", 16) or 16)

        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""

        audio_format = (audio_format_override or output_settings["format"]).strip().lower() or "wav"
        merged_data = np.array([], dtype=np.float32)
        timings: List[tuple] = []
        skipped = 0
        total = len(segments)

        for i, seg in enumerate(segments):
            audio_rel = seg.get("audio_file", "")
            # JSON 来源：audio_file 为相对 task_dir 的路径（TTS 保存规则 cache/dub_temp/xxxx.wav）
            # 目录来源：audio_file 已解析为绝对路径
            audio_path = audio_rel if os.path.isabs(audio_rel) else os.path.join(task_dir, audio_rel)
            if not os.path.exists(audio_path) or os.path.getsize(audio_path) <= 0:
                print(f"  [{seg.get('index', i)}] ⚠ 音频文件不存在，跳过: {audio_path}")
                skipped += 1
                continue

            try:
                seg_data, seg_sr = sf.read(audio_path, dtype="float32")
            except Exception as e:
                print(f"  [{seg.get('index', i)}] ⚠ 读取失败: {e}")
                skipped += 1
                continue

            if seg_data.ndim > 1:
                seg_data = np.mean(seg_data, axis=1).astype(np.float32)
            if seg_sr != target_sr:
                seg_data = resample_audio(seg_data, seg_sr, target_sr)

            start = len(merged_data) / target_sr
            # 片段之间插入静音
            if i > 0 and silence_interval > 0:
                silence_samples = int(round(silence_interval * target_sr))
                merged_data = np.concatenate([
                    merged_data, np.zeros(silence_samples, dtype=np.float32)
                ])
            merged_data = np.concatenate([merged_data, seg_data])
            end = len(merged_data) / target_sr
            timings.append((round(start, 4), round(end, 4)))

            if callback and ((i + 1) % 20 == 0 or (i + 1) == total):
                pct = 30 + int((i + 1) / max(total, 1) * 50)
                callback(pct, f"拼接进度: {i + 1}/{total} 段")

        if merged_data.size == 0:
            print("[S_MergeDub] 没有任何有效音频片段，拼接失败")
            return None, None, []

        # 峰值保护
        peak = float(np.max(np.abs(merged_data)))
        if peak > 1e-8 and peak > 1.0:
            merged_data = merged_data / peak

        # 导出
        if audio_format == "wav":
            out_name = f"dub_merge{node_suffix}.wav"
            output_path = os.path.join(output_dir, out_name)
            wav_subtype = "PCM_24" if target_bit_depth >= 24 else "PCM_16"
            sf.write(output_path, merged_data, target_sr, subtype=wav_subtype)
        elif audio_format == "flac":
            out_name = f"dub_merge{node_suffix}.flac"
            output_path = os.path.join(output_dir, out_name)
            sf.write(output_path, merged_data, target_sr, format="FLAC")
        else:
            # mp3
            out_name = f"dub_merge{node_suffix}.mp3"
            output_path = os.path.join(output_dir, out_name)
            if HAS_PYDUB:
                import tempfile
                wav_tmp = os.path.join(output_dir, "_dub_merge_tmp.wav")
                sf.write(wav_tmp, merged_data, target_sr, subtype="PCM_16")
                bitrate = int(audio_bitrate_override) if audio_bitrate_override else output_settings["bitrate"]
                audio_seg = AudioSegment.from_wav(wav_tmp)
                audio_seg.export(output_path, format="mp3", bitrate=f"{bitrate}k")
                try:
                    os.remove(wav_tmp)
                except OSError:
                    pass
            else:
                output_path = os.path.join(output_dir, f"dub_merge{node_suffix}.wav")
                sf.write(output_path, merged_data, target_sr, subtype="PCM_16")

        dub_srt_path = os.path.join(output_dir, f"dub_merge{node_suffix}.srt")
        print(f"  - 已导出合并音频: {output_path}")
        print(f"  - 跳过 {skipped} 段无效音频")
        return output_path, dub_srt_path, timings

    # ─────────────────── 字幕生成 ───────────────────

    @staticmethod
    def _write_srt(segments: List[Dict], output_path: str, timings: List[tuple]) -> None:
        """生成与合并音频对齐的配音字幕（顺序时间戳）。"""
        lines = []
        count = 0
        for i, (seg, (start, end)) in enumerate(zip(segments, timings), 1):
            text = seg.get("read_text") or seg.get("text", "")
            if end <= start:
                end = start + 0.1
            lines.append(str(i))
            lines.append(f"{S_MergeDub._format_srt_time(start)} --> {S_MergeDub._format_srt_time(end)}")
            lines.append(text)
            lines.append("")
            count += 1
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"  - 配音字幕已生成: {output_path}，共 {count} 条")

    @staticmethod
    def _format_srt_time(seconds: float) -> str:
        total_ms = max(0, int(round(seconds * 1000)))
        h, rem = divmod(total_ms, 3600_000)
        m, rem = divmod(rem, 60_000)
        s, ms = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


StepMergeDub = S_MergeDub
