from typing import Dict, List, Optional


def clear_timeline_fields(segments: List[Dict]) -> int:
    fields = [
        "raw_speed_factor", "speed_factor", "effective_audio_speed", "need_speed",
        "adjusted_duration", "audio_file_adjusted", "video_speed_ratio", "overflow",
        "need_truncate", "truncate_target_dur", "target_start", "target_end",
        "theory_gap", "new_start", "new_end", "planned_audio_speed",
        "planned_video_speed", "planned_audio_duration", "target_audio_duration",
        "actual_visual_duration", "actual_audio_duration", "audio_drift_ms",
        "video_drift_ms", "align_warning", "truncate_reason",
    ]
    cleared = 0
    for seg in segments:
        for field in fields:
            if field in seg:
                del seg[field]
                cleared += 1
    return cleared


def build_initial_timeline_plan(
    segments: List[Dict],
    speed_min: float,
    speed_max: float,
    gap_threshold: float,
    fast_limit: float,
    video_speed_adjust: bool,
    align_policy: str = "tolerant",
) -> List[Dict]:
    for i, seg in enumerate(segments):
        duration = float(seg.get("duration", 0) or 0)
        real_dur = float(seg.get("real_duration", 0) or 0)
        gap = float(seg.get("gap_after", 0) or 0)
        gap_budget = gap * gap_threshold
        available = duration + gap_budget

        seg["align_policy"] = align_policy
        seg["planned_audio_speed"] = 1.0
        seg["planned_video_speed"] = 1.0
        seg["audio_gap_budget"] = round(gap_budget, 4)
        seg["speed_factor"] = 1.0
        seg["raw_speed_factor"] = 1.0
        seg["need_speed"] = False
        seg["overflow"] = False
        seg["planned_audio_duration"] = round(real_dur or duration, 4)
        seg["target_audio_duration"] = round(real_dur or duration, 4)

        if duration <= 0 or real_dur <= 0:
            continue

        if real_dur <= duration:
            ratio = real_dur / duration if duration > 0 else 1.0
            seg["speed_factor"] = round(max(speed_min, ratio), 4)
            seg["raw_speed_factor"] = seg["speed_factor"]
            continue

        raw_factor = real_dur / available if available > 0 else real_dur / duration
        audio_speed = min(max(raw_factor, 1.0), speed_max)
        audio_duration = real_dur / audio_speed if audio_speed > 0 else real_dur

        seg["raw_speed_factor"] = round(raw_factor, 4)
        seg["speed_factor"] = round(audio_speed, 4)
        seg["planned_audio_speed"] = round(audio_speed, 4)
        seg["planned_audio_duration"] = round(audio_duration, 4)
        seg["target_audio_duration"] = round(audio_duration, 4)
        seg["need_speed"] = audio_speed > 1.01
        seg["overflow"] = raw_factor > speed_max

        if video_speed_adjust and seg["overflow"] and audio_duration > available + 0.01:
            slow_factor = _calculate_video_slow_factor(duration, audio_duration, gap_budget, fast_limit)
            if slow_factor > 1.01:
                video_ratio = 1.0 / slow_factor
                capacity_with_video = duration * slow_factor + gap_budget
                seg["video_speed_ratio"] = round(video_ratio, 4)
                seg["planned_video_speed"] = round(slow_factor, 4)
                seg["target_audio_duration"] = round(min(audio_duration, capacity_with_video), 4)

        visual_capacity = duration * float(seg.get("planned_video_speed", 1.0) or 1.0) + gap_budget
        # 截断判断必须用"变速后可达时长"（real/上限倍速）与容量比较：
        # target_audio_duration 可能已被视频减速分支钳制到容量，拿它比较
        # 永远不会触发截断；即使倍速拉满也放不下的段必须截断音频到槽位容量
        if audio_duration > visual_capacity + 0.01:
            seg["need_truncate"] = True
            seg["truncate_reason"] = "achievable duration exceeds available slot"
            if visual_capacity > 0:
                seg["truncate_target_dur"] = round(visual_capacity, 4)
                seg["target_audio_duration"] = round(visual_capacity, 4)
        elif i == len(segments) - 1:
            seg.setdefault("need_truncate", False)

        seg["effective_audio_speed"] = round(audio_speed, 4)

    return segments


