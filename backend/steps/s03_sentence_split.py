"""
s03_sentence_split: Split ASR results into meaningful sentences
with word-level timestamp alignment.

Flow:
  1. Load ASR result (segments with words)
  2. Merge short segments
  3. Split long sentences by punctuation, align using word timestamps
  4. For sentences still too long -> batch LLM split -> rebuild timestamps from words
  5. Loop until all sentences within max_length
  6. Save sentences.json with word-level timestamps preserved
"""
import os
import json
import re
from typing import Callable, Optional, List, Dict
from backend.steps.base_step import BaseStep, find_artifact
from backend.config.config_manager import config
from backend.utils import sentence_split_utils as split_utils
from backend.utils.sentence_split_core import (
    load_language_char_weights, sentence_gap, normalize_word_spans,
    is_all_punctuation_or_whitespace, normalize_text_for_alignment_check,
    has_multi_speaker, pre_split_at_terminals, fix_leading_punctuation,
    split_chinese_by_chars, split_english_by_chars, distribute_timestamps_to_chunks,
    assign_words_by_char_offset,
    salvage_json_response, build_smart_batches,
)


class S03SentenceSplit(BaseStep):
    step_id = "s03_sentence_split"
    step_name = "句子分割"
    dependencies = ["s02_asr"]
    artifacts = ["cache/sentences.json", "cache/sentences_text.txt"]

    def check_artifact(self, task_dir: str) -> bool:
        node_suffix = f"_{self._node_id}" if self._node_id else ""
        out_files = [
            os.path.join(task_dir, "cache", f"sentences{node_suffix}.json"),
            os.path.join(task_dir, "cache", f"sentences_text{node_suffix}.txt"),
        ]
        if not all(os.path.exists(p) for p in out_files):
            return False

        asr_path = find_artifact(os.path.join(task_dir, "cache"), "asr_result.json")
        if not asr_path:
            return False

        try:
            asr_mtime = os.path.getmtime(asr_path)
        except OSError:
            return False

        for art_path in out_files:
            try:
                art_mtime = os.path.getmtime(art_path)
            except OSError:
                return False
            if art_mtime < asr_mtime:
                print(f"[Split] Stale artifact detected: {os.path.basename(art_path)} older than asr_result.json")
                return False
        return True

    def validate_inputs(self, task_dir: str) -> bool:
        return find_artifact(os.path.join(task_dir, "cache"), "asr_result.json") is not None

    # ── helpers ──────────────────────────────────────────────────────

    def _get_param(self, key: str, default=None):
        """只读取当前节点卡片上的设置，不再回退到全局配置。"""
        node_cfg = getattr(self, "_node_config", {}) or {}
        val = node_cfg.get(key)
        if val is None or val == "":
            return default
        return val

    def _get_bool_param(self, key: str, default: bool = False) -> bool:
        """Read a boolean param, tolerating string values like "true"/"false"."""
        val = self._get_param(key, default)
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in ("1", "true", "yes", "on")

    @staticmethod
    def _coerce_bool(val, default: bool = False) -> bool:
        if val is None or val == "":
            return default
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in ("1", "true", "yes", "on")

    def _get_effective_max_length(self, base_max_length: int, lang: str) -> int:
        """Calculate effective max sentence length based on language weight.
        The base_max_length is in Chinese characters; for other languages,
        multiply by the language's character weight.
        """
        weights = self._load_language_char_weights()
        lang_lower = (lang or "").lower().strip()
        # Try exact match, then base lang (e.g., "en" from "en-us"), then default
        weight = (
            weights.get(lang_lower)
            or weights.get(lang_lower.split("-")[0] if "-" in lang_lower else lang_lower)
            or weights.get("_default", 1.0)
        )
        effective = int(round(base_max_length * weight))
        if effective != base_max_length:
            print(f"[Split] Max length adjusted: {base_max_length} (zh) × {weight} = {effective} ({lang})")
        return effective

    def _build_words_index(self, segments: List[Dict]) -> List[Dict]:
        """Flatten all segments' words into a single sorted list with source info."""
        words = []
        for seg in segments:
            for w in seg.get("words", []):
                words.append({
                    "word": w.get("word", ""),
                    "start": w.get("start", 0),
                    "end": w.get("end", 0),
                    "speaker": w.get("speaker", ""),
                })
        return words

    @staticmethod
    def _is_compact_spacing_language(lang: str = "auto") -> bool:
        return split_utils.is_compact_spacing_language(lang)

    def _clean_sentence_text(self, text: str, lang: Optional[str] = None) -> str:
        return split_utils.clean_sentence_text(text, lang or getattr(self, "_resolved_language", "auto"))

    def _sentence_text_from_words(
        self,
        words: List[Dict],
        fallback_text: str = "",
        lang: Optional[str] = None,
    ) -> str:
        """Build sentence text from words without inventing or rewriting content."""
        compact = self._is_compact_spacing_language(lang or getattr(self, "_resolved_language", "auto"))
        parts = [str(word.get("word", "") or "") for word in words or [] if str(word.get("word", "") or "")]
        if not parts:
            return self._clean_sentence_text(fallback_text, lang=lang)
        if compact:
            return self._clean_sentence_text("".join(parts), lang=lang)
        text = " ".join(part.strip() for part in parts if part.strip())
        text = re.sub(r"\s+([,.;!?])", r"\1", text)
        return self._clean_sentence_text(text, lang=lang)

    def _is_punctuation_word(self, word: Dict, lang: Optional[str] = None) -> bool:
        """Return True when a token contains punctuation only."""
        raw = str((word or {}).get("word", "") or "")
        compact = re.sub(r"\s+", "", raw)
        if not compact:
            return True
        puncts = self._load_language_puncts(lang or getattr(self, "_resolved_language", "auto"))
        all_puncts = puncts.get("sentence_ends", set()) | puncts.get("clause_breaks", set())
        return all(ch in all_puncts for ch in compact)

    def _sentence_content_bounds(
        self,
        words: List[Dict],
        fallback_start: float,
        fallback_end: float,
        lang: Optional[str] = None,
    ) -> tuple[float, float]:
        """Use first/last non-punctuation words as sentence bounds."""
        if not words:
            return fallback_start, fallback_end

        content_words = [word for word in words if not self._is_punctuation_word(word, lang=lang)]
        if not content_words:
            return fallback_start, fallback_end

        try:
            start = float(content_words[0].get("start", fallback_start) or fallback_start)
        except (TypeError, ValueError):
            start = fallback_start
        try:
            end = float(content_words[-1].get("end", fallback_end) or fallback_end)
        except (TypeError, ValueError):
            end = fallback_end
        return start, end

    def _is_sentence_terminal(self, text: str, lang: str = "auto") -> bool:
        """Return True when text ends with a sentence-terminating punctuation mark."""
        stripped = str(text or "").strip()
        if not stripped:
            return False
        stripped = stripped.rstrip(" \t\r\n\"'”’）)]】》」』")
        if not stripped:
            return False
        puncts = self._load_language_puncts(lang).get("sentence_ends", set())
        return stripped[-1] in puncts

    def _repair_abnormal_word_spans(
        self,
        words: List[Dict],
        start_hint: float,
        end_hint: float,
    ) -> List[Dict]:
        """Smooth obviously abnormal word spans while preserving order and text."""
        if len(words or []) < 2:
            return words or []

        prepared = []
        for word in words or []:
            item = dict(word)
            try:
                start = float(item.get("start", 0) or 0)
            except (TypeError, ValueError):
                start = 0.0
            try:
                end = float(item.get("end", start) or start)
            except (TypeError, ValueError):
                end = start
            if end <= start:
                end = start + 0.06
            item["start"] = start
            item["end"] = end
            prepared.append(item)

        durations = [item["end"] - item["start"] for item in prepared if item["end"] > item["start"]]
        if not durations:
            return prepared

        sorted_durations = sorted(durations)
        mid = len(sorted_durations) // 2
        if len(sorted_durations) % 2:
            median_duration = sorted_durations[mid]
        else:
            median_duration = (sorted_durations[mid - 1] + sorted_durations[mid]) / 2

        window_start = max(float(start_hint or 0), float(prepared[0]["start"]))
        window_end = max(float(end_hint or 0), float(prepared[-1]["end"]), window_start + 0.06)
        window_span = window_end - window_start
        dominant_limit = window_span * 0.6
        abnormal = [
            item for item in prepared
            if (item["end"] - item["start"]) > max(1.2, median_duration * 4)
            and (item["end"] - item["start"]) > dominant_limit
        ]
        if not abnormal:
            return prepared

        print(
            f"[Split] Repaired {len(abnormal)} abnormal word spans "
            f"(window={window_span:.2f}s, median={median_duration:.2f}s)"
        )

        weights = []
        for item in prepared:
            norm_word = self._normalize_text_for_alignment_check(item.get("word", ""))
            weights.append(max(len(norm_word), 1))

        repaired = []
        current = window_start
        remaining_weight = sum(weights) or len(prepared)
        for idx, item in enumerate(prepared):
            weight = weights[idx]
            words_left = len(prepared) - idx - 1
            min_tail = words_left * 0.06
            available = max(window_end - current - min_tail, 0.06)
            if idx == len(prepared) - 1:
                end = window_end
            else:
                share = available * (weight / max(remaining_weight, 1))
                end = min(window_end - min_tail, current + max(share, 0.06))
            fixed = dict(item)
            fixed["start"] = round(current, 4)
            fixed["end"] = round(max(end, current + 0.06), 4)
            repaired.append(fixed)
            current = fixed["end"]
            remaining_weight -= weight

        return repaired

    def _finalize_sentences(self, sentences: List[Dict], lang: str = "auto") -> List[Dict]:
        """Use sentence words as the source of truth for sentence timestamps."""
        finalized = []
        prev_end = 0.0
        for idx, sent in enumerate(sentences, start=1):
            item = dict(sent)
            text = self._clean_sentence_text(item.get("text", ""))
            if not text:
                continue

            try:
                start = float(item.get("start", prev_end))
            except (TypeError, ValueError):
                start = prev_end
            try:
                end = float(item.get("end", start))
            except (TypeError, ValueError):
                end = start

            words = self._repair_abnormal_word_spans(item.get("words", []) or [], start, end)
            words = self._normalize_word_spans(words, start, end)
            if words:
                start, end = self._sentence_content_bounds(words, words[0]["start"], words[-1]["end"])
            else:
                start = max(start, prev_end)
                if end <= start:
                    # Fallback: estimate a short duration instead of crashing
                    est_duration = max(0.5, len(text) * 0.06)
                    end = start + est_duration
                    print(f"[Split] Sentence {idx} has no usable word timestamps, estimated {est_duration:.1f}s")

            if start < prev_end:
                shift = prev_end - start
                start += shift
                end += shift
                if words:
                    shifted_words = []
                    for word in words:
                        shifted = dict(word)
                        shifted["start"] = round(float(word["start"]) + shift, 4)
                        shifted["end"] = round(float(word["end"]) + shift, 4)
                        shifted_words.append(shifted)
                    words = shifted_words

            item["id"] = idx
            item["text"] = text
            item["start"] = round(start, 4)
            item["end"] = round(max(end, start + 0.06), 4)
            item["words"] = words
            finalized.append(item)
            prev_end = item["end"]

        return self._merge_orphan_punctuation(finalized, lang=lang)

    def _merge_orphan_punctuation(
        self, sentences: List[Dict], lang: str = "auto"
    ) -> List[Dict]:
        """Merge punctuation-only sentences into the preceding sentence.

        This handles cases where force-splitting leaves standalone punctuation
        like '？' or '。' as their own sentence.
        """
        if len(sentences) < 2:
            return sentences

        compact = self._is_compact_spacing_language(lang)
        result = []
        i = 0
        while i < len(sentences):
            cur = sentences[i]
            cur_text = str(cur.get("text", "")).strip()
            if self._is_all_punctuation_or_whitespace(cur_text) and result:
                # Merge into previous sentence
                prev = result[-1]
                prev_text = str(prev.get("text", ""))
                # Concatenate without space for compact languages
                if compact:
                    prev["text"] = prev_text.rstrip() + cur_text
                else:
                    prev["text"] = prev_text.rstrip() + " " + cur_text
                # Extend end time to cover the punctuation sentence
                prev["end"] = max(
                    float(prev.get("end", 0) or 0),
                    float(cur.get("end", prev.get("end", 0)) or 0),
                )
                # Append orphan's words to previous
                prev_words = list(prev.get("words", []) or [])
                cur_words = list(cur.get("words", []) or [])
                prev["words"] = prev_words + cur_words
                i += 1
                continue
            result.append(dict(cur))
            i += 1
        return result

    def _split_by_pause(
        self,
        sentences: List[Dict],
        pause_threshold: float,
        lang: str = "auto",
    ) -> List[Dict]:
        """Split sentences at large intra-sentence pauses detected from word timestamps."""
        if pause_threshold <= 0:
            return sentences

        result = []
        split_count = 0
        for sent in sentences:
            words = list(sent.get("words", []) or [])
            if len(words) < 2:
                result.append(sent)
                continue

            chunks = []
            current_words = [words[0]]
            for word in words[1:]:
                prev_word = current_words[-1]
                try:
                    gap = float(word.get("start", 0) or 0) - float(prev_word.get("end", 0) or 0)
                except (TypeError, ValueError):
                    gap = 0.0
                if gap >= pause_threshold:
                    text = self._sentence_text_from_words(current_words, sent.get("text", ""), lang=lang)
                    if text:
                        chunks.append({
                            "text": text,
                            "start": current_words[0].get("start", sent.get("start", 0)),
                            "end": current_words[-1].get("end", sent.get("end", 0)),
                            "words": list(current_words),
                        })
                    current_words = [word]
                    split_count += 1
                else:
                    current_words.append(word)

            text = self._sentence_text_from_words(current_words, sent.get("text", ""), lang=lang)
            if text:
                chunks.append({
                    "text": text,
                    "start": current_words[0].get("start", sent.get("start", 0)),
                    "end": current_words[-1].get("end", sent.get("end", 0)),
                    "words": list(current_words),
                })

            if len(chunks) > 1:
                result.extend(chunks)
            else:
                result.append(sent)

        if split_count:
            print(f"[Split] Pause-based split created {split_count} additional sentence boundaries")
        return result

    def _merge_short_sentences(self, sentences: List[Dict],
                                max_length: int,
                                lang: str = "auto",
                                gap_threshold: Optional[float] = None) -> List[Dict]:
        if len(sentences) <= 1:
            return sentences

        compact = self._is_compact_spacing_language(lang)
        min_len = max(3, int(max_length * 0.3))

        def _text_len(s: Dict) -> int:
            return len(self._clean_sentence_text(s.get("text", ""), lang=lang))

        def _speaker(s: Dict) -> str:
            ws = s.get("words", []) or []
            if ws:
                return str(ws[0].get("speaker", "") or "")
            return ""

        def _can_merge(left: Dict, right: Dict) -> bool:
            if _speaker(left) and _speaker(right) and _speaker(left) != _speaker(right):
                return False
            if _text_len(left) + _text_len(right) > max_length:
                return False
            return True

        result = list(sentences)
        i = 0
        while i < len(result):
            cur = result[i]
            if _text_len(cur) > min_len:
                i += 1
                continue

            if i < len(result) - 1:
                nxt = result[i + 1]
                if _can_merge(cur, nxt):
                    sep = "" if compact else " "
                    nxt["text"] = cur["text"].strip() + sep + nxt["text"].strip()
                    nxt["start"] = cur.get("start", nxt.get("start", 0))
                    nxt["words"] = (cur.get("words", []) or []) + (nxt.get("words", []) or [])
                    result.pop(i)
                    continue

            if i > 0:
                prev = result[i - 1]
                if _can_merge(prev, cur):
                    sep = "" if compact else " "
                    prev["text"] = prev["text"].rstrip() + sep + cur["text"].strip()
                    prev["end"] = cur.get("end", prev.get("end", 0))
                    prev["words"] = (prev.get("words", []) or []) + (cur.get("words", []) or [])
                    result.pop(i)
                    continue

            i += 1

        for idx, s in enumerate(result, start=1):
            s["id"] = idx
        return result

    def _merge_close_gap_sentences(self, sentences: List[Dict],
                                   max_length: int,
                                   max_gap: float,
                                   lang: str = "auto") -> List[Dict]:
        if len(sentences) <= 1 or max_gap <= 0:
            return sentences

        compact = self._is_compact_spacing_language(lang)

        def _text_len(s: Dict) -> int:
            return len(self._clean_sentence_text(s.get("text", ""), lang=lang))

        def _speaker(s: Dict) -> str:
            ws = s.get("words", []) or []
            if ws:
                return str(ws[0].get("speaker", "") or "")
            return ""

        result = list(sentences)
        i = 0
        while i < len(result) - 1:
            left = result[i]
            right = result[i + 1]
            if _speaker(left) and _speaker(right) and _speaker(left) != _speaker(right):
                i += 1
                continue
            if _text_len(left) + _text_len(right) > max_length:
                i += 1
                continue
            if self._sentence_gap(left, right) >= max_gap:
                i += 1
                continue
            sep = "" if compact else " "
            left["text"] = left["text"].rstrip() + sep + right["text"].strip()
            left["end"] = right.get("end", left.get("end", 0))
            left["words"] = (left.get("words", []) or []) + (right.get("words", []) or [])
            result.pop(i + 1)

        for idx, s in enumerate(result, start=1):
            s["id"] = idx
        return result

    def _validate_sentence_word_alignment(self, sentences: List[Dict]) -> List[Dict]:
        """Check for sentence text / word-sequence drift. Returns mismatch list (never raises)."""
        mismatches = []
        for sent in sentences:
            words = sent.get("words", []) or []
            if not words:
                continue

            sentence_text = self._normalize_text_for_alignment_check(sent.get("text", ""))
            words_text = self._normalize_text_for_alignment_check(
                "".join(str(word.get("word", "")) for word in words)
            )
            if sentence_text == words_text:
                continue

            mismatches.append(
                {
                    "id": sent.get("id"),
                    "start": sent.get("start"),
                    "end": sent.get("end"),
                    "text": str(sent.get("text", ""))[:120],
                    "words_text": "".join(str(word.get("word", "")) for word in words)[:120],
                    "word_count": len(words),
                }
            )

        if mismatches:
            first = mismatches[0]
            print(
                f"[Split] Alignment mismatch: id={first.get('id')}, "
                f"text={first.get('text')!r}, words={first.get('words_text')!r}, "
                f"total_mismatches={len(mismatches)}"
            )

        return mismatches

    def _validate_and_fix_alignment(self, sentences: List[Dict]) -> List[Dict]:
        """Validate alignment and fix any mismatches.
        Tolerates small drift (<3 chars) without clearing words.
        Never raises — always returns usable sentences."""
        mismatches = self._validate_sentence_word_alignment(sentences)
        if not mismatches:
            return sentences

        mismatch_ids = {m["id"] for m in mismatches}
        print(f"[Split] Fixing {len(mismatches)} alignment mismatches...")

        for sent in sentences:
            if sent.get("id") not in mismatch_ids:
                continue

            words = sent.get("words", []) or []
            sent_text = self._normalize_text_for_alignment_check(sent.get("text", ""))
            words_text = self._normalize_text_for_alignment_check(
                "".join(str(w.get("word", "")) for w in words)
            )

            # Try to rebuild first
            rebuilt = self._rebuild_words_from_sentence(sent, words)
            if rebuilt:
                rebuilt_text = self._normalize_text_for_alignment_check(
                    "".join(str(w.get("word", "")) for w in rebuilt)
                )
                if rebuilt_text == sent_text:
                    sent["words"] = rebuilt
                    continue
                print(
                    f"[Split] Alignment rebuild rejected: text={sent_text!r}, "
                    f"rebuilt={rebuilt_text!r}, original={words_text!r}"
                )
            elif words:
                print(f"[Split] Alignment rebuild rejected: no exact monotonic match for {sent_text!r}")
            # Last resort: keep words if they exist, rather than clearing
            # _finalize_sentences will still use them for timestamps
            if not words:
                sent["words"] = []

        return sentences

    def _fix_alignment_by_dropping_words(self, sentences: List[Dict]) -> List[Dict]:
        """Last-resort fix: for sentences with alignment mismatch, clear their words
        so the validation passes (empty words are skipped by the validator)."""
        fixed = 0
        for sent in sentences:
            words = sent.get("words", []) or []
            if not words:
                continue
            sentence_text = self._normalize_text_for_alignment_check(sent.get("text", ""))
            words_text = self._normalize_text_for_alignment_check(
                "".join(str(w.get("word", "")) for w in words)
            )
            if sentence_text != words_text:
                # Try to rebuild words from sentence text using available word timestamps
                rebuilt = self._rebuild_words_from_sentence(sent, words)
                if rebuilt:
                    sent["words"] = rebuilt
                else:
                    sent["words"] = []
                fixed += 1
        if fixed:
            print(f"[Split] Word-drop fix applied to {fixed} sentences")
        return sentences

    def _rebuild_words_from_sentence(self, sent: Dict, original_words: List[Dict]) -> List[Dict]:
        """Rebuild word list using exact monotonic matching against original words."""
        target = self._normalize_text_for_alignment_check(sent.get("text", ""))
        if not target or not original_words:
            return []

        rebuilt = []
        pos = 0
        for word in original_words:
            word_norm = self._normalize_text_for_alignment_check(word.get("word", ""))
            if not word_norm:
                if rebuilt:
                    rebuilt.append(word)
                continue
            if target.startswith(word_norm, pos):
                rebuilt.append(word)
                pos += len(word_norm)
                if pos >= len(target):
                    break

        rebuilt_text = self._normalize_text_for_alignment_check(
            "".join(str(word.get("word", "")) for word in rebuilt)
        )
        return rebuilt if rebuilt_text == target else []

    _PUNCTS_CACHE = {}

    @classmethod
    def _load_language_puncts(cls, lang: str = "auto") -> Dict[str, set]:
        return split_utils.load_language_puncts(lang)

    def _align_sentence_to_words(self, text: str, words: List[Dict],
                                  start_hint: float = 0, end_hint: float = 0) -> Dict:
        """Find word-level timestamps that belong to this sentence text.

        Uses case-insensitive character subsequence matching against the
        flattened word list.  Returns a sentence dict with start/end from
        matched words and the words list.
        """
        clean_text = self._clean_sentence_text(text)
        clean = re.sub(r'\s+', '', clean_text)
        clean_lower = clean.lower()
        matched_words = []

        # Find starting position: search words starting from a reasonable point
        # Use start_hint to narrow the search window
        search_start = 0
        for i, w in enumerate(words):
            if w["end"] >= start_hint - 0.5:
                search_start = max(0, i - 2)
                break

        pos = 0
        for w in words[search_start:]:
            w_clean = re.sub(r'\s+', '', w["word"])
            if not w_clean:
                continue
            w_clean_lower = w_clean.lower()
            # Try to match this word's characters against the remaining text
            if pos < len(clean_lower):
                # Case-insensitive character subsequence matching
                match = True
                temp_pos = pos
                for ch in w_clean_lower:
                    found = False
                    while temp_pos < len(clean_lower):
                        if clean_lower[temp_pos] == ch:
                            temp_pos += 1
                            found = True
                            break
                        temp_pos += 1
                    if not found:
                        match = False
                        break
                if match:
                    matched_words.append(w)
                    pos = temp_pos

        if matched_words:
            return {
                "text": clean_text,
                "start": round(matched_words[0]["start"], 4),
                "end": round(matched_words[-1]["end"], 4),
                "words": matched_words,
            }
        else:
            # Fallback: use hints
            return {
                "text": clean_text,
                "start": round(start_hint, 4),
                "end": round(end_hint, 4),
                "words": [],
            }

    def _align_chunk_to_local_words(
        self,
        text: str,
        words: List[Dict],
        start_hint: float = 0,
        end_hint: float = 0,
    ) -> tuple[Dict, int]:
        """Align a chunk against the current sentence's remaining local words.

        Uses sequential prefix matching with multiple fallback strategies:
        1. Exact prefix match (case-sensitive)
        2. Case-insensitive prefix match
        3. Skip-mode: allow skipping mismatched words and continue
        4. Partial match: accept if coverage >= 50%

        Returns (sentence_dict, consumed_count) where consumed_count is the
        number of words consumed from the input list, ensuring later chunks
        never reuse earlier words.
        """
        clean_text = self._clean_sentence_text(text)
        clean = re.sub(r"\s+", "", clean_text)
        if not clean:
            return {
                "text": clean_text,
                "start": round(start_hint, 4),
                "end": round(end_hint, 4),
                "words": [],
            }, 0

        if not words:
            return {
                "text": clean_text,
                "start": round(start_hint, 4),
                "end": round(end_hint, 4),
                "words": [],
            }, 0

        search_start = 0
        for i, w in enumerate(words):
            try:
                word_end = float(w.get("end", 0) or 0)
            except (TypeError, ValueError):
                word_end = 0.0
            if word_end >= float(start_hint or 0) - 0.1:
                search_start = i
                break

        clean_lower = clean.lower()
        # Wider tolerance window: try up to 5 starting positions
        max_start = min(len(words), search_start + 5)

        best_partial = None  # (matched_words, consumed_count, coverage)

        for start_idx in range(search_start, max_start):
            pos = 0
            matched_words = []
            consumed_count = 0
            skipped_count = 0
            max_skips = 3  # Allow skipping mismatched words

            for current_word in words[start_idx:]:
                word_text = re.sub(r"\s+", "", str(current_word.get("word", "")))
                if not word_text:
                    consumed_count += 1
                    continue

                consumed_count += 1
                word_lower = word_text.lower()

                # Try exact match first, then case-insensitive
                if clean.startswith(word_text, pos) or clean_lower.startswith(word_lower, pos):
                    matched_words.append(current_word)
                    pos += len(word_text)
                    if pos >= len(clean):
                        # Full match — return immediately
                        return {
                            "text": clean_text,
                            "start": round(float(matched_words[0].get("start", start_hint) or start_hint), 4),
                            "end": round(float(matched_words[-1].get("end", end_hint) or end_hint), 4),
                            "words": matched_words,
                        }, start_idx + consumed_count
                else:
                    # Skip this word and try the next one
                    skipped_count += 1
                    if skipped_count > max_skips:
                        break

            # Evaluate partial match coverage
            if matched_words:
                coverage = pos / len(clean) if clean else 0
                if coverage >= 0.5 and (best_partial is None or coverage > best_partial[2]):
                    best_partial = (list(matched_words), start_idx + consumed_count, coverage)

        # Accept best partial match if found
        if best_partial:
            matched, consumed, _ = best_partial
            return {
                "text": clean_text,
                "start": round(float(matched[0].get("start", start_hint) or start_hint), 4),
                "end": round(float(matched[-1].get("end", end_hint) or end_hint), 4),
                "words": matched,
            }, consumed

        fallback = self._align_sentence_to_words(text, words, start_hint, end_hint)
        return fallback, 0

    # ── merge short segments ─────────────────────────────────────────

    def _split_by_speaker(self, segments: List[Dict],
                            min_duration: float = 1.0,
                            max_gap: float = 0.5) -> List[Dict]:
        """Force a cut whenever the speaker id changes between adjacent segments.

        This is the highest-priority split: speaker boundaries must never be merged
        or absorbed by later steps.
        """
        if not segments:
            return segments

        def _seg_speaker(seg: Dict) -> str:
            # Prefer the segment-level speaker; fall back to the first word's speaker
            sp = seg.get("speaker")
            if sp:
                return str(sp)
            for w in seg.get("words", []) or []:
                ws = w.get("speaker")
                if ws:
                    return str(ws)
            return ""

        result = []
        current = {
            "start": segments[0]["start"],
            "end": segments[0]["end"],
            "text": segments[0]["text"],
            "words": list(segments[0].get("words", [])),
            "speaker": _seg_speaker(segments[0]),
        }
        for seg in segments[1:]:
            seg_sp = _seg_speaker(seg)
            speaker_changed = (
                seg_sp
                and current["speaker"]
                and seg_sp != current["speaker"]
            )
            gap = seg["start"] - current["end"]
            duration = current["end"] - current["start"]
            # If speaker changed, always close the current segment first
            if speaker_changed:
                result.append(current)
                current = {
                    "start": seg["start"],
                    "end": seg["end"],
                    "text": seg["text"],
                    "words": list(seg.get("words", [])),
                    "speaker": seg_sp,
                }
                continue
            # Otherwise apply the normal merge rule
            if duration < min_duration or gap < max_gap:
                current["end"] = seg["end"]
                current["text"] = current["text"].strip() + " " + seg["text"].strip()
                current["words"].extend(seg.get("words", []))
            else:
                result.append(current)
                current = {
                    "start": seg["start"],
                    "end": seg["end"],
                    "text": seg["text"],
                    "words": list(seg.get("words", [])),
                    "speaker": seg_sp,
                }
        result.append(current)

        # Strip the helper field so downstream code stays unchanged
        for item in result:
            item.pop("speaker", None)
        return result

    def _merge_short_segments(self, segments: List[Dict],
                               min_duration: float = 1.0,
                               max_gap: float = 0.5,
                               enable_duration: bool = True,
                               enable_gap: bool = True) -> List[Dict]:
        if not segments:
            return segments

        def _seg_speaker(seg: Dict) -> str:
            sp = seg.get("speaker")
            if sp:
                return str(sp)
            for w in seg.get("words", []) or []:
                ws = w.get("speaker")
                if ws:
                    return str(ws)
            return ""

        merged = []
        current = {
            "start": segments[0]["start"],
            "end": segments[0]["end"],
            "text": segments[0]["text"],
            "words": list(segments[0].get("words", [])),
            "speaker": _seg_speaker(segments[0]),
        }
        for seg in segments[1:]:
            seg_sp = _seg_speaker(seg)
            gap = seg["start"] - current["end"]
            duration = current["end"] - current["start"]
            # P0 fix: never merge segments spoken by different speakers
            speaker_changed = (
                seg_sp
                and current["speaker"]
                and seg_sp != current["speaker"]
            )
            if (enable_duration and duration < min_duration) or (enable_gap and gap < max_gap):
                if not speaker_changed:
                    current["end"] = seg["end"]
                    current["text"] = current["text"].strip() + " " + seg["text"].strip()
                    current["words"].extend(seg.get("words", []))
                    # Keep the latest non-empty speaker on the merged segment
                    if seg_sp:
                        current["speaker"] = seg_sp
                else:
                    merged.append(current)
                    current = {
                        "start": seg["start"],
                        "end": seg["end"],
                        "text": seg["text"],
                        "words": list(seg.get("words", [])),
                        "speaker": seg_sp,
                    }
            else:
                merged.append(current)
                current = {
                    "start": seg["start"],
                    "end": seg["end"],
                    "text": seg["text"],
                    "words": list(seg.get("words", [])),
                    "speaker": seg_sp,
                }
        merged.append(current)
        for item in merged:
            item.pop("speaker", None)
        return merged

    # ── split by punctuation, align with word timestamps ─────────────

    def _resolve_language(self, task_dir: str) -> str:
        """解析节点处理语言，from_input 时回退到输入节点和 ASR 结果。"""
        node_language = str((getattr(self, "_node_config", {}) or {}).get("processing_language") or "from_input").strip()
        if node_language not in ("", "from_input", "auto"):
            return node_language
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        # 1. Try input node config from workflow.json
        wf_path = os.path.join(task_dir, "workflow.json")
        if os.path.exists(wf_path):
            try:
                with open(wf_path, "r", encoding="utf-8") as f:
                    wf = json.load(f)
                for node in wf.get("nodes", []):
                    if node.get("data", {}).get("nodeType") == "input":
                        lang = node.get("data", {}).get("config", {}).get("source_language", "")
                        if lang and lang != "auto":
                            return lang
                        break
            except Exception:
                pass

        # 2. Fall back to ASR result language
        asr_path = step_inputs.get("subtitle") or find_artifact(os.path.join(task_dir, "cache"), "asr_result.json")
        if asr_path and not os.path.isabs(asr_path):
            asr_path = os.path.join(task_dir, asr_path)
        if asr_path and os.path.exists(asr_path):
            try:
                with open(asr_path, "r", encoding="utf-8") as f:
                    asr_data = json.load(f)
                lang = asr_data.get("language", "auto")
                if lang and lang != "auto":
                    return lang
            except Exception:
                pass

        return "auto"

    @staticmethod
    def _is_part_of_number(text: str, pos: int) -> bool:
        return split_utils.is_part_of_number(text, pos)

    @staticmethod
    def _split_text_by_ends(text: str, sentence_ends: set) -> List[str]:
        return split_utils.split_text_by_ends(text, sentence_ends)

    @staticmethod
    def _split_text_by_clauses(text: str, clause_breaks: set) -> List[str]:
        return split_utils.split_text_by_clauses(text, clause_breaks)

    def _split_by_punctuation(self, sentences: List[Dict],
                            all_words: List[Dict],
                            max_length: int,
                            lang: str = "auto",
                            split_sentence_ends: bool = True,
                            split_clause_breaks: bool = True) -> List[Dict]:
        puncts = self._load_language_puncts(lang)
        sentence_ends = puncts["sentence_ends"] if split_sentence_ends else set()
        clause_breaks = puncts["clause_breaks"] if split_clause_breaks else set()

        result: List[Dict] = []

        for sent in sentences:
            text = sent["text"].strip()
            text = self._clean_sentence_text(text, lang=lang)
            words_pool = list(sent.get("words", []))
            sent_start = sent["start"]
            sent_end = sent["end"]

            if not split_sentence_ends and not split_clause_breaks:
                result.append({
                    "text": text,
                    "start": sent_start,
                    "end": sent_end,
                    "words": words_pool,
                })
                continue

            if sentence_ends:
                phase1_chunks = self._split_text_by_ends(text, sentence_ends)
                if not phase1_chunks:
                    phase1_chunks = [text]
            else:
                phase1_chunks = [text]

            final_text_chunks: List[str] = []
            for chunk in phase1_chunks:
                if clause_breaks:
                    final_text_chunks.extend(
                        self._split_text_by_clauses(chunk, clause_breaks)
                    )
                else:
                    final_text_chunks.append(chunk)

            if len(final_text_chunks) == 1 and final_text_chunks[0].strip() == text:
                result.append({
                    "text": text,
                    "start": sent_start,
                    "end": sent_end,
                    "words": words_pool,
                })
                continue

            # Deterministic character-offset alignment: every chunk is a substring of
            # `text`, so assign words in order and split boundary-straddling words by time.
            aligned_chunks = assign_words_by_char_offset(
                words_pool, final_text_chunks, sent_start, sent_end
            )
            for ac in aligned_chunks:
                if not str(ac.get("text", "")).strip():
                    continue
                if ac.get("start") is None:
                    ac["start"] = round(sent_start, 4)
                    ac["end"] = round(sent_end, 4)
                result.append(ac)

        return result

    # ── LLM split helpers ────────────────────────────────────────────

    def _align_split_result(
        self,
        new_texts: List[str],
        orig_sent: Dict,
        lang: str = "auto",
    ) -> List[Dict]:
        """Align LLM-split text chunks back to the original sentence's word timestamps.

        Uses sequential word matching: each chunk consumes words from where the
        previous chunk left off, so later chunks never reuse earlier words.
        If word matching fails for a chunk, falls back to time interpolation
        based on character count.
        """
        words_pool = list(orig_sent.get("words", []) or [])
        sent_start = float(orig_sent.get("start", 0) or 0)
        sent_end = float(orig_sent.get("end", sent_start) or sent_start)

        # Fix leading punctuation before alignment
        new_texts = self._fix_leading_punctuation(new_texts)

        # Deterministic character-offset alignment against the original sentence's words.
        cleaned_texts = [self._clean_sentence_text(t, lang=lang) for t in new_texts]
        aligned_chunks = assign_words_by_char_offset(
            words_pool, cleaned_texts, sent_start, sent_end
        )

        result: List[Dict] = []
        for ac in aligned_chunks:
            if not str(ac.get("text", "")).strip():
                continue
            if ac.get("start") is None:
                # No words mapped onto this chunk — let interpolation fill timestamps.
                ac["start"] = round(sent_start, 4)
                ac["end"] = round(sent_end, 4)
            result.append(ac)

        # Last-resort interpolation only for chunks that still lack word timing.
        self._interpolate_missing_timestamps(result, sent_start, sent_end)

        return result

    @staticmethod
    def _interpolate_missing_timestamps(
        chunks: List[Dict], sent_start: float, sent_end: float
    ) -> None:
        """Fill in timestamps for chunks without word-level data using
        time interpolation proportional to character count."""
        if not chunks:
            return

        total_duration = max(sent_end - sent_start, 0.1)
        total_chars = sum(len(c.get("text", "")) for c in chunks) or 1

        # Calculate how much time is already assigned to chunks with words
        # and distribute remaining time to chunks without words
        has_any_words = any(c.get("words") for c in chunks)
        if not has_any_words:
            # No chunks have words — distribute all time proportionally
            current = sent_start
            for chunk in chunks:
                char_len = len(chunk.get("text", ""))
                duration = max(0.3, (char_len / total_chars) * total_duration)
                chunk["start"] = round(current, 4)
                chunk["end"] = round(current + duration, 4)
                current += duration
            return

        # Some chunks have words, some don't — interpolate the missing ones
        current = sent_start
        for chunk in chunks:
            char_len = len(chunk.get("text", ""))
            if chunk.get("words"):
                # Has word data — use it, but ensure start >= current
                w_start = float(chunk["words"][0].get("start", current))
                w_end = float(chunk["words"][-1].get("end", w_start + 0.3))
                chunk["start"] = round(max(w_start, current), 4)
                chunk["end"] = round(max(w_end, chunk["start"] + 0.1), 4)
                current = chunk["end"]
            else:
                # No word data — estimate duration from char count
                duration = max(0.3, (char_len / total_chars) * total_duration)
                chunk["start"] = round(current, 4)
                chunk["end"] = round(current + duration, 4)
                current += duration

    def _llm_split_single_strict(
        self,
        llm,
        original_text: str,
        max_length: int,
        lang: str = "auto",
    ) -> Optional[List[str]]:
        """Retry splitting a single sentence with a strict prompt that emphasises
        exact text preservation.  Returns the list of split texts or None on failure."""
        prompt = """You are a precise text segmentation assistant.

## CRITICAL RULE — STRICT TEXT PRESERVATION
You MUST NOT add, remove, or modify ANY character of the original text.
The concatenation of your output sentences must equal the original text exactly,
character for character, in the same order.

## Task
Split the following text into shorter sentences.
Each sentence must be AT MOST {max_length} characters.

## Splitting Rules
        - FIRST PRIORITY: Always try to split near the middle of the sentence at the most semantically natural point, so the resulting parts are as balanced in length as possible
        - PUNCTUATION BELONGS TO THE PRECEDING SENTENCE: When splitting at a punctuation mark, the punctuation MUST stay at the END of the preceding sentence, NEVER at the BEGINNING of the next sentence
        - NEVER produce a segment that starts with a punctuation mark (e.g., no segment should begin with 。！？，、；：.!?,;:)
        - NEVER produce a segment that contains only punctuation marks (e.g., a single period, comma, or question mark alone on one line)
        - NEVER produce a segment that contains only numbers or a single number
        - Split at natural boundaries: punctuation, clause breaks, conjunctions

## Original Text
{text}

## Output Format
Return a JSON array of strings, e.g. ["sentence1", "sentence2"]
Return ONLY the JSON array, no explanation.""".format(
            max_length=str(max_length),
            text=original_text,
        )

        try:
            resp = llm.chat("s03_sentence_split", prompt, response_json=True)
            if not isinstance(resp, list) or not resp:
                return None
            texts = [str(t).strip() for t in resp if str(t).strip()]
            if not texts:
                return None

            # Quick sanity: total chars should roughly match original
            orig_clean = re.sub(r"\s+", "", original_text)
            resp_clean = re.sub(r"\s+", "", "".join(texts))
            if abs(len(resp_clean) - len(orig_clean)) > max(2, len(orig_clean) * 0.15):
                print(f"[Split] Strict retry: char count mismatch ({len(resp_clean)} vs {len(orig_clean)}), discarding")
                return None

            return self._fix_leading_punctuation(texts)
        except Exception as e:
            print(f"[Split] Strict single-sentence LLM call failed: {e}")
            return None

    def _build_split_prompt(self, batch: List[tuple], max_length: int) -> dict:
        """Build the LLM prompt for a single batch of sentences."""
        segments = "\n".join(
            f"[{i}] {sent['text']}"
            for i, (_, sent) in enumerate(batch)
        )
        # Try to use JSON template via prompt service
        from backend.prompts.prompt_service import get_prompt_service
        svc = get_prompt_service()
        result = svc.assemble_prompt("s03_sentence_split", {
            "max_length": max_length,
            "segments": segments,
            "raw_segments": [{"index": i, "text": sent["text"]} for i, (_, sent) in enumerate(batch)],
        })
        if result.get("found"):
            return {
                "system_prompt": result.get("system_prompt") or "You are a precise text segmentation assistant.",
                "user_prompt": result.get("user_prompt")
            }
        
        # Fallback to hardcoded prompt
        return {
            "system_prompt": "You are a precise text segmentation assistant.",
            "user_prompt": (
                "## Task Requirements\n"
                "1. Split each text segment into multiple shorter sentences\n"
                f"2. Each resulting sentence must be AT MOST {max_length} characters\n"
                "3. Do NOT correct grammar, spelling, or punctuation — preserve the original text exactly\n\n"
                "## Splitting Guidelines\n"
                "- FIRST PRIORITY: Always try to split near the middle of the sentence at the most semantically natural point, so the resulting parts are as balanced in length as possible\n"
                "- PUNCTUATION BELONGS TO THE PRECEDING SENTENCE: When splitting at a punctuation mark (period, comma, question mark, exclamation, semicolon, etc.), the punctuation MUST stay at the END of the preceding sentence, NEVER at the BEGINNING of the next sentence\n"
                "- NEVER produce a segment that starts with a punctuation mark (e.g., no segment should begin with 。！？，、；：.!?,;:)\n"
                "- NEVER produce a segment that contains only punctuation marks (e.g., a single period, comma, or question mark alone on one line)\n"
                "- NEVER produce a segment that contains only numbers or a single number\n"
                "- Preserve semantic completeness - avoid splitting in the middle of phrases\n"
                "- Keep related words together (e.g., subject-verb, adjective-noun pairs)\n"
                "- If a segment contains multiple sentences, split at existing punctuation first\n"
                "- If a single sentence is still too long, split at logical pause points\n\n"
                "## Input Format\n"
                "You will receive text segments, each marked with [index]:\n"
                "[0] First text segment...\n"
                "[1] Second text segment...\n\n"
                "## Output Format\n"
                "Return a JSON object mapping each segment index to an array of split sentences:\n"
                '{"0": ["sentence1", "sentence2"], "1": ["sentence3", "sentence4"]}\n\n'
                "## Critical Constraints\n"
                "- You MUST return valid JSON format only\n"
                "- Do NOT include any explanatory text, only the JSON object\n"
                "- Do NOT merge content from different segments\n"
                "- Do NOT change the original text content — no corrections, no rephrasing\n"
                f"- If a segment is already short enough (<={max_length} chars), "
                "return it as a single-element array\n\n"
                f"## Segments to Split:\n{segments}\n\n"
                "Return ONLY the JSON object:"
            )
        }

    def _llm_split_batch(self, sentences: List[Dict],
                          all_words: List[Dict],
                          max_length: int,
                          callback: Optional[Callable] = None,
                          lang: str = "auto") -> List[Dict]:
        """Send long sentences to LLM for intelligent splitting,
        then rebuild timestamps from word-level data.

        Uses smart batching (based on max_request_chars) and concurrent
        requests (based on max_concurrent) for better performance.
        """
        to_split = [(i, s) for i, s in enumerate(sentences) if len(s["text"]) > max_length]
        if not to_split:
            return sentences

        from backend.llm.llm_client import get_llm_client

        llm = get_llm_client()
        max_chars = int(config.get("llm.max_request_chars") or 12000)
        max_concurrent = int(config.get("llm.max_concurrent") or 10)

        # Smart batching: group sentences so total chars per batch <= max_chars
        batches = self._build_smart_batches(to_split, max_chars)
        print(f"[Split] {len(to_split)} sentences -> {len(batches)} batches "
              f"(max_chars={max_chars}, max_concurrent={max_concurrent})")

        # Build LLM requests for all batches
        requests = []
        for batch in batches:
            prompt_data = self._build_split_prompt(batch, max_length)
            requests.append({
                "step_name": "s03_sentence_split",
                "prompt": prompt_data["user_prompt"],
                "system_prompt": prompt_data["system_prompt"],
                "response_json": True,
            })

        # Concurrent LLM requests
        if callback:
            callback(55, f"Sending {len(batches)} LM split requests concurrently...")

        try:
            results = llm.batch_chat(requests, max_workers=max_concurrent)
        except Exception as e:
            print(f"[Split] batch_chat failed entirely: {e}")
            # Return sentences unchanged — caller will try fallback methods
            return sentences

        # Process results and align timestamps
        result = list(sentences)
        # 记录未成功拆分（错误 / 非 dict / 抢救失败）批次的原始句子索引，供严格重试
        failed_indices: List[int] = []

        for batch_idx, (batch, llm_result) in enumerate(zip(batches, results)):
            if isinstance(llm_result, dict) and "error" in llm_result:
                print(f"[Split] Batch {batch_idx} failed: {llm_result['error']}")
                failed_indices.extend(i for i, _ in batch)
                continue

            if isinstance(llm_result, str):
                # 模型可能忽略了 response_format 返回纯文本，尝试从中抢救 JSON
                print(f"[Split] Batch {batch_idx} returned str, salvaging JSON from: {llm_result[:200]!r}")
                llm_result = self._salvage_json_response(llm_result)
                if not isinstance(llm_result, dict):
                    print(f"[Split] Batch {batch_idx} salvage failed, its sentences will strict-retry")
                    failed_indices.extend(i for i, _ in batch)
                    continue

            if not isinstance(llm_result, dict):
                print(f"[Split] Batch {batch_idx} returned non-dict: {type(llm_result)}")
                failed_indices.extend(i for i, _ in batch)
                continue

            for batch_item_idx_str, new_texts in llm_result.items():
                if not isinstance(new_texts, list):
                    continue
                batch_item_idx = int(batch_item_idx_str)
                if batch_item_idx >= len(batch):
                    continue
                orig_idx, orig_sent = batch[batch_item_idx]

                # Align timestamps. This is a node-internal step — a failure here
                # is NOT an LLM failure, so handle it locally and route the
                # sentence to strict retry instead of aborting the whole batch.
                try:
                    aligned_result = self._align_split_result(new_texts, orig_sent, lang)
                except Exception as align_err:
                    print(f"[Split] Batch {batch_idx} sentence {orig_idx} alignment failed "
                          f"(node-internal, not an LLM error): {align_err}")
                    failed_indices.append(orig_idx)
                    continue
                result[orig_idx] = aligned_result

            if callback:
                pct = min(85, 55 + int((batch_idx + 1) / len(batches) * 30))
                callback(pct, f"Processed batch {batch_idx + 1}/{len(batches)}")

        # Build a map from original index -> original sentence for retry context
        orig_sent_map = {i: s for i, s in enumerate(sentences)}

        # 失败批次（模型未返回可解析 JSON）的句子先走单句严格重试
        failed_indices = sorted(set(failed_indices))
        if failed_indices:
            print(f"[Split] {len(failed_indices)} sentences from failed batches, retrying strictly...")
            retry_results = self._strict_retry_with_context(
                result, failed_indices, orig_sent_map, max_length, lang, max_retries=2
            )
            for idx, retry_result in retry_results:
                result[idx] = retry_result

        # Collect alignment failures for strict retry
        alignment_failures = []
        for idx, item in enumerate(result):
            if isinstance(item, list):
                # This was replaced by LLM split result
                if any(not s.get("words") for s in item):
                    alignment_failures.append(idx)
            elif isinstance(item, dict) and not item.get("words"):
                if len(item.get("text", "")) > max_length:
                    alignment_failures.append(idx)

        if alignment_failures:
            print(f"[Split] {len(alignment_failures)} sentences with alignment failures, retrying...")
            retry_results = self._strict_retry_with_context(
                result, alignment_failures, orig_sent_map, max_length, lang, max_retries=2
            )
            for idx, retry_result in retry_results:
                result[idx] = retry_result

        # Flatten nested lists
        flat = []
        for item in result:
            if isinstance(item, list):
                flat.extend(item)
            else:
                flat.append(item)
        return flat

    def _strict_retry_with_context(
        self,
        result: List,
        failure_indices: List[int],
        orig_sent_map: Dict[int, Dict],
        max_length: int,
        lang: str = "auto",
        max_retries: int = 1,
    ) -> List[tuple]:
        """Retry failed alignment sentences with strict prompt.
        Limited to at most 10 sentences to avoid long waits.
        Returns list of (idx, aligned_result) tuples.
        """
        from backend.llm.llm_client import get_llm_client
        llm = get_llm_client()
        updates = []

        # Limit retries to avoid excessive wait time
        retry_limit = min(len(failure_indices), 10)
        if len(failure_indices) > retry_limit:
            print(f"[Split] Limiting strict retries to {retry_limit} of {len(failure_indices)} failures")

        for idx in failure_indices[:retry_limit]:
            orig_sent = orig_sent_map.get(idx)
            if not orig_sent:
                continue

            original_text = orig_sent.get("text", "")
            if not original_text or len(original_text) <= max_length:
                continue

            try:
                strict_texts = self._llm_split_single_strict(
                    llm, original_text, max_length, lang
                )
                if not strict_texts:
                    continue

                aligned = self._align_split_result(strict_texts, orig_sent, lang)
                # Accept if at least some chunks got word-level timestamps
                has_words = sum(1 for s in aligned if s.get("words"))
                if has_words > 0:
                    updates.append((idx, aligned))
                    print(f"[Split] Strict retry succeeded for sentence {idx} "
                          f"({has_words}/{len(aligned)} chunks with words)")

            except Exception as e:
                print(f"[Split] Strict retry for sentence {idx} failed: {e}")

        return updates

    def _force_split_by_chars(
        self,
        sentences: List[Dict],
        max_length: int,
        lang: str = "auto",
    ) -> List[Dict]:
        """Force-split sentences that still exceed max_length after LLM processing.

        - English/alphabetic: split at word boundaries (spaces)
        - Chinese/CJK: use jieba segmentation, split at word boundaries
        """
        try:
            import jieba
            has_jieba = True
        except ImportError:
            has_jieba = False

        result = []
        puncts = self._load_language_puncts(lang)
        terminals = puncts.get("sentence_ends", set())
        for sent in sentences:
            text = sent.get("text", "")
            if len(text) <= max_length:
                result.append(sent)
                continue

            # Pre-split at sentence-terminal punctuation to avoid chunks crossing
            # sentence boundaries, then split each sub-segment by character budget.
            segments = self._pre_split_at_terminals(text, terminals)
            sent_chunks = []
            for segment_text in segments:
                if self._is_compact_spacing_language(lang):
                    sent_chunks.extend(self._split_chinese_by_chars(segment_text, max_length, has_jieba))
                else:
                    sent_chunks.extend(self._split_english_by_chars(segment_text, max_length))

            # The final chunks are substrings of `text`; align them against the
            # sentence's words in one deterministic character-offset pass.
            aligned = assign_words_by_char_offset(
                list(sent.get("words", []) or []),
                sent_chunks,
                float(sent.get("start", 0) or 0),
                float(sent.get("end", 0) or 0),
            )
            for ac in aligned:
                if not str(ac.get("text", "")).strip():
                    continue
                if ac.get("start") is None:
                    ac["start"] = round(float(sent.get("start", 0) or 0), 4)
                    ac["end"] = round(float(sent.get("end", 0) or 0), 4)
                result.append(ac)

        return result

    # ── main run ─────────────────────────────────────────────────────

    def _split_at_internal_terminals(
        self, sentences: List[Dict], lang: str = "auto"
    ) -> List[Dict]:
        """Split sentences that contain internal sentence-terminal punctuation.

        Force-splitting by character count can group multiple sentences
        together (e.g. '找男人。再有来女人嘛。').  This re-splits them
        at sentence-terminal boundaries.
        """
        puncts = self._load_language_puncts(lang)
        terminals = puncts.get("sentence_ends", set())

        result = []
        for sent in sentences:
            text = str(sent.get("text", ""))
            words = list(sent.get("words", []) or [])

            if not words or len(words) < 2:
                result.append(sent)
                continue

            # Find word indices where the word IS a sentence-terminal punctuation
            # and the preceding word is NOT already terminal-ending
            split_indices = []
            for i, word in enumerate(words):
                word_text = str(word.get("word", "")).strip()
                if not word_text:
                    continue
                # Check if this word is a terminal character
                if len(word_text) == 1 and word_text in terminals:
                    # Only split if there's content before and after
                    if i > 0 and i < len(words) - 1:
                        split_indices.append(i)

            if not split_indices:
                result.append(sent)
                continue

            # Build split sentences from the word groups
            start = 0
            for split_idx in split_indices:
                # Include the terminal punctuation in this chunk
                chunk_words = words[start:split_idx + 1]
                if chunk_words:
                    chunk_text = self._sentence_text_from_words(chunk_words, "", lang=lang)
                    if chunk_text:
                        result.append({
                            "text": chunk_text,
                            "start": chunk_words[0].get("start", sent.get("start", 0)),
                            "end": chunk_words[-1].get("end", sent.get("end", 0)),
                            "words": chunk_words,
                        })
                start = split_idx + 1

            # Remaining words
            remaining_words = words[start:]
            if remaining_words:
                remaining_text = self._sentence_text_from_words(remaining_words, "", lang=lang)
                if remaining_text:
                    result.append({
                        "text": remaining_text,
                        "start": remaining_words[0].get("start", sent.get("start", 0)),
                        "end": remaining_words[-1].get("end", sent.get("end", 0)),
                        "words": remaining_words,
                    })
                elif result:
                    # Merge remaining words (likely just punctuation) into previous
                    prev = result[-1]
                    prev["words"] = list(prev.get("words", [])) + remaining_words
                    prev["end"] = max(
                        float(prev.get("end", 0) or 0),
                        float(remaining_words[-1].get("end", prev.get("end", 0)) or 0),
                    )
                    prev_text = str(prev.get("text", ""))
                    remaining_text = self._sentence_text_from_words(remaining_words, "", lang=lang)
                    prev["text"] = prev_text.rstrip() + remaining_text

        return result

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        if callback:
            callback(5, "Loading ASR results...")

        # 只从当前节点卡片读取参数，不再回退到全局 config.yaml
        max_length = int(self._get_param("max_sentence_length", 30))
        use_llm = self._get_bool_param("use_llm_split", True)
        split_sentence_ends = self._get_param("split_sentence_ends", None)
        split_clause_breaks = self._get_param("split_clause_breaks", None)
        split_by_punct = self._get_param("split_by_punct", None)
        if split_sentence_ends is None and split_clause_breaks is None:
            if split_by_punct is None:
                split_sentence_ends = True
                split_clause_breaks = True
            else:
                split_sentence_ends = self._coerce_bool(split_by_punct, True)
                split_clause_breaks = self._coerce_bool(split_by_punct, True)
        else:
            if split_sentence_ends is None:
                split_sentence_ends = self._coerce_bool(split_by_punct, True) if split_by_punct is not None else True
            if split_clause_breaks is None:
                split_clause_breaks = self._coerce_bool(split_by_punct, True) if split_by_punct is not None else True
        split_sentence_ends = self._coerce_bool(split_sentence_ends, True)
        split_clause_breaks = self._coerce_bool(split_clause_breaks, True)
        merge_min_duration = float(self._get_param("merge_min_duration", 0.5))
        merge_max_gap = float(self._get_param("merge_max_gap", 0.5))
        pause_threshold = float(self._get_param("pause_split_threshold", 1.0))
        split_on_speaker = self._get_bool_param("split_on_speaker", False)
        # 是否执行各操作的勾选开关（与内置节点默认配置保持一致）
        merge_short_enabled = self._get_bool_param("merge_short_enabled", True)
        merge_gap_enabled = self._get_bool_param("merge_gap_enabled", True)
        pause_split_enabled = self._get_bool_param("pause_split_enabled", True)
        if not pause_split_enabled:
            pause_threshold = 0  # 关闭停顿断句（含最终合并的间隔限制）

        # 诊断：打印本节点实际生效的参数（排查“改参数无效”时对照 backend 日志）
        print(
            f"[Split] effective params -> node_config={json.dumps(getattr(self, '_node_config', {}) or {}, ensure_ascii=False)} "
            f"max_length={max_length} use_llm={use_llm} split_sentence_ends={split_sentence_ends} split_clause_breaks={split_clause_breaks} "
            f"merge_min_duration={merge_min_duration} merge_max_gap={merge_max_gap} "
            f"pause_threshold={pause_threshold} split_on_speaker={split_on_speaker} "
            f"merge_short_enabled={merge_short_enabled} merge_gap_enabled={merge_gap_enabled} pause_split_enabled={pause_split_enabled}"
        )

        # Load ASR results
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        asr_path = step_inputs.get("subtitle") or find_artifact(os.path.join(task_dir, "cache"), "asr_result.json")
        if not asr_path:
            raise FileNotFoundError("ASR result not found in cache directory")
        if not os.path.isabs(asr_path):
            asr_path = os.path.join(task_dir, asr_path)
        with open(asr_path, "r", encoding="utf-8") as f:
            asr_data = json.load(f)

        segments = asr_data.get("segments", [])
        if not segments:
            raise ValueError("No segments found in ASR results")

        if callback:
            callback(15, f"Processing {len(segments)} segments...")

        # Build global word index
        all_words = self._build_words_index(segments)

        # Step 0 (highest priority): cut on speaker change
        # Only effective when the user enabled the switch AND the ASR output
        # actually contains multi-speaker info. Otherwise it's a no-op so
        # single-speaker content is untouched.
        speaker_active = False
        if split_on_speaker and self._has_multi_speaker(segments):
            if callback:
                callback(18, "Splitting by speaker change...")
            segments = self._split_by_speaker(segments, merge_min_duration, merge_max_gap)
            speaker_active = True
            print(f"[Split] Speaker-based cut active (multi-speaker ASR detected)")

        # Step 1: Split by punctuation, align word timestamps
        # Read language from input node config (same as ASR step logic)
        detected_lang = self._resolve_language(task_dir)
        self._resolved_language = detected_lang
        print(f"[Split] Language for punctuation: {detected_lang}")

        # Adjust max_length based on language weight
        max_length = self._get_effective_max_length(max_length, detected_lang)

        if callback:
            callback(35, "Splitting by pauses and punctuation...")
        sentences = self._split_by_punctuation(
            segments, all_words, max_length,
            lang=detected_lang,
            split_sentence_ends=split_sentence_ends,
            split_clause_breaks=split_clause_breaks,
        )

        if pause_split_enabled and pause_threshold > 0:
            sentences = self._split_by_pause(sentences, pause_threshold, lang=detected_lang)

        if merge_short_enabled or merge_gap_enabled:
            if callback:
                callback(40, "Merging short sentences...")
            if merge_short_enabled:
                sentences = self._merge_short_sentences(
                    sentences,
                    max_length,
                    lang=detected_lang,
                    gap_threshold=pause_threshold,
                )
            if merge_gap_enabled:
                sentences = self._merge_close_gap_sentences(
                    sentences,
                    max_length,
                    max_gap=merge_max_gap,
                    lang=detected_lang,
                )

        sentences = self._finalize_sentences(sentences, lang=detected_lang)

        # Step 2: LLM split for sentences still exceeding max_length (up to 3 rounds)
        if use_llm:
            max_llm_rounds = 3
            for llm_round in range(max_llm_rounds):
                long_sentences = [s for s in sentences if len(s["text"]) > max_length]
                if not long_sentences:
                    break

                round_label = f"Round {llm_round + 1}/{max_llm_rounds}"
                if callback:
                    callback(
                        50 + llm_round * 10,
                        f"LLM splitting {len(long_sentences)} sentences ({round_label})..."
                    )

                print(f"[Split] LLM round {llm_round + 1}: {len(long_sentences)} sentences to split")

                try:
                    sentences = self._llm_split_batch(
                        sentences, all_words, max_length, callback, lang=detected_lang
                    )
                except Exception as e:
                    print(f"[Split] LLM split batch error (round {llm_round + 1}; "
                          f"node-internal/post-processing, NOT an LLM request failure): {e}")
                    # 安全降级：跳过本轮 LLM 拆分，继续走规则拆分兜底

                # Fix alignment mismatches and finalize timestamps
                sentences = self._validate_and_fix_alignment(sentences)
                sentences = self._finalize_sentences(sentences, lang=detected_lang)

        # Step 3: Final character-based fallback for any remaining long sentences
        still_long = [s for s in sentences if len(s["text"]) > max_length]
        if still_long:
            print(f"[Split] {len(still_long)} sentences still exceed {max_length} chars, splitting by word boundaries")
            if callback:
                callback(90, f"Force-splitting {len(still_long)} remaining long sentences by word boundaries...")
            sentences = self._force_split_by_chars(sentences, max_length, detected_lang)
            sentences = self._split_at_internal_terminals(sentences, lang=detected_lang)
            sentences = self._finalize_sentences(sentences, lang=detected_lang)

        if callback:
            callback(95, f"Saving {len(sentences)} sentences...")

        # Save results
        node_suffix = f"_{self._node_id}" if self._node_id else ""
        out_path = os.path.join(task_dir, "cache", f"sentences{node_suffix}.json")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(sentences, f, ensure_ascii=False, indent=2)

        # Save plain text: one sentence per line
        # When multi-speaker is detected, prefix each line with speaker ID
        has_speaker_info = any(
            (sent.get("words") or [{}])[0].get("speaker", "")
            for sent in sentences
            if sent.get("words")
        )
        txt_path = os.path.join(task_dir, "cache", f"sentences_text{node_suffix}.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            for sent in sentences:
                text = sent.get("text", "").strip()
                if has_speaker_info and text:
                    words = sent.get("words", [])
                    speaker = words[0].get("speaker", "") if words else ""
                    if speaker:
                        f.write(f"{speaker}：{text}\n")
                    else:
                        f.write(text + "\n")
                else:
                    f.write(text + "\n")

        if callback:
            callback(100, f"Split into {len(sentences)} sentences")

        return {
            "artifacts": [f"cache/sentences{node_suffix}.json", f"cache/sentences_text{node_suffix}.txt"],
            "outputs": {
                "subtitle": f"cache/sentences{node_suffix}.json",
                "text": f"cache/sentences_text{node_suffix}.txt",
            },
        }


# Bind reusable pure helpers (extracted to backend.utils.sentence_split_core) back
# onto the class as staticmethods so the existing self._xxx call sites keep working
# unchanged.
S03SentenceSplit._load_language_char_weights = staticmethod(load_language_char_weights)
S03SentenceSplit._sentence_gap = staticmethod(sentence_gap)
S03SentenceSplit._normalize_word_spans = staticmethod(normalize_word_spans)
S03SentenceSplit._is_all_punctuation_or_whitespace = staticmethod(is_all_punctuation_or_whitespace)
S03SentenceSplit._normalize_text_for_alignment_check = staticmethod(normalize_text_for_alignment_check)
S03SentenceSplit._has_multi_speaker = staticmethod(has_multi_speaker)
S03SentenceSplit._salvage_json_response = staticmethod(salvage_json_response)
S03SentenceSplit._build_smart_batches = staticmethod(build_smart_batches)
S03SentenceSplit._pre_split_at_terminals = staticmethod(pre_split_at_terminals)
S03SentenceSplit._fix_leading_punctuation = staticmethod(fix_leading_punctuation)
S03SentenceSplit._split_chinese_by_chars = staticmethod(split_chinese_by_chars)
S03SentenceSplit._split_english_by_chars = staticmethod(split_english_by_chars)
S03SentenceSplit._distribute_timestamps_to_chunks = staticmethod(distribute_timestamps_to_chunks)
