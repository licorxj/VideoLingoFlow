# -*- coding: utf-8 -*-
"""音轨混响节点（track_mix）。

将最多四路音频（主音轨、背景音乐、音轨3、音轨4）按前端设置混合后输出：
- 总时长控制：longest（以最长音轨为准）/ main（以主音轨为准）
- 每个音轨独立设置：响度（增益）、淡入/淡出时间、是否循环（主音轨固定不循环）

输出一段混音音频。基于 pydub（AudioSegment）实现。
"""
import os
import math

from backend.steps.base_step import BaseStep

try:
    from pydub import AudioSegment
    HAS_PYDUB = True
except ImportError:
    HAS_PYDUB = False


def _vol_to_gain_db(volume):
    """响度倍数 -> dB。volume=1 表示不增益(0dB)。"""
    try:
        volume = float(volume)
    except (TypeError, ValueError):
        volume = 1.0
    if volume <= 0:
        return -120.0
    return 20.0 * math.log10(volume)


def _make_silent(duration_ms, frame_rate, sample_width, channels):
    """构造与参考音轨同参数的静音片段（兼容旧版 pydub）。"""
    return (
        AudioSegment.silent(duration_ms, frame_rate=frame_rate)
        .set_sample_width(sample_width)
        .set_channels(channels)
    )


