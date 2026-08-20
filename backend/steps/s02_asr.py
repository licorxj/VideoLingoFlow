"""s02_asr: Speech recognition step.

Parameter resolution order (task overrides global defaults):
  1. Read task-specific params from workflow.json  (ASR node's data.config)
  2. Read global defaults from asr_interfaces.json  (matched interface config)
  3. Merge: task params override defaults
  4. Forward merged params to ASR engine via factory

Audio splitting:
  If the interface has a max_duration > 0 and the audio exceeds that limit,
  the audio is split into segments at silence boundaries (ffmpeg silencedetect).
  Each segment is transcribed independently, timestamps are offset-adjusted,
  and results are merged into a single output.
"""
import os
import gc
import json
import subprocess
import tempfile
import shutil
from statistics import median
from typing import Callable, Optional, Dict, Any, List, Tuple

from backend.steps.base_step import BaseStep, find_artifact

# ---------------------------------------------------------------------------
# Keys recognized as ASR runtime parameters (union of all engines).
# ---------------------------------------------------------------------------
_ASR_PARAM_KEYS = {
    "engine", "interface_id",
    "model", "language",
    # WhisperX params
    "compute_type", "batch_size",
    "word_timestamps",
    "vad_onset", "vad_offset",
    "temperatures", "initial_prompt",
    "align_model_name",
    # Qwen3-ASR params
    "dtype", "device_map",
    "context", "aligner_model",
    # ElevenLabs params
    "api_key", "diarize",
    "tag_audio_events", "num_speakers",
    # WhisperX diarization params
    "diarize_model", "hf_token",
    "min_speakers", "max_speakers",
    # MiMo ASR params
    "base_url",
    # FunASR Nano params
    "hotwords", "hotwords_enabled", "use_itn", "vad_model",
    "vad_max_segment_time", "sentence_timestamp",
}

# Fallback engine when neither task config nor interface config specifies one.
_DEFAULT_ENGINE = "whisperx_local"


# ---------------------------------------------------------------------------
# Audio splitting helpers
# ---------------------------------------------------------------------------

