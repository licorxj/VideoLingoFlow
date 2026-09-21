"""Audio splitting utilities for chunked ASR inference.

集中存放"按时长安全切分音频 + 按段偏移时间戳 + 重组装结果"的通用逻辑，
供 ``asr_factory.run_asr``（集中处理切分）与 ``steps/s02_asr.py`` 共用，
避免重复实现与层间循环依赖。

切分策略参考原始项目 ``core/all_whisper_methods/audio_preprocess.py``：
沿 ``max_duration`` 步进，在每个分段末端的静音窗口内寻找静音边界安全下刀，
找不到静音才退回到硬边界。
"""

import os
import re
import json
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple


def get_audio_duration(audio_path: str) -> float:
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

    Returns a list of **absolute** timestamps (in seconds) where silence ends.

    关键：`-ss` / `-to` 必须作为**输入侧**选项写在 `-i` 之前。
    若写成输出侧选项（`-i file -ss X -to Y`），ffmpeg 会先把输出时间轴平移
    到 0 再送进滤镜链，silencedetect 报告的是**相对于 -ss 起点**的时间
    （实测：同一段音频在同一窗口 [10,50] 上，输入侧写法报 `10 / 40`，
    输出侧写法报 `20 / 50.15`）。调用方按绝对秒使用这些值的结果是：
    窗口判定必然失败，算法静默退化成按 max_duration 硬切，把句子从中间劈开。
    """
    from backend.utils.ffmpeg_guard import apply_resource_args
    cmd = apply_resource_args([
        "ffmpeg", "-hide_banner",
        "-ss", str(start), "-to", str(end),
        "-i", audio_path,
        "-af", f"silencedetect=n={threshold_db}dB:d={min_duration}",
        "-f", "null", "-",
    ], mux_queue=64)
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

    # 兜底：个别 ffmpeg 构建即便用输入侧 seek 仍可能把时间轴平移到 0，
    # 表现为所有返回值都早于窗口起点，此时按相对值换算回绝对秒。
    if silence_ends and max(silence_ends) < start:
        silence_ends = [t + start for t in silence_ends]

    # 只保留落在检测窗口内的结果，避免误读到窗口外的静音点
    return [t for t in silence_ends if start <= t <= end]


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
    duration = get_audio_duration(audio_path)
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
            # 在检测窗口内取最贴近理想切点的静音边界：过早下刀会让段数膨胀、
            # 过晚会超过 max_duration；两者都不如"最接近"稳妥。
            ideal_cut = pos + max_duration
            candidates = [t for t in silence_points if win_start <= t <= win_end]
            split_at = min(candidates, key=lambda t: abs(t - ideal_cut)) if candidates else None

            # split_at 必须严格推进，否则可能落入死循环
            if split_at is not None and split_at > pos:
                segments.append((pos, split_at))
                pos = split_at
                continue

        # No good silence point found: cut at exact boundary
        segments.append((pos, pos + max_duration))
        pos += max_duration

    return segments


def cut_audio_segment(audio_path: str, start: float, end: float,
                      output_path: str) -> str:
    """按精确时间窗切出音频段（输入侧 seek + 重编码，边界不浮动）。

    关键：**不用** ``-c copy``。copy 模式只能从包/关键帧边界下刀，实际起点会
    被拉到窗口之前（aac/opus/mp3 尤其明显），相邻两段因此出现重叠音频，
    重叠区被两个 chunk 各识别一次 → 拼接处出现重复词句。这里统一走
    "输入侧 -ss（accurate_seek）+ 重编码 PCM"，起点固定在 start、长度固定为
    end-start，相邻段严格首尾相接；重编码到 16k 单声道也正是 ASR 的输入口径。
    """
    from backend.utils.ffmpeg_guard import apply_resource_args
    duration = max(0.0, float(end) - float(start))
    cmd = apply_resource_args([
        "ffmpeg", "-y", "-hide_banner",
        "-ss", f"{float(start):.6f}",
        "-i", audio_path,
        "-t", f"{duration:.6f}",
        "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        "-avoid_negative_ts", "make_zero",
        output_path,
    ], mux_queue=64)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        # 极少数容器无法重编码时，退回 copy 快速路径（边界可能有包级抖动）
        print(f"[ASR] 精确切分失败，回退 copy 模式: {result.stderr[:200]}", flush=True)
        cmd = apply_resource_args([
            "ffmpeg", "-y", "-i", audio_path,
            "-ss", str(start), "-to", str(end),
            "-c", "copy",
            output_path,
        ], mux_queue=64)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to split audio: {result.stderr[:300]}")
    return output_path


def adjust_timestamps(result: dict, time_offset: float) -> dict:
    """Offset all timestamps in an ASR result by time_offset seconds."""
    if not result:
        return result

    for seg in result.get("segments", []):
        if "start" in seg:
            seg["start"] = round(seg["start"] + time_offset, 4)
        if "end" in seg:
            seg["end"] = round(seg["end"] + time_offset, 4)
        for word in seg.get("words", []) or []:
            if "start" in word:
                word["start"] = round(word["start"] + time_offset, 4)
            if "end" in word:
                word["end"] = round(word["end"] + time_offset, 4)

    return result


def _strip_overlap_prefix(prev: Dict, nxt: Dict) -> int:
    """去掉 ``nxt`` 中与 ``prev`` 结尾重复的前缀，返回去掉的词数。"""
    pt = _tokens_of_text(prev.get("text"))
    nt = _tokens_of_text(nxt.get("text"))
    if not pt or not nt:
        return 0
    n = 0
    for k in range(min(len(pt), len(nt), 12), 0, -1):
        if pt[-k:] == nt[:k]:
            n = k
            break
    if not n:
        return 0

    if n >= len(nt):
        # 整段都是上一 chunk 的尾巴：整段丢弃
        nxt["text"] = ""
        nxt["words"] = []
        return n

    words = nxt.get("words") or []
    if words and len(words) >= n:
        kept = words[n:]
        nxt["words"] = kept
        nxt["start"] = round(
            _to_float(kept[0].get("start"), _to_float(nxt.get("start"))), 4)
    else:
        duration = max(0.0, _to_float(nxt.get("end")) - _to_float(nxt.get("start")))
        nxt["start"] = round(
            _to_float(nxt.get("start")) + duration * n / max(len(nt), 1), 4)
        nxt["words"] = synthesize_words(
            _join_words(nt[n:]), nxt["start"], nxt["end"])
    nxt["text"] = _join_words(nt[n:])
    return n


def _dedupe_chunk_boundaries(segments: List[dict], chunk_of: List[int]) -> List[dict]:
    """仅在"跨 chunk 接缝"处消除重复前缀。

    chunk 内部的相邻段由模型自己的断句给出，不做任何改动，避免误删
    正常的重复表达（口吃、叠词、强调句）。
    """
    out: List[dict] = []
    for i, seg in enumerate(segments):
        if out and i > 0 and chunk_of[i] != chunk_of[i - 1] and isinstance(seg, dict):
            removed = _strip_overlap_prefix(out[-1], seg)
            if removed:
                print(
                    f"[ASR] chunk 接缝去重: 去掉重复前缀 {removed} 词 -> "
                    f"{seg.get('text', '')[:40]!r}",
                    flush=True,
                )
        if isinstance(seg, dict) and not (seg.get("text") or "").strip():
            continue
        out.append(seg)
    return out


def merge_results(results: List[dict]) -> dict:
    """Merge multiple ASR results from sequential audio segments.

    组合各分段 segments、去重说话人、重排 segment id，并保留引擎内部
    执行标志（各分段由同一引擎转录时全部分段都带标志才保留，避免长音频
    合并后丢失标志导致下游重复执行 VAD/对齐/说话人识别）。
    """
    if not results:
        return {"segments": [], "language": "auto"}

    merged_segments: List[dict] = []
    chunk_of: List[int] = []
    all_speakers: set = set()
    detected_language = "auto"

    for r in results:
        lang = r.get("language", "auto")
        if lang and lang != "auto":
            detected_language = lang
            break

    for chunk_idx, r in enumerate(results):
        # Collect speakers (supports both list and dict forms)
        spk = r.get("speakers")
        if isinstance(spk, dict):
            all_speakers.update(spk.keys())
        elif isinstance(spk, (list, tuple, set)):
            all_speakers.update(spk)

        for seg in r.get("segments", []):
            merged_segments.append(seg)
            chunk_of.append(chunk_idx)

    # 接缝去重：即便切分已经精确到采样点，模型在窗口边缘仍可能把上一个
    # chunk 的尾句（或尾词）再识别一遍，表现为接缝处重复一两个词/一句。
    merged_segments = _dedupe_chunk_boundaries(merged_segments, chunk_of)

    # Re-number segment IDs
    for idx, seg in enumerate(merged_segments, start=1):
        seg["id"] = idx

    output: Dict[str, any] = {
        "language": detected_language,
        "segments": merged_segments,
    }

    # Include full text if present
    full_text = " ".join(
        seg.get("text", "") for seg in merged_segments if seg.get("text")
    )
    if full_text:
        output["text"] = full_text.strip()

    if all_speakers:
        output["speakers"] = sorted(all_speakers)

    # 保留引擎内部执行标志
    for flag in ("_vad_internally_executed", "_alignment_internally_executed",
                 "_diarization_internally_executed"):
        if all(r.get(flag) for r in results):
            output[flag] = True

    return output


# ---------------------------------------------------------------------------
# 断句健康检查：多段拼装后的最后一道防线
#
# 端到端引擎（MOSS / WhisperX / FunASR）会声明 `_vad_internally_executed`，
# 下游据此跳过 VAD 后处理。若某个 chunk 退化成 `[t][Sxx]整段文本[t]` 一条
# 巨 segment，merge 阶段不会报错，但句子切分/翻译/TTS 时间轴全线崩塌，
# 且因为那个"内部已完成 VAD"的标志，下游不会再补断句。这里统一兜底。
# ---------------------------------------------------------------------------

# 用于把未断句的巨段二次切开的句末标点（含 ASCII 句点，英文主要靠它断句）
_SENTENCE_END_CHARS = "。！？!?；;…"
_PERIOD_CHARS = ".．。"

# 常见缩写中的句点不是句子边界（Mr. / Dr. / etc.）
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "st", "jr", "sr", "prof", "vs", "etc",
    "eg", "ie", "fig", "no", "sec", "min", "approx", "dept",
}


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


_NON_WORD_RE = re.compile(r"[^\w\u4e00-\u9fff]", re.UNICODE)


def _norm_text(text: str) -> str:
    """归一化文本：去掉空白与标点，用于"文本是否与词序列一致"的比较。

    只比字/词，不比标点：对齐器返回的 word token 常常不含标点，若把标点差异
    也算作不一致，会误触发按文本重合成、白白丢掉真实的词级时间戳。
    """
    return _NON_WORD_RE.sub("", text or "")


def _is_sentence_break(text: str, idx: int) -> bool:
    """判断 ``text[idx]`` 是否可以作为句子边界。

    中文/全角标点一律视为边界；ASCII 句点存在歧义（小数、缩写、文件名、
    邮箱），只在"后面不是字母数字"且不是上述例外时才断句。
    """
    ch = text[idx]
    if ch in _SENTENCE_END_CHARS:
        return True
    if ch not in _PERIOD_CHARS:
        return False

    prev = text[idx - 1] if idx > 0 else ""
    nxt = text[idx + 1] if idx + 1 < len(text) else ""
    # 小数点 / 版本号：两侧都是数字或点，不切（3.14、v1.2.3）
    if prev.isdigit() and nxt.isdigit():
        return False
    # 后紧跟字母数字时不切（file.mp3、u.s.a、info@example.com）
    if nxt and (nxt.isalnum() or nxt == "_"):
        return False
    # 缩写词尾的句点不切（Mr. / Dr. / etc.）
    j = idx - 1
    tail = []
    while j >= 0 and text[j].isalpha():
        tail.append(text[j])
        j -= 1
    if tail and "".join(reversed(tail)).lower() in _ABBREVIATIONS:
        return False
    return True


def synthesize_words(text: str, start: float, end: float) -> List[Dict]:
    """在 [start, end] 内按字/词线性插值合成 word 级时间戳。

    只提供段级时间戳的引擎（MOSS 等）用它补齐 words，供下游句子切分与
    TTS 时间轴使用；中文按字切分，其余按空白边界切分。
    """
    text = (text or "").strip()
    if not text:
        return []

    tokens: List[str] = []
    buf = ""
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(ch)
        elif ch.isspace():
            if buf:
                tokens.append(buf)
                buf = ""
        else:
            buf += ch
    if buf:
        tokens.append(buf)
    tokens = [t for t in tokens if t.strip()]
    if not tokens:
        return []

    start = _to_float(start)
    end = _to_float(end)
    dur = max(0.0, end - start)
    n = len(tokens)
    words: List[Dict] = []
    for i, tok in enumerate(tokens):
        words.append({
            "word": tok,
            "start": round(start + dur * i / n, 4),
            "end": round(start + dur * (i + 1) / n, 4),
        })
    return words


def split_text_sentences(text: str, start: float, end: float,
                         max_chars: int = 40) -> List[Dict]:
    """按句末标点 / 字数上限把一段文本切成多句，并按字数比例分摊时间窗。

    优先在真正的句末标点处下刀（含 ASCII 句点，见 ``_is_sentence_break``）；
    没有句末标点而被 ``max_chars`` 触发时，尽量回退到最近的空白处切开，
    避免把英文单词从中间劈成两半。
    """
    text = (text or "").strip()
    if not text:
        return []

    pieces: List[str] = []
    buf = ""
    for i, ch in enumerate(text):
        if ch == "\n":
            if buf.strip():
                pieces.append(buf.strip())
            buf = ""
            continue
        buf += ch
        if len(buf) >= 4 and _is_sentence_break(text, i):
            pieces.append(buf.strip())
            buf = ""
        elif len(buf) >= max_chars:
            # 优先在最近的空白处断开（英文避免劈词；中文无空格则硬断）
            cut = max(buf.rfind(" "), buf.rfind("\u3000"))
            if cut >= max(1, max_chars // 2):
                pieces.append(buf[:cut].strip())
                buf = buf[cut:].lstrip()
            else:
                pieces.append(buf.strip())
                buf = ""
    if buf.strip():
        pieces.append(buf.strip())
    pieces = [p for p in pieces if p]
    if not pieces:
        return []

    _start, _end = _to_float(start), _to_float(end)
    dur = max(0.0, _end - _start)
    total = sum(len(p) for p in pieces) or 1

    out: List[Dict] = []
    cursor = _start
    for i, piece in enumerate(pieces):
        piece_end = _end if i == len(pieces) - 1 else cursor + dur * len(piece) / total
        out.append({
            "start": round(cursor, 4),
            "end": round(piece_end, 4),
            "text": piece,
        })
        cursor = piece_end
    return out


def _tokens_of_text(text: str) -> List[str]:
    """按空白/中日韩字符边界切词，用于跨段重复检测。"""
    text = (text or "").strip()
    if not text:
        return []
    tokens: List[str] = []
    buf = ""
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(ch)
        elif ch.isspace():
            if buf:
                tokens.append(buf)
                buf = ""
        else:
            buf += ch
    if buf:
        tokens.append(buf)
    return [t for t in tokens if t]


def _join_words(tokens: List[str]) -> str:
    """按语言拼接词序列：英文补空格，中日韩直接相连。"""
    out = ""
    for tok in tokens:
        tok = tok or ""
        if not tok:
            continue
        if not out:
            out = tok
            continue
        if out[-1].isascii() and tok[0].isascii():
            out += " " + tok
        else:
            out += tok
    return out


def _slice_words(words: List[Dict], start: float, end: float) -> List[Dict]:
    """按 [start, end) 半开区间切出词，保证每个词**只归属一个片段**。

    旧实现用 ``w.start < piece.end and w.end > piece.start`` 的双开区间判定：
    跨界的词（start < 切点 < end）会同时命中左右两片，被**复制进两段**，
    于是下一段的 words 多出上一段的尾词（text 却没有），下游以 words 为准
    重写 text 时就会看到"上下段重复词汇"。半开区间按词的 start 归属，
    既不重复也不丢失。
    """
    kept: List[Dict] = []
    for w in words or []:
        if not isinstance(w, dict):
            continue
        try:
            ws = float(w.get("start"))
        except (TypeError, ValueError):
            # 缺起点的词退化为按终点判定，同样只归属一片
            try:
                we = float(w.get("end"))
            except (TypeError, ValueError):
                continue
            if start <= we < end:
                kept.append(w)
            continue
        if start <= ws < end:
            kept.append(w)
    return kept


def split_long_segment(seg: Dict, max_chars: int = 40) -> List[Dict]:
    """对单条超长 segment 做二次断句；切不开时原样返回（列表长度恒为 1）。"""
    start = _to_float(seg.get("start"))
    end = _to_float(seg.get("end"))
    pieces = split_text_sentences(seg.get("text") or "", start, end, max_chars=max_chars)
    if len(pieces) <= 1:
        return [seg]

    orig_words = seg.get("words") or []
    out: List[Dict] = []
    for piece in pieces:
        new_seg = dict(seg)
        new_seg.update({
            "start": piece["start"],
            "end": piece["end"],
            "text": piece["text"],
        })
        # 父段已有词级时间戳时按新区间裁剪保留，否则按字数插值补齐
        kept = _slice_words(orig_words, piece["start"], piece["end"])
        # 一致性兜底：文本是被互斥切开的，词必须与之对应。裁剪结果一旦与
        # 本段文本对不上（旧数据、时间戳漂移、跨界重复等），直接按文本重合成，
        # 绝不让 words 与 text 出现"多词/少词"。
        if kept and _norm_text("".join(w.get("word", "") for w in kept)) != _norm_text(piece["text"]):
            kept = []
        new_seg["words"] = kept or synthesize_words(
            piece["text"], piece["start"], piece["end"])
        out.append(new_seg)
    return out


def enforce_segmentation_health(result: Dict, *, max_chars: int = 80,
                                max_duration: float = 60.0) -> Dict:
    """多段拼装后的 VAD 断句健康检查与兜底修正。

    处理策略：
      1. 超长（字数 >= max_chars）或超久（时长 >= max_duration）的段，
         按句末标点二次断句，时间窗按字数比例分摊，words 同步裁剪；
      2. 文本自身没有任何可切分位置、纯文本兜底救不回来时，判定引擎的
         "内部已完成 VAD"声明失实，撤销 ``_vad_internally_executed``，
         把断句交还给下游 VAD 后处理阶段（s02_asr / s_asr_stages）。
    """
    if not isinstance(result, dict):
        return result
    segments = result.get("segments")
    if not isinstance(segments, list) or not segments:
        return result

    offender_ids = set()
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        start = _to_float(seg.get("start"))
        end = _to_float(seg.get("end"))
        n_chars = len((seg.get("text") or "").strip())
        if n_chars >= max_chars or (end - start) >= max_duration:
            offender_ids.add(id(seg))

    if not offender_ids:
        return result

    new_segments: List[Dict] = []
    for seg in segments:
        pieces: Optional[List[Dict]] = None
        if isinstance(seg, dict) and id(seg) in offender_ids:
            candidate = split_long_segment(seg, max_chars=max_chars)
            if len(candidate) > 1:
                pieces = candidate
        if pieces:
            new_segments.extend(pieces)
        else:
            new_segments.append(seg)

    for idx, seg in enumerate(new_segments, start=1):
        if isinstance(seg, dict):
            seg["id"] = idx
    result["segments"] = new_segments

    # 复检：仍存在"巨段"才说明纯文本兜底救不回来（交还下游 VAD）。
    # 阈值放宽一倍字数上限：句末标点晚于硬切断出现时，片段可能略微超过
    # max_chars（如 80→90 字），这属于正常粒度，不应触发全链路 VAD。
    unresolved = sum(
        1 for seg in new_segments
        if isinstance(seg, dict)
        and (
            len((seg.get("text") or "").strip()) >= max_chars * 2
            or (_to_float(seg.get("end")) - _to_float(seg.get("start"))) >= max_duration
        )
    )

    full_text = " ".join(
        (seg.get("text") or "").strip()
        for seg in new_segments if isinstance(seg, dict)
    )
    if full_text.strip():
        result["text"] = full_text.strip()

    if unresolved:
        # 仅删除内部标志还不够：接口 capabilities.vad=true 同样会一票否决下游
        # VAD（s02_asr / s_asr_stages 均按"具备该能力即跳过"判定）。这里额外
        # 置 `_vad_required`，明确要求下游无论如何都要跑一遍 VAD 补断句。
        result.pop("_vad_internally_executed", None)
        result["_vad_required"] = True
        print(
            f"[ASR] Warning: {unresolved} unbreakable giant segment(s) "
            f"(>= {max_chars * 2} chars or >= {max_duration}s); internal VAD flag "
            f"revoked, downstream VAD will be executed",
            flush=True,
        )
    else:
        # 已经修干净：撤销上一轮可能留下的强制 VAD 标记，避免无谓的全链路补跑
        result.pop("_vad_required", None)
    return result
