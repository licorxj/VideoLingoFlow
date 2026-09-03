"""Regression tests for ``assign_words_by_char_offset`` (word→chunk alignment).

Covers Chinese / English / Japanese and explicit word-straddling splits, asserting
that for every language:

  * no word is dropped — every original word is fully consumed;
  * total covered time is conserved (== segment duration);
  * every chunk timestamp stays within [seg_start, seg_end] (no over-run / 越界);
  * chunk timestamps are monotonic and contiguous (shared straddle borders).

Run directly:
    python backend/tests/test_sentence_split_align.py
Or, once pytest is available:
    python -m pytest backend/tests/test_sentence_split_align.py
"""
import os
import sys

# Allow running directly from the repo root without installing the package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.utils.sentence_split_core import (  # noqa: E402
    assign_words_by_char_offset,
    distribute_timestamps_to_chunks,
    split_chinese_by_chars,
    split_english_by_chars,
)

EPS = 1e-3


def count_consumed(words, chunks):
    """Mirror assign_words_by_char_offset's consumption loop and return how many
    original words were fully consumed. Equals len(words) iff no word is dropped."""
    import re

    _clean = lambda s: re.sub(r"\s+", "", str(s or ""))
    wt = [_clean(w.get("word", "")) for w in words]
    wi, wp, n = 0, 0, len(words)
    for chunk in chunks:
        need = len(_clean(chunk))
        filled = 0
        if need == 0:
            continue
        while filled < need and wi < n:
            t = wt[wi]
            if not t:
                wi += 1
                wp = 0
                continue
            rem = len(t) - wp
            take = rem if rem <= (need - filled) else (need - filled)
            filled += take
            wp += take
            if wp >= len(t):
                wi += 1
                wp = 0
    return wi


def _substr_words(text, starts_ends):
    """Build word dicts from (substring, start, end) tuples that concatenate to text
    (valid for compact-spacing languages where words carry no inter-word spaces)."""
    words, idx = [], 0
    for piece, s, e in starts_ends:
        assert text[idx:idx + len(piece)] == piece, (
            f"piece {piece!r} not at {idx} in {text!r}"
        )
        words.append({"word": piece, "start": float(s), "end": float(e)})
        idx += len(piece)
    assert idx == len(text), f"words cover {idx}/{len(text)} chars of {text!r}"
    return words


def verify(result, words, chunks, seg_start, seg_end, label):
    # no word dropped: every original word must be fully consumed
    assert count_consumed(words, chunks) == len(words), (
        f"[{label}] word drop! consumed={count_consumed(words, chunks)}/{len(words)}"
    )

    # monotonic + bounds + intra-chunk contiguity
    prev_end = None
    for ci, c in enumerate(result):
        ws = c.get("words", [])
        if not ws:
            continue
        cs = ws[0]["start"]
        ce = ws[-1]["end"]
        assert cs >= seg_start - EPS, f"[{label}] chunk {ci} start {cs} < seg_start {seg_start}"
        assert ce <= seg_end + EPS, f"[{label}] chunk {ci} end {ce} > seg_end {seg_end}"
        assert cs <= ce + EPS, f"[{label}] chunk {ci} negative duration"
        if prev_end is not None:
            assert cs >= prev_end - EPS, f"[{label}] chunk {ci} start {cs} < prev end {prev_end}"
        for k in range(len(ws) - 1):
            assert abs(ws[k]["end"] - ws[k + 1]["start"]) < 1e-2, (
                f"[{label}] chunk {ci} gap between sub-words"
            )
        prev_end = ce

    # time conservation: covered span == segment span
    ends = [c["words"][-1]["end"] for c in result if c.get("words")]
    starts = [c["words"][0]["start"] for c in result if c.get("words")]
    if starts and ends:
        covered = max(ends) - min(starts)
        assert abs(covered - (seg_end - seg_start)) < 1e-2, (
            f"[{label}] time not conserved: covered={covered}, seg={seg_end - seg_start}"
        )
    print(f"  [OK] {label}: chunks={len(result)} words_consumed={count_consumed(words, chunks)}/{len(words)}")


