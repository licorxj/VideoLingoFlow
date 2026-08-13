"""s10_merge_audio: 合并配音片段，支持音频变速、视频变速（纯 OpenCV 光流插针）。

执行流程（优化后）：
1. 分析变速倍数（基于 real_duration / duration）
2. 计算视频变速片段（如果开启视频变速）
3. 执行视频变速（纯 OpenCV，分批读取帧 + 多线程并行处理 + 逐帧写入）
4. 音频变速（对需要变速的片段）
5. 计算新时间戳（基于变速后的实际时长）
6. 合并音频（pydub overlay，精确定位）
7. 生成配音字幕 dub.srt

产物：
- output/dub.{format} - 合并后的配音音频（格式由配置决定）
- output/dub.srt - 时间戳对齐后的SRT字幕
- output/dub_bilingual.srt - 双语字幕
- output/video_adjusted.mp4 - 调速后的视频（如果执行调速）
"""
import os
import json
import csv
from typing import Callable, Optional, List, Dict

from backend.steps.base_step import BaseStep, find_artifact
from backend.config.config_manager import config
from backend.utils.audio_segmenter import get_audio_output_settings

try:
    from pydub import AudioSegment
    HAS_PYDUB = True
except ImportError:
    HAS_PYDUB = False

try:
    from backend.utils.audio_speed import adjust_audio_speed, get_audio_duration, adjust_audio_speed_precise
    HAS_AUDIO_SPEED = True
except ImportError:
    HAS_AUDIO_SPEED = False