class S_TrackMix(BaseStep):
    step_id = "track_mix"

    def check_artifact(self, task_dir):
        node_id = getattr(self, "_node_id", "")
        prefix = f"track_mix_{node_id}" if node_id else "track_mix"
        cache_dir = os.path.join(task_dir, "cache")
        if not os.path.isdir(cache_dir):
            return False
        return any(f.startswith(prefix) for f in os.listdir(cache_dir))

    def validate_inputs(self, task_dir):
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        raw = step_inputs.get("main_audio")
        if isinstance(raw, list):
            raw = raw[0] if raw else None
        return bool(raw)

    # ───────────────────────── 工具 ─────────────────────────

    @staticmethod
    def _resolve_audio(step_inputs, key, task_dir):
        raw = step_inputs.get(key)
        if isinstance(raw, list):
            raw = raw[0] if raw else None
        if not raw or not isinstance(raw, str):
            return None
        if os.path.isabs(raw) and os.path.isfile(raw):
            return raw
        rel = os.path.join(task_dir, raw)
        if os.path.isfile(rel):
            return rel
        return raw if os.path.isfile(raw) else None

    @staticmethod
    def _cfg(node_config, key, default):
        val = node_config.get(key)
        if val is None or val == "":
            return default
        return val

    @staticmethod
    def _process_track(seg, volume, fade_in, fade_out, loop, target_ms, ref_params):
        """按响度/淡入淡出/循环处理单条音轨，并裁剪/填充到目标时长。"""
        # 统一采样参数，保证 overlay 不会因格式不一致报错
        seg = seg.set_frame_rate(ref_params["frame_rate"])
        seg = seg.set_channels(ref_params["channels"])
        seg = seg.set_sample_width(ref_params["sample_width"])

        seg = seg.apply_gain(_vol_to_gain_db(volume))

        if loop and len(seg) > 0 and len(seg) < target_ms:
            reps = target_ms // len(seg) + 1
            seg = seg * reps

        if fade_in and fade_in > 0:
            seg = seg.fade_in(int(round(fade_in * 1000)))
        if fade_out and fade_out > 0:
            seg = seg.fade_out(int(round(fade_out * 1000)))

        if len(seg) < target_ms:
            seg = seg + _make_silent(
                target_ms - len(seg),
                ref_params["frame_rate"],
                ref_params["sample_width"],
                ref_params["channels"],
            )
        elif len(seg) > target_ms:
            seg = seg[:target_ms]
        return seg

    # ───────────────────────── 主流程 ─────────────────────────

    def run(self, task_dir, callback=None, cancel_callback=None):
        if not HAS_PYDUB:
            raise RuntimeError("未找到 pydub，请先安装：pip install pydub（并安装 ffmpeg）")

        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        node_id = getattr(self, "_node_id", "")
        cache_dir = os.path.join(task_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)

        main_path = self._resolve_audio(step_inputs, "main_audio", task_dir)
        if not main_path or not os.path.isfile(main_path):
            raise ValueError("音轨混响失败：主音轨(main_audio)为必填且文件必须存在")

        if callback:
            callback(10, "加载主音轨...")
        main_seg = AudioSegment.from_file(main_path)
        ref_params = {
            "frame_rate": main_seg.frame_rate,
            "channels": main_seg.channels,
            "sample_width": main_seg.sample_width,
        }

        others = []
        for key in ("bgm", "track3", "track4"):
            p = self._resolve_audio(step_inputs, key, task_dir)
            if p and os.path.isfile(p):
                others.append(AudioSegment.from_file(p))

        # 总时长模式
        duration_mode = self._cfg(node_config, "duration_mode", "longest")
        if duration_mode == "main":
            target_ms = len(main_seg)
        else:  # longest
            target_ms = max([len(main_seg)] + [len(s) for s in others])

        if target_ms <= 0:
            raise ValueError("音轨混响失败：主音轨时长为 0")

        if callback:
            callback(25, "处理主音轨（淡入淡出/响度）...")

        def _getf(prefix, name, default):
            return float(self._cfg(node_config, f"{prefix}_{name}", default))

        # 主音轨（固定不循环）
        main_proc = self._process_track(
            main_seg,
            volume=_getf("main", "volume", 1.0),
            fade_in=_getf("main", "fade_in", 0.3),
            fade_out=_getf("main", "fade_out", 0.3),
            loop=False,
            target_ms=target_ms,
            ref_params=ref_params,
        )

        result = _make_silent(
            target_ms,
            ref_params["frame_rate"],
            ref_params["sample_width"],
            ref_params["channels"],
        )
        result = result.overlay(main_proc)

        # 其他音轨
        extra_defs = [
            ("bgm", [("volume", 0.3), ("fade_in", 1.0), ("fade_out", 1.0), ("loop", True)]),
            ("track3", [("volume", 0.5), ("fade_in", 0.3), ("fade_out", 0.3), ("loop", False)]),
            ("track4", [("volume", 0.5), ("fade_in", 0.3), ("fade_out", 0.3), ("loop", False)]),
        ]
        for idx, (prefix, defaults) in enumerate(extra_defs, start=1):
            p = self._resolve_audio(step_inputs, prefix, task_dir)
            if not p or not os.path.isfile(p):
                continue
            seg = AudioSegment.from_file(p)
            kwargs = {
                name: (
                    bool(self._cfg(node_config, f"{prefix}_{name}", d))
                    if name == "loop"
                    else float(self._cfg(node_config, f"{prefix}_{name}", d))
                )
                for name, d in defaults
            }
            if callback:
                callback(35 + idx * 15, f"处理{prefix}（淡入淡出/响度/循环）...")
            proc = self._process_track(
                seg,
                volume=kwargs["volume"],
                fade_in=kwargs["fade_in"],
                fade_out=kwargs["fade_out"],
                loop=kwargs["loop"],
                target_ms=target_ms,
                ref_params=ref_params,
            )
            result = result.overlay(proc)

        # 导出
        audio_format = (self._cfg(node_config, "audio_format", "wav") or "wav").lower()
        if audio_format not in ("wav", "mp3", "flac"):
            audio_format = "wav"
        ext = audio_format
        out_name = f"track_mix_{node_id}.{ext}" if node_id else f"track_mix.{ext}"
        out_path = os.path.join(cache_dir, out_name)

        if callback:
            callback(85, f"导出混音音频（{audio_format.upper()}）...")
        if audio_format == "mp3":
            bitrate = self._cfg(node_config, "audio_bitrate", "192") or "192"
            result.export(out_path, format="mp3", bitrate=f"{bitrate}k")
        else:
            result.export(out_path, format=audio_format)

        self.artifacts = [os.path.join("cache", out_name)]
        if callback:
            callback(100, f"音轨混响完成，时长 {target_ms / 1000.0:.2f}s")
        return {
            "artifacts": self.artifacts,
            "outputs": {"audio": os.path.join("cache", out_name)},
        }