def _get_audio_duration(audio_path: str) -> float:
    """Get audio duration in seconds using ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def _detect_silence(audio_path: str, start: float, end: float,
                    threshold_db: float = -30.0, min_duration: float = 0.5) -> List[float]:
    """Detect silence_end points in [start, end] using ffmpeg silencedetect.

    Returns a list of timestamps (in seconds) where silence ends.
    """
    cmd = [
        "ffmpeg", "-y", "-i", audio_path,
        "-ss", str(start), "-to", str(end),
        "-af", f"silencedetect=n={threshold_db}dB:d={min_duration}",
        "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, encoding="utf-8")
        stderr = proc.stderr
    except Exception:
        return []

    silence_ends = []
    for line in stderr.split("\n"):
        if "silence_end" in line:
            try:
                val = float(line.split("silence_end: ")[1].split(" ")[0])
                silence_ends.append(val)
            except (IndexError, ValueError):
                continue
    return silence_ends


def split_audio_at_silence(audio_path: str, max_duration: float,
                           silence_win: float = 60.0) -> List[Tuple[float, float]]:
    """Split audio into segments, cutting at silence boundaries.

    Algorithm (matching original project logic):
    1. Walk through audio in max_duration chunks.
    2. For the last ~silence_win seconds of each chunk, search for silence.
    3. If a silence point is found, cut there; otherwise cut at the boundary.
    4. The remaining tail is a shorter final segment.

    Parameters
    ----------
    audio_path : str     Path to audio file.
    max_duration : float Max segment duration in seconds.
    silence_win : float  Window (seconds) before max_duration to search for silence.

    Returns
    -------
    List[Tuple[float, float]]  List of (start, end) in seconds.
    """
    duration = _get_audio_duration(audio_path)
    if duration <= 0:
        return [(0.0, 0.0)]

    if duration <= max_duration:
        return [(0.0, duration)]

    segments: List[Tuple[float, float]] = []
    pos = 0.0

    while pos < duration:
        remaining = duration - pos
        if remaining <= max_duration:
            segments.append((pos, duration))
            break

        # Search window: [pos + max_duration - win, pos + max_duration + win]
        win_start = pos + max_duration - silence_win
        win_end = min(pos + max_duration + silence_win, duration)

        silence_points = _detect_silence(audio_path, win_start, win_end)

        if silence_points:
            # Find the first silence_end that is past the ideal cut point
            ideal_cut = pos + max_duration
            split_at = None
            for t in silence_points:
                if t > ideal_cut - silence_win and t <= ideal_cut + silence_win:
                    split_at = t
                    break
                # Also accept the first one that is close enough
                if t >= ideal_cut:
                    split_at = t
                    break
            # Fallback: pick the closest to ideal_cut
            if split_at is None and silence_points:
                split_at = min(silence_points, key=lambda t: abs(t - ideal_cut))

            if split_at is not None and win_start <= split_at <= win_end:
                segments.append((pos, split_at))
                pos = split_at
                continue

        # No good silence point found: cut at exact boundary
        segments.append((pos, pos + max_duration))
        pos += max_duration

    return segments


def _split_audio_file(audio_path: str, start: float, end: float,
                      output_path: str) -> str:
    """Extract a segment from audio file using ffmpeg."""
    cmd = [
        "ffmpeg", "-y", "-i", audio_path,
        "-ss", str(start), "-to", str(end),
        "-c", "copy",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        # Fallback: re-encode if copy fails
        cmd = [
            "ffmpeg", "-y", "-i", audio_path,
            "-ss", str(start), "-to", str(end),
            "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to split audio: {result.stderr[:300]}")
    return output_path


def _adjust_timestamps(result: dict, time_offset: float) -> dict:
    """Offset all timestamps in an ASR result by time_offset seconds."""
    if not result:
        return result

    for seg in result.get("segments", []):
        if "start" in seg:
            seg["start"] = round(seg["start"] + time_offset, 4)
        if "end" in seg:
            seg["end"] = round(seg["end"] + time_offset, 4)
        for word in seg.get("words", []):
            if "start" in word:
                word["start"] = round(word["start"] + time_offset, 4)
            if "end" in word:
                word["end"] = round(word["end"] + time_offset, 4)

    return result


def _merge_results(results: List[dict]) -> dict:
    """Merge multiple ASR results from sequential audio segments.

    Combines segments, deduplicates speakers, and re-numbers segment IDs.
    """
    if not results:
        return {"segments": [], "language": "auto"}

    merged_segments: List[dict] = []
    all_speakers: set = set()
    detected_language = "auto"

    for r in results:
        lang = r.get("language", "auto")
        if lang and lang != "auto":
            detected_language = lang
            break

    for r in results:
        # Collect speakers
        for spk in r.get("speakers", []):
            all_speakers.add(spk)

        for seg in r.get("segments", []):
            merged_segments.append(seg)

    # Re-number segment IDs
    for idx, seg in enumerate(merged_segments, start=1):
        seg["id"] = idx

    output: Dict[str, any] = {
        "language": detected_language,
        "segments": merged_segments,
    }

    # Include full text if present
    full_text = " ".join(
        seg.get("text", "") for seg in merged_segments
    )
    if full_text:
        output["text"] = full_text.strip()

    if all_speakers:
        output["speakers"] = sorted(all_speakers)

    # 保留引擎内部执行标志（各分段由同一引擎转录，全部分段都带标志时才保留，
    # 避免长音频合并后丢失标志导致下游重复执行 VAD/对齐/说话人识别）
    for flag in ("_vad_internally_executed", "_alignment_internally_executed",
                 "_diarization_internally_executed"):
        if all(r.get(flag) for r in results):
            output[flag] = True

    return output


def _clamp_result_to_duration(result: dict, duration: float) -> dict:
    """将 ASR 结果中所有时间戳钳制到 [0, duration]，并修复退化段。

    后处理（VAD 文本按比例分配 + 对齐引擎）在尾部语音上可能产生退化时间戳：
    超出音源时长、零时长、对齐失败后的均匀间隔伪造链等。若不钳制，这些时间戳
    会流入断句与配音阶段，导致视频变速目标超出媒体末尾（actual_visual_duration=0）
    与时间轴漂移爆炸。

    处理步骤：
    1. 所有 segment/word 时间戳钳制到 [0, duration]，保证 end >= start；
    2. 词链溢出钳制后窗口时（伪造均匀间隔），在窗口内重新均匀分布；
    3. 连续的零时长退化段，在前后有效段之间的空窗内按词数/文本长度加权铺开。
    """
    if not result or not isinstance(duration, (int, float)) or duration <= 0:
        return result

    duration = float(duration)
    segments = result.get("segments", []) or []

    def _fit(v, lo=0.0, hi=None):
        hi = duration if hi is None else hi
        try:
            return min(max(float(v), lo), hi)
        except (TypeError, ValueError):
            return lo

    # Pass 1: 钳制到媒体范围
    for seg in segments:
        words = seg.get("words") or []
        for w in words:
            w["start"] = round(_fit(w.get("start", 0)), 4)
            w["end"] = round(max(_fit(w.get("end", 0)), w["start"]), 4)
        seg_start = _fit(seg.get("start", 0))
        seg_end = max(_fit(seg.get("end", 0)), seg_start)

        # 词链超出钳制后窗口（如伪造的均匀间隔链）：在窗口内重新均匀分布
        if words and seg_end - seg_start > 1e-3:
            overflow = words[-1]["end"] > seg_end + 1e-3
            collapsed = all(w["end"] - w["start"] < 1e-3 for w in words)
            if overflow or collapsed:
                slot = (seg_end - seg_start) / len(words)
                t = seg_start
                for w in words:
                    w["start"] = round(t, 4)
                    w["end"] = round(min(t + slot, seg_end), 4)
                    t += slot

        seg["start"] = round(seg_start, 4)
        seg["end"] = round(seg_end, 4)

    # Pass 2: 零时长退化段在相邻有效段之间的空窗内加权铺开
    _EPS = 0.05
    i = 0
    n = len(segments)
    while i < n:
        seg = segments[i]
        if seg["end"] - seg["start"] >= _EPS:
            i += 1
            continue
        # 收集连续退化段
        j = i
        while j < n and segments[j]["end"] - segments[j]["start"] < _EPS:
            j += 1
        next_start = segments[j]["start"] if j < n else duration
        # 可铺开区间：向前回溯到最后一个有效段的末尾（退化段常被钉死在
        # 末尾或 0，只有前向空窗可铺时无法展开），向后到下一个有效段的起点
        k = i - 1
        while k >= 0 and segments[k]["end"] - segments[k]["start"] < _EPS:
            k -= 1
        back_end = segments[k]["end"] if k >= 0 else 0.0
        win_start = min(max(back_end, min(segments[i]["start"], next_start)), next_start)
        win_end = min(max(next_start, win_start), duration)
        window = max(0.0, win_end - win_start)

        def _weight(s):
            wc = len(s.get("words") or [])
            if wc > 0:
                return float(wc)
            return float(max(1, len(str(s.get("text", "") or ""))))

        group = segments[i:j]
        # 空窗不足时，把退化组与紧邻的上一个有效段合并，在二者并集区间内
        # 按权重重新铺开（典型场景：尾部段被钉死在媒体末尾，无空窗可用）
        if window < 0.3 and k >= 0:
            win_start = min(segments[k]["start"], win_start)
            win_end = min(max(next_start, win_start), duration)
            window = max(0.0, win_end - win_start)
            group = segments[k:j]

        total_w = sum(_weight(s) for s in group) or 1.0
        t = win_start
        for s in group:
            span = window * _weight(s) / total_w if window > 0 else 0.0
            s["start"] = round(min(t, duration), 4)
            s["end"] = round(min(t + span, duration), 4)
            words = s.get("words") or []
            if words and s["end"] > s["start"]:
                slot = (s["end"] - s["start"]) / len(words)
                wt = s["start"]
                for w in words:
                    w["start"] = round(wt, 4)
                    w["end"] = round(min(wt + slot, s["end"]), 4)
                    wt += slot
            t += span
        i = j

    # Pass 3: 单调性兜底（不缩短有效段，只把后段起点推到前段末尾并再次钳制）
    prev_end = 0.0
    for seg in segments:
        if seg["start"] < prev_end:
            seg["start"] = round(min(prev_end, duration), 4)
            if seg["end"] < seg["start"]:
                seg["end"] = seg["start"]
        prev_end = max(prev_end, seg["end"])

    return result


def _normalize_segment_words(words: List[dict], seg_start: float, seg_end: float) -> List[dict]:
    """Repair word timestamps to be monotonic and bounded by the segment window."""
    normalized: List[dict] = []
    prev_end = max(float(seg_start or 0), 0.0)
    valid_durations = []
    for word in words or []:
        start = word.get("start")
        end = word.get("end")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end > start:
            valid_durations.append(float(end) - float(start))
    fallback_duration = median(valid_durations) if valid_durations else 0.18

    for word in words or []:
        item = dict(word)
        start = item.get("start")
        end = item.get("end")
        try:
            start = float(start)
        except (TypeError, ValueError):
            start = prev_end
        try:
            end = float(end)
        except (TypeError, ValueError):
            end = start + fallback_duration

        start = max(start, prev_end, float(seg_start or 0))
        if end <= start:
            end = start + fallback_duration
        if seg_end and end > seg_end:
            end = float(seg_end)
        if end <= start:
            end = min(float(seg_end), start + max(0.06, fallback_duration)) if seg_end else start + max(0.06, fallback_duration)

        item["start"] = round(start, 4)
        item["end"] = round(end, 4)
        normalized.append(item)
        prev_end = item["end"]
    return normalized


def _normalize_asr_result(result: dict) -> dict:
    """Normalize ASR result timestamps so downstream sentence splitting has a stable source of truth."""
    if not result:
        return {"segments": [], "language": "auto"}

    segments = result.get("segments", []) or []
    normalized_segments: List[dict] = []
    prev_end = 0.0
    valid_segment_durations = []
    for seg in segments:
        start = seg.get("start")
        end = seg.get("end")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end > start:
            valid_segment_durations.append(float(end) - float(start))
    fallback_seg_duration = median(valid_segment_durations) if valid_segment_durations else 1.2

    for idx, seg in enumerate(segments, start=1):
        item = dict(seg)
        words = item.get("words", []) or []

        try:
            seg_start = float(item.get("start", 0))
        except (TypeError, ValueError):
            seg_start = prev_end
        try:
            seg_end = float(item.get("end", 0))
        except (TypeError, ValueError):
            seg_end = seg_start + fallback_seg_duration

        seg_start = max(seg_start, prev_end)
        if seg_end <= seg_start:
            seg_end = seg_start + fallback_seg_duration

        normalized_words = _normalize_segment_words(words, seg_start, seg_end)
        if normalized_words:
            first_word_start = normalized_words[0]["start"]
            last_word_end = normalized_words[-1]["end"]
            seg_start = max(seg_start, first_word_start)
            seg_end = max(last_word_end, seg_start + 0.06)

        item["id"] = idx
        item["start"] = round(seg_start, 4)
        item["end"] = round(seg_end, 4)
        item["words"] = normalized_words
        normalized_segments.append(item)
        prev_end = item["end"]

    result["segments"] = normalized_segments
    return result


# ---------------------------------------------------------------------------
# Config loaders
# ---------------------------------------------------------------------------

def _resolve_input_language(task_dir: str) -> str:
    """从任务 workflow.json 的 input 节点解析源语言；未设置时返回 auto。"""
    wf_path = os.path.join(task_dir, "workflow.json")
    if not os.path.exists(wf_path):
        return "auto"
    try:
        with open(wf_path, "r", encoding="utf-8") as f:
            wf = json.load(f)
    except Exception:
        return "auto"
    for node in wf.get("nodes", []):
        if node.get("data", {}).get("nodeType") == "input":
            src_lang = node.get("data", {}).get("config", {}).get("source_language", "auto")
            if src_lang and src_lang != "auto":
                print(f"[ASR] Resolved language from input node: {src_lang}")
                return src_lang
            return "auto"
    return "auto"


def _load_task_node_config(task_dir: str, node_type: str = "asr") -> Dict[str, Any]:
    """Load the ASR node's config from the task's workflow.json."""
    wf_path = os.path.join(task_dir, "workflow.json")
    if not os.path.exists(wf_path):
        return {}
    try:
        with open(wf_path, "r", encoding="utf-8") as f:
            wf = json.load(f)
    except Exception:
        return {}
    asr_cfg = {}
    for node in wf.get("nodes", []):
        if node.get("data", {}).get("nodeType") == node_type:
            asr_cfg = node.get("data", {}).get("config", {}) or {}
            break
    # Resolve language: if "from_input" or not set, read from input node
    lang = asr_cfg.get("language")
    if lang == "from_input" or not lang:
        asr_cfg["language"] = _resolve_input_language(task_dir)
    return asr_cfg


def _load_default_interface_config(engine_id: str) -> Dict[str, Any]:
    """Load the default config for a given ASR interface from asr_interfaces.json."""
    iface_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config", "asr_interfaces.json",
    )
    if not os.path.exists(iface_path):
        return {}
    try:
        with open(iface_path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        return {}
    for iface in data.get("interfaces", []):
        if iface.get("id") == engine_id:
            return iface.get("config", {})
    return {}


def _resolve_engine_id(task_cfg: Dict[str, Any]) -> str:
    """Determine which ASR engine to use.

    Priority: task config 'engine' > fallback 'whisperx_local'.
    """
    engine = task_cfg.get("engine", "")
    if engine:
        return engine
    return _DEFAULT_ENGINE


def _merge_asr_params(task_cfg: Dict[str, Any], default_cfg: Dict[str, Any]) -> tuple:
    """Merge task-specific params over default interface config.

    Returns (merged_kwargs, engine_id).
    """
    merged: Dict[str, Any] = {}

    for key in _ASR_PARAM_KEYS:
        task_val = task_cfg.get(key)
        default_val = default_cfg.get(key)

        winner = None
        if task_val is not None and task_val != "":
            winner = task_val
        elif default_val is not None and default_val != "":
            winner = default_val

        if winner is not None:
            merged[key] = winner

    # Extract engine/routing param (not forwarded to engine)
    engine_id = merged.pop("engine", None) or merged.pop("interface_id", None)

    # batch_size=0 means "auto-detect" -> remove so engine uses None
    if merged.get("batch_size") in (0, "0", 0.0):
        merged.pop("batch_size", None)

    # Group vad_onset/vad_offset into vad_options dict
    vad_onset = merged.pop("vad_onset", None)
    vad_offset = merged.pop("vad_offset", None)
    if vad_onset is not None or vad_offset is not None:
        vad_opts = {}
        if vad_onset is not None:
            vad_opts["vad_onset"] = vad_onset
        if vad_offset is not None:
            vad_opts["vad_offset"] = vad_offset
        merged["vad_options"] = vad_opts

    # Group temperatures/initial_prompt into asr_options dict
    temps = merged.pop("temperatures", None)
    prompt = merged.pop("initial_prompt", None)
    if temps is not None or prompt is not None:
        asr_opts = {}
        if temps is not None:
            asr_opts["temperatures"] = temps
        if prompt is not None:
            asr_opts["initial_prompt"] = prompt
        merged["asr_options"] = asr_opts

    # Convert booleans
    for bkey in ("word_timestamps", "diarize", "use_itn", "sentence_timestamp", "hotwords_enabled"):
        if bkey in merged:
            merged[bkey] = bool(merged[bkey])

    # Convert numeric strings
    for nkey in ("num_speakers", "min_speakers", "max_speakers", "batch_size",
                 "vad_max_segment_time", "max_concurrent", "timeout"):
        if nkey in merged:
            try:
                merged[nkey] = int(merged[nkey])
            except (ValueError, TypeError):
                pass

    # Only forward hotwords if hotwords_enabled is true
    hotwords_enabled = merged.pop("hotwords_enabled", False)
    if not hotwords_enabled:
        merged.pop("hotwords", None)

    return merged, engine_id


# ---------------------------------------------------------------------------
# Audio input resolution (shared by ASR / ASR-recognize / ASR-postprocess)
# ---------------------------------------------------------------------------

def resolve_asr_audio_inputs(task_dir: str, step_inputs: Dict[str, Any]) -> Dict[str, Any]:
    """解析 ASR / 后处理节点的音频输入。

    识别优先级：ASR音源 → 人声音源 → 视频 → 缓存回退。
    返回 dict：
      input_path         识别用音频/视频（无有效输入时抛 FileNotFoundError）
      asr_audio/vocal_audio  存在的原始输入路径（可能为 None）
      alignment_audio    显式指定的对齐音源（可能为 None）
      post_process_audio 后处理用音源（人声 > ASR > 识别音源）
    """
    asr_audio = step_inputs.get("asr_audio", "")
    vocal_audio = step_inputs.get("vocal_audio", "")
    input_video = step_inputs.get("video", "")

    # 对齐音频输入（可选，用于词级时间戳对齐）
    alignment_audio = step_inputs.get("alignment_audio", "")
    if alignment_audio and not os.path.isabs(alignment_audio):
        alignment_audio = os.path.join(task_dir, alignment_audio)
    alignment_audio = alignment_audio if alignment_audio and os.path.exists(alignment_audio) else None
    if alignment_audio:
        print(f"[ASR] Alignment audio provided: {alignment_audio}")

    # 解析为绝对路径
    if asr_audio and not os.path.isabs(asr_audio):
        asr_audio = os.path.join(task_dir, asr_audio)
    if vocal_audio and not os.path.isabs(vocal_audio):
        vocal_audio = os.path.join(task_dir, vocal_audio)
    if input_video and not os.path.isabs(input_video):
        input_video = os.path.join(task_dir, input_video)

    # 缓存路径（用于回退）
    cache_video = os.path.join(task_dir, "cache", "input_video.mp4")
    cache_audio = os.path.join(task_dir, "cache", "audio.wav")
    # 兼容 input 节点复制命名（input_audio.{ext}）与音频分离产物：扫描 cache 目录找音频文件
    if not os.path.exists(cache_audio) and os.path.isdir(os.path.join(task_dir, "cache")):
        for name in sorted(os.listdir(os.path.join(task_dir, "cache"))):
            if name.startswith("input_audio") or name.endswith((".wav", ".mp3", ".flac", ".m4a")):
                cache_audio = os.path.join(task_dir, "cache", name)
                break

    vocal_path = vocal_audio if vocal_audio and os.path.exists(vocal_audio) else None
    asr_path = asr_audio if asr_audio and os.path.exists(asr_audio) else None

    # ASR识别优先级：ASR音源 → 人声音源 → 视频 → 缓存
    input_path = None
    if asr_path:
        input_path = asr_path
        print(f"[ASR] Using ASR audio: {input_path}")
    elif vocal_path:
        input_path = vocal_path
        print(f"[ASR] Using vocal audio (fallback): {input_path}")
    elif input_video and os.path.exists(input_video):
        input_path = input_video
        print(f"[ASR] Using upstream video: {input_path}")
    else:
        # 回退：检查 cache 默认路径（ASR 直接从 input 节点接收视频的场景）
        if os.path.exists(cache_audio):
            input_path = cache_audio
            print(f"[ASR] Fallback to cache audio: {input_path}")
        elif os.path.exists(cache_video):
            input_path = cache_video
            print(f"[ASR] Fallback to cache video: {input_path}")

    if not input_path:
        raise FileNotFoundError(
            f"ASR 输入文件不存在。"
            f"上游连线: asr_audio='{asr_audio}', vocal_audio='{vocal_audio}', video='{input_video}'。"
            f"请检查上游连线是否正确连接，或确认缓存目录中有输入文件。"
        )

    # 确定后处理使用的音频路径（优先人声音源，其次ASR音源）
    # VAD、词级对齐、说话人识别使用更纯净的人声音源
    if vocal_path:
        post_process_audio = vocal_path
        print(f"[ASR] Post-processing will use vocal audio: {vocal_path}")
    elif asr_path:
        post_process_audio = asr_path
        print(f"[ASR] Post-processing will use ASR audio: {asr_path}")
    else:
        post_process_audio = input_path
        print(f"[ASR] Post-processing will use input audio: {input_path}")

    return {
        "input_path": input_path,
        "asr_audio": asr_path,
        "vocal_audio": vocal_path,
        "alignment_audio": alignment_audio,
        "post_process_audio": post_process_audio,
    }


# ---------------------------------------------------------------------------
# ASR Step
# ---------------------------------------------------------------------------

class S02ASR(BaseStep):
    """ASR step with automatic audio splitting for long files."""

    # 对应 builtin_node_types 中的节点类型（子类可覆写）
    _node_type = "asr"

    def __init__(self):
        pass

    def _load_node_config(self, task_dir: str) -> Dict[str, Any]:
        """加载本节点配置：优先运行时注入的 _node_config，回退扫描 workflow.json。

        语言解析规则与 _load_task_node_config 保持一致（from_input → 输入节点语言）。
        """
        injected = getattr(self, "_node_config", None)
        if injected:
            cfg = dict(injected)
            lang = cfg.get("language")
            if lang == "from_input" or not lang:
                cfg["language"] = _resolve_input_language(task_dir)
            return cfg
        return _load_task_node_config(task_dir, getattr(self, "_node_type", "asr"))

    def check_artifact(self, task_dir: str) -> bool:
        return find_artifact(os.path.join(task_dir, "cache"), "asr_result.json") is not None

    def validate_inputs(self, task_dir: str) -> bool:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        # 优先检查上游连线传入的音频/视频路径
        for key in ("asr_audio", "vocal_audio", "video"):
            val = step_inputs.get(key, "")
            if val:
                p = val if os.path.isabs(val) else os.path.join(task_dir, val)
                if os.path.exists(p):
                    return True
        # 回退到缓存默认路径（扫描 input_audio* 或音频扩展名，兼容 input 节点复制命名）
        video = os.path.exists(os.path.join(task_dir, "cache", "input_video.mp4"))
        audio = os.path.exists(os.path.join(task_dir, "cache", "audio.wav"))
        if not audio and os.path.isdir(os.path.join(task_dir, "cache")):
            audio = any(
                name.startswith("input_audio") or name.endswith((".wav", ".mp3", ".flac", ".m4a"))
                for name in os.listdir(os.path.join(task_dir, "cache"))
            )
        return video or audio

    def _extract_audio(self, video_path: str, audio_path: str,
                       callback: Optional[Callable] = None):
        if callback:
            callback(10, "Extracting audio from video...")
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            audio_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise Exception(f"Audio extraction failed: {result.stderr[:200]}")
        if callback:
            callback(20, "Audio extracted")

    @staticmethod
    def _get_video_duration(video_path: str) -> float:
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return float(result.stdout.strip())
        except Exception:
            return 60.0

    # ── real ASR call ─────────────────────────────────────────────────

    def _run_real_asr(self, input_path: str, output_path: str,
                      callback: Optional[Callable] = None,
                      cancel_callback: Optional[Callable] = None) -> Optional[dict]:
        """Resolve params, split audio if needed, transcribe, merge."""

        task_dir = getattr(self, "_task_dir", "") or os.path.dirname(output_path)

        # 1) Load task-specific node config (injected _node_config > workflow.json)
        task_cfg = self._load_node_config(task_dir)

        # 2) Determine which engine to use (task > default)
        engine_id = _resolve_engine_id(task_cfg)

        # 3) Load global default config from asr_interfaces.json
        default_cfg = _load_default_interface_config(engine_id)

        # 4) Merge: task params override defaults
        merged_params, engine_id = _merge_asr_params(task_cfg, default_cfg)

        # 5) Read max_duration from default config (task can override)
        max_duration = 0
        if "max_duration" in merged_params:
            max_duration = int(merged_params.pop("max_duration", 0))
        elif "max_duration" in default_cfg:
            max_duration = int(default_cfg.get("max_duration", 0))

        print(f"[ASR] engine={engine_id}, max_duration={max_duration}s, params={merged_params}")

        # 6) Get audio duration and decide whether to split
        audio_duration = _get_audio_duration(input_path)
        print(f"[ASR] Audio duration: {audio_duration:.1f}s")

        needs_split = max_duration > 0 and audio_duration > max_duration

        if not needs_split:
            # --- Single-shot transcription ---
            result = self._transcribe_single(
                input_path, output_path, engine_id, merged_params, callback,
                time_offset=0.0, progress_base=30, progress_range=60,
                cancel_callback=cancel_callback,
            )
        else:
            # --- Split and transcribe ---
            result = self._transcribe_split(
                input_path, output_path, audio_duration,
                max_duration, engine_id, merged_params, callback,
                cancel_callback=cancel_callback,
            )

        # 7) Apply post-processing if configured
        if cancel_callback and cancel_callback():
            from backend.control_plane.runtime import TaskCancelledError
            raise TaskCancelledError("Cancelled by user")
        result = self._apply_post_processing(result, input_path, engine_id, callback, cancel_callback)

        return result

    def _transcribe_single(self, input_path, output_path, engine_id,
                           params, callback, *,
                           time_offset=0.0, progress_base=30,
                           progress_range=60,
                           cancel_callback=None) -> dict:
        """Transcribe a single audio file (no splitting)."""
        if cancel_callback and cancel_callback():
            from backend.control_plane.runtime import TaskCancelledError
            raise TaskCancelledError("Cancelled by user")
        from backend.asr.asr_factory import run_asr

        def progress_cb(pct, msg):
            if callback:
                callback(progress_base + int(pct * progress_range / 100), msg)

        result = run_asr(
            input_path=input_path,
            output_path=output_path,
            callback=progress_cb,
            engine_name=engine_id,
            **params,
        )

        # Save raw engine output for debugging
        self._save_raw_output(output_path, engine_id, result)

        if time_offset > 0.0:
            result = _adjust_timestamps(result, time_offset)

        return _normalize_asr_result(result)

    @staticmethod
    def _save_raw_output(output_path: str, engine_id: str, result: dict):
        """Save raw engine output alongside the final result for debugging."""
        try:
            base_dir = os.path.dirname(output_path) or "."
            raw_path = os.path.join(base_dir, f"asr_raw_{engine_id}.json")
            os.makedirs(base_dir, exist_ok=True)
            with open(raw_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"[ASR] Raw output saved: {raw_path}")
        except Exception as e:
            print(f"[ASR] Warning: failed to save raw output: {e}")

    def _transcribe_split(self, input_path, output_path, audio_duration,
                          max_duration, engine_id, params, callback,
                          cancel_callback=None) -> dict:
        """Split audio at silence boundaries, transcribe each segment, merge."""
        silence_win = min(60.0, max_duration * 0.3)

        if callback:
            callback(5, f"Splitting audio ({audio_duration:.0f}s) into <= {max_duration}s segments...")

        segments = split_audio_at_silence(input_path, max_duration, silence_win)
        print(f"[ASR] Audio split into {len(segments)} segments: {segments}")

        if callback:
            callback(10, f"Audio split into {len(segments)} segments")

        # Create temp dir for segment files
        tmp_dir = tempfile.mkdtemp(prefix="asr_split_")
        all_results: List[dict] = []

        try:
            for seg_idx, (start, end) in enumerate(segments):
                # Cancel check between segments
                if cancel_callback and cancel_callback():
                    from backend.control_plane.runtime import TaskCancelledError
                    raise TaskCancelledError("Cancelled by user")

                seg_dur = end - start
                print(f"[ASR] Segment {seg_idx+1}/{len(segments)}: {start:.1f}s - {end:.1f}s ({seg_dur:.1f}s)")

                if callback:
                    seg_pct_base = 10 + int(80 * seg_idx / len(segments))
                    seg_pct_range = int(80 / len(segments))
                    callback(seg_pct_base, f"Transcribing segment {seg_idx+1}/{len(segments)} ({start:.1f}s-{end:.1f}s)")

                # Cut segment audio
                seg_path = os.path.join(tmp_dir, f"seg_{seg_idx:04d}.wav")
                _split_audio_file(input_path, start, end, seg_path)

                # Transcribe segment
                from backend.asr.asr_factory import run_asr

                seg_output = os.path.join(tmp_dir, f"result_{seg_idx:04d}.json")

                def seg_progress_cb(pct, msg, _idx=seg_idx, _base=seg_pct_base, _range=seg_pct_range):
                    if callback:
                        callback(_base + int(pct * _range / 100), msg)

                result = run_asr(
                    input_path=seg_path,
                    output_path=seg_output,
                    callback=seg_progress_cb,
                    engine_name=engine_id,
                    **params,
                )

                # Adjust timestamps by segment offset
                _adjust_timestamps(result, start)
                all_results.append(result)

                # Clean up segment audio
                if os.path.exists(seg_path):
                    os.remove(seg_path)

                # Free GPU memory between segments (prevent OOM on long audio)
                gc.collect()
                try:
                    import torch as _torch
                    if _torch.cuda.is_available():
                        _torch.cuda.empty_cache()
                except ImportError:
                    pass

            # Merge all results
            if callback:
                callback(90, "Merging transcription results...")

            merged = _normalize_asr_result(_merge_results(all_results))

            # Save merged result
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)

            return merged

        finally:
            # Clean up temp dir
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    # ── post-processing ──────────────────────────────────────────────

    def _apply_post_processing(self, result: dict, audio_path: str, engine_id: str, callback=None, cancel_callback=None) -> dict:
        """Apply post-processing (VAD, alignment, diarization) based on settings and interface capabilities."""
        from backend.config.config_manager import config
        from backend.asr.asr_interface_manager import ASRInterfaceManager

        # 1. Load interface capabilities
        manager = ASRInterfaceManager()
        iface = manager.get(engine_id) or {}
        capabilities = iface.get("capabilities", {})
        print(f"[ASR PostProcess] engine={engine_id}, capabilities={capabilities}")

        # 2. Load global post-processing settings
        # Support both boolean true and string "true"
        vad_enabled_raw = config.get("asr.post_process.vad.enabled", False)
        vad_enabled = vad_enabled_raw is True or str(vad_enabled_raw).lower() == "true"
        vad_engine = config.get("asr.post_process.vad.engine", "fsmn")

        alignment_enabled_raw = config.get("asr.post_process.alignment.enabled", False)
        alignment_enabled = alignment_enabled_raw is True or str(alignment_enabled_raw).lower() == "true"
        alignment_engine = config.get("asr.post_process.alignment.engine", "whisperx")

        diarization_enabled_raw = config.get("asr.post_process.diarization.enabled", False)
        diarization_enabled = diarization_enabled_raw is True or str(diarization_enabled_raw).lower() == "true"
        diarization_engine = config.get("asr.post_process.diarization.engine", "pyannote")

        # 2.1 节点级后处理勾选：复选框直接决定执行哪些阶段，不勾选的不执行；
        # 各阶段处理引擎均读取全局设置（ASR 引擎不具备该能力时由全局引擎补执行）。
        # 旧配置兼容：post_process_mode="global" 的历史节点仍完全沿用全局开关；
        # 复选框键缺失时也回退到对应的全局启用开关。
        node_cfg = self._load_node_config(getattr(self, "_task_dir", "") or "")
        pp_mode = str(node_cfg.get("post_process_mode", "") or "")
        if pp_mode != "global":
            def _flag(key, fallback):
                v = node_cfg.get(key)
                if v is None:
                    return fallback
                return v is True or str(v).lower() == "true"
            vad_enabled = _flag("post_vad", vad_enabled)
            alignment_enabled = _flag("post_alignment", alignment_enabled)
            diarization_enabled = _flag("post_diarization", diarization_enabled)
            print(f"[ASR PostProcess] node checkboxes: vad={vad_enabled}, alignment={alignment_enabled}, diarization={diarization_enabled}")
        else:
            print("[ASR PostProcess] legacy global mode: following global post-process switches")

        print(f"[ASR PostProcess] vad_enabled={vad_enabled}, vad_engine={vad_engine}")
        print(f"[ASR PostProcess] alignment_enabled={alignment_enabled}, alignment_engine={alignment_engine}")
        print(f"[ASR PostProcess] diarization_enabled={diarization_enabled}, diarization_engine={diarization_engine}")

        # 3. Determine which post-processing to apply
        # Check both interface capabilities AND internal execution flags
        # Some engines (Whisper, FunASR) execute VAD/alignment/diarization internally
        vad_internally_executed = result.get("_vad_internally_executed", False)
        alignment_internally_executed = result.get("_alignment_internally_executed", False)
        diarization_internally_executed = result.get("_diarization_internally_executed", False)

        apply_vad = vad_enabled and not capabilities.get("vad", False) and not vad_internally_executed
        apply_alignment = alignment_enabled and not capabilities.get("word_timestamps", False) and not alignment_internally_executed
        apply_diarization = diarization_enabled and not capabilities.get("speaker_diarization", False) and not diarization_internally_executed

        if vad_internally_executed:
            print("[ASR PostProcess] VAD was executed internally by ASR engine, skipping")
        if alignment_internally_executed:
            print("[ASR PostProcess] Alignment was executed internally by ASR engine, skipping")
        if diarization_internally_executed:
            print("[ASR PostProcess] Diarization was executed internally by ASR engine, skipping")

        print(f"[ASR PostProcess] apply_vad={apply_vad}, apply_alignment={apply_alignment}, apply_diarization={apply_diarization}")

        if not (apply_vad or apply_alignment or apply_diarization):
            print("[ASR PostProcess] No post-processing needed, returning original result")
            return result

        # 4. Cancel check before starting post-processing
        if cancel_callback and cancel_callback():
            from backend.control_plane.runtime import TaskCancelledError
            raise TaskCancelledError("Cancelled by user")

        # 5. Apply post-processing
        print("[ASR PostProcess] Starting post-processing...")
        if callback:
            callback(92, "Applying post-processing...")

        from backend.asr.asr_factory import apply_post_processing

        # 6. Determine language for post-processing
        # Priority: ASR result language > task input node language > "auto"
        language = result.get("language", "")
        if not language or language == "auto":
            # Try to get language from task config (input node)
            task_dir = getattr(self, "_task_dir", "")
            if task_dir:
                task_cfg = self._load_node_config(task_dir)
                input_lang = task_cfg.get("language", "")
                if input_lang and input_lang != "auto":
                    language = input_lang
                    print(f"[ASR PostProcess] Using language from input node: {language}")
        
        if not language or language == "auto":
            language = "auto"
            print(f"[ASR PostProcess] Warning: language is auto, alignment may not work correctly")
        
        print(f"[ASR PostProcess] Language for post-processing: {language}")

        # 7. Determine audio path for post-processing
        # Priority: alignment_audio (explicit) > vocal_audio > asr_audio > input audio
        alignment_audio_path = getattr(self, "_alignment_audio_path", None)
        post_process_audio = getattr(self, "_post_process_audio_path", audio_path)
        
        if alignment_audio_path:
            print(f"[ASR PostProcess] Using explicit alignment audio: {alignment_audio_path}")
        
        print(f"[ASR PostProcess] Using audio for VAD/diarization: {post_process_audio}")

        try:
            result = apply_post_processing(
                asr_result=result,
                audio_path=post_process_audio,
                callback=callback,
                language=language,
                vad_engine=vad_engine if apply_vad else None,
                alignment_engine=alignment_engine if apply_alignment else None,
                diarize_engine=diarization_engine if apply_diarization else None,
                alignment_audio_path=alignment_audio_path,
            )
            print(f"[ASR PostProcess] Post-processing complete, segments={len(result.get('segments', []))}")
        except Exception as e:
            print(f"[ASR PostProcess] Error during post-processing: {e}")
            # Return original result if post-processing fails

        return result

    def _finalize_recognition(self, result: dict, input_path: str) -> dict:
        """识别结果收尾：规范化时间戳并钳制到音源实际时长（子类可覆写）。

        将时间戳钳制到音源实际时长：后处理（VAD/对齐）可能产出越界、零时长或
        对齐失败后的伪造均匀间隔时间戳，若不钳制会流入断句与配音阶段，
        导致视频变速目标超出媒体末尾与时间轴漂移累积。
        """
        result = _normalize_asr_result(result)
        audio_duration = _get_audio_duration(input_path)
        if audio_duration > 0:
            result = _clamp_result_to_duration(result, audio_duration)
        return result

    # ── main entry ────────────────────────────────────────────────────

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        if callback:
            callback(5, "Initializing ASR...")

        self._task_dir = task_dir
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        print(f"[ASR] step_inputs keys: {list(step_inputs.keys())}, values: {step_inputs}")

        audio_io = resolve_asr_audio_inputs(task_dir, step_inputs)
        input_path = audio_io["input_path"]
        self._asr_audio_path = audio_io["asr_audio"]
        self._vocal_audio_path = audio_io["vocal_audio"]
        self._alignment_audio_path = audio_io["alignment_audio"]
        self._post_process_audio_path = audio_io["post_process_audio"]

        node_suffix = f"_{self._node_id}" if self._node_id else ""
        output_path = os.path.join(task_dir, "cache", f"asr_result{node_suffix}.json")

        result = self._finalize_recognition(
            self._run_real_asr(input_path, output_path, callback, cancel_callback),
            input_path,
        )

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        seg_count = len(result.get("segments", []))
        if callback:
            callback(100, f"ASR completed: {seg_count} segments")
        return {
            "artifacts": [f"cache/asr_result{node_suffix}.json"],
            "outputs": {
                "subtitle": f"cache/asr_result{node_suffix}.json",
            },
        }