class S10MergeAudio(BaseStep):
    step_id = "s10_merge_audio"
    step_name = "音频合并"
    dependencies = ["s09_tts"]

    def check_artifact(self, task_dir: str) -> bool:
        from backend.utils.audio_segmenter import get_audio_output_settings
        audio_format = get_audio_output_settings().get("format", "wav")
        output_dir = os.path.join(task_dir, "output")
        return bool(
            find_artifact(output_dir, f"dub.{audio_format}")
            and find_artifact(output_dir, "dub.srt")
            and find_artifact(output_dir, "dub_bilingual.srt")
        )

    def validate_inputs(self, task_dir: str) -> bool:
        return bool(find_artifact(os.path.join(task_dir, "cache"), "dub_task.json"))

    # ───────────────────────── 主流程 ─────────────────────────

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        if callback:
            callback(5, "加载配音任务表...")

        step_inputs = getattr(self, "_step_inputs", {}) or {}
        node_config = getattr(self, "_node_config", {}) or {}

        def _resolve_param(key: str, global_default=None):
            """优先读取节点前端配置，回退全局设置，最后用默认值兜底。"""
            node_val = node_config.get(key)
            if node_val is not None and node_val != "":
                try:
                    return float(node_val)
                except (ValueError, TypeError):
                    pass
            return global_default

        # 读取节点配置
        video_speed_adjust = node_config.get("video_speed_adjust", False)

        # 获取输入视频路径（优先使用连线传入的视频）
        input_video_path = self._resolve_input_video(step_inputs, task_dir)
        if input_video_path:
            print(f"[S10] 输入视频: {input_video_path}")
        else:
            print("[S10] ⚠ 未检测到输入视频，视频变速功能将不可用")

        # 读取 config.yaml 中 video.speed 参数（前端优先，全局回退）
        speed_cfg = config.get("video.speed", {}) or {}
        speed_min = _resolve_param("speed_min", speed_cfg.get("min", 1.0))
        speed_max = _resolve_param("speed_max", speed_cfg.get("max", 1.5))
        gap_threshold = _resolve_param("gap_threshold", speed_cfg.get("gap_threshold", 0.1))
        fast_limit = _resolve_param("fast_limit", speed_cfg.get("fast_limit", 2.0))

        # 音频输出格式/码率（前端优先，全局回退）
        audio_format_override = (node_config.get("audio_format") or "").strip()
        audio_bitrate_override = node_config.get("audio_bitrate")

        # 加载配音任务表
        dub_task_path = step_inputs.get("audio_manifest") or step_inputs.get("audio") or \
            find_artifact(os.path.join(task_dir, "cache"), "dub_task.json") or \
            os.path.join(task_dir, "cache", "dub_task.json")
        if not os.path.isabs(dub_task_path):
            dub_task_path = os.path.join(task_dir, dub_task_path)
        if not os.path.exists(dub_task_path):
            raise FileNotFoundError(
                f"音频合并缺少配音任务单 audio_manifest: {dub_task_path}\n"
                "请检查工作流连线：将上游 dub_task/tts 节点的「TTS任务单」输出"
                "连接到本节点的 audio_manifest 输入，并确保上游已成功执行。"
            )
        with open(dub_task_path, "r", encoding="utf-8") as f:
            dub_data = json.load(f)

        segments = dub_data.get("segments", [])
        total = len(segments)
        if total == 0:
            return {"artifacts": [], "outputs": {}}

        print(f"\n[S10] 音频合并开始，共 {total} 段")
        print(f"[S10] 配置: 视频变速={video_speed_adjust}")
        print(f"[S10] 速度范围: min={speed_min}, max={speed_max}, gap_threshold={gap_threshold}, fast_limit={fast_limit}")
        if audio_format_override:
            print(f"[S10] 音频输出: 格式={audio_format_override}, 码率={audio_bitrate_override or '全局'}")

        # ═══════════ Step 0: 清除旧变速信息 ═══════════
        self._clear_old_speed_info(segments, task_dir)

        # ═══════════ Step 0.5: 回填真实音频时长 ═══════════
        self._ensure_real_durations(segments, task_dir)

        # ═══════════ Step 1: 分析变速倍数 ═══════════
        if callback:
            callback(10, "分析变速倍数...")
        self._analyze_speed_factors(segments, speed_min, speed_max, gap_threshold)

        # ═══════════ Step 2: 计算视频变速片段 ═══════════
        video_speed_segments = []
        if video_speed_adjust:
            if callback:
                callback(15, "计算视频变速片段...")
            video_speed_segments = self._calculate_video_speed_segments(
                segments, speed_max, gap_threshold, fast_limit
            )

        # ═══════════ Step 3: 执行视频变速（在音频变速之前） ═══════════
        adjusted_video_path = None
        if video_speed_adjust and video_speed_segments:
            if callback:
                callback(20, f"视频变速处理 ({len(video_speed_segments)} 段)...")
            adjusted_video_path = self._adjust_video_speed_opencv(
                task_dir, video_speed_segments, input_video_path=input_video_path
            )

        # ═══════════ Step 3.5: 视频变速后时长核验 ═══════════
        video_timeline_adjusted = bool(adjusted_video_path and os.path.exists(adjusted_video_path))
        if video_speed_segments and not video_timeline_adjusted:
            self._disable_video_speed_assumptions(segments)
            video_speed_segments = []

        if video_timeline_adjusted and video_speed_segments:
            if callback:
                callback(30, "核验视频变速时长...")
            self._verify_video_speed_durations(
                segments, video_speed_segments, adjusted_video_path, task_dir
            )

        # ═══════════ Step 3.6: 标记需要截断的段（视频变速后仍超出上限） ═══════════
        self._mark_truncate_segments(segments, speed_max, gap_threshold, fast_limit)

        # ═══════════ Step 4: 精确音频变速 ═══════════
        if callback:
            callback(45, "精确音频变速处理...")
        self._adjust_audio_speed_all(segments, task_dir)

        # ═══════════ Step 5: 计算理论时间戳 ═══════════
        if callback:
            callback(55, "计算理论时间戳...")
        self._calculate_theoretical_timestamps(
            segments, video_timeline_adjusted=video_timeline_adjusted
        )

        # ═══════════ Step 6: 逐段拼接合并音频（含漂移补偿） ═══════════
        if callback:
            callback(60, "逐段拼接合并音频...")
        self._merge_audio_consecutive(segments, task_dir, callback,
                                      audio_format_override=audio_format_override,
                                      audio_bitrate_override=audio_bitrate_override)

        # ═══════════ Step 7: 生成配音字幕 ═══════════
        if callback:
            callback(85, "生成配音字幕...")
        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        dub_srt_path = os.path.join(output_dir, f"dub{node_suffix}.srt")
        dub_bilingual_srt_path = os.path.join(output_dir, f"dub_bilingual{node_suffix}.srt")
        self._generate_dub_srt(segments, dub_srt_path)
        self._generate_bilingual_srt(segments, dub_bilingual_srt_path)

        # 确定实际输出音频文件名（与 _merge_audio_consecutive 的导出格式一致）
        from backend.utils.audio_segmenter import get_audio_output_settings
        audio_format = get_audio_output_settings().get("format", "wav")
        dub_filename = f"dub{node_suffix}.{audio_format}"
        dub_audio_path = os.path.join(output_dir, dub_filename)

        # ═══════════ Step 8: 保存配音任务表 ═══════════
        if callback:
            callback(90, "保存配音任务表...")
        dub_data["segments"] = segments
        with open(dub_task_path, "w", encoding="utf-8") as f:
            json.dump(dub_data, f, ensure_ascii=False, indent=2)

        csv_path = find_artifact(os.path.join(task_dir, "cache"), "dub_task.csv") or \
            os.path.join(task_dir, "cache", "dub_task.csv")
        self._write_dub_task_csv(segments, csv_path)

        dub_mp3_path = os.path.join(output_dir, dub_filename)

        # 构建产物列表
        artifacts = [f"output/{dub_filename}", f"output/dub{node_suffix}.srt", f"output/dub_bilingual{node_suffix}.srt"]
        outputs = {
            "audio": f"output/{dub_filename}",
            "dub_srt": f"output/dub{node_suffix}.srt",
            "dub_bilingual_srt": f"output/dub_bilingual{node_suffix}.srt",
            "配音任务单": os.path.relpath(csv_path, task_dir),
        }

        # 输出视频：优先输出变速后的视频，否则直接输出输入视频路径
        if adjusted_video_path and os.path.exists(adjusted_video_path):
            artifacts.append("output/video_adjusted.mp4")
            outputs["video_adjusted"] = "output/video_adjusted.mp4"
        elif input_video_path and os.path.isfile(input_video_path):
            # 未执行变速，直接输出输入视频路径
            outputs["video_adjusted"] = input_video_path

        if callback:
            callback(100, "音频合并完成")

        print(f"\n[S10] 音频合并完成")
        print(f"  - 配音音频: {dub_mp3_path}")
        print(f"  - 配音字幕: {dub_srt_path}")
        print(f"  - 双语字幕: {dub_bilingual_srt_path}")
        print(f"  - 配音任务表: {csv_path}")
        if adjusted_video_path:
            print(f"  - 调速视频: {adjusted_video_path}")
        elif input_video_path:
            print(f"  - 输出视频(未变速): {input_video_path}")

        return {
            "artifacts": artifacts,
            "outputs": outputs,
        }

    # ─────────────────── Step 0: 清除旧变速信息 ───────────────────

    @staticmethod
    def _clear_old_speed_info(segments: List[Dict], task_dir: str) -> None:
        """清除 JSON 中的旧变速计算结果，确保重新计算时不被残留数据干扰。"""
        speed_fields = [
            "raw_speed_factor", "speed_factor", "need_speed",
            "adjusted_duration", "audio_file_adjusted",
            "video_speed_ratio", "overflow",
            "need_truncate", "truncate_target_dur",
            "target_start", "target_end", "theory_gap",
            "new_start", "new_end",
        ]
        cleared = 0
        for seg in segments:
            for field in speed_fields:
                if field in seg:
                    del seg[field]
                    cleared += 1

        # 清除旧的变速临时文件
        temp_dir = os.path.join(task_dir, "cache", "dub_temp")
        if os.path.isdir(temp_dir):
            for name in os.listdir(temp_dir):
                if "_adjusted" in name or "_precise" in name:
                    try:
                        os.remove(os.path.join(temp_dir, name))
                    except OSError:
                        pass

        if cleared > 0:
            print(f"[S10] Step 0: 已清除 {cleared} 个旧变速字段")

    @staticmethod
    def _disable_video_speed_assumptions(segments: List[Dict]) -> None:
        """视频未实际变速时，移除依赖变速视频时间轴的字段。"""
        timeline_fields = ("video_speed_ratio", "need_truncate", "truncate_target_dur")
        cleared = 0
        for seg in segments:
            for field in timeline_fields:
                if field in seg:
                    del seg[field]
                    cleared += 1
        if cleared > 0:
            print(f"[S10] Video speed not applied; cleared {cleared} video-timeline fields")

    # ─────────────────── Step 1: 分析变速倍数 ───────────────────

    @staticmethod
    def _ensure_real_durations(segments: List[Dict], task_dir: str) -> None:
        """从已有音频文件回填 real_duration，避免上游 TTS 被跳过时丢失时长信息。"""
        recovered = 0
        missing = 0

        for seg in segments:
            real_dur = seg.get("real_duration", 0)
            if isinstance(real_dur, (int, float)) and real_dur > 0:
                continue

            audio_rel = seg.get("audio_file_adjusted") or seg.get("audio_file", "")
            if not audio_rel:
                missing += 1
                continue

            audio_path = os.path.join(task_dir, audio_rel)
            if not os.path.exists(audio_path):
                missing += 1
                continue

            try:
                probed = get_audio_duration(audio_path)
            except Exception:
                probed = 0

            if probed > 0:
                seg["real_duration"] = round(probed, 4)
                recovered += 1
            else:
                missing += 1

        if recovered > 0:
            print(f"[S10] 已从现有音频回填 real_duration: {recovered} 段")
        if missing > 0:
            print(f"[S10] ⚠ 仍有 {missing} 段缺少 real_duration，变速判断可能回退为默认值")

    @staticmethod
    def _analyze_speed_factors(segments: List[Dict], speed_min: float,
                               speed_max: float, gap_threshold: float) -> None:
        """遍历所有 segment，计算每个的变速倍数。"""
        print("\n[S10] Step 1: 分析变速倍数")
        for seg in segments:
            duration = seg.get("duration", 0)
            real_dur = seg.get("real_duration", 0)
            gap = seg.get("gap_after", 0)

            if duration <= 0 or real_dur <= 0:
                seg["speed_factor"] = 1.0
                seg["raw_speed_factor"] = 1.0
                seg["need_speed"] = False
                seg["overflow"] = False
                continue

            if real_dur <= duration:
                # 配音时长 <= 时间槽，不需要加速
                ratio = real_dur / duration if duration > 0 else 1.0
                seg["speed_factor"] = max(speed_min, ratio)
                seg["raw_speed_factor"] = seg["speed_factor"]
                seg["need_speed"] = False
                seg["overflow"] = False
            else:
                # 配音超出时间槽，需要加速
                available = duration + gap * gap_threshold
                if available > 0:
                    raw_factor = real_dur / available
                else:
                    raw_factor = real_dur / duration
                # 保存原始需求倍数（用于溢出判断）
                seg["raw_speed_factor"] = round(raw_factor, 4)
                # 实际变速倍数限制在 speed_max 以内
                capped_factor = max(speed_min, min(raw_factor, speed_max))
                seg["speed_factor"] = round(capped_factor, 4)
                seg["need_speed"] = capped_factor > 1.01
                # 标记是否溢出（需要视频变速或字幕缩减）
                seg["overflow"] = raw_factor > speed_max

        need_count = sum(1 for s in segments if s.get("need_speed"))
        overflow_count = sum(1 for s in segments if s.get("overflow"))
        print(f"  - 需要变速: {need_count} 段")
        print(f"  - 超出最大变速({speed_max}x): {overflow_count} 段")

    # ─────────────────── Step 2: 计算视频变速片段 ───────────────────

    @staticmethod
    def _calculate_video_speed_segments(
        segments: List[Dict],
        speed_max: float,
        gap_threshold: float,
        fast_limit: float = 2.0,
    ) -> List[tuple]:
        """计算需要视频变速的片段列表。

        视频变速是音频变速+间隙侵占之后的兜底。
        先用音频变速（到 speed_max）+ 间隙侵占（gap * gap_threshold），
        如果仍然放不下，才叠加视频变速来补齐剩余缺口。
        视频变速倍率上限为 fast_limit。
        """
        print("\n[S10] Step 2: 计算视频变速片段")
        speed_segments = []

        for seg in segments:
            if not seg.get("overflow"):
                continue

            start = seg.get("start", 0)
            end = seg.get("end", start)
            duration = end - start

            if duration <= 0:
                continue

            real_dur = seg.get("real_duration", duration)
            gap = seg.get("gap_after", 0)

            # 可用时间 = 原始时长 + 间隙侵占
            available = duration + gap * gap_threshold

            # 音频以 speed_max 变速后的时长
            audio_adjusted_dur = real_dur / speed_max

            # 如果音频变速+间隙侵占仍放不下，需要视频变速
            if audio_adjusted_dur > available and available > 0:
                video_speed_ratio = audio_adjusted_dur / available
            elif audio_adjusted_dur > duration:
                # 间隙为0或很小的情况
                video_speed_ratio = audio_adjusted_dur / duration
            else:
                continue

            # 限制在合理范围内
            video_speed_ratio = max(1.05, min(video_speed_ratio, fast_limit))

            # video_speed_ratio 可能被上限截断，回写到 segment 以便音频变速对齐
            seg["video_speed_ratio"] = round(video_speed_ratio, 3)
            speed_segments.append((start, end, video_speed_ratio))
            print(f"  - 片段 {seg.get('index')}: 视频变速 {video_speed_ratio:.3f}x "
                  f"({start:.2f}s-{end:.2f}s), "
                  f"音频变速后={audio_adjusted_dur:.3f}s, 可用={available:.3f}s")

        print(f"  - 需要视频变速: {len(speed_segments)} 段")
        return speed_segments

    # ─────────────────── Step 3.5: 标记截断段 ───────────────────

    @staticmethod
    def _mark_truncate_segments(
        segments: List[Dict],
        speed_max: float,
        gap_threshold: float,
        fast_limit: float,
    ) -> None:
        """检测视频变速后仍超出的段，标记为需要截断。

        判断条件：音频变速(speed_max) + 间隙侵占(gap * gap_threshold)
        + 视频变速(fast_limit) 仍然放不下 → 截断配音音频。
        """
        print("\n[S10] Step 3.5: 检测需要截断的段")
        truncate_count = 0

        for seg in segments:
            real_dur = seg.get("real_duration", 0)
            duration = seg.get("duration", 0)
            gap = seg.get("gap_after", 0)
            video_speed = seg.get("video_speed_ratio", 1.0)

            if real_dur <= 0 or duration <= 0:
                continue

            # 可用时间 = 原始时长 + 间隙侵占
            available = duration + gap * gap_threshold

            # 叠加所有加速手段后的音频时长
            audio_after_speed = real_dur / speed_max
            video_after_speed = audio_after_speed / video_speed

            # 如果仍然超出可用时间，需要截断
            if video_after_speed > available + 0.01:
                # 截断目标时长 = 可用时间（音频变速后填满可用空间）
                seg["need_truncate"] = True
                seg["truncate_target_dur"] = round(available / speed_max, 3)
                truncate_count += 1
                print(f"  - 片段 {seg.get('index')}: 需截断 "
                      f"(音频变速后={audio_after_speed:.3f}s, "
                      f"视频变速后={video_after_speed:.3f}s, "
                      f"可用={available:.3f}s)")

        if truncate_count > 0:
            print(f"  - 需要截断: {truncate_count} 段")
        else:
            print("  - 无需截断")

    # ─────────────────── Step 3: 视频变速（OpenCV） ───────────────────

    def _adjust_video_speed_opencv(
        self,
        task_dir: str,
        speed_segments: List[tuple],
        input_video_path: Optional[str] = None,
    ) -> Optional[str]:
        """使用 OpenCV 对视频进行局部变速（纯 OpenCV，无 ffmpeg 回退）。"""
        print("\n[S10] Step 3: 视频变速 (OpenCV)")

        # 使用传入的视频路径（来自输入节点连线）
        video_path = input_video_path
        if not video_path:
            print("  ⚠ 未找到输入视频，跳过视频变速")
            return None

        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        adjusted_video = os.path.join(output_dir, "video_adjusted.mp4")

        try:
            from backend.utils.video_speed_opencv import adjust_video_speed_segments

            print(f"  - 输入视频: {video_path}")
            print(f"  - 输出视频: {adjusted_video}")

            def _progress(pct: int, msg: str):
                print(f"    [{pct}%] {msg}")

            result_path = adjust_video_speed_segments(
                video_path,
                adjusted_video,
                speed_segments,
                progress_callback=_progress,
            )

            if result_path and os.path.exists(result_path):
                print(f"  - 视频变速完成: {result_path}")
                return result_path
            else:
                print("  ⚠ 视频变速失败，输出文件不存在")
                return None

        except Exception as e:
            print(f"  ⚠ OpenCV 视频变速失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    @staticmethod
    def _resolve_input_video(step_inputs: dict, task_dir: str) -> Optional[str]:
        """解析输入视频路径，优先使用连线传入的视频。"""
        # 1. 优先使用连线传入的视频路径
        video_input = step_inputs.get("video", "")
        if video_input:
            # 绝对路径
            if os.path.isabs(video_input) and os.path.isfile(video_input):
                return video_input
            # 相对路径（相对于任务目录）
            rel_path = os.path.join(task_dir, video_input)
            if os.path.isfile(rel_path):
                return rel_path

        # 2. 回退：检查 output 目录中的常见视频文件名
        output_dir = os.path.join(task_dir, "output")
        for name in ["original.mp4", "video.mp4", "input.mp4"]:
            path = os.path.join(output_dir, name)
            if os.path.exists(path):
                return path

        # 3. 回退：检查 cache 目录中的视频文件
        cache_dir = os.path.join(task_dir, "cache")
        if os.path.exists(cache_dir):
            # 优先匹配 input_video.* 文件
            for name in sorted(os.listdir(cache_dir)):
                if name.startswith("input_video") and name.endswith((".mp4", ".mkv", ".avi", ".mov")):
                    return os.path.join(cache_dir, name)
            # 再匹配其他视频文件
            for name in sorted(os.listdir(cache_dir)):
                if name.endswith((".mp4", ".mkv", ".avi", ".mov")):
                    return os.path.join(cache_dir, name)

        return None

    # ─────────────────── Step 3.5: 视频变速后时长核验 ───────────────────

    @staticmethod
    def _verify_video_speed_durations(
        segments: List[Dict],
        video_speed_segments: List[tuple],
        adjusted_video_path: Optional[str],
        task_dir: str,
    ) -> None:
        """核验视频变速后各段的实际时长，必要时对音频做精确二次变速。

        OpenCV 变速使用 round() 计算帧数，会导致舍入误差。
        此方法读取输出视频的实际帧数/时长，重新计算每段在输出视频中的
        实际时长，并在偏差 > 5ms 时对对应音频段做精确二次变速。
        """
        if not adjusted_video_path or not os.path.exists(adjusted_video_path):
            return
        if not video_speed_segments:
            return

        print("\n[S10] Step 3.5: 视频变速后时长核验")

        try:
            import cv2
        except ImportError:
            print("  ⚠ cv2 不可用，跳过视频时长核验")
            return

        # 读取输入视频 fps（与 video_speed_opencv.py 中一致）
        # 需要从 speed_segments 推算各段在输出中的实际帧数
        cap = cv2.VideoCapture(adjusted_video_path)
        if not cap.isOpened():
            print("  ⚠ 无法打开变速后视频")
            return

        out_fps = cap.get(cv2.CAP_PROP_FPS)
        out_total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()

        if out_fps <= 0:
            return

        print(f"  - 变速后视频: {out_total_frames} 帧, {out_fps:.2f} fps")

        # 构建 speed_segment 索引映射: start -> (start, end, ratio)
        speed_map = {}
        for start, end, ratio in video_speed_segments:
            speed_map[round(start, 4)] = (start, end, ratio)

        # 遍历 segments 找出有视频变速的段，计算 OpenCV 实际输出时长
        for seg in segments:
            vs_ratio = seg.get("video_speed_ratio", 1.0)
            if vs_ratio <= 1.01:
                continue

            start = seg.get("start", 0)
            end = seg.get("end", start)
            duration = end - start

            if duration <= 0:
                continue

            # 用与 video_speed_opencv.py 相同的公式计算实际帧数
            # input_frames = round(end * fps_in) - round(start * fps_in)
            # output_frames = max(1, round(input_frames / ratio))
            # 这里我们反推：读取输出视频信息来计算该段的实际输出时长
            # 但由于 OpenCV 没有提供段级别的帧索引，我们用公式精确计算
            # 注意：需要输入视频的 fps，这里从输入视频获取
            # 实际上我们可以直接从 fps 计算
            # 简化方案：用公式估算实际帧数
            fps_in = out_fps  # OpenCV 变速不改变 fps
            input_frames = round(end * fps_in) - round(start * fps_in)
            output_frames = max(1, round(input_frames / vs_ratio))
            actual_seg_dur = output_frames / fps_in

            theory_dur = seg.get("adjusted_duration") or (duration / vs_ratio)
            drift = abs(actual_seg_dur - theory_dur) * 1000  # ms

            print(f"  [{seg.get('index')}] 视频变速 {vs_ratio:.3f}x: "
                  f"理论={theory_dur:.4f}s, 实际={actual_seg_dur:.4f}s, "
                  f"偏差={drift:.1f}ms")

            if drift > 5.0:
                # 偏差超过 5ms，对音频做精确二次变速到 actual_seg_dur
                audio_rel = seg.get("audio_file_adjusted") or seg.get("audio_file", "")
                audio_path = os.path.join(task_dir, audio_rel)
                if not os.path.exists(audio_path):
                    continue

                cache_dir = os.path.join(task_dir, "cache", "dub_temp")
                os.makedirs(cache_dir, exist_ok=True)
                idx = seg.get("index", 0)
                precise_path = os.path.join(cache_dir, f"{idx:04d}_precise.wav")

                try:
                    from backend.utils.audio_speed import adjust_audio_speed_precise
                    actual_dur, sr = adjust_audio_speed_precise(
                        audio_path, precise_path,
                        speed_factor=1.0,  # 不再变速，直接裁剪/填充到精确时长
                        target_duration=actual_seg_dur
                    )
                    if os.path.exists(precise_path):
                        seg["audio_file_adjusted"] = os.path.relpath(precise_path, task_dir).replace("\\", "/")
                        seg["adjusted_duration"] = round(actual_dur, 4)
                        print(f"  [{idx}] 精确校正: {theory_dur:.4f}s → {actual_dur:.4f}s")
                except Exception as e:
                    print(f"  [{idx}] 精确校正失败: {e}")

    # ─────────────────── Step 4: 音频变速 ───────────────────

    @staticmethod
    def _adjust_audio_speed_all(segments: List[Dict], task_dir: str) -> None:
        """对需要变速的片段执行精确音频变速。

        使用 adjust_audio_speed_precise（soundfile + numpy），
        确保变速后音频时长精确可控。当有视频变速时，
        可通过 target_duration 裁剪到精确时长。
        """
        print("\n[S10] Step 4: 音频变速（精确模式）")
        cache_dir = os.path.join(task_dir, "cache", "dub_temp")
        os.makedirs(cache_dir, exist_ok=True)

        adjusted_count = 0
        truncated_count = 0
        for i, seg in enumerate(segments):
            need_speed = seg.get("need_speed") and seg.get("speed_factor", 1.0) > 1.01
            need_truncate = seg.get("need_truncate", False)

            if not need_speed and not need_truncate:
                continue

            input_audio = os.path.join(task_dir, seg.get("audio_file", ""))
            if not os.path.exists(input_audio):
                continue

            idx = seg.get("index", i)
            adjusted_path = os.path.join(cache_dir, f"{idx:04d}_adjusted.wav")

            # 计算实际需要的变速倍率
            video_speed = seg.get("video_speed_ratio", 1.0)
            base_speed = seg.get("speed_factor", 1.0)
            real_dur = seg.get("real_duration", 0)
            duration = seg.get("duration", 0)

            if video_speed > 1.01 and duration > 0 and real_dur > 0:
                # 有视频变速时：目标时长 = 原始时间槽 / 视频变速比
                target_dur = duration / video_speed
                speed_factor = real_dur / target_dur
            else:
                speed_factor = base_speed
                target_dur = None

            if not need_speed:
                speed_factor = 1.0

            # 如果需要截断，将截断时长作为精确目标
            if need_truncate:
                truncate_dur = seg.get("truncate_target_dur", 0)
                if truncate_dur > 0:
                    target_dur = truncate_dur

            try:
                actual_dur, sr = adjust_audio_speed_precise(
                    input_audio, adjusted_path, speed_factor,
                    target_duration=target_dur
                )
                if actual_dur > 0 and os.path.exists(adjusted_path):
                    seg["audio_file_adjusted"] = os.path.relpath(adjusted_path, task_dir).replace("\\", "/")
                    seg["adjusted_duration"] = round(actual_dur, 4)
                    adjusted_count += 1
                    label = f"{speed_factor:.3f}x"
                    if video_speed > 1.01:
                        label += f" (audio={base_speed:.3f} * video={video_speed:.3f})"
                    if target_dur is not None:
                        label += f" → 精确{target_dur:.3f}s"
                    if need_truncate:
                        label += " [截断]"
                    print(f"  [{idx}] 变速 {label} → 实际{actual_dur:.3f}s")
            except Exception as e:
                print(f"  [{idx}] 变速失败: {e}")

        print(f"  - 变速完成: {adjusted_count} 段")
        if truncated_count > 0:
            print(f"  - 截断完成: {truncated_count} 段")

    # ─────────────────── Step 5: 计算理论时间戳 ───────────────────

    @staticmethod
    def _calculate_theoretical_timestamps(
        segments: List[Dict],
        video_timeline_adjusted: bool = False,
    ) -> None:
        """计算每段的理论时间戳（target_start / theory_gap），供合并时漂移补偿使用。

        与原 _update_timestamps 的区别：
        - 只写 target_start / target_end / theory_gap（理论值）
        - new_start / new_end 改由 _merge_audio_consecutive 从实测值填充
        - 间隙从原始时间轴的段边界差值计算（而非 gap_after / speed）
        """
        print("\n[S10] Step 5: 计算理论时间戳")
        initial_offset = segments[0].get("start", 0) if segments else 0
        current_time = initial_offset
        if not video_timeline_adjusted:
            print("  - 视频未变速：按原始字幕时间轴锚定每段起点")
        if initial_offset > 0:
            print(f"  - 开头静音段: {initial_offset:.3f}s")

        for i, seg in enumerate(segments):
            adjusted_dur = seg.get("adjusted_duration") or seg.get("real_duration") or seg.get("duration", 0)
            if video_timeline_adjusted:
                target_start = current_time
            else:
                target_start = seg.get("start", current_time)

            seg["target_start"] = round(target_start, 4)
            seg["target_end"] = round(target_start + adjusted_dur, 4)

            if not video_timeline_adjusted:
                if i < len(segments) - 1:
                    next_seg = segments[i + 1]
                    original_gap = next_seg.get("start", 0) - seg.get("end", seg.get("start", 0))
                    seg["theory_gap"] = round(max(0.0, original_gap), 4)
                else:
                    seg["theory_gap"] = 0
                current_time = seg["target_end"]
                if seg.get("need_speed"):
                    print(f"  [{seg.get('index', i)}] "
                          f"原始: {seg.get('start', 0):.3f}-{seg.get('end', 0):.3f} → "
                          f"理论: {seg['target_start']:.3f}-{seg['target_end']:.3f} "
                          f"(时长: {adjusted_dur:.3f}s, 变速: {seg.get('speed_factor', 1.0):.3f}x)")
                continue

            if i < len(segments) - 1:
                next_seg = segments[i + 1]
                # 从原始时间轴计算段间间隙（考虑视频变速导致的段时长变化）
                original_gap = next_seg.get("start", 0) - seg.get("end", seg.get("start", 0))
                video_speed = seg.get("video_speed_ratio", 1.0)
                if video_speed > 1.01:
                    new_gap = original_gap / video_speed
                else:
                    new_gap = original_gap
                # 间隙不允许为负（原始时间轴重叠时填 0）
                new_gap = max(0.0, new_gap)
                seg["theory_gap"] = round(new_gap, 4)
                current_time = seg["target_end"] + new_gap
            else:
                seg["theory_gap"] = 0
                current_time = seg["target_end"]

            if seg.get("need_speed"):
                print(f"  [{seg.get('index', i)}] "
                      f"原始: {seg.get('start', 0):.3f}-{seg.get('end', 0):.3f} → "
                      f"理论: {seg['target_start']:.3f}-{seg['target_end']:.3f} "
                      f"(时长: {adjusted_dur:.3f}s, 变速: {seg.get('speed_factor', 1.0):.3f}x)")

        print(f"  - 理论总时长: {current_time:.3f}s")

    # ─────────────────── Step 6: 逐段拼接合并音频（含漂移补偿） ───────────────────

    def _merge_audio_consecutive(self, segments: List[Dict], task_dir: str,
                                 callback: Optional[Callable] = None,
                                 audio_format_override: str = "",
                                 audio_bitrate_override=None) -> None:
        """逐段拼接合并音频，每段之间进行理论时间点检测和静音补偿。

        核心机制：
        - 累积实际时长，每段拼接前计算与理论位置的漂移
        - 在静音间隙中补偿漂移，确保后续片段位置正确
        - new_start/new_end 从实测值写回 segments
        """
        import numpy as np
        import soundfile as sf
        from backend.utils.audio_speed import resample_audio

        print("\n[S10] Step 6: 逐段拼接合并音频（含漂移补偿）")
        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        node_suffix = f"_{getattr(self, '_node_id', '')}" if getattr(self, "_node_id", "") else ""
        total = len(segments)

        output_settings = get_audio_output_settings()
        target_sr = int(output_settings.get("sample_rate", 48000))
        target_bit_depth = int(output_settings.get("bit_depth", 16) or 16)

        def _active_rms_dbfs(audio: np.ndarray) -> Optional[float]:
            if audio.size == 0:
                return None
            active = audio[np.abs(audio) > 1e-4]
            if active.size < max(128, audio.size // 100):
                active = audio
            if active.size == 0:
                return None
            rms = float(np.sqrt(np.mean(np.square(active, dtype=np.float64))))
            if rms <= 1e-8:
                return None
            return float(20.0 * np.log10(rms))

        def _normalize_segment_loudness(
            audio: np.ndarray,
            target_dbfs: float,
            max_boost_db: float = 8.0,
            max_cut_db: float = 8.0,
            peak_ceiling_dbfs: float = -1.0,
        ) -> tuple[np.ndarray, float, Optional[float]]:
            current_dbfs = _active_rms_dbfs(audio)
            if current_dbfs is None:
                return audio, 0.0, None

            gain_db = max(-max_cut_db, min(target_dbfs - current_dbfs, max_boost_db))
            peak = float(np.max(np.abs(audio))) if audio.size else 0.0
            if peak > 1e-8:
                peak_dbfs = 20.0 * np.log10(peak)
                gain_db = min(gain_db, peak_ceiling_dbfs - peak_dbfs)

            if abs(gain_db) < 0.05:
                return audio, gain_db, current_dbfs

            gain = float(10.0 ** (gain_db / 20.0))
            normalized = audio * gain
            peak_ceiling = float(10.0 ** (peak_ceiling_dbfs / 20.0))
            normalized_peak = float(np.max(np.abs(normalized))) if normalized.size else 0.0
            if normalized_peak > peak_ceiling and normalized_peak > 1e-8:
                normalized = normalized * (peak_ceiling / normalized_peak)
            return normalized.astype(np.float32, copy=False), gain_db, current_dbfs

        # 先扫一遍片段响度，使用中位数作为目标响度，避免逐段忽大忽小。
        segment_loudness = []
        for i, seg in enumerate(segments):
            audio_rel = seg.get("audio_file_adjusted") or seg.get("audio_file", "")
            audio_path = os.path.join(task_dir, audio_rel)
            if not os.path.exists(audio_path):
                continue
            try:
                probe_data, probe_sr = sf.read(audio_path, dtype='float32')
                if probe_data.ndim > 1:
                    probe_data = np.mean(probe_data, axis=1).astype(np.float32)
                if probe_sr != target_sr:
                    probe_data = resample_audio(probe_data, probe_sr, target_sr)
                loudness_dbfs = _active_rms_dbfs(probe_data)
                if loudness_dbfs is not None:
                    segment_loudness.append(loudness_dbfs)
            except Exception as e:
                print(f"  [{seg.get('index', i)}] ⚠ 响度分析失败: {e}")

        if segment_loudness:
            target_loudness_dbfs = float(np.median(segment_loudness))
            target_loudness_dbfs = max(-24.0, min(target_loudness_dbfs, -16.0))
            print(
                f"  - 响度对齐目标: {target_loudness_dbfs:.1f} dBFS "
                f"(样本中位数, 共{len(segment_loudness)}段)"
            )
        else:
            target_loudness_dbfs = -20.0
            print("  - 响度对齐目标: -20.0 dBFS (默认值)")

        # 累积的音频数据
        merged_data = np.array([], dtype=np.float32)
        accumulated_duration = 0.0  # 实际累积时长（秒）

        drift_log = []  # 记录每段漂移用于最终报告

        for i, seg in enumerate(segments):
            # 优先使用变速后的音频
            audio_rel = seg.get("audio_file_adjusted") or seg.get("audio_file", "")
            audio_path = os.path.join(task_dir, audio_rel)

            if not os.path.exists(audio_path):
                print(f"  [{seg.get('index', i)}] ⚠ 音频文件不存在: {audio_path}")
                continue

            # 读取音频
            try:
                seg_data, seg_sr = sf.read(audio_path, dtype='float32')
            except Exception as e:
                print(f"  [{seg.get('index', i)}] ⚠ 读取失败: {e}")
                continue

            # 转单声道
            if seg_data.ndim > 1:
                seg_data = np.mean(seg_data, axis=1).astype(np.float32)

            # 采样率对齐
            if seg_sr != target_sr:
                seg_data = resample_audio(seg_data, seg_sr, target_sr)

            seg_data, gain_db, loudness_dbfs = _normalize_segment_loudness(
                seg_data, target_loudness_dbfs
            )
            seg_actual_dur = len(seg_data) / target_sr

            # === 理论时间点检测与漂移补偿 ===
            # target_start 已包含 theory_gap（在 _calculate_theoretical_timestamps 中计算），
            # 所以只需确保 accumulated_duration 达到 target_start 即可，
            # 静音 = target_start - accumulated_duration（正值补静音，负值/零则直接拼接）。
            target_start = seg.get("target_start", 0)
            target_end = seg.get("target_end", target_start + seg_actual_dur)
            drift = accumulated_duration - target_start  # 正值=超前，负值=滞后

            # 实际需要填充的静音 = 使当前位置到达 target_start 的时间差
            actual_silence = max(0.0, target_start - accumulated_duration)
            silence_samples = int(round(actual_silence * target_sr))

            # 记录实际时间戳：segment 在合并音频中的起始位置
            actual_start = accumulated_duration + actual_silence

            # 追加静音 + 当前段音频
            if silence_samples > 0:
                merged_data = np.concatenate([
                    merged_data, np.zeros(silence_samples, dtype=np.float32)
                ])
            merged_data = np.concatenate([merged_data, seg_data])

            accumulated_duration = len(merged_data) / target_sr
            seg["new_start"] = round(actual_start, 4)
            seg["new_end"] = round(accumulated_duration, 4)

            drift_ms = drift * 1000
            drift_log.append(abs(drift_ms))
            loudness_label = ""
            if loudness_dbfs is not None:
                loudness_label = f", 响度: {loudness_dbfs:.1f}→{target_loudness_dbfs:.1f} dBFS, 增益: {gain_db:+.1f}dB"
            print(f"  [{seg.get('index', i)}] 实际: {seg['new_start']:.3f}-{seg['new_end']:.3f}s "
                  f"(漂移: {drift_ms:+.1f}ms, 补偿静音: {actual_silence*1000:.1f}ms, "
                  f"音频时长: {seg_actual_dur:.3f}s{loudness_label})")

            pct = 65 + int((i + 1) / max(total, 1) * 18)
            if callback:
                callback(pct, f"合并 {i + 1}/{total}")

        # 漂移统计
        if drift_log:
            max_drift = max(drift_log)
            avg_drift = sum(drift_log) / len(drift_log)
            print(f"\n  - 漂移统计: 最大={max_drift:.1f}ms, 平均={avg_drift:.1f}ms")
            print(f"  - 累积实际时长: {accumulated_duration:.3f}s")

        # 最终输出前做一次峰值保护，避免拼接后边界峰值接近削波。
        if merged_data.size:
            peak = float(np.max(np.abs(merged_data)))
            peak_ceiling = float(10.0 ** (-1.0 / 20.0))
            if peak > peak_ceiling and peak > 1e-8:
                merged_data = merged_data * (peak_ceiling / peak)
                print(f"  - 峰值保护: {20.0 * np.log10(peak):.1f} dBFS → -1.0 dBFS")

        # 导出音频
        audio_format = audio_format_override or output_settings["format"]

        if audio_format == "wav":
            output_path = os.path.join(output_dir, f"dub{node_suffix}.wav")
            wav_subtype = 'PCM_24' if target_bit_depth >= 24 else 'PCM_16'
            sf.write(output_path, merged_data, target_sr, subtype=wav_subtype)
        elif audio_format == "flac":
            output_path = os.path.join(output_dir, f"dub{node_suffix}.flac")
            sf.write(output_path, merged_data, target_sr, format='FLAC')
        else:
            # mp3: 先用 soundfile 写 wav，再用 pydub 转 mp3
            output_path = os.path.join(output_dir, f"dub{node_suffix}.mp3")
            if HAS_PYDUB:
                import tempfile
                wav_tmp = os.path.join(output_dir, "_dub_tmp.wav")
                sf.write(wav_tmp, merged_data, target_sr, subtype='PCM_16')
                bitrate = int(audio_bitrate_override) if audio_bitrate_override else output_settings["bitrate"]
                audio_seg = AudioSegment.from_wav(wav_tmp)
                audio_seg.export(output_path, format="mp3", bitrate=f"{bitrate}k")
                try:
                    os.remove(wav_tmp)
                except OSError:
                    pass
            else:
                # 无 pydub 时写 wav
                output_path = os.path.join(output_dir, f"dub{node_suffix}.wav")
                sf.write(output_path, merged_data, target_sr, subtype='PCM_16')

        print(f"  - 已导出: {output_path}")

    # ─────────────────── Step 7: 生成配音字幕 ───────────────────

    @staticmethod
    def _generate_dub_srt(segments: List[Dict], output_path: str) -> None:
        """生成配音字幕 SRT 文件。

        时间戳使用 new_start/new_end，确保与合并后的音频精确对齐。
        """
        print("\n[S10] Step 7: 生成配音字幕")
        lines = []
        for i, seg in enumerate(segments, 1):
            start = seg.get("new_start", seg.get("start", 0))
            end = seg.get("new_end", seg.get("end", 0))
            text = seg.get("read_text", seg.get("text", ""))

            # 确保时间戳有效
            if end <= start:
                end = start + 0.1

            lines.append(str(i))
            lines.append(f"{S10MergeAudio._format_srt_time(start)} --> {S10MergeAudio._format_srt_time(end)}")
            lines.append(text)
            lines.append("")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"  - 配音字幕已生成: {output_path}")
        print(f"  - 字幕条数: {len(segments)}")

    @staticmethod
    def _generate_bilingual_srt(segments: List[Dict], output_path: str) -> None:
        """生成双语字幕 SRT 文件（原文在上，译文在下）。

        时间戳使用 new_start/new_end，确保与合并后的音频精确对齐。
        """
        lines = []
        for i, seg in enumerate(segments, 1):
            start = seg.get("new_start", seg.get("start", 0))
            end = seg.get("new_end", seg.get("end", 0))
            original = seg.get("text", "")
            translated = seg.get("read_text", "")

            if end <= start:
                end = start + 0.1

            lines.append(str(i))
            lines.append(f"{S10MergeAudio._format_srt_time(start)} --> {S10MergeAudio._format_srt_time(end)}")
            # 原文在上，译文在下
            if original and translated and original != translated:
                lines.append(f"{original}\n{translated}")
            elif translated:
                lines.append(translated)
            else:
                lines.append(original)
            lines.append("")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"  - 双语字幕已生成: {output_path}")
        print(f"  - 字幕条数: {len(segments)}")

    @staticmethod
    def _format_srt_time(seconds: float) -> str:
        """将秒数转换为 SRT 时间格式 HH:MM:SS,mmm"""
        total_ms = max(0, int(round(seconds * 1000)))
        h, rem = divmod(total_ms, 3600_000)
        m, rem = divmod(rem, 60_000)
        s, ms = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    # ─────────────────── 工具方法 ───────────────────

    @staticmethod
    def _write_dub_task_csv(segments: List[Dict], csv_path: str) -> None:
        """将 segments 写入 CSV 文件。"""
        if not segments:
            return
        fieldnames = [
            "index", "text", "read_text", "read_text_original", "read_tone_desc",
            "start", "end", "duration", "original_duration", "real_duration",
            "gap_after", "speed_factor", "raw_speed_factor", "need_speed", "overflow",
            "adjusted_duration", "new_start", "new_end",
            "audio_file", "audio_file_adjusted",
            "character_id", "read_character_id", "character_voice_desc",
            "dialect",
        ]
        try:
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for seg in segments:
                    writer.writerow(seg)
            print(f"  - 配音任务表已保存: {csv_path}")
        except Exception as e:
            print(f"  ⚠ 写入 CSV 失败: {e}")
