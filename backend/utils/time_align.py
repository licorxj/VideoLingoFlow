"""句子级时间轴对齐（可复用）。

背景
----
ASR 引擎产出的「词级时间戳」常常是**稀疏**的：大量文字字符并没有对应的 word
时间戳（例如某句 70 个字符，但只有 15 个词带时间戳）。此前逐句把句子文本当作
字符子序列、从全局游标往后「贪心消费」 word 的做法，在词缺口处会发生「跨句抢词」：
为填满当前句缺失的字符，匹配器会一直往后扫、把下一句的词也吞进来，游标随之漂移，
误差逐句累积（实测从第 6~7 句开始整段错乱）。

本模块改用「全局字符锚点 + 线性插值」：
1. 用**同一份用于断句的全文** ``full_text``，把每个 word 锚定到它在全文归一化
   文本中的字符区间 [cs, ce)。word 按出现顺序锚定，中间允许有缺口（稀疏）。
2. 每个句子已知自己在全文归一化文本中的字符区间 [cs, ce)，直接收集落在该区间内的
   word，并用离区间边界最近的 word/segment 锚点做线性插值得到起止时间。
3. 因为每句只依赖「自己的字符区间」，相互之间完全独立，不会跨句抢词、也不会漂移，
   即使词时间戳稀疏也能给出合理时间轴。

API
---
- ``SentenceTimeAligner(full_text, words, segments=None, max_expansion=4.0)``
- ``aligner.align_next(sentence_text)`` -> ``(words_in_span, start, end)``
  顺序处理句子，内部游标自动推进，不会与下一句重叠。
- ``aligner.align_by_span(cs, ce)`` -> ``(words_in_span, start, end)``
  已知字符区间时直接对齐（断句节点若已算好偏移可走这条）。
- ``aligner.time_at_char(pos)`` -> 任意字符位置的时间（插值）。

适用节点：断句预处理、AI 字幕纠错、AI 标点补全、句子切割等任何需要把
「文本片段」映射到「带词级时间戳的 ASR 结果」的环节。
"""
from typing import Dict, List, Optional, Sequence, Tuple

import re

_WS = re.compile(r"\s+")

# Unicode 标点归一化表：把各类弯引号 / 破折号 / 不换行空格折成 ASCII 等价物。
# ASR 的 word 词元与全文 text 常使用不同码点的「同类」标点（弯引号 vs 直引号、
# em-dash vs hyphen、全角 vs 半角），若不归一化会导致字符子序列匹配失败，
# 进而触发锚定游标跳变（见 _build_word_anchors 的窗口限制）。
_PUNCT_FOLD = {
    "\u2018": "'", "\u2019": "'", "\u02bc": "'", "\u2032": "'",   # 左/右单引号等
    "\u201c": '"', "\u201d": '"', "\u2033": '"',                   # 左/右双引号
    "\u00ab": '"', "\u00bb": '"',                                  # « »
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",    # hyphen/en-dash
    "\u2014": "-", "\u2015": "-", "\u2212": "-",                   # em-dash/minus
    "\ufe58": "-", "\ufe63": "-", "\uff0d": "-",                   # 小/全角减号
    "\u00a0": " ", "\u3000": " ",                                  # 不换行/全角空格
}
_FOLD_TABLE = str.maketrans(_PUNCT_FOLD)


def norm_chars(s: str) -> str:
    """小写 + 标点归一化 + 折叠空白，保留标点（标点同样参与锚定，保证与原始词一致）。"""
    return _WS.sub("", (s or "").lower().translate(_FOLD_TABLE))


class _WordAnchor:
    __slots__ = ("cs", "ce", "start", "end", "word")

    def __init__(self, cs: int, ce: int, start, end, word: dict):
        self.cs = cs          # 第一个字符在归一化全文中的位置
        self.ce = ce          # 最后一个字符位置 + 1
        self.start = start    # 词级时间戳
        self.end = end
        self.word = word      # 原始 word 字典