def run_pipeline(text, words, splitter, max_len, seg_start, seg_end, label):
    chunks = splitter(text, max_len)
    assert "".join(chunks).replace(" ", "") == text.replace(" ", ""), (
        f"[{label}] chunks not a substring partition of text"
    )
    result = assign_words_by_char_offset(words, chunks, seg_start, seg_end)
    verify(result, words, chunks, seg_start, seg_end, label)
    # also via the wrapper used by the LLM / force-split paths
    sent = {"text": text, "start": seg_start, "end": seg_end, "words": words}
    wrapped = distribute_timestamps_to_chunks(sent, chunks)
    verify(wrapped, words, chunks, seg_start, seg_end, label + " [distribute]")


def test_japanese():
    text = "今日はいい天気なので、公園に行って散歩しましょう。"
    parts = [
        ("今日は", 0.0, 0.6), ("いい", 0.6, 1.1), ("天気", 1.1, 1.7),
        ("なので", 1.7, 2.2), ("、", 2.2, 2.3), ("公園に", 2.3, 3.0),
        ("行って", 3.0, 3.8), ("散歩", 3.8, 4.4), ("しましょう", 4.4, 5.3),
        ("。", 5.3, 5.5),
    ]
    words = _substr_words(text, parts)
    run_pipeline(text, words, lambda t, m: split_chinese_by_chars(t, m, has_jieba=False),
                 8, 0.0, 5.5, "Japanese(compact)")


def test_chinese():
    text = "我今天去了公园，看到了很多美丽的花朵和飞舞的蝴蝶。"
    parts = [
        ("我今天", 0.0, 0.7), ("去了", 0.7, 1.2), ("公园", 1.2, 1.8),
        ("，", 1.8, 1.9), ("看到了", 1.9, 2.6), ("很多", 2.6, 3.1),
        ("美丽的", 3.1, 3.9), ("花朵", 3.9, 4.6), ("和", 4.6, 4.9),
        ("飞舞的", 4.9, 5.7), ("蝴蝶", 5.7, 6.4), ("。", 6.4, 6.6),
    ]
    words = _substr_words(text, parts)
    run_pipeline(text, words, lambda t, m: split_chinese_by_chars(t, m, has_jieba=False),
                 10, 0.0, 6.6, "Chinese(compact)")


def test_english():
    # English word tokens do NOT contain inter-word spaces, so build them directly
    # and let the aligner match on whitespace-stripped forms.
    text = "Hello world, this is a test of the alignment logic working correctly."
    tokens = ["Hello", "world", ",", "this", "is", "a", "test", "of",
              "the", "alignment", "logic", "working", "correctly", "."]
    durations = [0.4, 0.5, 0.1, 0.4, 0.3, 0.2, 0.4, 0.3,
                 0.4, 0.7, 0.5, 0.7, 0.8, 0.2]
    words, t = [], 0.0
    for tok, d in zip(tokens, durations):
        words.append({"word": tok, "start": round(t, 4), "end": round(t + d, 4)})
        t += d
    assert abs(t - 5.9) < 1e-6, f"english word span = {t}, expected 5.9"
    run_pipeline(text, words, split_english_by_chars, 22, 0.0, 5.9, "English(spaced)")


