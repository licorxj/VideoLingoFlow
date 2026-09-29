"""中文同音字修复（术语表 + 拼音匹配）。

场景：ASR 把专有名词识别成同音字/近音字（如"玄戒"→"悬界"、"哔哩哔哩"→"比例比例"），
用一份"正确术语表"按拼音在字幕文本中做等长替换。

设计要点
--------
* **等长替换**：只替换与术语**字数完全相同**的片段，保证 word 级时间戳与字幕行长度不变
  （下游断句/对齐/配音都不受影响）。
* **拼音归一**：默认忽略声调；可选模糊音（zh/z、ch/c、sh/s、n/l、前后鼻音等）。
* **首字分桶**：按术语首字拼音建索引，O(n·k) 扫描，长字幕也很快。
* **无依赖**：仅需 pypinyin（纯 Python）。
"""
import os
import re
from typing import Dict, List, Optional, Tuple

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def _is_cjk(ch: str) -> bool:
    return bool(_CJK_RE.match(ch))


# 模糊音归一（把易混拼音合并到同一形式）
_FUZZY_RULES: List[Tuple[str, str]] = [
    ("zh", "z"), ("ch", "c"), ("sh", "s"),
    ("ang", "an"), ("eng", "en"), ("ing", "in"),
    ("iang", "ian"), ("uang", "uan"),
    ("ong", "on"), ("iong", "ion"),
]


class HomophoneFixer:
    """按术语表做中文同音字替换。"""

    def __init__(self, terms: List[str], fuzzy: bool = False, min_len: int = 2):
        self.fuzzy = bool(fuzzy)
        self.min_len = max(1, int(min_len))
        self.terms: List[str] = []
        self._pinyin_cache: Dict[str, str] = {}
        self._index: Dict[str, List[str]] = {}

        seen = set()
        for t in terms or []:
            t = (t or "").strip()
            if not t or t in seen:
                continue
            if len(t) < self.min_len:
                continue
            if not any(_is_cjk(c) for c in t):
                continue  # 纯英文/数字术语不做同音替换
            seen.add(t)
            self.terms.append(t)

        # 长词优先：避免短词先命中导致长词匹配不到
        self.terms.sort(key=len, reverse=True)
        for t in self.terms:
            key = self._norm_first(t[0])
            self._index.setdefault(key, []).append(t)

    # ------------------------------------------------------------------
    def _pinyin(self, s: str) -> str:
        """把字符串转为归一化拼音串（非汉字字符小写原样保留）。"""
        cached = self._pinyin_cache.get(s)
        if cached is not None:
            return cached
        try:
            from pypinyin import Style, lazy_pinyin
        except ImportError:
            # 无 pypinyin 时退化为大小写无关的字面匹配
            out = s.lower()
            self._pinyin_cache[s] = out
            return out

        parts: List[str] = []
        for ch in s:
            if _is_cjk(ch):
                try:
                    py = (lazy_pinyin(ch, style=Style.NORMAL) or [""])[0]
                except Exception:
                    py = ch
            else:
                py = ch.lower()
            if self.fuzzy and py:
                for a, b in _FUZZY_RULES:
                    if py.endswith(a):
                        py = py[: -len(a)] + b
                        break
            parts.append(py)
        out = "".join(parts)
        self._pinyin_cache[s] = out
        return out

    def _norm_first(self, ch: str) -> str:
        return self._pinyin(ch)

    # ------------------------------------------------------------------
    def fix_text(self, text: str) -> Tuple[str, List[str]]:
        """修复单段文本，返回 (新文本, 本次命中的术语列表)。"""
        if not text or not self.terms:
            return text, []

        out: List[str] = []
        hits: List[str] = []
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            matched = None
            if _is_cjk(ch):
                for term in self._index.get(self._norm_first(ch), ()):
                    L = len(term)
                    if i + L > n:
                        continue
                    frag = text[i:i + L]
                    if frag == term:
                        break  # 已是正确写法
                    if self._pinyin(frag) == self._pinyin(term):
                        matched = term
                        break

            if matched and matched != ch:
                out.append(matched)
                hits.append(matched)
                i += len(matched)
            else:
                out.append(ch)
                i += 1
        return "".join(out), hits

    # ------------------------------------------------------------------
    def fix_segment(self, segment: dict) -> Tuple[int, List[str]]:
        """就地修复一个 segment（text 与 words 同步）。返回 (替换数, 命中术语)。"""
        text = (segment.get("text") or "")
        if not text:
            return 0, []

        new_text, hits = self.fix_text(text)
        if not hits:
            return 0, []

        segment["text"] = new_text

        # words 同步：等长替换 → 按原 word 长度切分回填，时间戳保持不变
        words = segment.get("words") or []
        if words:
            try:
                joined = "".join(str(w.get("word", "")) for w in words)
                if len(joined) == len(new_text):
                    pos = 0
                    ok = True
                    for w in words:
                        wlen = len(str(w.get("word", "")))
                        w["word"] = new_text[pos:pos + wlen]
                        pos += wlen
                    if not ok:
                        raise ValueError
                else:
                    # 长度不一致（理论上不会发生）：放弃 words 同步，仅改 text
                    pass
            except Exception:
                pass
        return len(hits), hits


# ---------------------------------------------------------------------------
# 术语表读取
# ---------------------------------------------------------------------------
def load_terms(include_project_glossary: bool = True,
               terms_file: Optional[str] = None,
               extra_terms: Optional[str] = None) -> List[str]:
    """汇总术语来源：项目自定义术语表 + 指定文件 + 直接输入。"""
    terms: List[str] = []

    if include_project_glossary:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        default_file = os.path.join(root, "自定义术语表.json")
        terms.extend(_read_glossary_file(default_file))

    if terms_file:
        terms.extend(_read_glossary_file(terms_file))

    if extra_terms:
        for line in re.split(r"[\n,，;；]+", str(extra_terms)):
            line = line.strip()
            if line:
                terms.append(line)

    # 去重保序
    seen = set()
    out = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _read_glossary_file(path: str) -> List[str]:
    """读取术语表：支持 {"terminology": [{"term": ...}]} / {"terms": [...]} / 纯文本行。"""
    if not path or not os.path.exists(path):
        return []
    try:
        if path.lower().endswith(".json"):
            import json
            with open(path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            items: List[str] = []
            if isinstance(data, dict):
                raw = data.get("terminology") or data.get("terms") or []
                for it in raw:
                    if isinstance(it, dict):
                        term = it.get("term") or it.get("src") or it.get("word") or ""
                        # 中英对照表里 src 为中文原词时同样可用于同音修复
                        items.append(str(term).strip())
            elif isinstance(data, list):
                for it in data:
                    if isinstance(it, str):
                        items.append(it.strip())
                    elif isinstance(it, dict):
                        items.append(str(it.get("term") or "").strip())
            return [t for t in items if t]
        with open(path, "r", encoding="utf-8-sig") as f:
            return [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    except Exception:
        return []
