"""s07_subtitle_align: Split long translations and align with source text.

Flow:
  1. Load translation results (reflect or direct fallback)
  2. Resolve source/target languages from input node via workflow.json
  3. Identify translations exceeding max_subtitle_length
  4. For each long sentence:
     a. LLM splits SOURCE text into N parts at natural break points ([br] markers)
     b. LLM aligns translation to match the source parts
  5. Recalculate timestamps using word-level ASR data
  6. Repeat up to 3 rounds until all within length limit
  7. Output aligned pairs: [{id, src, tr, start, end}, ...]
"""
import os
import re
import json
from typing import Callable, Optional, List, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from backend.steps.base_step import BaseStep, find_artifact
from backend.config.config_manager import config
from backend.llm.llm_client import get_llm_client


# ── Weighted character length ────────────────────────────────────────


def _load_language_weights_config() -> Dict[str, Any]:
    """Load full language character weights config from file."""
    weights_path = os.path.join(
        os.path.dirname(__file__), "..", "config", "language_char_weights.json"
    )
    try:
        with open(weights_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"weights": {"en": 3.5}, "fullwidth": 1.5, "default": 1.0}


def get_language_weight(lang_code: str) -> float:
    """Get the character weight for a specific language code.
    
    Args:
        lang_code: ISO 639-1 language code (e.g., 'en', 'zh', 'ja')
    
    Returns:
        Weight value for the language (e.g., 3.5 for English, 1.0 for Chinese)
    """
    config = _load_language_weights_config()
    weights = config.get("weights", {})
    default_weight = config.get("default", 1.0)
    return weights.get(lang_code, default_weight)


def calc_len(text: str) -> float:
    """Calculate weighted character count for subtitle length checking.
    
    Uses language-specific weights from backend/config/language_char_weights.json.
    CJK characters count as 1.0 (baseline), English/other languages have higher weights.
    """
    config = _load_language_weights_config()
    weights = config.get("weights", {})
    fullwidth_weight = config.get("fullwidth", 1.5)
    default_weight = config.get("default", 1.0)

    def char_weight(char: str) -> float:
        code = ord(char)
        # CJK 字符（中日韩）
        if (
            0x4E00 <= code <= 0x9FFF  # 中文
            or 0x3040 <= code <= 0x30FF  # 日文假名
            or 0xAC00 <= code <= 0xD7A3  # 韩文
            or 0x0E00 <= code <= 0x0E7F  # 泰文
        ):
            return default_weight  # CJK baseline is 1.0
        # 全角符号
        elif 0xFF01 <= code <= 0xFF5E:
            return fullwidth_weight
        # ASCII / 半角字符（英文等）- 使用 'en' 权重作为默认
        else:
            return weights.get("en", 3.5)

    return sum(char_weight(c) for c in text)


def _normalize_for_matching(text: str) -> str:
    """Normalize text for word-timestamp matching: remove punctuation and spaces."""
    text = re.sub(r'[，。！？；：、,.!?;:\s\-]', '', text)
    return text.lower()


# ── Prompt builders ──────────────────────────────────────────────────


def _get_split_system_prompt(src_lang: str = "source", tgt_lang: str = "target") -> str:
    return f"""### Role
You are a professional Netflix subtitle split-and-align expert fluent in both {src_lang} and {tgt_lang}.

### Core Task
Split BOTH the {tgt_lang} translation AND the {src_lang} source text into aligned parts.

### ABSOLUTE RULES - VIOLATION = FAILURE
1. **ONLY CUT, NEVER MODIFY** - You are ONLY allowed to cut the text at specific positions. NEVER change, rewrite, add, or remove any words.
2. **FORBIDDEN: Placeholders** - NEVER use text like "(This is part of...)", "[continued]", "(combined clause)" etc. Every part MUST contain REAL text from the original.
3. **FORBIDDEN: Partial cuts** - If you cut the translation, you MUST also cut the source text at the corresponding position.
4. **Punctuation stays with preceding text** - Commas, periods etc. must stay attached to the word before them.
5. **NEVER create duplicate content** - Each part must be unique, no repeated sentences or phrases.
6. **Preserve all content** - Do not add, omit, summarize, or merge any content.

### Technical Rules
1. Maintain sentence meaning coherence according to Netflix subtitle standards
2. Keep parts roughly equal in length (minimum 3 words each)
3. Split at natural points like punctuation marks or conjunctions (keep punctuation with preceding part)
4. Prioritize splitting at commas or periods
5. It is forbidden to split words or consecutive numbers
6. Source parts must be contiguous slices of the original source text
7. Target parts must be contiguous slices of the full translation

### Output Format in JSON
{{
    "analysis": "Brief explanation of where and why you split",
    "source_parts": ["part1", "part2"],
    "target_parts": ["aligned_part1", "aligned_part2"]
}}

### Your Answer, Provide ONLY a valid JSON object, Don't give any other redundant explanations.
"""