def test_straddle():
    """Explicit boundary-straddling of a single atomic word across chunks."""
    # English: one long word split into 3 char pieces -> proportional time, shared borders
    w = [{"word": "internationalization", "start": 0.0, "end": 2.0}]  # 20 chars
    chunks = ["international", "iz", "ation"]  # 13 + 2 + 5 = 20
    res = assign_words_by_char_offset(w, chunks, 0.0, 2.0)
    assert abs(res[0]["end"] - res[1]["start"]) < 1e-2, "EN straddle border mismatch"
    assert abs(res[1]["end"] - res[2]["start"]) < 1e-2, "EN straddle border mismatch"
    assert abs(res[0]["end"] - 1.3) < 1e-2, f"EN proportional wrong: {res[0]['end']}"
    assert abs(res[2]["end"] - 2.0) < 1e-2, "EN last piece must reach seg_end"
    print("  [OK] English single-word straddle: proportional + shared borders")

    # Chinese per-char straddle (美丽的花朵 = 5 chars)
    w = [{"word": "美丽的花朵", "start": 0.0, "end": 1.0}]
    chunks = ["美丽的", "花朵"]  # 3 + 2
    res = assign_words_by_char_offset(w, chunks, 0.0, 1.0)
    assert abs(res[0]["end"] - 0.6) < 1e-2, f"ZH proportional wrong: {res[0]['end']}"
    assert abs(res[1]["start"] - 0.6) < 1e-2
    print("  [OK] Chinese single-word straddle: proportional + shared borders")

    # Japanese per-char straddle (公園に行って = 6 chars)
    w = [{"word": "公園に行って", "start": 0.0, "end": 1.2}]
    chunks = ["公園に", "行って"]  # 公園に=3, 行って=3 -> 6 chars total
    res = assign_words_by_char_offset(w, chunks, 0.0, 1.2)
    assert abs(res[0]["end"] - 0.6) < 1e-2, f"JA proportional wrong: {res[0]['end']}"
    print("  [OK] Japanese single-word straddle: proportional + shared borders")


def test_straddle_word_text_sliced():
    """A word that straddles a chunk boundary must have its *text* sliced too, not just
    its timestamps — otherwise the chunk's ``text`` and its ``words`` disagree
    (the exact bug that broke ASR validation on the Japanese short-drama task)."""
    import re
    _clean = lambda s: re.sub(r"\s+", "", str(s or ""))

    # Segment text and its (atomic) ASR words; one word straddles the sentence split.
    text = "そんなに特に深い意味はないんですけど。"
    parts = [
        ("そんなに", 0.0, 1.0), ("特", 1.0, 1.3), ("に", 1.3, 1.6),
        ("深", 1.6, 1.9), ("い", 1.9, 2.2), ("意", 2.2, 2.5),
        ("味", 2.5, 2.8), ("はないんですけど。", 2.8, 3.2),
    ]
    words = _substr_words(text, parts)
    chunks = ["そんなに特に深い意味はない", "んですけど。"]  # the two sentences

    res = assign_words_by_char_offset(words, chunks, 0.0, 3.2)
    assert len(res) == 2

    # chunk 0 keeps only "はない" of the straddling word (not the whole token)
    c0_words = res[0]["words"]
    assert c0_words[-1]["word"] == "はない", (
        f"chunk0 boundary word not sliced: {c0_words[-1]['word']!r}"
    )
    # chunk 1 keeps the remainder
    c1_words = res[1]["words"]
    assert c1_words[-1]["word"] == "んですけど。", (
        f"chunk1 boundary word not sliced: {c1_words[-1]['word']!r}"
    )

    # invariant: concatenated (cleaned) sub-word texts == cleaned chunk text, per chunk
    for ci, c in enumerate(res):
        joined = _clean("".join(w["word"] for w in c["words"]))
        assert joined == _clean(chunks[ci]), (
            f"chunk {ci}: words {joined!r} != chunk {chunks[ci]!r}"
        )
    print("  [OK] straddle word TEXT sliced in sync with timestamps (text==words)")


def test_no_words_fallback():
    """Segment with no word timestamps must stay within bounds (interpolation)."""
    sent = {"text": "hello world", "start": 1.0, "end": 3.0, "words": []}
    res = distribute_timestamps_to_chunks(sent, ["hello", "world"])
    for c in res:
        assert c["start"] >= 1.0 - EPS and c["end"] <= 3.0 + EPS
        assert c["start"] <= c["end"] + EPS
    print("  [OK] no-word fallback: stays within [seg_start, seg_end]")


def _run_all():
    print("Running cross-language alignment tests...\n")
    test_japanese()
    test_chinese()
    test_english()
    test_straddle()
    test_straddle_word_text_sliced()
    test_no_words_fallback()
    print("\nAll tests passed.")


if __name__ == "__main__":
    _run_all()
