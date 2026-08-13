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
        """Read param from node config first, then global config."""
        node_cfg = getattr(self, "_node_config", {}) or {}
        val = node_cfg.get(key)
        if val is not None and val != "":
            return val
        val = config.get(f"general.{key}")
        return val if val is not None else default

    def _get_bool_param(self, key: str, default: bool = False) -> bool:
        """Read a boolean param, tolerating string values like "true"/"false"."""
        val = self._get_param(key, default)
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in ("1", "true", "yes", "on")

    @staticmethod
    def _load_language_char_weights() -> Dict[str, float]:
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
        """Languages like zh/ja/ko should not keep internal whitespace."""
        raw = str(lang or "").strip()
        lowered = raw.lower()
        return (
            lowered.startswith(("zh", "ja", "ko"))
            or raw in {"中文", "日语", "日文", "韩语", "韩文"}
            or lowered in {"chinese", "japanese", "korean"}
        )

    def _clean_sentence_text(self, text: str, lang: Optional[str] = None) -> str:
        """Normalize sentence text so outputs are clean and stable."""
        text = str(text or "").replace("\u3000", " ")
        if self._is_compact_spacing_language(lang or getattr(self, "_resolved_language", "auto")):
            return re.sub(r"\s+", "", text).strip()
        return re.sub(r"\s+", " ", text).strip()

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

    @staticmethod
    def _sentence_gap(left: Dict, right: Dict) -> float:
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

    @staticmethod
    def _normalize_word_spans(words: List[Dict], start_hint: float, end_hint: float) -> List[Dict]:
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

    @staticmethod
    def _is_all_punctuation_or_whitespace(text: str) -> bool:
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
        """Merge sentences that are too short into adjacent sentences.

        A sentence is considered "too short" if its cleaned text length is
        <= max_length * 0.3.  Merging prefers the shorter neighbor to keep
        resulting lengths balanced.  Skips merging across speaker boundaries
        when speaker info is present.
        """
        if len(sentences) <= 1:
            return sentences

        compact = self._is_compact_spacing_language(lang)
        min_len = max(3, int(max_length * 0.3))
        gap_limit = float(gap_threshold or 0)

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
            if self._is_sentence_terminal(left.get("text", ""), lang=lang):
                print(f"[Split] Merge blocked by terminal punctuation: {left.get('text', '')!r}")
                return False
            gap = self._sentence_gap(left, right)
            if gap_limit > 0 and gap > gap_limit:
                print(f"[Split] Merge blocked by large gap: {gap:.2f}s")
                return False
            return True

        result = list(sentences)
        i = 0
        while i < len(result):
            cur = result[i]
            if _text_len(cur) > min_len:
                i += 1
                continue

            # Try merging with previous neighbor first, then next
            prev_ok = i > 0
            next_ok = i < len(result) - 1

            if prev_ok:
                prev = result[i - 1]
                prev_ok = _can_merge(prev, cur)

            if next_ok and not prev_ok:
                nxt = result[i + 1]
                next_ok = _can_merge(cur, nxt)

            if prev_ok:
                prev = result[i - 1]
                sep = "" if compact else " "
                prev["text"] = prev["text"].rstrip() + sep + cur["text"].strip()
                prev["end"] = cur.get("end", prev["end"])
                prev["words"] = (prev.get("words", []) or []) + (cur.get("words", []) or [])
                result.pop(i)
                # Don't advance i — recheck the merged result
                continue

            if next_ok:
                nxt = result[i + 1]
                sep = "" if compact else " "
                cur["text"] = cur["text"].rstrip() + sep + nxt["text"].strip()
                cur["end"] = nxt.get("end", cur["end"])
                cur["words"] = (cur.get("words", []) or []) + (nxt.get("words", []) or [])
                result.pop(i + 1)
                continue

            # Neither neighbor can accept — keep as is
            i += 1

        # Reassign ids
        for idx, s in enumerate(result, start=1):
            s["id"] = idx
        return result

    @staticmethod
    def _normalize_text_for_alignment_check(text: str) -> str:
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
        """Load sentence-ending and clause-break punctuation for a given language.
        Merges language-specific puncts with the _common set for broader coverage."""
        cache_key = lang
        if cache_key in cls._PUNCTS_CACHE:
            return cls._PUNCTS_CACHE[cache_key]

        puncts_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "language_puncts.json"
        )
        try:
            with open(puncts_path, "r", encoding="utf-8") as f:
                all_puncts = json.load(f)
        except Exception:
            all_puncts = {}

        # Load _common punctuation (full-width + half-width)
        common = all_puncts.get("_common", {})
        common_ends = set(common.get("sentence_ends", []))
        common_breaks = set(common.get("clause_breaks", []))

        # Resolve: try exact lang, then base lang (e.g. "zh" from "zh-yue-hk"), then default
        lang_base = lang.split("-")[0] if "-" in lang else lang
        entry = all_puncts.get(lang) or all_puncts.get(lang_base) or all_puncts.get("_default", {})

        # Merge: language-specific + common (deduplicated via set union)
        result = {
            "sentence_ends": set(entry.get("sentence_ends", [".", "!", "?"])) | common_ends,
            "clause_breaks": set(entry.get("clause_breaks", [","])) | common_breaks,
        }
        cls._PUNCTS_CACHE[cache_key] = result
        return result

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

    def _has_multi_speaker(self, segments: List[Dict]) -> bool:
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
        """Resolve language from input node config, falling back to ASR output, then auto."""
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
        """Check if the punctuation char at pos is part of a number or math expression.

        Returns True for:
        - Decimal points: 3.14, 0.5
        - Thousands separators: 1,000, 10,000
        - Full-width variants: ３。１４ (unlikely but safe)
        Also protects trailing math context: "5." at end of "x = 5." is ambiguous,
        but "5." followed by a digit is a decimal.
        """
        if pos < 0 or pos >= len(text):
            return False
        ch = text[pos]
        # Only check punctuation that could be part of a number
        if ch not in ".,，":
            return False

        digits = "0123456789０１２３４５６７８９"
        prev_ch = text[pos - 1] if pos > 0 else ""
        next_ch = text[pos + 1] if pos + 1 < len(text) else ""

        # Decimal point or thousands separator: digit PUNCT digit  (e.g. 3.14, 1,000)
        if prev_ch in digits and next_ch in digits:
            return True

        # Trailing decimal like "3." at end of token followed by digit in next token
        # e.g. "3. 14" — treat as decimal if next non-space char is a digit
        if prev_ch in digits:
            # Look ahead past whitespace
            j = pos + 1
            while j < len(text) and text[j] in " \t":
                j += 1
            if j < len(text) and text[j] in digits:
                return True

        return False

    @staticmethod
    def _split_text_by_ends(text: str, sentence_ends: set) -> List[str]:
        """Phase 1: hard cut on sentence-ending punctuation (。！？； etc).

        Each chunk keeps its trailing delimiter. A trailing segment without
        any terminator is preserved as the final chunk.
        Skips punctuation that is part of a number (e.g. 3.14, 1,000).
        """
        if not text:
            return []
        chunks: List[str] = []
        current = ""
        for i, ch in enumerate(text):
            current += ch
            if ch in sentence_ends:
                # Don't split if this punctuation is part of a number
                if S03SentenceSplit._is_part_of_number(text, i):
                    continue
                chunks.append(current)
                current = ""
        if current.strip():
            chunks.append(current)
        return chunks

    @staticmethod
    def _split_text_by_clauses(text: str, clause_breaks: set,
                                max_length: int) -> List[str]:
        """Phase 2: cut on clause-level punctuation, but only when the
        chunk would otherwise exceed max_length.

        Tokens are accumulated greedily: a token is added to the current
        buffer; once adding it would exceed max_length, the buffer is
        flushed and a new one starts. Stops at the first sentence-end
        already inside the buffer to avoid cross-sentence leakage.
        Skips punctuation that is part of a number (e.g. 3.14, 1,000).
        """
        if not text:
            return []

        # Tokenize: each token ends at a clause-break char and keeps that char
        tokens: List[str] = []
        current = ""
        for i, ch in enumerate(text):
            current += ch
            if ch in clause_breaks:
                # Don't split if this punctuation is part of a number
                if S03SentenceSplit._is_part_of_number(text, i):
                    continue
                tokens.append(current)
                current = ""
        if current.strip():
            tokens.append(current)

        chunks: List[str] = []
        buf = ""
        for tok in tokens:
            if not buf:
                buf = tok
                continue
            if len(buf) + len(tok) <= max_length:
                buf += tok
            else:
                # If current token is very short, prefer merging it with the
                # previous buf (even if slightly over max_length) instead of
                # producing a tiny standalone chunk.
                if len(tok) <= max_length * 0.2:
                    buf += tok
                    chunks.append(buf.strip())
                    buf = ""
                else:
                    chunks.append(buf.strip())
                    buf = tok
        if buf.strip():
            chunks.append(buf.strip())
        return chunks

    def _split_by_punctuation(self, sentences: List[Dict],
                            all_words: List[Dict],
                            max_length: int,
                            lang: str = "auto",
                            pause_threshold: float = 2.0,
                            force_all: bool = False) -> List[Dict]:
        """Two-phase split by language-specific punctuation.

        Phase 1: hard cut on `sentence_ends` (。！？；) so every real
        sentence boundary is preserved.

        Phase 2: for chunks that still exceed `max_length`, cut on
        `clause_breaks` (,，、) to break long sentences into smaller
        pieces, while still respecting `max_length`.

        Args:
            force_all: If True, run Phase 1 on ALL sentences regardless
                       of length (preserves all punctuation boundaries).
                       If False, only process sentences longer than max_length.

        Chunks still over `max_length` after phase 2 are left intact for
        downstream LLM fallback to handle.

        Punctuation loaded from backend/config/language_puncts.json
        based on the detected language from upstream ASR.
        """
        puncts = self._load_language_puncts(lang)
        sentence_ends = puncts["sentence_ends"]
        clause_breaks = puncts["clause_breaks"]
        if pause_threshold > 0:
            sentences = self._split_by_pause(sentences, pause_threshold, lang=lang)

        result: List[Dict] = []

        for sent in sentences:
            text = sent["text"].strip()
            text = self._clean_sentence_text(text, lang=lang)
            words_pool = list(sent.get("words", []))
            sent_start = sent["start"]
            sent_end = sent["end"]

            # When force_all=False, short sentences pass through untouched
            if not force_all and len(text) <= max_length:
                result.append({
                    "text": text,
                    "start": sent_start,
                    "end": sent_end,
                    "words": words_pool,
                })
                continue

            # Phase 1: cut on sentence-end punctuation
            phase1_chunks = self._split_text_by_ends(text, sentence_ends)
            if not phase1_chunks:
                phase1_chunks = [text]

            # Phase 2: for each phase-1 chunk, if still over max_length,
            # apply clause-level splitting
            final_text_chunks: List[str] = []
            for chunk in phase1_chunks:
                if len(chunk) > max_length and clause_breaks:
                    final_text_chunks.extend(
                        self._split_text_by_clauses(chunk, clause_breaks, max_length)
                    )
                else:
                    final_text_chunks.append(chunk)

            # If only one chunk and it equals original text (no split happened),
            # just pass through
            if len(final_text_chunks) == 1 and final_text_chunks[0].strip() == text:
                result.append({
                    "text": text,
                    "start": sent_start,
                    "end": sent_end,
                    "words": words_pool,
                })
                continue

            # Align each final chunk to word timestamps
            words_remaining = words_pool
            hint = sent_start
            for chunk in final_text_chunks:
                if not chunk.strip():
                    continue
                aligned, consumed_count = self._align_chunk_to_local_words(
                    chunk, words_remaining, hint, sent_end
                )
                if not aligned["words"]:
                    aligned = self._align_sentence_to_words(
                        chunk, words_remaining, hint, sent_end
                    )
                if aligned["words"]:
                    hint = aligned["words"][-1]["end"]
                    if consumed_count > 0:
                        words_remaining = words_remaining[consumed_count:]
                result.append(aligned)

        if pause_threshold > 0:
            result = self._split_by_pause(result, pause_threshold, lang=lang)
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
        hint = sent_start

        # Fix leading punctuation before alignment
        new_texts = self._fix_leading_punctuation(new_texts)

        result: List[Dict] = []
        for chunk in new_texts:
            chunk_text = self._clean_sentence_text(chunk, lang=lang)
            if not chunk_text:
                continue
            aligned, consumed = self._align_chunk_to_local_words(
                chunk_text, words_pool, hint, sent_end
            )
            if not aligned.get("words"):
                # Fallback to broader matching
                aligned = self._align_sentence_to_words(
                    chunk_text, words_pool, hint, sent_end
                )
            if aligned.get("words"):
                hint = float(aligned["words"][-1].get("end", hint))
                if consumed > 0:
                    words_pool = words_pool[consumed:]
            result.append(aligned)

        # Post-pass: interpolate timestamps for chunks that have no words
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

    @staticmethod
    def _salvage_json_response(content: str):
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

    def _build_smart_batches(
        self,
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

                # Align timestamps
                aligned_result = self._align_split_result(new_texts, orig_sent, lang)
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

    @staticmethod
    def _pre_split_at_terminals(text: str, terminals: set) -> List[str]:
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

            # Pre-split at sentence-terminal punctuation to avoid
            # jieba chunks crossing sentence boundaries
            segments = self._pre_split_at_terminals(text, terminals)
            
            for segment_text in segments:
                if self._is_compact_spacing_language(lang):
                    chunks = self._split_chinese_by_chars(segment_text, max_length, has_jieba)
                else:
                    chunks = self._split_english_by_chars(segment_text, max_length)
                result.extend(self._distribute_timestamps_to_chunks(sent, chunks))

        return result

    def _split_chinese_by_chars(
        self, text: str, max_length: int, has_jieba: bool = True
    ) -> List[str]:
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

        return self._fix_leading_punctuation(chunks)

    @staticmethod
    def _fix_leading_punctuation(chunks: List[str]) -> List[str]:
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

    def _split_english_by_chars(self, text: str, max_length: int) -> List[str]:
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

        return self._fix_leading_punctuation(chunks)

    def _distribute_timestamps_to_chunks(
        self, original_sent: Dict, chunks: List[str]
    ) -> List[Dict]:
        """Distribute timestamps from original sentence to split chunks."""
        words = original_sent.get("words", [])
        start = original_sent.get("start", 0)
        end = original_sent.get("end", 0)

        if not chunks:
            return [original_sent]

        if not words:
            # No word-level data, distribute evenly by char count
            total_chars = sum(len(c) for c in chunks)
            current_time = start
            result = []
            for chunk in chunks:
                chunk_duration = (len(chunk) / total_chars) * (end - start) if total_chars > 0 else 0
                result.append({
                    "text": chunk,
                    "start": round(current_time, 4),
                    "end": round(current_time + chunk_duration, 4),
                    "words": [],
                })
                current_time += chunk_duration
            return result

        # Distribute using word timestamps
        result = []
        word_idx = 0
        for chunk in chunks:
            chunk_clean = re.sub(r"\s+", "", chunk)
            matched_words = []
            pos = 0

            while word_idx < len(words) and pos < len(chunk_clean):
                word_text = re.sub(r"\s+", "", str(words[word_idx].get("word", "")))
                if chunk_clean.startswith(word_text, pos):
                    matched_words.append(words[word_idx])
                    pos += len(word_text)
                    word_idx += 1
                else:
                    break

            if matched_words:
                chunk_start = float(matched_words[0].get("start", start))
                chunk_end = float(matched_words[-1].get("end", end))
            else:
                chunk_start = start
                chunk_end = end

            result.append({
                "text": chunk,
                "start": round(chunk_start, 4),
                "end": round(chunk_end, 4),
                "words": matched_words,
            })

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

        # Load params: node config first, then config.yaml
        max_length = int(self._get_param("max_sentence_length", 30))
        use_llm = self._get_param("use_llm_split", True)
        split_by_punct = bool(self._get_param("split_by_punct", True))
        merge_min_duration = float(self._get_param("merge_min_duration", 0.5))
        merge_max_gap = float(self._get_param("merge_max_gap", 0.5))
        pause_threshold = float(self._get_param("pause_split_threshold", 1.0))
        split_on_speaker = bool(self._get_param("split_on_speaker", False))
        # 是否执行各操作的勾选开关（默认开启，兼容旧工作流缺省配置）
        merge_short_enabled = self._get_bool_param("merge_short_enabled", True)
        merge_gap_enabled = self._get_bool_param("merge_gap_enabled", True)
        pause_split_enabled = self._get_bool_param("pause_split_enabled", True)
        if not pause_split_enabled:
            pause_threshold = 0  # 关闭停顿断句（含最终合并的间隔限制）

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

        # Step 1: Merge short segments（按勾选控制是否执行时长/间隔合并）
        if merge_short_enabled or merge_gap_enabled:
            if callback:
                callback(20, "Merging short segments...")
            sentences = self._merge_short_segments(
                segments, merge_min_duration, merge_max_gap,
                enable_duration=merge_short_enabled, enable_gap=merge_gap_enabled,
            )
        else:
            sentences = segments

        # Step 2: Split by punctuation, align word timestamps
        # Read language from input node config (same as ASR step logic)
        detected_lang = self._resolve_language(task_dir)
        self._resolved_language = detected_lang
        print(f"[Split] Language for punctuation: {detected_lang}")

        # Adjust max_length based on language weight
        max_length = self._get_effective_max_length(max_length, detected_lang)

        if callback:
            callback(35, "Splitting by pauses and punctuation...")
        sentences = self._split_by_punctuation(
            sentences, all_words, max_length,
            lang=detected_lang, pause_threshold=pause_threshold,
            force_all=split_by_punct,
        )
        sentences = self._finalize_sentences(sentences, lang=detected_lang)

        # Step 3: LLM split for sentences still exceeding max_length (up to 3 rounds)
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
                    print(f"[Split] LLM round {llm_round + 1} failed: {e}")
                    # Continue to fallback below

                # Fix alignment mismatches and finalize timestamps
                sentences = self._validate_and_fix_alignment(sentences)
                sentences = self._finalize_sentences(sentences, lang=detected_lang)

        # Step 4: Final character-based fallback for any remaining long sentences
        still_long = [s for s in sentences if len(s["text"]) > max_length]
        if still_long:
            print(f"[Split] {len(still_long)} sentences still exceed {max_length} chars, splitting by word boundaries")
            if callback:
                callback(90, f"Force-splitting {len(still_long)} remaining long sentences by word boundaries...")
            sentences = self._force_split_by_chars(sentences, max_length, detected_lang)
            sentences = self._split_at_internal_terminals(sentences, lang=detected_lang)
            sentences = self._finalize_sentences(sentences, lang=detected_lang)

        # Final pass: merge any sentences that ended up too short（由"合并过短句子"勾选控制）
        if merge_short_enabled:
            before_count = len(sentences)
            sentences = self._merge_short_sentences(
                sentences,
                max_length,
                lang=detected_lang,
                gap_threshold=pause_threshold,
            )
            if len(sentences) < before_count:
                print(f"[Split] Merged {before_count - len(sentences)} short sentences into neighbors")
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