def _build_split_prompt(
    source_text: str, 
    translation: str, 
    num_parts: int, 
    word_limit: float,
    src_lang: str = "source",
    tgt_lang: str = "target"
) -> dict:
    # Try to use JSON template via prompt service
    from backend.prompts.prompt_service import get_prompt_service
    svc = get_prompt_service()
    result = svc.assemble_prompt("s07_subtitle_align", {
        "src_lang": src_lang,
        "tgt_lang": tgt_lang,
        "num_parts": num_parts,
        "word_limit": f"{word_limit:.0f}",
        "source_text": source_text,
        "translation": translation,
    })
    if result.get("found"):
        return {
            "system_prompt": result.get("system_prompt") or _get_split_system_prompt(src_lang, tgt_lang),
            "user_prompt": result.get("user_prompt")
        }
    
    # Fallback to hardcoded prompt
    return {
        "system_prompt": _get_split_system_prompt(src_lang, tgt_lang),
        "user_prompt": f"""### Task
Split BOTH the {tgt_lang} translation AND the {src_lang} source text into exactly {num_parts} aligned parts.

### ABSOLUTE RULES - VIOLATION = FAILURE
1. **ONLY CUT, NEVER MODIFY** - You are ONLY allowed to cut the text at specific positions. NEVER change, rewrite, add, or remove any words.
2. **FORBIDDEN: Placeholders** - NEVER use text like "(This is part of...)", "[continued]", "(combined clause)" etc. Every part MUST contain REAL text from the original.
3. **FORBIDDEN: Partial cuts** - If you cut the translation, you MUST also cut the source text at the corresponding position.
4. **Punctuation stays with preceding text** - Commas, periods etc. must stay attached to the word before them.

### How to Split (Step by Step)
1. Read the FULL translation
2. Find {num_parts - 1} natural break points (commas, conjunctions, clause boundaries)
3. Cut the translation at these points
4. Cut the source text at the corresponding semantic positions
5. Verify: concatenating all source parts = original source text

### Example CORRECT Split (2 parts):
Input:
  Source: "如果你一周三天都晚上十一点才睡，"
  Translation: "If you're staying up past 11 PM three nights a week,"

Output:
  {{
    "source_parts": ["如果你一周三天都晚上十一点才睡，"],
    "target_parts": ["If you're staying up past 11 PM three nights a week,"]
  }}

Note: Even though the text is long, we keep it as ONE part because there's no natural break point that would create two meaningful parts.

### Example INCORRECT Split (DO NOT DO THIS):
  {{
    "source_parts": ["如果你一周三天", "都晚上十一点才睡，"],
    "target_parts": ["If you're staying up past 11 PM", "(This is part of the combined clause)"]
  }}
This is WRONG because: (1) placeholder text used, (2) translation modified

### Hard Requirements
1. Return exactly {num_parts} source parts and exactly {num_parts} target parts
2. Every part must be non-empty (minimum 3 words each)
3. Source parts = contiguous slices of original source (in order, no gaps, no overlaps)
4. Target parts = contiguous slices of original translation (in order, no gaps, no overlaps)
5. Each target part <= {word_limit:.0f} characters
6. If text cannot be meaningfully split, keep as 1 part (validation will handle it)

### Validation Checklist (I will check ALL of these):
- [ ] source_parts length == {num_parts}
- [ ] target_parts length == {num_parts}
- [ ] No empty strings
- [ ] No placeholder text ("part of", "continued", "combined clause" etc.)
- [ ] Source parts concatenate to original source
- [ ] Target parts concatenate to original translation
- [ ] No duplicate content across parts
- [ ] Each target part <= {word_limit:.0f} chars

### Source Text ({src_lang}):
{source_text}

### Full Translation ({tgt_lang}):
{translation}

### Return this JSON object exactly:
{{
    "analysis": "Where and why you split (brief)",
    "source_parts": ["part1", "part2"],
    "target_parts": ["aligned_part1", "aligned_part2"]
}}
"""
    }


def _build_retry_prompt(
    source_text: str,
    translation: str,
    num_parts: int,
    word_limit: float,
    issues: List[str],
    previous_result: Any,
    src_lang: str = "source",
    tgt_lang: str = "target",
) -> dict:
    issue_lines = "\n".join(f"- {issue}" for issue in issues) or "- unknown validation failure"
    previous_json = json.dumps(previous_result, ensure_ascii=False)[:1000]
    prompt_data = _build_split_prompt(source_text, translation, num_parts, word_limit, src_lang, tgt_lang)
    
    prompt_data["user_prompt"] += (
        f"\n\nYour previous answer was invalid.\n"
        + f"Validation errors:\n{issue_lines}\n\n"
        + f"Previous invalid JSON:\n{previous_json}\n\n"
        + f"Fix the result and return a new JSON object with exactly {num_parts} aligned source parts "
        + f"and exactly {num_parts} aligned target parts."
    )
    return prompt_data