def _calculate_video_slow_factor(duration: float, audio_duration: float, gap_budget: float, fast_limit: float) -> float:
    if duration <= 0:
        return 1.0
    required = max(1.0, (audio_duration - gap_budget) / duration)
    return max(1.0, min(required, fast_limit))


def video_speed_segments_from_plan(
    segments: List[Dict],
    speed_max: Optional[float] = None,
    gap_threshold: Optional[float] = None,
) -> List[tuple]:
    speed_segments = []
    for seg in segments:
        duration = float(seg.get("duration", 0) or 0)
        real_dur = float(seg.get("real_duration", 0) or 0)
        gap = float(seg.get("gap_after", 0) or 0)

        if duration <= 0 or real_dur <= 0 or real_dur <= duration:
            seg.pop("video_speed_ratio", None)
            seg["planned_video_speed"] = 1.0
            continue

        if speed_max is not None and gap_threshold is not None:
            available = duration + gap * gap_threshold
            audio_after_speed = real_dur / speed_max if speed_max > 0 else real_dur
            if available > 0 and audio_after_speed <= available + 0.01:
                seg.pop("video_speed_ratio", None)
                seg["planned_video_speed"] = 1.0
                continue

        ratio = float(seg.get("video_speed_ratio", 1.0) or 1.0)
        if abs(ratio - 1.0) <= 0.01:
            continue
        speed_segments.append((
            float(seg.get("start", 0) or 0),
            float(seg.get("end", seg.get("start", 0)) or 0),
            ratio,
            int(seg.get("index", len(speed_segments)) or 0),
        ))
    return speed_segments


def reconcile_video_manifest(segments: List[Dict], manifest: Optional[Dict]) -> None:
    if not manifest:
        return
    by_index = {int(item.get("index", -1)): item for item in manifest.get("segments", [])}
    for seg in segments:
        idx = int(seg.get("index", -1) or -1)
        item = by_index.get(idx)
        if not item:
            continue
        actual_duration = float(item.get("actual_duration", 0) or 0)
        planned = float(seg.get("target_audio_duration", actual_duration) or actual_duration)
        seg["actual_visual_duration"] = round(actual_duration, 4)
        seg["video_drift_ms"] = round((actual_duration - planned) * 1000.0, 3)


def calculate_target_timestamps(segments: List[Dict], video_timeline_adjusted: bool = False) -> float:
    if not segments:
        return 0.0
    current_time = float(segments[0].get("start", 0) or 0)
    for i, seg in enumerate(segments):
        if video_timeline_adjusted:
            target_start = current_time
        else:
            target_start = float(seg.get("start", current_time) or current_time)

        target_audio_dur = float(
            seg.get("target_audio_duration")
            or seg.get("adjusted_duration")
            or seg.get("real_duration")
            or seg.get("duration")
            or 0
        )
        visual_duration = float(
            seg.get("actual_visual_duration")
            or seg.get("duration")
            or target_audio_dur
            or 0
        )
        seg["target_start"] = round(target_start, 4)
        seg["target_end"] = round(target_start + target_audio_dur, 4)

        if i < len(segments) - 1:
            next_seg = segments[i + 1]
            original_gap = float(next_seg.get("start", 0) or 0) - float(seg.get("end", seg.get("start", 0)) or 0)
            original_gap = max(0.0, original_gap)
        else:
            original_gap = 0.0

        seg["theory_gap"] = round(original_gap, 4)
        if video_timeline_adjusted:
            current_time = target_start + visual_duration + original_gap
        else:
            current_time = seg["target_end"]
    return current_time