class SentenceTimeAligner:
    """把文本句子对齐到带词级时间戳的 ASR 结果上。"""

    def __init__(self, full_text: str, words: Sequence[dict],
                 segments: Optional[Sequence[dict]] = None,
                 max_expansion: float = 4.0):
        self.full_text = full_text or ""
        self.norm = norm_chars(self.full_text)
        self.n = len(self.norm)
        # 子序列定位时允许的最大字符跨度膨胀倍数（防止稀疏缺口把句子拉到很远的词）
        self.max_expansion = max(1.0, float(max_expansion))
        self.anchors: List[_WordAnchor] = []
        self._build_word_anchors(words)
        self.seg_spans: List[Tuple[int, int, float, float]] = []
        self._build_segment_spans(segments)
        self._cursor = 0

    def _match_forward(self, target: str, start: int) -> Tuple[Optional[int], int]:
        """从 ``start`` 起在归一化全文中按顺序匹配 ``target`` 的字符子序列。

        返回 (first, last)。为保证鲁棒性，前向搜索被限制在
        ``start + len(target) * max_expansion + 40`` 的窗口内：当某个词元
        （尤其是单独的标点，或与全文码点不一致的标点）在附近找不到匹配时，
        直接判定失败并跳过，**绝不**让它匹配到很远的同形字符——否则游标会
        一次性跳变大段文本，导致其后所有词全部锚定失败（整段丢词级时间戳）。
        找不到返回 (None, start)。
        """
        m = len(target)
        if m == 0:
            return start, start
        cap = int(m * self.max_expansion) + 40
        limit = min(self.n, start + cap)
        i = start
        first = None
        last = start
        for ch in target:
            found = False
            while i < limit:
                if self.norm[i] == ch:
                    if first is None:
                        first = i
                    last = i
                    i += 1
                    found = True
                    break
                i += 1
            if not found:
                return None, start
        return first, last

    # ── 锚点构建 ───────────────────────────────────────────────
    def _build_word_anchors(self, words: Sequence[dict]) -> None:
        prev = 0
        for w in words or []:
            wc = norm_chars(w.get("word", ""))
            if not wc:
                continue
            first, last = self._match_forward(wc, prev)
            if first is None:
                # 该词在窗口内找不到（稀疏缺口 / 标点不一致），跳过且不推进游标
                continue
            self.anchors.append(_WordAnchor(first, last + 1,
                                            w.get("start"), w.get("end"), w))
            prev = last + 1

    def _build_segment_spans(self, segments: Optional[Sequence[dict]]) -> None:
        if not segments:
            return
        prev = 0
        for seg in segments:
            st = norm_chars(seg.get("text", ""))
            s0 = float(seg.get("start", 0) or 0)
            e0 = float(seg.get("end", 0) or 0)
            if not st:
                self.seg_spans.append((prev, prev, s0, e0))
                continue
            first, last = self._match_forward(st, prev)
            if first is None:
                self.seg_spans.append((prev, prev, s0, e0))
                continue
            self.seg_spans.append((first, last + 1, s0, e0))
            prev = last + 1

    # ── 任意字符位置 -> 时间（线性插值） ───────────────────────
    def time_at_char(self, pos: int) -> Optional[float]:
        if not self.anchors:
            return self._seg_time_at_char(pos)
        if pos <= 0:
            return self.anchors[0].start
        if pos >= self.n:
            return self.anchors[-1].end
        # 1) 命中某个 word 区间内部 -> 在该词内插值
        for a in self.anchors:
            if a.cs <= pos < a.ce:
                if a.ce > a.cs:
                    return round(a.start + (a.end - a.start) * (pos - a.cs) / (a.ce - a.cs), 4)
                return a.start
        # 2) 落在 word 缺口 -> 用前后最近的两个锚点插值
        prev_a = None
        next_a = None
        for a in self.anchors:
            if a.ce <= pos:
                prev_a = a
            if a.cs >= pos:
                next_a = a
                break
        if prev_a and next_a and prev_a is not next_a:
            span = next_a.cs - prev_a.ce
            if span > 0:
                t = prev_a.end + (next_a.start - prev_a.end) * (pos - prev_a.ce) / span
                return round(t, 4)
            return prev_a.end
        if prev_a:
            return prev_a.end
        if next_a:
            return next_a.start
        return self._seg_time_at_char(pos)

    def _seg_time_at_char(self, pos: int) -> Optional[float]:
        if not self.seg_spans:
            return None
        for cs, ce, s, e in self.seg_spans:
            if cs <= pos < ce:
                if ce > cs:
                    return round(s + (e - s) * (pos - cs) / (ce - cs), 4)
                return s
        if pos < self.seg_spans[0][0]:
            return self.seg_spans[0][2]
        if pos >= self.seg_spans[-1][1]:
            return self.seg_spans[-1][3]
        prev = None
        nxt = None
        for sp in self.seg_spans:
            if sp[1] <= pos:
                prev = sp
            if sp[0] >= pos:
                nxt = sp
                break
        if prev and nxt and prev is not nxt:
            span = nxt[0] - prev[1]
            if span > 0:
                return round(prev[3] + (nxt[2] - prev[3]) * (pos - prev[1]) / span, 4)
            return prev[3]
        return None

    # ── 句子定位 ───────────────────────────────────────────────
    def span_for_text(self, text: str, start_from: int = 0) -> Tuple[Optional[int], Optional[int]]:
        """在归一化全文中从 ``start_from`` 起，定位 ``text``（作为子序列）的字符区间
        [cs, ce)。找不到返回 (None, None)。"""
        t = norm_chars(text)
        m = len(t)
        if m == 0:
            return start_from, start_from
        i = max(0, min(start_from, self.n))
        cap = int(m * self.max_expansion) + 8
        while i < self.n:
            if self.norm[i] == t[0]:
                pos = i
                last = i
                ok = True
                for ch in t:
                    found = False
                    while pos < self.n:
                        if self.norm[pos] == ch:
                            last = pos
                            pos += 1
                            found = True
                            break
                        pos += 1
                    if not found:
                        ok = False
                        break
                if ok:
                    ce = last + 1
                    if ce - i > cap:
                        ce = i + cap  # 稀疏缺口导致膨胀过大时截断，避免跨句抢词
                    return i, ce
            i += 1
        return None, None

    def align_by_span(self, cs: int, ce: int) -> Tuple[List[dict], Optional[float], Optional[float]]:
        cs = max(0, min(cs, self.n))
        ce = max(cs, min(ce, self.n))
        # 每个 word 按其中点归到唯一一句，避免边界重叠导致跨句重复计数
        in_words = []
        for a in self.anchors:
            mid = (a.cs + a.ce) // 2
            if cs <= mid < ce:
                in_words.append(a.word)
        start = self.time_at_char(cs)
        end = self.time_at_char(ce)
        if start is not None and end is not None and start > end:
            start, end = end, start
        return in_words, start, end

    def align_next(self, text: str) -> Tuple[List[dict], Optional[float], Optional[float]]:
        """顺序对齐下一句：从内部游标处定位，结束后游标推进到句尾，避免与下一句重叠。"""
        cs, ce = self.span_for_text(text, self._cursor)
        if cs is None:
            # 定位失败（如 AI 改写导致非子序列）：游标前移一段，返回空词与 None 时间
            self._cursor = min(self._cursor + max(1, len(norm_chars(text))), self.n)
            return [], None, None
        self._cursor = ce
        return self.align_by_span(cs, ce)