# ── Step class ───────────────────────────────────────────────────────


class S07SubtitleAlign(BaseStep):
    step_id = "s07_subtitle_align"
    step_name = "译文断句和双语对齐"
    dependencies = ["s05_translate"]
    artifacts = ["cache/subtitle_aligned.json"]

    MAX_ROUNDS = 3

    # ── Config helpers ───────────────────────────────────────────────

    def _get_param(self, key: str, default=None):
        node_cfg = getattr(self, "_node_config", {}) or {}
        val = node_cfg.get(key)
        if val is not None and val != "":
            return val
        val = config.get(f"general.{key}")
        return val if val is not None else default

    def _resolve_languages_from_input(self, task_dir: str) -> Tuple[str, str]:
        """Read source_language and target_language from input node in workflow.json."""
        src_lang = "auto"
        tgt_lang = "en"
        wf_path = os.path.join(task_dir, "workflow.json")
        if os.path.exists(wf_path):
            try:
                with open(wf_path, "r", encoding="utf-8") as f:
                    wf = json.load(f)
                for node in wf.get("nodes", []):
                    if node.get("data", {}).get("nodeType") == "input":
                        cfg = node.get("data", {}).get("config", {})
                        src = cfg.get("source_language", "")
                        tgt = cfg.get("target_language", "")
                        if src and src != "auto":
                            src_lang = src
                        if tgt:
                            tgt_lang = tgt
                        break
            except Exception:
                pass
        return src_lang, tgt_lang

    # ── Artifact checks ──────────────────────────────────────────────

    def check_artifact(self, task_dir: str) -> bool:
        node_suffix = f"_{self._node_id}" if self._node_id else ""
        return os.path.exists(os.path.join(task_dir, "cache", f"subtitle_aligned{node_suffix}.json"))

    def validate_inputs(self, task_dir: str) -> bool:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        # 优先检查上游连线传入的翻译结果路径
        subtitle_input = step_inputs.get("subtitle", "")
        if subtitle_input:
            p = subtitle_input if os.path.isabs(subtitle_input) else os.path.join(task_dir, subtitle_input)
            if os.path.exists(p):
                return True
        # 回退：检查缓存默认路径
        sentences = find_artifact(os.path.join(task_dir, "cache"), "sentences.json")
        reflect = find_artifact(os.path.join(task_dir, "cache"), "translation_reflect.json")
        direct = find_artifact(os.path.join(task_dir, "cache"), "translation_direct.json")
        return bool(sentences) and (bool(reflect) or bool(direct))

    # ── Core logic ───────────────────────────────────────────────────

    def _load_translation_map(self, task_dir: str) -> Dict[int, Dict]:
        """Load translation data and build an id-based lookup table."""
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        # 优先使用上游连线传入的翻译结果路径
        subtitle_input = step_inputs.get("subtitle", "")
        if subtitle_input:
            p = subtitle_input if os.path.isabs(subtitle_input) else os.path.join(task_dir, subtitle_input)
            if os.path.exists(p):
                print(f"[SubtitleAlign] Using upstream translation: {p}")
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                mapping: Dict[int, Dict] = {}
                for item in data:
                    try:
                        mapping[int(item.get("id"))] = item
                    except (TypeError, ValueError):
                        continue
                return mapping

        # 回退：从 cache 目录读取
        reflect_path = find_artifact(os.path.join(task_dir, "cache"), "translation_reflect.json")
        direct_path = find_artifact(os.path.join(task_dir, "cache"), "translation_direct.json")

        data = []
        if reflect_path:
            with open(reflect_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        elif direct_path:
            with open(direct_path, "r", encoding="utf-8") as f:
                data = json.load(f)

        mapping: Dict[int, Dict] = {}
        for item in data:
            try:
                mapping[int(item.get("id"))] = item
            except (TypeError, ValueError):
                continue
        return mapping

    def _build_processing_sentences(self, task_dir: str) -> List[Dict]:
        """Build an in-memory processing view from sentences.json + translation results.

        This method never rewrites sentences.json. The original sentence data remains
        the single source of truth for other nodes; translation fields are only
        attached to temporary copies used by this alignment step.
        """
        sentences_path = find_artifact(os.path.join(task_dir, "cache"), "sentences.json")
        if not sentences_path:
            return []
        with open(sentences_path, "r", encoding="utf-8") as f:
            sentences = json.load(f)

        translation_map = self._load_translation_map(task_dir)
        merged = []
        for sentence in sentences:
            item = dict(sentence)
            try:
                sid = int(item.get("id"))
            except (TypeError, ValueError):
                sid = None
            translation_item = translation_map.get(sid or -1, {})
            item["direct"] = translation_item.get("direct", "")
            item["reflect"] = translation_item.get("reflect", "")
            merged.append(item)
        return merged

    def _get_translation_text(self, item: Dict) -> str:
        """Get the best translation text: reflect > direct."""
        return item.get("reflect") or item.get("direct") or ""

    @staticmethod
    def _find_split_index_by_weight(text: str, target_weight: float) -> int:
        if not text:
            return 0
        cumulative = 0.0
        target_idx = len(text) // 2
        for idx, char in enumerate(text, start=1):
            cumulative += calc_len(char)
            if cumulative >= target_weight:
                target_idx = idx
                break

        candidate_positions: List[Tuple[int, int]] = []
        for idx in range(1, len(text)):
            prev_char = text[idx - 1]
            curr_char = text[idx]
            if prev_char in "，。！？；：、,.;:!?":
                candidate_positions.append((idx, 0))
            elif curr_char.isspace():
                candidate_positions.append((idx, 1))
            elif prev_char in "-/)]}" or curr_char in "([{":
                candidate_positions.append((idx, 2))

        if candidate_positions:
            best_pos = min(
                candidate_positions,
                key=lambda item: (abs(item[0] - target_idx), item[1]),
            )[0]
            if 0 < best_pos < len(text):
                return best_pos
        return max(1, min(target_idx, len(text) - 1))

    def _split_text_locally(self, text: str, num_parts: int) -> List[str]:
        """Split text locally by punctuation and weight.
        
        Raises ValueError if split fails.
        """
        text = str(text or "").strip()
        if num_parts <= 1 or not text:
            return [text]

        parts: List[str] = []
        remaining = text
        remaining_parts = num_parts
        while remaining_parts > 1 and remaining:
            total_weight = calc_len(remaining)
            target_weight = total_weight / remaining_parts
            split_idx = self._find_split_index_by_weight(remaining, target_weight)
            left = remaining[:split_idx].strip()
            right = remaining[split_idx:].strip()
            if not left or not right:
                raise ValueError(f"Failed to split text into {num_parts} parts: unable to find valid split point")
            parts.append(left)
            remaining = right
            remaining_parts -= 1

        parts.append(remaining.strip())
        if len(parts) != num_parts or any(not part for part in parts):
            raise ValueError(f"Failed to split text into {num_parts} parts: got {len([p for p in parts if p])} non-empty parts")
        return parts

    def _build_local_fallback_parts(
        self,
        src_text: str,
        translation: str,
        num_parts: int,
        max_length: float,
    ) -> Tuple[List[str], List[str], List[str]]:
        """Build local fallback parts.
        
        Raises ValueError if split or validation fails.
        """
        src_parts = self._split_text_locally(src_text, num_parts)
        tr_parts = self._split_text_locally(translation, num_parts)
        issues = self._validate_split_parts(src_parts, tr_parts, num_parts, max_length)
        if issues:
            raise ValueError(f"Local fallback validation failed: {'; '.join(issues)}")
        return src_parts, tr_parts, []

    @staticmethod
    def _validate_split_parts(
        src_parts: List[str], 
        tr_parts: List[str], 
        num_parts: int, 
        max_length: float,
        original_src: str = "",
    ) -> List[str]:
        """Validate split parts from LLM response.
        
        Args:
            src_parts: Source text parts
            tr_parts: Translation text parts
            num_parts: Expected number of parts
            max_length: Maximum allowed character length (actual chars, not weighted)
            original_src: Original source text for continuity check (optional)
        """
        issues: List[str] = []
        if len(src_parts) != num_parts or len(tr_parts) != num_parts:
            issues.append(f"part count mismatch: src={len(src_parts)}, tr={len(tr_parts)}, expected={num_parts}")
        if any(not p.strip() for p in src_parts):
            issues.append("empty source part detected")
        if any(not p.strip() for p in tr_parts):
            issues.append("empty target part detected")
        
        # Check source text continuity - parts should concatenate to form original
        if original_src and src_parts:
            reconstructed = "".join(src_parts)
            # Normalize both for comparison (remove spaces)
            original_normalized = re.sub(r'\s+', '', original_src)
            reconstructed_normalized = re.sub(r'\s+', '', reconstructed)
            if original_normalized != reconstructed_normalized:
                issues.append(f"source parts don't match original text (original: {len(original_src)} chars, reconstructed: {len(reconstructed)} chars)")
        
        # Check for placeholder text that indicates LLM didn't actually split
        placeholder_patterns = [
            "(this is part of",
            "[continued]",
            "[part of",
            "(continued)",
            "(see part",
            "(combined clause",
            "part of the",
            "part of #",
        ]
        for idx, part in enumerate(tr_parts):
            part_lower = part.strip().lower()
            for pattern in placeholder_patterns:
                if pattern in part_lower:
                    issues.append(f"placeholder text detected in target part {idx + 1}: '{part[:50]}...'")
                    break
        
        # Check for punctuation-only parts (。！？，、 etc.)
        punctuation_only = set("。！？，、；：""''【】《》（）…—,.!?;:\"'()[]{}")
        for idx, part in enumerate(src_parts):
            stripped = part.strip()
            if stripped and all(c in punctuation_only for c in stripped):
                issues.append(f"punctuation-only source part {idx + 1}: '{stripped}'")
        for idx, part in enumerate(tr_parts):
            stripped = part.strip()
            if stripped and all(c in punctuation_only for c in stripped):
                issues.append(f"punctuation-only target part {idx + 1}: '{stripped}'")
        
        # Check for duplicate content across parts
        src_seen = set()
        for idx, part in enumerate(src_parts):
            normalized = part.strip()
            if normalized in src_seen:
                issues.append(f"duplicate source content in part {idx + 1}: '{normalized[:30]}...'")
            src_seen.add(normalized)
        
        tr_seen = set()
        for idx, part in enumerate(tr_parts):
            normalized = part.strip()
            if normalized in tr_seen:
                issues.append(f"duplicate target content in part {idx + 1}: '{normalized[:30]}...'")
            tr_seen.add(normalized)
        
        # Use len() for actual character count, not calc_len() which applies weights
        too_long = []
        for idx, part in enumerate(tr_parts):
            part_len = len(part)
            if part_len > max_length:
                too_long.append(f"part {idx + 1} ({part_len} chars, limit {max_length:.0f})")
        if too_long:
            issues.append(f"target parts exceed limit: {'; '.join(too_long)}")
        return issues

    def _find_split_point(
        self, words: List[Dict], ratio: float, text_len: int
    ) -> int:
        """Find the word index closest to the character ratio split point."""
        if not words:
            return 0
        target_char = text_len * ratio
        cumulative = 0.0
        best_idx = 0
        best_diff = float("inf")
        for i, w in enumerate(words):
            word_text = w.get("word", "")
            cumulative += len(word_text)
            diff = abs(cumulative - target_char)
            if diff < best_diff:
                best_diff = diff
                best_idx = i
        return best_idx

    def _build_part_timestamps(
        self,
        words: List[Dict],
        src_parts: List[str],
        sentence_start: float = 0,
        sentence_end: float = 0,
    ) -> List[Dict[str, float]]:
        """Build start/end timestamps for each source part using word-level data.
        
        Uses punctuation-tolerant matching: removes punctuation and spaces before
        comparing source parts with word timestamps for better accuracy.
        
        Raises ValueError if word-level alignment fails instead of falling back
        to character-based distribution.
        """
        if not src_parts:
            return []

        # Validate word count is sufficient
        if len(words) < len(src_parts):
            raise ValueError(
                f"Word count ({len(words)}) is less than src_parts count ({len(src_parts)}), "
                f"cannot perform accurate timestamp alignment"
            )

        timestamps = []
        word_idx = 0

        for i, part in enumerate(src_parts):
            # Normalize part for matching (remove punctuation and spaces)
            normalized_part = _normalize_for_matching(part)
            part_len = len(normalized_part)

            # Find start word
            start_w = word_idx
            if start_w >= len(words):
                raise ValueError(
                    f"Word index out of range when processing part {i+1}: "
                    f"word_idx={word_idx}, words_len={len(words)}"
                )

            # Find end word by accumulating normalized word lengths
            end_w = word_idx
            word_chars = 0
            for j in range(word_idx, len(words)):
                word_text = _normalize_for_matching(words[j].get("word", ""))
                word_chars += len(word_text)
                end_w = j
                # Allow 15% tolerance for matching
                if word_chars >= part_len * 0.9:
                    break

            # Ensure end_w is at least start_w
            if end_w < start_w:
                end_w = start_w

            timestamps.append({
                "start": words[start_w].get("start", 0),
                "end": words[end_w].get("end", 0),
            })

            word_idx = end_w + 1

        return timestamps

    @staticmethod
    def _validate_entry_timestamps(entries: List[Dict], sentence: Dict) -> List[str]:
        """Validate entry timestamps are positive, ordered and within sentence bounds."""
        issues: List[str] = []
        prev_end = None
        sent_start = float(sentence.get("start", 0) or 0)
        sent_end = float(sentence.get("end", 0) or 0)
        has_sentence_window = sent_end > sent_start

        for idx, entry in enumerate(entries):
            start = float(entry.get("start", 0) or 0)
            end = float(entry.get("end", 0) or 0)
            if end <= start:
                issues.append(f"part {idx+1} duration invalid ({start}->{end})")
                continue
            if prev_end is not None and start < prev_end - 0.02:
                issues.append(f"part {idx+1} overlaps previous ({start} < {prev_end})")
            if has_sentence_window:
                if start < sent_start - 0.05 or end > sent_end + 0.05:
                    issues.append(
                        f"part {idx+1} out of sentence bounds ({start}->{end} not in {sent_start}->{sent_end})"
                    )
            prev_end = end
        return issues

    def _split_once(
        self,
        llm,
        sid: Any,
        src_text: str,
        translation: str,
        words: List[Dict],
        max_length: float,
        src_lang: str,
        tgt_lang: str,
        sentence: Dict,
    ) -> Tuple[List[str], List[str], List[Dict[str, float]]]:
        """Split a single source+translation pair into 2 parts using LLM.
        
        Returns (src_parts, tr_parts, timestamps) on success.
        Raises ValueError on failure after 2 LLM retries.
        """
        num_parts = 2  # Always split into exactly 2 parts
        last_issues: List[str] = []
        last_result: Any = None
        
        for retry_round in range(2):
            if retry_round == 0:
                split_prompt = _build_split_prompt(
                    src_text, translation, num_parts, max_length, src_lang, tgt_lang
                )
            else:
                split_prompt = _build_retry_prompt(
                    src_text, translation, num_parts, max_length,
                    last_issues, last_result, src_lang, tgt_lang,
                )
            
            split_result = llm.chat(
                self.step_id,
                split_prompt["user_prompt"],
                system_prompt=split_prompt["system_prompt"],
                response_json=True,
            )
            last_result = split_result

            # 1. Check LLM response is valid dict
            if not isinstance(split_result, dict):
                last_issues = ["LLM returned invalid response (not a dict)"]
                print(f"[SubtitleAlign] Retry {retry_round+1} failed for id={sid}: {last_issues[0]}")
                continue

            # 2. Extract and validate source/target parts
            src_parts = [str(p).strip() for p in (split_result.get("source_parts") or []) if str(p).strip()]
            tr_parts = [str(p).strip() for p in (split_result.get("target_parts") or []) if str(p).strip()]
            
            # 3. Non-empty check
            if not src_parts or not tr_parts:
                last_issues = ["Empty source_parts or target_parts in LLM response"]
                print(f"[SubtitleAlign] Retry {retry_round+1} failed for id={sid}: {last_issues[0]}")
                continue
            
            # 4. Count and length validation (with original source text check)
            last_issues = self._validate_split_parts(
                src_parts, tr_parts, num_parts, max_length, original_src=src_text
            )
            if last_issues:
                print(f"[SubtitleAlign] Retry {retry_round+1} validation failed for id={sid}: {'; '.join(last_issues)}")
                continue

            # 5. Build timestamps from word-level data
            try:
                ts_list = self._build_part_timestamps(
                    words=words,
                    src_parts=src_parts,
                    sentence_start=sentence.get("start", 0),
                    sentence_end=sentence.get("end", 0),
                )
            except ValueError as e:
                last_issues = [f"Timestamp alignment failed: {e}"]
                print(f"[SubtitleAlign] Retry {retry_round+1} timestamp failed for id={sid}: {e}")
                continue

            # 6. Timestamp validation
            result_entries = []
            for i, (sp, tp) in enumerate(zip(src_parts, tr_parts)):
                ts = ts_list[i] if i < len(ts_list) else {"start": 0, "end": 0}
                result_entries.append({
                    "id": sid,
                    "src": sp,
                    "tr": tp,
                    "start": ts.get("start", 0),
                    "end": ts.get("end", 0),
                })

            ts_issues = self._validate_entry_timestamps(result_entries, sentence)
            if not ts_issues:
                return src_parts, tr_parts, ts_list

            last_issues = ts_issues
            print(f"[SubtitleAlign] Retry {retry_round+1} timestamp validation failed for id={sid}: {'; '.join(ts_issues)}")

        raise ValueError(f"Split failed for id={sid} after 2 retries: {'; '.join(last_issues)}")

    def _process_sentence(
        self,
        llm,
        sentence: Dict,
        max_length: float,
        src_lang: str = "source",
        tgt_lang: str = "target",
        max_rounds: int = 4,
    ) -> List[Dict]:
        """Process a single sentence with iterative splitting.
        
        Strategy: Split long translations into 2 parts each round.
        After each round, check if any parts still exceed max_length.
        Repeat until all parts are within limit or max_rounds is reached.
        If max_rounds reached, package remaining parts as-is (no error).
        """
        sid = sentence.get("id", "")
        src_text = sentence.get("text", "")
        translation = self._get_translation_text(sentence)
        words = sentence.get("words", [])

        # Use len() for actual character count, not calc_len()
        if not translation or len(translation) <= max_length:
            return [{
                "id": sid,
                "src": src_text,
                "tr": translation,
                "start": sentence.get("start", 0),
                "end": sentence.get("end", 0),
            }]

        if not words:
            raise ValueError(f"Sentence id={sid} is missing word-level timestamps in sentences.json")

        # Initialize with the original single entry
        current_entries = [{
            "id": sid,
            "src": src_text,
            "tr": translation,
            "words": words,  # Keep words for timestamp alignment
            "start": sentence.get("start", 0),
            "end": sentence.get("end", 0),
        }]

        # Placeholder patterns to detect invalid LLM output
        placeholder_patterns = [
            "(this is part of",
            "[continued]",
            "[part of",
            "(continued)",
            "(see part",
            "(combined clause",
            "part of the",
            "part of #",
        ]
        
        def _has_placeholder(text: str) -> bool:
            """Check if text contains placeholder patterns."""
            text_lower = text.strip().lower()
            return any(pattern in text_lower for pattern in placeholder_patterns)
        
        for round_num in range(max_rounds):
            # Find entries that still exceed max_length OR contain placeholders
            over_limit = []
            for idx, entry in enumerate(current_entries):
                tr_text = entry.get("tr", "")
                if len(tr_text) > max_length or _has_placeholder(tr_text):
                    over_limit.append((idx, entry))
            
            if not over_limit:
                break  # All within limit and no placeholders
            
            print(f"[SubtitleAlign] Round {round_num + 1}: {len(over_limit)} entries still over limit for id={sid}")
            
            # Process each over-limit entry (in reverse to maintain indices)
            new_entries = list(current_entries)
            for entry_idx, entry in reversed(over_limit):
                entry_src = entry.get("src", "")
                entry_tr = entry.get("tr", "")
                entry_words = entry.get("words", [])
                entry_start = entry.get("start", 0)
                entry_end = entry.get("end", 0)
                
                try:
                    # Try to split this entry into 2 parts
                    src_parts, tr_parts, ts_list = self._split_once(
                        llm, sid, entry_src, entry_tr, entry_words,
                        max_length, src_lang, tgt_lang, sentence
                    )
                    
                    # Build new entries with timestamps
                    split_entries = []
                    for i, (sp, tp) in enumerate(zip(src_parts, tr_parts)):
                        ts = ts_list[i] if i < len(ts_list) else {"start": entry_start, "end": entry_end}
                        # Distribute words to the corresponding part
                        part_words = entry_words  # Keep all words for now (timestamp alignment handles it)
                        split_entries.append({
                            "id": sid,
                            "src": sp,
                            "tr": tp,
                            "words": part_words,
                            "start": ts.get("start", entry_start),
                            "end": ts.get("end", entry_end),
                        })
                    
                    # Replace the original entry with split entries
                    new_entries[entry_idx:entry_idx + 1] = split_entries
                    print(f"[SubtitleAlign] Round {round_num + 1}: Split entry {entry_idx} into {len(split_entries)} parts")
                    
                except ValueError as e:
                    # Split failed for this entry - keep it as-is, will try again next round
                    print(f"[SubtitleAlign] Round {round_num + 1}: Failed to split entry {entry_idx} for id={sid}: {e}")
                    continue
            
            current_entries = new_entries

        # Build final result (remove words field)
        result = []
        for entry in current_entries:
            result.append({
                "id": entry.get("id", sid),
                "src": entry.get("src", ""),
                "tr": entry.get("tr", ""),
                "start": entry.get("start", 0),
                "end": entry.get("end", 0),
            })
        
        return result

    # ── Main entry ───────────────────────────────────────────────────

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        if callback:
            callback(5, "Loading sentences and translations into memory...")
        node_suffix = f"_{self._node_id}" if self._node_id else ""

        processing_sentences = self._build_processing_sentences(task_dir)
        if not processing_sentences:
            raise ValueError(
                "No translation sentence data found (sentences.json + translation results required)"
            )

        # max_subtitle_length is in "Chinese character units" (weight=1.0)
        # For other languages, we need to multiply by the language weight
        # e.g., max_subtitle_length=20 for English -> 20 * 3.5 = 70 actual chars
        src_lang, tgt_lang = self._resolve_languages_from_input(task_dir)
        base_max_length = float(self._get_param("max_subtitle_length", 30))
        tgt_lang_weight = get_language_weight(tgt_lang)
        max_length = base_max_length * tgt_lang_weight
        
        if callback:
            callback(10, f"Loaded {len(processing_sentences)} sentences, "
                       f"max_length={max_length:.0f} chars "
                       f"(base={base_max_length:.0f} * weight={tgt_lang_weight})")

        llm = get_llm_client()
        max_workers = config.get("llm.max_concurrent") or 10

        # Identify sentences needing split
        to_process = []
        for s in processing_sentences:
            tr = self._get_translation_text(s)
            # Use len() for actual character count, not calc_len()
            if tr and len(tr) > max_length:
                to_process.append(s)

        if callback:
            callback(15, f"{len(to_process)} sentences exceed {max_length:.0f} chars, processing...")

        if not to_process:
            # All within limit — just build clean output
            result = self._build_clean_output(processing_sentences)
            self._save_output(task_dir, result)
            if callback:
                callback(100, f"All {len(processing_sentences)} sentences within length limit")
            return {"artifacts": [f"cache/subtitle_aligned{node_suffix}.json"]}

        # Process long sentences concurrently
        processed_map: Dict[int, List[Dict]] = {}
        total = len(to_process)

        def _worker(sentence: Dict) -> Tuple[int, List[Dict]]:
            idx = processing_sentences.index(sentence)
            parts = self._process_sentence(llm, sentence, max_length, src_lang, tgt_lang)
            return idx, parts

        with ThreadPoolExecutor(max_workers=min(max_workers, total)) as executor:
            futures = {executor.submit(_worker, s): s for s in to_process}
            done_count = 0
            for future in as_completed(futures):
                try:
                    idx, parts = future.result()
                    processed_map[idx] = parts
                except Exception as e:
                    s = futures[future]
                    raise RuntimeError(
                        f"Subtitle align failed for id={s.get('id', '')}: {e}"
                    ) from e
                done_count += 1
                if callback:
                    pct = int(15 + 55 * done_count / total)
                    callback(min(pct, 70), f"Split {done_count}/{total} sentences")

        if callback:
            callback(72, "Assembling results...")

        # Build full result list: unprocessed sentences + processed parts
        full_result: List[Dict] = []
        for i, s in enumerate(processing_sentences):
            if i in processed_map:
                full_result.extend(processed_map[i])
            else:
                full_result.append({
                    "id": s.get("id", ""),
                    "src": s.get("text", ""),
                    "tr": self._get_translation_text(s),
                    "start": s.get("start", 0),
                    "end": s.get("end", 0),
                })

        # Check for entries still over limit (after max_rounds iterations)
        # These are packaged as-is rather than causing an error
        still_over = [
            e for e in full_result if len(e.get("tr", "")) > max_length
        ]
        if still_over:
            ids = [str(e.get("id", "")) for e in still_over[:10]]
            print(f"[SubtitleAlign] Warning: {len(still_over)} entries still over limit after max rounds, packaging as-is: {', '.join(ids)}")

        if callback:
            callback(95, "Saving results...")

        # Strip any word-level timestamps from output
        clean_output = []
        for entry in full_result:
            clean_output.append({
                "id": entry.get("id", ""),
                "src": entry.get("src", ""),
                "tr": entry.get("tr", ""),
                "start": entry.get("start", 0),
                "end": entry.get("end", 0),
            })

        self._save_output(task_dir, clean_output)

        if callback:
            total_parts = len(clean_output)
            callback(100, f"Alignment complete: {total_parts} subtitle entries from {len(processing_sentences)} sentences")

        return {
            "artifacts": [f"cache/subtitle_aligned{node_suffix}.json"],
            "outputs": {
                "subtitle": f"cache/subtitle_aligned{node_suffix}.json",
            },
        }

    def _build_clean_output(self, translations: List[Dict]) -> List[Dict]:
        """Build clean output from translations that are already within limit."""
        output = []
        for s in translations:
            output.append({
                "id": s.get("id", ""),
                "src": s.get("text", ""),
                "tr": self._get_translation_text(s),
                "start": s.get("start", 0),
                "end": s.get("end", 0),
            })
        return output

    def _save_output(self, task_dir: str, data: List[Dict]):
        """Save aligned subtitle data to cache."""
        node_suffix = f"_{self._node_id}" if self._node_id else ""
        output_path = os.path.join(task_dir, "cache", f"subtitle_aligned{node_suffix}.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[SubtitleAlign] Saved {len(data)} aligned entries")
