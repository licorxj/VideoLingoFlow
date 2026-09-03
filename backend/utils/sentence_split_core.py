"""
sentence_split_core: Reusable functional helpers for sentence splitting.

These are pure / self-contained functions extracted from
``backend/steps/s03_sentence_split.py`` so the step file stays focused on
orchestration. They do not depend on the step instance (no ``self``); the step
re-binds them onto its class as staticmethods so existing ``self._xxx`` call
sites keep working unchanged.

Dependency on ``backend.utils.sentence_split_utils`` is preserved (e.g. for the
shared ``load_language_puncts`` / ``is_compact_spacing_language`` helpers).
"""

import os
import json
import re
from typing import List, Dict


# ── language / weight helpers ───────────────────────────────────────────

def load_language_char_weights() -> Dict[str, float]:
    """Load language character weights from config file.

    Returns a dict mapping language code -> weight (relative to Chinese=1.0).
    """
    weights_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config", "language_char_weights.json"
    )
    try:
        with open(weights_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        weights = data.get("weights", {})
        default_weight = data.get("default", 1.0)
        weights["_default"] = default_weight
        return weights
    except Exception:
        return {"_default": 1.0}


# ── word-span / timing helpers ──────────────────────────────────────────

def sentence_gap(left: Dict, right: Dict) -> float:
    """Return silence gap between adjacent sentences."""
    try:
        left_end = float(left.get("end", 0) or 0)
    except (TypeError, ValueError):
        left_end = 0.0
    try:
        right_start = float(right.get("start", left_end) or left_end)
    except (TypeError, ValueError):
        right_start = left_end
    return right_start - left_end


def normalize_word_spans(words: List[Dict], start_hint: float, end_hint: float) -> List[Dict]:
    """Normalize word timestamps into a monotonic span within the sentence window."""
    normalized = []
    prev_end = float(start_hint or 0)
    for word in words or []:
        item = dict(word)
        try:
            start = float(item.get("start", prev_end))
        except (TypeError, ValueError):
            start = prev_end
        try:
            end = float(item.get("end", start))
        except (TypeError, ValueError):
            end = start

        start = max(start, prev_end, float(start_hint or 0))
        if end <= start:
            end = start + 0.06
        if end_hint and end > float(end_hint):
            end = float(end_hint)
        if end <= start:
            end = start + 0.06

        item["start"] = round(start, 4)
        item["end"] = round(end, 4)
        normalized.append(item)
        prev_end = item["end"]
    return normalized


def is_all_punctuation_or_whitespace(text: str) -> bool:
    """Return True when text consists entirely of punctuation/whitespace."""
    import unicodedata
    stripped = str(text or "").strip()
    if not stripped:
        return True
    for ch in stripped:
        cat = unicodedata.category(ch)
        # Letters (L*), numbers (N*), and marks (M*) are content
        if cat.startswith(("L", "N", "M")):
            return False
    return True


def normalize_text_for_alignment_check(text: str) -> str:
    """Normalize text before comparing sentence text with joined word text.

    Strips whitespace AND punctuation. The point of this check is to detect
    semantic drift between the sentence text and the underlying word
    sequence; punctuation legitimately differs (e.g. word lists rarely
    include trailing "。" or ",") and must not be reported as a mismatch.
    """
    text = str(text or "")
    text = text.replace("\u3000", " ")
    # Remove Unicode punctuation categories: Po (other punct), Pe/Pd/Ps
    # (bracket/dash), Pi/Pf (quotation marks), plus common CJK punct.
    text = re.sub(
        r"[\u3000-\u303f\u2000-\u206f\u2e00-\u2e7f"
        r"。，！？；：、…—·•·,!?;:.\"'`"
        r"()\[\]{}<>《》「」『』【】]",
        "",
        text,
    )
    return re.sub(r"\s+", "", text)


# ── speaker helpers ─────────────────────────────────────────────────────

def has_multi_speaker(segments: List[Dict]) -> bool:
    """Return True only when ASR actually carries speaker ids and there are >=2 distinct speakers.

    If any segment has no speaker info, or all segments share the same speaker,
    treat it as single-speaker content and skip speaker-based cutting.
    """
    speakers = set()
    for seg in segments:
        seg_speaker = seg.get("speaker")
        if seg_speaker:
            speakers.add(seg_speaker)
        for w in seg.get("words", []) or []:
            ws = w.get("speaker")
            if ws:
                speakers.add(ws)
    # Filter out empty/None placeholders
    speakers = {s for s in speakers if s not in (None, "", "null", "None")}
    return len(speakers) >= 2


# ── force / character split helpers ─────────────────────────────────────

def pre_split_at_terminals(text: str, terminals: set) -> List[str]:
    """Split text at sentence-terminal punctuation, keeping the punctuation
    attached to its preceding segment.

    '找男人。再有来女人嘛。' -> ['找男人。', '再有来女人嘛。']
    """
    if not text:
        return [text]

    segments = []
    current = ""
    for ch in text:
        current += ch
        if ch in terminals:
            segments.append(current)
            current = ""
    if current:
        segments.append(current)
    return segments if segments else [text]


def fix_leading_punctuation(chunks: List[str]) -> List[str]:
    """Move leading punctuation marks to the end of the preceding chunk.

    Handles cases like: ["春天到了", "，万物复苏"] -> ["春天到了，", "万物复苏"]
    Also merges punctuation-only chunks into the preceding chunk.
    """
    if not chunks or len(chunks) < 2:
        return chunks

    # Common punctuation (CJK + Western) that should follow the preceding sentence
    punct_chars = set(
        '。！？，、；：…～~'  # CJK
        '.!?,;:'               # Western
        '。！？'               # CJK full-width (redundant safety)
        '、；：'               # more CJK
    )
    # Quotation marks and brackets should NOT be moved
    keep_as_is = set('"\'"\'「」『』（）()【】[]{}<>《》')

    result = list(chunks)

    i = 1
    while i < len(result):
        text = result[i]
        # Find leading punctuation characters
        punct_prefix = ""
        for ch in text:
            if ch in keep_as_is:
                break  # Stop at quotes/brackets — they start a new phrase
            if ch in punct_chars:
                punct_prefix += ch
            elif not ch.isalnum() and not ch.isspace() and ch not in keep_as_is:
                # Other non-alphanumeric chars (e.g., ellipsis, tilde)
                punct_prefix += ch
            else:
                break

        if punct_prefix:
            # Move leading punctuation to the end of previous chunk
            result[i - 1] = result[i - 1] + punct_prefix
            remainder = text[len(punct_prefix):]
            if remainder.strip():
                result[i] = remainder
            else:
                # The entire chunk was punctuation — merge and remove
                result.pop(i)
                continue
        i += 1

    # Filter out empty chunks
    return [c for c in result if c.strip()]


def split_chinese_by_chars(text: str, max_length: int, has_jieba: bool = True) -> List[str]:
    """Split Chinese text at word boundaries using jieba."""
    if has_jieba:
        import jieba
        words = list(jieba.cut(text))
    else:
        # Fallback: treat each character as a word
        words = list(text)

    chunks = []
    current = ""
    for word in words:
        if len(current) + len(word) > max_length and current:
            chunks.append(current)
            current = word
        else:
            current += word
    if current:
        chunks.append(current)

    return fix_leading_punctuation(chunks)


def split_english_by_chars(text: str, max_length: int) -> List[str]:
    """Split English text at word boundaries (spaces)."""
    words = text.split()
    chunks = []
    current = []
    current_len = 0

    for word in words:
        word_len = len(word) + (1 if current else 0)  # +1 for space
        if current_len + word_len > max_length and current:
            chunks.append(" ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len += word_len

    if current:
        chunks.append(" ".join(current))

    return fix_leading_punctuation(chunks)


def assign_words_by_char_offset(
    seg_words: List[Dict],
    chunks: List[str],
    seg_start: float = 0.0,
    seg_end: float = 0.0,
) -> List[Dict]:
    """Deterministically assign each word (or a proportional slice of it) to the
    chunk whose character span contains it.

    Replaces the previous fuzzy prefix/subsequence re-matching. Every chunk is an
    exact substring of the original segment text, so the concatenated (whitespace
    stripped) chunk texts correspond character-for-character to the concatenated word
    texts. We therefore consume words in order against each chunk's character budget:

      * words are consumed in order — never skipped, never over-consumed;
      * a word that straddles a chunk boundary is split by TIME proportionally to the
        fraction of its characters that fall inside the chunk, giving both neighbouring
        chunks a real sub-word timestamp;
      * chunk timestamps are always within [word.start, word.end], so they never exceed
        the true segment bounds.

    Returns a list (parallel to ``chunks``) of
    ``{"text": chunk, "start": float|None, "end": float|None, "words": [...]}``.
    Empty-text chunks get ``words: []`` and ``start/end == None`` (the caller fills
    these from ``seg_start``/``seg_end``).
    """
    import re

    _clean = lambda s: re.sub(r"\s+", "", str(s or ""))
    word_texts = [_clean(w.get("word", "")) for w in seg_words]
    chunk_texts = [_clean(c) for c in chunks]

    result: List[Dict] = []
    wi = 0   # current word index
    wp = 0   # char offset inside the current word
    n = len(seg_words)

    for ci, chunk in enumerate(chunks):
        need = len(chunk_texts[ci])
        assigned: List[Dict] = []
        filled = 0

        if need == 0:
            result.append({"text": chunk, "start": None, "end": None, "words": []})
            continue

        while filled < need and wi < n:
            wt = word_texts[wi]
            if not wt:
                # empty word: advance without consuming characters
                wi += 1
                wp = 0
                continue
            remaining = len(wt) - wp
            take = remaining if remaining <= (need - filled) else (need - filled)
            w = seg_words[wi]
            try:
                w_start = float(w.get("start", 0) or 0)
                w_end = float(w.get("end", 0) or 0)
            except (TypeError, ValueError):
                w_start = w_end = 0.0
            span = w_end - w_start
            if span:
                sub_start = w_start + span * (wp / len(wt))
                sub_end = w_start + span * ((wp + take) / len(wt))
            else:
                sub_start = sub_end = w_start
            sub_word = dict(w)
            sub_word["start"] = round(sub_start, 4)
            sub_word["end"] = round(sub_end, 4)
            assigned.append(sub_word)

            filled += take
            wp += take
            if wp >= len(wt):
                wi += 1
                wp = 0

        if assigned:
            cstart = assigned[0]["start"]
            cend = assigned[-1]["end"]
        else:
            cstart = cend = None
        result.append({"text": chunk, "start": cstart, "end": cend, "words": assigned})

    return result


def distribute_timestamps_to_chunks(
    original_sent: Dict, chunks: List[str]
) -> List[Dict]:
    """Distribute timestamps from original sentence to split chunks.

    Uses deterministic character-offset assignment (see
    :func:`assign_words_by_char_offset`) so words are never dropped and chunk
    timestamps never exceed the segment bounds.
    """
    words = list(original_sent.get("words", []) or [])
    start = float(original_sent.get("start", 0) or 0)
    end = float(original_sent.get("end", start) or start)

    if not chunks:
        return [original_sent]

    if not words:
        # No word-level data at all — distribute evenly by char count (legacy fallback)
        total_chars = sum(len(re.sub(r"\s+", "", c)) for c in chunks) or 1
        current_time = start
        result = []
        for chunk in chunks:
            chunk_duration = (len(re.sub(r"\s+", "", chunk)) / total_chars) * (end - start)
            result.append({
                "text": chunk,
                "start": round(current_time, 4),
                "end": round(current_time + chunk_duration, 4),
                "words": [],
            })
            current_time += chunk_duration
        return result

    out = assign_words_by_char_offset(words, chunks, start, end)
    for cd in out:
        if cd.get("start") is None:
            cd["start"] = round(start, 4)
            cd["end"] = round(end, 4)
    return out


# ── LLM split helpers ───────────────────────────────────────────────────

def salvage_json_response(content: str):
    """尝试从非 JSON 纯文本响应中抢救 JSON 对象/数组。

    部分模型/路由会忽略 response_format(json_object) 并返回纯文本，
    此时 json_repair.loads 会把无 JSON 结构的文本"宽容地"解析成空字符串，
    导致下游拿到 str 而不是 dict。这里先剥掉 markdown 代码块围栏，
    再提取最外层 {..} / [..] 块用标准 json 解析，失败再交给 json_repair。
    返回解析结果（dict/list）或 None。
    """
    if not isinstance(content, str) or not content.strip():
        return None
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE).strip()
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = text.find(open_ch)
        if start < 0:
            continue
        depth = 0
        end = -1
        for i in range(start, len(text)):
            if text[i] == open_ch:
                depth += 1
            elif text[i] == close_ch:
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end < 0:
            continue
        block = text[start:end + 1]
        try:
            import json as _json
            return _json.loads(block)
        except Exception:
            try:
                import json_repair
                return json_repair.loads(block)
            except Exception:
                continue
    return None


def build_smart_batches(
    to_split: List[tuple],
    max_chars: int = 12000,
) -> List[List[tuple]]:
    """Group sentences into batches so that total text chars per batch
    stays under *max_chars*.  Each batch is a list of (orig_idx, sent) tuples.
    A single sentence that alone exceeds max_chars gets its own batch."""
    batches: List[List[tuple]] = []
    current: List[tuple] = []
    current_chars = 0

    for item in to_split:
        idx, sent = item
        text_len = len(sent.get("text", ""))

        # If adding this sentence would overflow, close current batch first
        if current and current_chars + text_len > max_chars:
            batches.append(current)
            current = []
            current_chars = 0

        current.append(item)
        current_chars += text_len

    if current:
        batches.append(current)

    return batches
