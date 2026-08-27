import json
import os
import re
from typing import Dict, List


_PUNCTS_CACHE: Dict[str, Dict[str, set]] = {}


def load_language_puncts(lang: str = "auto") -> Dict[str, set]:
    cache_key = lang or "auto"
    if cache_key in _PUNCTS_CACHE:
        return _PUNCTS_CACHE[cache_key]

    puncts_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config", "language_puncts.json"
    )
    try:
        with open(puncts_path, "r", encoding="utf-8") as f:
            all_puncts = json.load(f)
    except Exception:
        all_puncts = {}

    common = all_puncts.get("_common", {})
    common_ends = set(common.get("sentence_ends", []))
    common_breaks = set(common.get("clause_breaks", []))

    lang = lang or "auto"
    lang_base = lang.split("-")[0] if "-" in lang else lang
    entry = all_puncts.get(lang) or all_puncts.get(lang_base) or all_puncts.get("_default", {})
    result = {
        "sentence_ends": set(entry.get("sentence_ends", [".", "!", "?"])) | common_ends,
        "clause_breaks": set(entry.get("clause_breaks", [",", ";", ":"])) | common_breaks,
    }
    _PUNCTS_CACHE[cache_key] = result
    return result


def is_compact_spacing_language(lang: str = "auto") -> bool:
    raw = str(lang or "").strip()
    lowered = raw.lower()
    return (
        lowered.startswith(("zh", "ja", "ko"))
        or raw in {"中文", "日语", "日文", "韩语", "韩文"}
        or lowered in {"chinese", "japanese", "korean"}
    )


def clean_sentence_text(text: str, lang: str = "auto") -> str:
    text = str(text or "").replace("\u3000", " ")
    if is_compact_spacing_language(lang):
        return re.sub(r"\s+", "", text).strip()
    return re.sub(r"\s+", " ", text).strip()


def is_part_of_number(text: str, pos: int) -> bool:
    if pos < 0 or pos >= len(text):
        return False
    ch = text[pos]
    if ch not in ".,，":
        return False

    digits = "0123456789０１２３４５６７８９"
    prev_ch = text[pos - 1] if pos > 0 else ""
    next_ch = text[pos + 1] if pos + 1 < len(text) else ""

    if prev_ch in digits and next_ch in digits:
        return True

    if prev_ch in digits:
        j = pos + 1
        while j < len(text) and text[j] in " \t":
            j += 1
        if j < len(text) and text[j] in digits:
            return True

    return False


def split_text_by_ends(text: str, sentence_ends: set) -> List[str]:
    if not text:
        return []
    chunks: List[str] = []
    current = ""
    for i, ch in enumerate(text):
        current += ch
        if ch in sentence_ends:
            if is_part_of_number(text, i):
                continue
            chunks.append(current)
            current = ""
    if current.strip():
        chunks.append(current)
    return chunks


def split_text_by_clauses(text: str, clause_breaks: set) -> List[str]:
    """Split at clause-break punctuation (comma/semicolon/colon).

    Runs whenever ``clause_breaks`` is non-empty, with NO length limit: every
    clause break becomes its own sentence, mirroring sentence-end splitting.
    """
    if not text:
        return []

    tokens: List[str] = []
    current = ""
    for i, ch in enumerate(text):
        current += ch
        if ch in clause_breaks:
            if is_part_of_number(text, i):
                continue
            tokens.append(current)
            current = ""
    if current.strip():
        tokens.append(current)
    return [t for t in tokens if t.strip()]

