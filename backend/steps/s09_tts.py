"""s09_tts: Text-to-speech synthesis from JSON or pandas dubbing task sheets."""
import os
import json
import csv
import wave
import struct
from typing import Callable, Optional, List, Dict

try:
    import numpy as np
except ImportError:
    np = None
from backend.steps.base_step import BaseStep, find_artifact
from backend.config.config_manager import config
from backend.utils.audio_segmenter import split_audio_by_timestamps
from backend.utils.audio_speed import get_audio_duration as probe_audio_duration


class S09TTS(BaseStep):
    step_id = "s09_tts"
    step_name = "语音合成(TTS)"
    dependencies = ["s08_dub_task"]
    artifacts = ["cache/dub_audio", "cache/dub_temp"]

    @staticmethod
    def _get_canonical_dub_task_path(task_dir: str) -> str:
        return find_artifact(os.path.join(task_dir, "cache"), "dub_task.json") or ""

    @classmethod
    def _has_complete_tts_cache(cls, task_dir: str) -> bool:
        """判断 TTS 缓存是否完整。

        仅存在旧 wav 文件并不代表缓存可复用；还要求 dub_task.json 中
        每段都能对应到有效音频且 real_duration 已写回。
        """
        dub_task_path = cls._get_canonical_dub_task_path(task_dir)
        if not os.path.exists(dub_task_path):
            return False

        try:
            with open(dub_task_path, "r", encoding="utf-8") as f:
                dub_data = json.load(f)
        except Exception:
            return False

        segments = dub_data.get("segments", [])
        if not segments:
            return False

        valid_count = 0
        for i, seg in enumerate(segments):
            audio_rel = str(seg.get("audio_file") or f"cache/dub_temp/{i:04d}.wav").strip()
            audio_path = audio_rel if os.path.isabs(audio_rel) else os.path.join(task_dir, audio_rel)
            if not os.path.exists(audio_path) or os.path.getsize(audio_path) <= 0:
                return False

            try:
                real_dur = float(seg.get("real_duration", 0) or 0)
            except (TypeError, ValueError):
                real_dur = 0
            if real_dur <= 0:
                return False
            valid_count += 1

        return valid_count == len(segments)

    @staticmethod
    def _clear_downstream_fields(segments: List[Dict]) -> int:
        """移除下游步骤写回的临时字段，恢复为 TTS 的标准任务单。"""
        removable_fields = (
            "audio_file_adjusted",
            "adjusted_duration",
            "video_speed_ratio",
            "overflow",
            "need_truncate",
            "truncate_target_dur",
            "target_start",
            "target_end",
            "theory_gap",
            "new_start",
            "new_end",
        )
        cleared = 0
        for seg in segments:
            for field in removable_fields:
                if field in seg:
                    del seg[field]
                    cleared += 1
        return cleared

    def check_artifact(self, task_dir: str) -> bool:
        cache_dir = os.path.join(task_dir, "cache")
        if not os.path.exists(cache_dir):
            return False

        # 仅有旧 wav 文件并不足以跳过；任务单也必须包含完整真实时长。
        if self._has_complete_tts_cache(task_dir):
            return True

        # 兼容旧缓存格式：legacy dub_audio 文件存在时，仍要求 canonical json 完整。
        legacy_audio_files = [
            f for f in os.listdir(cache_dir)
            if f.startswith("dub_audio_") and f.endswith(".wav")
        ]
        if legacy_audio_files and self._has_complete_tts_cache(task_dir):
            return True

        return False

    def validate_inputs(self, task_dir: str) -> bool:
        cache_dir = os.path.join(task_dir, "cache")
        return bool(
            find_artifact(cache_dir, "dub_task.json")
            or find_artifact(cache_dir, "dub_task.csv")
        )

    @staticmethod
    def _to_float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _load_segments_from_csv(cls, csv_path: str):
        try:
            import pandas as pd

            rows = pd.read_csv(csv_path).fillna("").to_dict(orient="records")
        except Exception:
            with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))

        segments = []
        for index, row in enumerate(rows):
            read_text = str(row.get("read_text") or row.get("朗读文本") or row.get("text") or "").strip()
            segments.append({
                "index": int(cls._to_float(row.get("index"), index)),
                "text": str(row.get("text") or "").strip(),
                "read_text": read_text,
                "read_tone_desc": str(row.get("read_tone_desc") or row.get("朗读语气") or "").strip(),
                "start": cls._to_float(row.get("start")),
                "end": cls._to_float(row.get("end")),
                "duration": cls._to_float(row.get("duration"), cls._to_float(row.get("end")) - cls._to_float(row.get("start"))),
                "original_duration": cls._to_float(row.get("original_duration"), cls._to_float(row.get("duration"), 0.0)),
                "gap_after": cls._to_float(row.get("gap_after")),
                "speed_ratio": cls._to_float(row.get("speed_ratio"), 1.0),
                "audio_file": str(row.get("audio_file") or f"cache/dub_temp/{index:04d}.wav").strip(),
                "character_id": int(cls._to_float(row.get("character_id"), 0)),
                "read_character_id": int(cls._to_float(row.get("read_character_id"), cls._to_float(row.get("character_id"), 0))),
                "character_voice_desc": str(row.get("character_voice_desc") or "").strip(),
                "dialect": str(row.get("dialect") or row.get("方言") or "").strip(),
                "方言": str(row.get("方言") or row.get("dialect") or "").strip(),
            })
        return segments

    @classmethod
    def _load_dub_task(cls, task_dir: str, step_inputs: dict):
        pandas_path = step_inputs.get("pandas") or ""
        json_path = step_inputs.get("text") or find_artifact(
            os.path.join(task_dir, "cache"), "dub_task.json"
        ) or os.path.join(task_dir, "cache", "dub_task.json")

        if pandas_path:
            if not os.path.isabs(pandas_path):
                pandas_path = os.path.join(task_dir, pandas_path)
            segments = cls._load_segments_from_csv(pandas_path)
            dub_data = {
                "segments": segments,
                "total_segments": len(segments),
            }
            canonical_json_path = find_artifact(os.path.join(task_dir, "cache"), "dub_task.json") or \
                os.path.join(task_dir, "cache", "dub_task.json")
            with open(canonical_json_path, "w", encoding="utf-8") as f:
                json.dump(dub_data, f, ensure_ascii=False, indent=2)
            return dub_data, canonical_json_path

        if not os.path.isabs(json_path):
            json_path = os.path.join(task_dir, json_path)
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f), json_path

    def _create_placeholder_audio(self, text: str, output_path: str, duration: float):
        """Create a placeholder silent WAV file using wave module."""
        sample_rate = 16000
        num_samples = int(sample_rate * duration)

        with wave.open(output_path, 'w') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            for _ in range(num_samples):
                wav_file.writeframes(struct.pack('<h', 0))

    def _parse_tts_config(self) -> Dict:
        """解析TTS配置参数"""
        node_cfg = getattr(self, "_node_config", {}) or {}

        # 处理tts_mode为数组的情况，取第一个值
        tts_mode_raw = node_cfg.get("tts_mode", ["preset_voice"])
        if isinstance(tts_mode_raw, list):
            tts_mode = tts_mode_raw[0] if tts_mode_raw else "preset_voice"
        else:
            tts_mode = tts_mode_raw

        tts_config = {
            "mode": tts_mode,
            "engine": node_cfg.get("tts_engine") or config.get("tts.method") or "edge_tts",
            "clone_source": node_cfg.get("clone_source", "fixed"),
            "ref_audio_path": node_cfg.get("ref_audio_path", ""),
            "ref_audio_roles": [
                node_cfg.get("ref_audio_role_1", ""),
                node_cfg.get("ref_audio_role_2", ""),
                node_cfg.get("ref_audio_role_3", ""),
                node_cfg.get("ref_audio_role_4", ""),
            ],
            "voice_roles": [
                node_cfg.get("voice_role_1", ""),
                node_cfg.get("voice_role_2", ""),
                node_cfg.get("voice_role_3", ""),
                node_cfg.get("voice_role_4", ""),
            ],
            "voice_design_roles": [
                node_cfg.get("voice_design_role_1_desc", ""),
                node_cfg.get("voice_design_role_2_desc", ""),
                node_cfg.get("voice_design_role_3_desc", ""),
                node_cfg.get("voice_design_role_4_desc", ""),
            ],
        }

        print(f"\n{'='*60}")
        print(f"[TTS] 配置参数:")
        print(f"  - TTS模式: {tts_config['mode']}")
        print(f"  - 配音引擎: {tts_config['engine']}")
        print(f"  - 克隆来源: {tts_config['clone_source']}")
        print(f"  - 参考音频: {tts_config['ref_audio_path'] or '(未设置)'}")
        print(f"  - 角色音频: {[a or '(未设置)' for a in tts_config['ref_audio_roles']]}")
        print(f"  - 预置音色: {[v or '(未设置)' for v in tts_config['voice_roles']]}")
        print(f"  - 音色描述: {[d or '(未设置)' for d in tts_config['voice_design_roles']]}")
        print(f"{'='*60}\n")

        return tts_config

    def _validate_engine_capability(self, engine_id: str, mode: str):
        """验证TTS引擎是否支持指定模式"""
        from backend.tts.tts_interface_manager import get_tts_interface_manager

        manager = get_tts_interface_manager()
        iface = manager.get(engine_id)

        if not iface:
            raise ValueError(f"TTS引擎 '{engine_id}' 不存在")

        modes = iface.get("config", {}).get("modes", {})
        if mode not in modes or not modes[mode].get("enabled"):
            supported = [m for m, cfg in modes.items() if cfg.get("enabled")]
            supported_str = ", ".join(supported) if supported else "无"
            raise ValueError(
                f"TTS引擎 '{iface.get('name')}' 不支持 '{mode}' 模式。"
                f"支持的模式: {supported_str}"
            )

        print(f"[TTS] 引擎能力验证通过: {engine_id} 支持 {mode}")
        return True

    @staticmethod
    def _is_untimed(segments: List[Dict]) -> bool:
        """判断是否为「无时间戳」的一般文本配音模式。

        只要存在任一段缺少 start/end/duration 时间戳（为 None 或 <=0），
        即视为无时间轴配音：不存在原始音频切割、调速、字幕缩减的需求。
        """
        for seg in segments:
            start = seg.get("start")
            end = seg.get("end")
            duration = seg.get("duration")
            if start is None or end is None or duration is None:
                return True
            try:
                if float(start) <= 0 and float(end) <= 0:
                    return True
            except (TypeError, ValueError):
                return True
        return False

    def _resolve_source_audio(self, task_dir: str, step_inputs: dict = None) -> Optional[str]:
        """解析用于切割参考音频的原始音频路径。

        - 优先使用连线传入的 source_audio 输入点
        - 回退到任务缓存中常见的原始/人声音频文件
        """
        step_inputs = step_inputs or {}
        src = step_inputs.get("source_audio") or ""
        if src:
            src_abs = src if os.path.isabs(src) else os.path.join(task_dir, src)
            if os.path.exists(src_abs):
                return src_abs

        cache_dir = os.path.join(task_dir, "cache")
        audio_candidates = [
            os.path.join(cache_dir, "vocal.wav"),
            os.path.join(cache_dir, "extracted_audio.wav"),
            find_artifact(os.path.join(task_dir, "output"), "extracted_audio.wav"),
        ]
        for path in audio_candidates:
            if path and os.path.exists(path):
                return path
        return None

    def _extract_reference_audio(self, segments: List[Dict], task_dir: str,
                                 source_audio: str = None) -> Dict[int, str]:
        """按句子时间段切割原始音频作为参考音频

        Args:
            segments: 配音片段列表（带 start/end 时间戳）
            task_dir: 任务目录
            source_audio: 指定原始音频路径（连线传入的 source_audio），为空则自动查找

        Returns:
            Dict[int, str]: {segment_index: ref_audio_path}
        """
        audio_path = source_audio or self._resolve_source_audio(task_dir)
        if not audio_path:
            print("[TTS] 警告: 未找到原始音频文件，无法切割参考音频")
            return {}

        # 创建参考音频目录
        ref_dir = os.path.join(task_dir, "cache", "refe")

        print(f"[TTS] 开始切割参考音频，原始音频: {audio_path}")
        print(f"[TTS] 参考音频输出目录: {ref_dir}")

        # 使用统一的音频切割工具，读取全局配置
        settings = split_audio_by_timestamps(
            audio_path=audio_path,
            segments=segments,
            output_dir=ref_dir,
        )

        return settings

    def _extract_reference_audio_untimed(self, segments: List[Dict], task_dir: str,
                                         source_audio: str = None) -> Dict[int, str]:
        """无时间戳模式下，按「生成配音的真实时长」顺序切割原始音频作为参考音频。

        不同于有时间戳的按 start/end 切割，这里从上一段的截止位置开始，
        依次按每段 real_duration 截取等长音频作为该段的参考。
        """
        audio_path = source_audio or self._resolve_source_audio(task_dir)
        if not audio_path:
            print("[TTS] 警告: 未找到原始音频文件，无时间戳模式跳过参考音频切割")
            return {}

        try:
            import soundfile as sf
        except ImportError:
            print("[TTS] 警告: soundfile 未安装，无法切割参考音频")
            return {}

        try:
            audio_data, sr = sf.read(audio_path)
            if len(audio_data.shape) > 1:
                audio_data = np.mean(audio_data, axis=1)
        except Exception as e:
            print(f"[TTS] 读取原始音频失败: {e}")
            return {}

        ref_dir = os.path.join(task_dir, "cache", "refe")
        os.makedirs(ref_dir, exist_ok=True)

        ref_map: Dict[int, str] = {}
        cursor = 0  # 当前切割位置（采样点）
        total_samples = len(audio_data)
        for seg in segments:
            idx = seg.get("index", len(ref_map))
            real_dur = float(seg.get("real_duration") or 0)
            if real_dur <= 0:
                continue
            n_samples = int(real_dur * sr)
            end_sample = min(total_samples, cursor + n_samples)
            if end_sample <= cursor:
                break
            seg_data = audio_data[cursor:end_sample]
            out_file = os.path.join(ref_dir, f"{idx:04d}.wav")
            try:
                sf.write(out_file, seg_data, sr)
                ref_map[idx] = out_file
            except Exception as e:
                print(f"[TTS] 保存第 {idx} 段参考音频失败: {e}")
            cursor = end_sample

        print(f"[TTS] 无时间戳模式参考音频切割完成，共 {len(ref_map)} 段")
        return ref_map

    @staticmethod
    def _generate_sequential_timestamps(segments: List[Dict]) -> None:
        """无时间戳模式下，根据每段真实配音时长生成连续的顺序时间戳。

        这样下游 s10 合并音频时可以按真实朗读时长逐段拼接，并生成对齐的字幕。
        同时把 duration/original_duration 回填为真实时长，避免合并时缺字段。
        """
        cursor = 0.0
        for seg in segments:
            real_dur = float(seg.get("real_duration") or 0)
            if real_dur <= 0:
                real_dur = 0.0
            seg["start"] = round(cursor, 4)
            seg["end"] = round(cursor + real_dur, 4)
            seg["duration"] = round(real_dur, 4)
            seg["original_duration"] = round(real_dur, 4)
            seg["gap_after"] = 0.0
            cursor = seg["end"]
        print(f"[TTS] 已为 {len(segments)} 段生成顺序时间戳，总时长 {cursor:.3f}s")

    def _resolve_reference_audio(self, seg: Dict, tts_config: dict, task_dir: str, ref_map: Dict[int, str] = None) -> Optional[str]:
        """根据克隆模式解析参考音频路径"""
        mode = tts_config["mode"]
        clone_source = tts_config["clone_source"]

        if mode not in ["clone", "controllable_clone"]:
            return None

        if clone_source == "fixed":
            ref = tts_config["ref_audio_path"]
            if ref and not os.path.isabs(ref):
                ref = os.path.join(task_dir, ref)
            return ref or None

        elif clone_source == "multi_role":
            role_id = seg.get("read_character_id", 0)
            roles = tts_config["ref_audio_roles"]
            if 0 <= role_id < len(roles) and roles[role_id]:
                ref = roles[role_id]
                if ref and not os.path.isabs(ref):
                    ref = os.path.join(task_dir, ref)
                return ref
            return None

        elif clone_source == "per_segment":
            # 原文逐段参考：使用切割后的参考音频
            if ref_map:
                idx = seg.get("index", 0)
                return ref_map.get(idx)
            return None

        return None

    def _resolve_voice(self, seg: Dict, tts_config: dict) -> str:
        """根据角色解析预置音色"""
        mode = tts_config["mode"]

        if mode != "preset_voice":
            return ""

        role_id = seg.get("read_character_id", 0)
        voice_roles = tts_config["voice_roles"]

        if 0 <= role_id < len(voice_roles) and voice_roles[role_id]:
            return voice_roles[role_id]

        return voice_roles[0] if voice_roles[0] else ""

    def _build_voice_design_instruction(self, seg: Dict, tts_config: dict) -> str:
        """构建音色设计指令
        
        - voice_design模式: 使用对应角色的音色描述 + 朗读语气
        - controllable_clone模式: 使用TTS任务表中的朗读语气作为指令
        """
        mode = tts_config["mode"]
        tone_desc = seg.get("read_tone_desc", "")
        role_id = seg.get("read_character_id", 0)

        if mode == "voice_design":
            # 获取对应角色的音色描述
            voice_design_roles = tts_config.get("voice_design_roles", [])
            role_desc = ""
            if 0 <= role_id < len(voice_design_roles):
                role_desc = voice_design_roles[role_id]
            elif voice_design_roles:
                role_desc = voice_design_roles[0]
            
            # 组合音色描述和朗读语气
            if tone_desc and role_desc:
                return f"{role_desc}，{tone_desc}"
            return role_desc or tone_desc or ""

        elif mode == "controllable_clone":
            # 指令克隆模式：直接使用朗读语气作为指令
            return tone_desc or ""

        return ""

    @staticmethod
    def _get_audio_duration(audio_path: str) -> float:
        """获取音频文件的真实时长（秒）"""
        return probe_audio_duration(audio_path)

    def _match_characters(self, segments: List[Dict], tts_config: dict) -> None:
        """前置角色匹配检查：校验角色数量并填充 read_character_id。
        
        根据当前模式和配置的角色列表，检查任务中的 character_id 是否超出配置范围，
        超出的降级到第一个角色，并将匹配结果写入每个 segment 的 read_character_id。
        """
        mode = tts_config["mode"]
        clone_source = tts_config.get("clone_source", "fixed")

        # 确定当前模式下使用的角色列表和配置的角色数
        if mode == "preset_voice":
            role_list = [v for v in tts_config.get("voice_roles", []) if v]
            role_label = "预置音色"
        elif mode in ["clone", "controllable_clone"]:
            if clone_source == "multi_role":
                role_list = [r for r in tts_config.get("ref_audio_roles", []) if r]
                role_label = "角色参考音频"
            else:
                # fixed / per_segment 模式不需要多角色匹配
                return
        elif mode == "voice_design":
            role_list = [d for d in tts_config.get("voice_design_roles", []) if d]
            role_label = "音色设计描述"
        else:
            return

        # 收集任务中所有唯一的 character_id
        all_char_ids = sorted(set(
            seg.get("character_id", 0) for seg in segments
        ))
        max_configured = len(role_list)

        print(f"\n[TTS] 角色匹配检查:")
        print(f"  - 模式: {mode}")
        print(f"  - 配置的{role_label}数量: {max_configured}")
        print(f"  - 任务中的角色ID: {all_char_ids}")

        # 检查溢出
        overflow_ids = [cid for cid in all_char_ids if cid >= max_configured]
        if overflow_ids:
            print(f"  ⚠ 警告: 角色ID {overflow_ids} 超出配置范围(0~{max_configured - 1})，"
                  f"将使用第1个角色(ID=0)代替")

        # 填充 read_character_id：将溢出的 character_id 降级到 0
        for seg in segments:
            char_id = seg.get("character_id", 0)
            if char_id >= max_configured:
                seg["read_character_id"] = 0
            else:
                seg["read_character_id"] = char_id

        # 统计匹配结果
        matched_count = sum(1 for seg in segments if seg.get("read_character_id") == seg.get("character_id", 0))
        fallback_count = len(segments) - matched_count
        print(f"  - 正常匹配: {matched_count} 段")
        if fallback_count > 0:
            print(f"  - 降级到默认角色: {fallback_count} 段")
        print(f"[TTS] 角色匹配完成\n")

    def _try_real_tts(self, seg: Dict, tts_config: dict, output_path: str, task_dir: str, ref_map: Dict[int, str] = None, speed: float = None) -> bool:
        """尝试使用真实TTS引擎

        Args:
            seg: 配音片段数据
            tts_config: TTS配置
            output_path: 输出音频路径
            task_dir: 任务目录
            ref_map: 参考音频映射（per_segment模式）
            speed: 可选的语速参数（用于调速重生成）
        """
        try:
            from backend.tts.tts_factory import get_tts_engine
            from backend.tts.tts_interface_manager import get_tts_interface_manager

            engine_id = tts_config["engine"]
            mode = tts_config["mode"]

            # 验证引擎能力
            self._validate_engine_capability(engine_id, mode)

            # 获取引擎
            engine = get_tts_engine(engine_id)

            # 解析参数
            text = seg.get("read_text") or seg.get("text", "")
            ref_text = seg.get("text", "") if mode in ["clone", "controllable_clone"] else ""
            ref_audio = self._resolve_reference_audio(seg, tts_config, task_dir, ref_map)
            voice = self._resolve_voice(seg, tts_config)
            voice_design = self._build_voice_design_instruction(seg, tts_config)

            # 根据模式决定是否传递克隆指令
            cc_instruction = voice_design if mode == "controllable_clone" else ""

            seg_index = seg.get("index", 0)
            print(f"\n[TTS] 合成第 {seg_index} 段:")
            print(f"  - 文本: {text[:80]}{'...' if len(text) > 80 else ''}")
            print(f"  - 模式: {mode}")
            print(f"  - 引擎: {engine_id}")
            print(f"  - 参考音频: {ref_audio or '(无)'}")
            if ref_text:
                print(f"  - 参考文本: {ref_text[:60]}{'...' if len(ref_text) > 60 else ''}")
            print(f"  - 音色: {voice or '(默认)'}")
            if voice_design:
                print(f"  - 音色指令: {voice_design}")
            if cc_instruction:
                print(f"  - 克隆指令: {cc_instruction}")
            if speed:
                print(f"  - 语速: {speed:.2f}x")

            # 构建请求参数
            manager = get_tts_interface_manager()
            params = manager.build_request_params(
                iface_id=engine_id,
                text=text,
                output_path=output_path,
                ref_audio=ref_audio,
                mode=mode,
                voice_design=voice_design,
                controllable_clone=cc_instruction,
                voice=voice,
                ref_text=ref_text
            )

            # 执行合成 - 只传递 synthesize 方法接受的参数
            if hasattr(engine, 'synthesize'):
                try:
                    engine.synthesize(
                        text, output_path,
                        ref_audio=ref_audio,
                        mode=mode,
                        voice_design=voice_design,
                        controllable_clone=cc_instruction,
                        voice=voice,
                        ref_text=ref_text,
                        speed=speed,
                    )
                except TypeError:
                    # 引擎不支持 speed 参数，回退到普通合成
                    engine.synthesize(
                        text, output_path,
                        ref_audio=ref_audio,
                        mode=mode,
                        voice_design=voice_design,
                        controllable_clone=cc_instruction,
                        voice=voice,
                        ref_text=ref_text,
                    )
            else:
                raise ValueError(f"引擎 {engine_id} 没有 synthesize 方法")

            print(f"  ✓ 合成成功: {output_path}")
            return True

        except Exception as e:
            print(f"  ✗ 合成失败: {e}")
            return False

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        if callback:
            callback(5, "解析TTS配置...")

        # 解析TTS配置
        tts_config = self._parse_tts_config()

        # 保存TTS配置供下游（s10音频合并）使用
        tts_config_path = os.path.join(task_dir, "cache", "tts_config.json")
        os.makedirs(os.path.dirname(tts_config_path), exist_ok=True)
        with open(tts_config_path, "w", encoding="utf-8") as f:
            json.dump(tts_config, f, ensure_ascii=False, indent=2)

        if callback:
            callback(10, "加载配音任务...")

        # 加载配音任务
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        dub_data, dub_task_path = self._load_dub_task(task_dir, step_inputs)

        segments = dub_data.get("segments", [])
        total = len(segments)

        cleared = self._clear_downstream_fields(segments)
        if cleared > 0:
            print(f"[TTS] 已清理下游残留字段: {cleared} 个")

        print(f"[TTS] 共 {total} 个片段需要合成")
        print(f"[TTS] TTS模式: {tts_config['mode']}, 克隆来源: {tts_config['clone_source']}")

        # 前置角色匹配检查：校验角色数量并填充 read_character_id
        self._match_characters(segments, tts_config)

        # 无时间戳（一般文本配音）模式判定：跳过原始音频切割/调速/字幕缩减
        untimed = self._is_untimed(segments)
        if untimed:
            print("[TTS] 检测到无时间戳文本配音模式：跳过调速与字幕缩减，参考音频按生成时长顺序切割")

        # 解析连线传入的原始音频（用于决定切割哪份原始音频作为参考）
        source_audio = step_inputs.get("source_audio") or ""
        if source_audio and not os.path.isabs(source_audio):
            source_audio = os.path.join(task_dir, source_audio)

        # 如果是原文逐段参考模式，先切割参考音频
        ref_map = {}
        if tts_config["mode"] in ["clone", "controllable_clone"] and tts_config["clone_source"] == "per_segment":
            if callback:
                callback(10, "切割参考音频...")
            print("[TTS] 原文逐段参考模式：开始切割参考音频")
            if untimed:
                # 无时间戳：等到真实时长回填后再按生成时长顺序切割
                pass
            else:
                ref_map = self._extract_reference_audio(segments, task_dir, source_audio=source_audio)
                if not ref_map:
                    print("[TTS] 警告: 参考音频切割失败，将使用默认参考音频")

        if callback:
            callback(15, f"准备合成 {total} 个音频片段...")

        # 创建音频目录
        audio_dir = os.path.join(task_dir, "cache", "dub_temp")
        os.makedirs(audio_dir, exist_ok=True)

        # 处理每个segment
        success_count = 0
        fail_count = 0
        skip_count = 0
        processed_count = 0

        # 读取覆盖生成配置：True=覆盖已有文件，False=跳过已有文件
        node_cfg = getattr(self, "_node_config", {}) or {}
        overwrite_generate = node_cfg.get("overwrite_generate", False)

        for i, seg in enumerate(segments):
            audio_file = os.path.join(task_dir, seg["audio_file"])

            # 跳过已存在的文件（除非勾选了覆盖生成）
            if not overwrite_generate and os.path.exists(audio_file) and os.path.getsize(audio_file) > 0:
                skip_count += 1
                processed_count += 1
                continue

            text = seg.get("read_text") or seg.get("text", "")
            text = text.replace("[待翻译]", "").replace("[To translate]", "").strip()
            if not text:
                text = "placeholder"

            # 更新进度 - 显示已完成句子数量和总数量
            processed_count += 1
            progress = 15 + int((processed_count / total) * 80)
            if callback:
                callback(progress, f"合成进度: {processed_count}/{total} 句")

            # 尝试真实TTS（含1次重试）
            success = self._try_real_tts(seg, tts_config, audio_file, task_dir, ref_map)
            if not success:
                print(f"[TTS] 第1次失败，1秒后重试...")
                import time
                time.sleep(1)
                success = self._try_real_tts(seg, tts_config, audio_file, task_dir, ref_map)
            if success:
                success_count += 1
            else:
                fail_count += 1
                print(f"[TTS] 错误: 第 {processed_count} 段合成失败（已重试1次）")

        # 打印汇总
        print(f"\n{'='*60}")
        print(f"[TTS] 合成完成汇总:")
        print(f"  - 总计: {total} 段")
        print(f"  - 成功: {success_count} 段")
        print(f"  - 失败: {fail_count} 段")
        print(f"  - 跳过: {skip_count} 段")
        print(f"{'='*60}\n")

        # 更新 real_duration：获取每个配音片段的真实时长
        if callback:
            callback(90, "更新配音片段真实时长...")

        print("[TTS] 获取配音片段真实时长...")
        updated_count = 0
        for seg in segments:
            audio_file = os.path.join(task_dir, seg.get("audio_file", ""))
            if os.path.exists(audio_file) and os.path.getsize(audio_file) > 0:
                real_dur = self._get_audio_duration(audio_file)
                if real_dur > 0:
                    seg["real_duration"] = round(real_dur, 4)
                    updated_count += 1
        print(f"[TTS] 已更新 {updated_count}/{total} 段的真实时长")

        # ═══════════ 校验：必须每个片段都生成有效音频，否则抛错 ═══════════
        # 避免“部分片段未合成却静默标记节点完成”的问题。
        missing = [
            i for i, seg in enumerate(segments)
            if not (
                os.path.exists(os.path.join(task_dir, seg.get("audio_file", "")))
                and os.path.getsize(os.path.join(task_dir, seg.get("audio_file", ""))) > 0
            )
        ]
        if missing:
            raise RuntimeError(
                f"[TTS] 有 {len(missing)} 个配音片段未生成有效音频"
                f"（段落索引: {missing}），请检查 TTS 引擎配置、参考音频与网络后重试。"
            )

        # 无时间戳模式：参考音频按生成配音的真实时长顺序切割（per_segment 克隆用）
        if untimed and tts_config["mode"] in ["clone", "controllable_clone"] \
                and tts_config["clone_source"] == "per_segment":
            if callback:
                callback(90, "按生成时长切割参考音频...")
            print("[TTS] 无时间戳模式：按生成配音真实时长顺序切割参考音频")
            ref_map = self._extract_reference_audio_untimed(segments, task_dir, source_audio=source_audio)
            if not ref_map:
                print("[TTS] 警告: 无时间戳模式参考音频切割失败，将使用默认参考音频")

        # ═══════════ 调速重生成 + AI缩减字幕 ═══════════
        node_cfg = getattr(self, "_node_config", {}) or {}
        speed_regenerate = node_cfg.get("speed_regenerate", True)
        ai_subtitle_reduction = node_cfg.get("ai_subtitle_reduction", True)
        speed_rounds = node_cfg.get("speed_rounds", 1)
        ai_rounds = node_cfg.get("ai_rounds", 1)

        # 无时间戳模式不存在时间槽约束：跳过调速重生成与字幕缩减，并强制关闭相关选项
        if untimed:
            speed_regenerate = False
            ai_subtitle_reduction = False

        if speed_regenerate or ai_subtitle_reduction:
            speed_cfg = config.get("video.speed", {}) or {}
            speed_max = speed_cfg.get("max", 1.5)
            speed_min = speed_cfg.get("min", 1.0)
            gap_threshold = speed_cfg.get("gap_threshold", 0.1)

            try:
                self._speed_and_reduce_loop(
                    segments, tts_config, task_dir, dub_data, dub_task_path,
                    speed_regenerate, ai_subtitle_reduction,
                    speed_max, speed_min, gap_threshold,
                    speed_rounds, ai_rounds, ref_map, callback
                )
            except Exception as e:
                print(f"[S09] 调速重生成/缩减字幕异常: {e}")
                import traceback
                traceback.print_exc()

        # 无时间戳模式：根据生成配音的真实时长生成顺序时间戳，供下游合并对齐
        if untimed:
            self._generate_sequential_timestamps(segments)

        # 写回 dub_task.json
        dub_data["segments"] = segments
        with open(dub_task_path, "w", encoding="utf-8") as f:
            json.dump(dub_data, f, ensure_ascii=False, indent=2)
        print(f"[TTS] 已更新任务文件: {dub_task_path}")

        # 写回 dub_task.csv
        csv_path = find_artifact(os.path.join(task_dir, "cache"), "dub_task.csv") or \
            os.path.join(task_dir, "cache", "dub_task.csv")
        self._write_dub_task_csv(segments, csv_path)

        if callback:
            callback(100, f"完成: {success_count}/{total} 句成功, {fail_count} 句失败, {skip_count} 句跳过")

        return {
            "artifacts": ["cache/dub_audio", "cache/dub_temp"],
            "outputs": {
                "text": os.path.relpath(dub_task_path, task_dir).replace("\\", "/"),
                "pandas": os.path.relpath(csv_path, task_dir).replace("\\", "/"),
            },
        }

    @staticmethod
    def _write_dub_task_csv(segments: List[Dict], csv_path: str) -> None:
        """将segments写入CSV文件"""
        if not segments:
            return
        fieldnames = [
            "index", "text", "read_text", "read_tone_desc",
            "start", "end", "duration", "original_duration", "real_duration",
            "gap_after", "speed_ratio", "audio_file",
            "character_id", "read_character_id", "character_voice_desc",
            "dialect",
        ]
        try:
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for seg in segments:
                    writer.writerow(seg)
            print(f"[TTS] 已更新CSV: {csv_path}")
        except Exception as e:
            print(f"[TTS] 写入CSV失败: {e}")


    # ═══════════ 调速重生成 + AI缩减字幕 辅助方法 ═══════════

    @staticmethod
    def _analyze_speed_factors(segments: List[Dict], speed_min: float,
                               speed_max: float, gap_threshold: float) -> None:
        """遍历所有 segment，计算每个的变速倍数。"""
        print("\n[S09] 分析变速倍数")
        for seg in segments:
            duration = seg.get("duration", 0)
            real_dur = seg.get("real_duration", 0)
            gap = seg.get("gap_after", 0)

            if duration <= 0 or real_dur <= 0:
                seg["speed_factor"] = 1.0
                seg["raw_speed_factor"] = 1.0
                seg["need_speed"] = False
                continue

            if real_dur <= duration:
                ratio = real_dur / duration if duration > 0 else 1.0
                seg["speed_factor"] = max(speed_min, ratio)
                seg["raw_speed_factor"] = seg["speed_factor"]
                seg["need_speed"] = False
            else:
                available = duration + gap * gap_threshold
                if available > 0:
                    raw_factor = real_dur / available
                elif duration > 0:
                    raw_factor = real_dur / duration
                else:
                    raw_factor = 1.0
                seg["raw_speed_factor"] = round(raw_factor, 4)
                capped_factor = max(speed_min, min(raw_factor, speed_max))
                seg["speed_factor"] = round(capped_factor, 4)
                seg["need_speed"] = capped_factor > 1.01

        need_count = sum(1 for s in segments if s.get("need_speed"))
        overflow_count = sum(1 for s in segments
                             if s.get("need_speed") and s.get("raw_speed_factor", 1.0) > speed_max)
        print(f"  - 需要变速: {need_count} 段")
        print(f"  - 超出最大变速({speed_max}x): {overflow_count} 段")

    def _speed_and_reduce_loop(self, segments: List[Dict], tts_config: dict,
                               task_dir: str, dub_data: dict, dub_task_path: str,
                               speed_regenerate: bool, ai_subtitle_reduction: bool,
                               speed_max: float, speed_min: float,
                               gap_threshold: float,
                               speed_rounds: int = 1,
                               ai_rounds: int = 1,
                               ref_map: Dict[int, str] = None,
                               callback: Optional[Callable] = None) -> None:
        """调速重生成 + AI缩减字幕主循环。"""
        print("\n" + "=" * 60)
        print("[S09] 调速重生成 + AI缩减字幕")
        print("=" * 60)

        # Step 1: 分析变速倍数
        self._analyze_speed_factors(segments, speed_min, speed_max, gap_threshold)

        # Step 2: 调速重生成（最多 speed_rounds 轮）
        if speed_regenerate and speed_rounds > 0:
            for sr in range(1, speed_rounds + 1):
                overflow_segs = [s for s in segments
                                 if s.get("need_speed") and s.get("raw_speed_factor", 1.0) > speed_max]
                if not overflow_segs:
                    print(f"  - 调速重生成第{sr}轮: 无需重生成")
                    break
                if callback:
                    callback(92, f"调速重生成 第{sr}轮 ({len(overflow_segs)} 段)...")
                print(f"  - 调速重生成第{sr}轮: {len(overflow_segs)} 段需要重生成")
                try:
                    self._speed_regenerate_tts(overflow_segs, tts_config, task_dir, ref_map)
                except Exception as e:
                    print(f"  ⚠ 调速重生成异常: {e}")
                    import traceback
                    traceback.print_exc()
                self._analyze_speed_factors(segments, speed_min, speed_max, gap_threshold)

        # Step 3: AI缩减字幕（最多 ai_rounds 轮）
        if ai_subtitle_reduction and ai_rounds > 0:
            for round_num in range(1, ai_rounds + 1):
                overflow_segs = [s for s in segments
                                 if s.get("need_speed") and s.get("raw_speed_factor", 1.0) > speed_max]
                if not overflow_segs:
                    print(f"  - AI缩减第{round_num}轮: 无需缩减")
                    break

                if callback:
                    callback(94, f"AI缩减字幕 第{round_num}轮 ({len(overflow_segs)} 段)...")
                print(f"  - AI缩减第{round_num}轮: {len(overflow_segs)} 段需要缩减")

                try:
                    self._llm_reduce_subtitles(overflow_segs)
                except Exception as e:
                    print(f"  ⚠ LLM缩减字幕异常: {e}")
                    import traceback
                    traceback.print_exc()

                try:
                    self._retts_reduced(segments, task_dir, tts_config, overflow_segs, ref_map)
                except Exception as e:
                    print(f"  ⚠ 重新配音异常: {e}")
                    import traceback
                    traceback.print_exc()

                self._analyze_speed_factors(segments, speed_min, speed_max, gap_threshold)

        # 标记最终仍 overflow 的段
        for seg in segments:
            seg["overflow"] = seg.get("need_speed") and seg.get("raw_speed_factor", 1.0) > speed_max

        overflow_count = sum(1 for s in segments if s.get("overflow"))
        print(f"[S09] 最终溢出段数: {overflow_count}")

    def _speed_regenerate_tts(self, overflow_segs: List[Dict], tts_config: dict,
                              task_dir: str, ref_map: Dict[int, str] = None) -> None:
        """对超出时间槽的 segment 尝试用更高 speed 参数重新生成 TTS，完全复用原始TTS执行逻辑。"""
        import math
        print(f"\n[S09] 调速重生成: {len(overflow_segs)} 段")

        regenerated = 0
        for seg in overflow_segs:
            idx = seg.get("index", "?")
            audio_file = os.path.join(task_dir, seg.get("audio_file", ""))
            # 使用实际计算的 raw_speed_factor，向上取一位小数作为 TTS speed 参数
            raw_speed = seg.get("raw_speed_factor", 1.0)
            speed_factor = math.ceil(raw_speed * 10) / 10

            # 检查文本是否有效
            text = seg.get("read_text") or seg.get("text", "")
            text = text.replace("[待翻译]", "").replace("[To translate]", "").strip()
            if not text:
                continue

            try:
                # 删除旧文件以便重新生成
                if os.path.exists(audio_file):
                    os.remove(audio_file)

                # 调速时不切换模式，保持原模式，仅把 speed 传给引擎，
                # 由服务层（build_request_params）按模式做变速容差处理
                # （克隆模式无原生语速时自动对参考音频做 ffmpeg atempo 变速）
                success = self._try_real_tts(seg, tts_config, audio_file, task_dir, ref_map, speed=speed_factor)
                if success:
                    # 更新 real_duration
                    real_dur = self._get_audio_duration(audio_file)
                    if real_dur > 0:
                        seg["real_duration"] = round(real_dur, 4)
                        regenerated += 1
                        print(f"  [{idx}] 调速重生成完成: {real_dur:.2f}s (raw={raw_speed:.2f} → speed={speed_factor:.1f})")
                else:
                    print(f"  [{idx}] 调速重生成失败")
            except Exception as e:
                print(f"  [{idx}] 调速重生成失败: {e}")

        print(f"  - 调速重生成完成: {regenerated}/{len(overflow_segs)} 段")

    @staticmethod
    def _llm_reduce_subtitles(overflow_segs: List[Dict]) -> None:
        """调用 LLM 缩减超长句子的朗读文本，使用批次并发请求。"""
        try:
            from backend.llm.llm_client import get_llm_client
            from backend.config.config_manager import config
            llm = get_llm_client()
        except Exception as e:
            print(f"  ⚠ LLM 客户端不可用，跳过字幕缩减: {e}")
            return

        # 读取全局设置
        max_concurrent = int(config.get("llm.max_concurrent") or 10)
        max_request_chars = int(config.get("llm.max_request_chars") or 12000)

        # 准备所有需要缩减的句子
        reduce_tasks = []
        for seg in overflow_segs:
            read_text = seg.get("read_text", "")
            if not read_text:
                continue
            reduce_tasks.append(seg)

        if not reduce_tasks:
            return

        print(f"  - 开始批次缩减 {len(reduce_tasks)} 段文本 (并发={max_concurrent}, 批次字数限制={max_request_chars})")

        # 将句子打包成批次，每个批次的字符数不超过 max_request_chars
        batches = []
        current_batch = []
        current_chars = 0

        for seg in reduce_tasks:
            read_text = seg.get("read_text", "")
            text_len = len(read_text)

            # 如果当前批次加上这个句子会超过限制，先保存当前批次
            if current_batch and current_chars + text_len > max_request_chars:
                batches.append(current_batch)
                current_batch = []
                current_chars = 0

            current_batch.append(seg)
            current_chars += text_len

        # 添加最后一个批次
        if current_batch:
            batches.append(current_batch)

        print(f"  - 分为 {len(batches)} 个批次处理")

        # 处理每个批次
        for batch_idx, batch in enumerate(batches):
            # 构建批次请求
            requests = []
            for seg in batch:
                read_text = seg.get("read_text", "")
                duration = seg.get("duration", 1)
                real_dur = seg.get("real_duration", duration)
                target_ratio = duration / real_dur if real_dur > 0 else 0.8
                target_ratio = max(0.5, target_ratio)
                max_reduction_pct = max(10, int((1 - target_ratio) * 100))

                # Try to use JSON template via prompt service
                from backend.prompts.prompt_service import get_prompt_service
                svc = get_prompt_service()
                assembled = svc.assemble_prompt("s09_subtitle_reduction", {
                    "target_ratio": f"{target_ratio:.0%}",
                    "max_reduction_pct": str(max_reduction_pct),
                    "read_text": read_text,
                })
                
                if assembled.get("found"):
                    prompt_data = {
                        "user_prompt": assembled["user_prompt"],
                        "system_prompt": assembled.get("system_prompt") or ""
                    }
                else:
                    # Fallback to hardcoded prompt
                    prompt_data = {
                        "user_prompt": (
                            f"你是一个专业的字幕朗读文本精简专家。请严格缩短以下朗读文本的长度，使其适合更快的语音合成。\n\n"
                            f"【严格要求】\n"
                            f"1. 必须将文本缩短至原文的 {target_ratio:.0%} 左右（即缩短约 {max_reduction_pct}%）\n"
                            f"2. 仅删除冗余修饰词、填充词、重复表达\n"
                            f"3. 保留全部关键信息（数字、日期、专有名词、动作主体）\n"
                            f"4. 必须保持完整句子结构，不能变成短语\n"
                            f"5. 如果是中文：删除'其实','真的','非常','特别',' basically',' literally',' you know',' I mean'等填充词\n"
                            f"6. 如果是英文：删除'article冗余','passive voice改为active'等\n"
                            f"7. 只输出精简后的文本，不要任何解释、引号或前后缀\n\n"
                            f"【原文】\n"
                            f"{read_text}\n\n"
                            f"【精简结果】"
                        ),
                        "system_prompt": ""
                    }

                requests.append({
                    "step_name": "s09_subtitle_reduction",
                    "prompt": prompt_data["user_prompt"],
                    "system_prompt": prompt_data["system_prompt"],
                    "response_json": False,
                })

            # 并发执行批次请求
            try:
                results = llm.batch_chat(requests, max_workers=max_concurrent)

                # 处理结果
                for seg, result in zip(batch, results):
                    read_text = seg.get("read_text", "")

                    # 检查结果是否有效
                    if not result or not isinstance(result, str):
                        continue
                    if isinstance(result, dict) and "error" in result:
                        print(f"  ⚠ LLM 缩减失败: {result['error']}")
                        continue

                    result = result.strip().strip('"').strip("'")
                    # 后处理校验：必须确实缩短了文本（至少缩短10%）
                    if result and result != read_text and len(result) < len(read_text) * 0.9:
                        seg["read_text_original"] = read_text
                        seg["read_text"] = result
                        idx = seg.get("index", "?")
                        print(f"    [{idx}] 缩减: {read_text[:40]}... → {result[:40]}...")
                    elif result and result != read_text:
                        # 缩短了但不足10%，记录警告但不应用
                        idx = seg.get("index", "?")
                        print(f"    [{idx}] 缩减不足({len(result)}/{len(read_text)})，跳过")
            except Exception as e:
                print(f"  ⚠ 批次 {batch_idx + 1} 处理异常: {e}")
                import traceback
                traceback.print_exc()

    def _retts_reduced(self, segments: List[Dict], task_dir: str,
                       tts_config: dict, overflow_segs: List[Dict],
                       ref_map: Dict[int, str] = None) -> None:
        """对缩减后的句子重新调用 TTS 配音，完全复用原始TTS执行逻辑。"""
        reduced_segs = [s for s in overflow_segs if "read_text_original" in s]
        if not reduced_segs:
            return

        print(f"  - 重新 TTS 配音: {len(reduced_segs)} 段")

        for seg in reduced_segs:
            idx = seg.get("index", "?")
            audio_file = os.path.join(task_dir, seg.get("audio_file", ""))

            try:
                # 删除旧文件
                if os.path.exists(audio_file):
                    os.remove(audio_file)

                # 缩减后重配保持原模式（不切换），变速容差交由服务层处理
                success = self._try_real_tts(seg, tts_config, audio_file, task_dir, ref_map)
                if success:
                    real_dur = self._get_audio_duration(audio_file)
                    if real_dur > 0:
                        seg["real_duration"] = round(real_dur, 4)
                        print(f"    [{idx}] 重配完成: {real_dur:.2f}s")
                else:
                    print(f"    [{idx}] 重配失败")
            except Exception as e:
                print(f"    [{idx}] 重配失败: {e}")


StepTTS = S09TTS
