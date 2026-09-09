"""tts_duration_estimator: 多语言 TTS 朗读时长估算（纯文本统计，无需调用 TTS 引擎）。

供需要「在合成前预测朗读时长」的节点复用（如 s08_dub_task 语速预测缩减）。

设计要点：
1. 多语言兼容：按 Unicode 文字系统（CJK / 假名 / 谚文 / 拉丁 / 西里尔 / 阿拉伯等）
   将文本拆分为不同语言的片段，分别套用各语言的典型语速，混合语言文本按时长累加。
2. 数字扩展：连续数字串按读法近似折算为单词数（如 1990 ≈ "nineteen ninety"）。
3. 标点停顿：句末/逗号等标点追加自然停顿时长。
4. 短句判定：提供 ``is_short_sentence``，中文少于 3 个汉字、单词类语言少于 2 个单词
   视为短句，供缩减逻辑跳过。
"""

import math
import re
from typing import Dict, Tuple

# 各文字系统的匹配正则
_SCRIPT_PATTERNS = {
    "han": re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"),
    "kana": re.compile(r"[\u3040-\u30ff\u31f0-\u31ff]"),
    "hangul": re.compile(r"[\u1100-\u11ff\uac00-\ud7af]"),
    "cyrillic": re.compile(r"[\u0400-\u04ff]"),
    "arabic": re.compile(r"[\u0600-\u06ff]"),
    "thai": re.compile(r"[\u0e00-\u0e7f]"),
    "latin": re.compile(r"[A-Za-z\u00c0-\u024f]"),
}

# 各语言典型语速（语速因子 speed=1.0 时的「秒/单位」）：
# - 表意文字按「字」计
# - 拉丁/西里尔/阿拉伯等按「词」计
_UNIT_RATES: Dict[str, float] = {
    # 中文 ≈ 4.2 字/秒
    "han": 0.24,
    # 日语（假名为主）≈ 6.5 字/秒
    "kana": 0.15,
    # 韩语 ≈ 5 音节/秒
    "hangul": 0.20,
    # 俄语等西里尔 ≈ 2.4 词/秒
    "cyrillic": 0.42,
    # 阿拉伯语 ≈ 2.3 词/秒
    "arabic": 0.44,
    # 泰语按字符近似 ≈ 8 字/秒
    "thai": 0.125,
    # 英语等拉丁 ≈ 2.6 词/秒
    "latin": 0.38,
}

# 兜底：无法归类字符（全角符号、扩展文字等）的近似秒/字
_FALLBACK_CHAR_RATE = 0.14

# 数字串单词数折算：每 3 位约折 1 个读词，最少 1 词
_DIGIT_RUN_RE = re.compile(r"\d+")
_WORD_RE = re.compile(r"[A-Za-z\u00c0-\u024f\u0400-\u04ff\u0600-\u06ff]+(?:['’\-][A-Za-z\u00c0-\u024f\u0400-\u04ff]+)*")

# 标点停顿（秒）
_STRONG_PAUSE_RE = re.compile(r"[.!?;。！？；…]+")
_WEAK_PAUSE_RE = re.compile(r"[,，、:：\u3001]+")

_STRONG_PAUSE = 0.25
_WEAK_PAUSE = 0.12

_MIN_DURATION = 0.3


def _count_script_chars(text: str) -> Dict[str, int]:
    """统计文本中各文字系统的字符数。"""
    counts: Dict[str, int] = {}
    for name, pattern in _SCRIPT_PATTERNS.items():
        n = len(pattern.findall(text))
        if n:
            counts[name] = n
    return counts


def _digit_extra_words(text: str) -> int:
    """数字串按读法折算的额外单词数。

    数字串本身不含字母，不会被 _WORD_RE 统计到；
    这里把每个数字串按每 3 位约 1 个读词折算（如 2024 → 2 词，7 → 1 词）。
    """
    extra = 0
    for run in _DIGIT_RUN_RE.findall(text):
        extra += max(1, math.ceil(len(run) / 3))
    return extra


def _detect_primary_language(text: str, hint: str = "") -> str:
    """粗略判定文本主要语言（用于短句判定与日志）。

    Returns:
        "zh" / "ja" / "ko" / "en"（泛指拉丁词类语言）/ "other"
    """
    if hint:
        h = hint.strip().lower()
        if h.startswith("zh"):
            return "zh"
        if h.startswith("ja"):
            return "ja"
        if h.startswith("ko"):
            return "ko"

    counts = _count_script_chars(text)
    if counts.get("hangul", 0) > 0 and counts.get("hangul", 0) >= counts.get("han", 0):
        return "ko"
    if counts.get("kana", 0) > 0:
        return "ja"
    if counts.get("han", 0) > 0:
        return "zh"
    if counts.get("latin", 0) > 0 or counts.get("cyrillic", 0) > 0 or counts.get("arabic", 0) > 0:
        return "en"
    return "other"


def count_language_units(text: str) -> Tuple[Dict[str, int], int]:
    """统计文本的语言单元数量。

    Returns:
        (script_char_counts, word_count)
        - script_char_counts: 各文字系统的字符数（han/kana/hangul/thai 等）
        - word_count: 词类语言（拉丁/西里尔/阿拉伯）的单词数 + 数字串折算词数
    """
    counts = _count_script_chars(text)
    word_count = len(_WORD_RE.findall(text)) + _digit_extra_words(text)
    return counts, word_count


def estimate_tts_duration(text: str, language: str = "", speed: float = 1.0) -> float:
    """估算文本的 TTS 朗读时长（秒）。

    多语言混合文本：各文字系统按各自语速分别计算后累加；
    标点追加自然停顿；无法归类字符按兜底速率计算。

    Args:
        text: 待朗读文本
        language: 语言提示（如 "zh"/"en"，可选，当前模型按字符系统自动识别）
        speed: 语速因子（>1 更快，<1 更慢），默认 1.0

    Returns:
        估算时长（秒），最小 0.3 秒
    """
    if not text or not str(text).strip():
        return 0.0
    text = str(text)

    counts = _count_script_chars(text)
    word_count = len(_WORD_RE.findall(text)) + _digit_extra_words(text)

    total = 0.0
    total += counts.get("han", 0) * _UNIT_RATES["han"]
    total += counts.get("kana", 0) * _UNIT_RATES["kana"]
    total += counts.get("hangul", 0) * _UNIT_RATES["hangul"]
    total += counts.get("thai", 0) * _UNIT_RATES["thai"]

    # 词类语言（拉丁/西里尔/阿拉伯）统一按 word_count 计，按字符占比加权词长速率
    if word_count:
        # 词类语言：西里尔/阿拉伯略慢，按字符占比微调；拉丁语速为基准
        cyrillic_chars = counts.get("cyrillic", 0)
        arabic_chars = counts.get("arabic", 0)
        latin_chars = counts.get("latin", 0)
        word_chars = cyrillic_chars + arabic_chars + latin_chars
        if word_chars > 0:
            # 加权平均词长速率（按字符占比在 latin 基准与更慢语种之间插值）
            weighted = (
                latin_chars * _UNIT_RATES["latin"]
                + cyrillic_chars * _UNIT_RATES["cyrillic"]
                + arabic_chars * _UNIT_RATES["arabic"]
            ) / word_chars
        else:
            weighted = _UNIT_RATES["latin"]
        total += word_count * weighted

    # 兜底：去除已归类字符后的剩余非空白字符
    accounted = sum(counts.values())
    rest_chars = len(re.sub(r"\s", "", text)) - accounted
    if rest_chars > 0:
        total += rest_chars * _FALLBACK_CHAR_RATE

    # 标点停顿
    total += len(_STRONG_PAUSE_RE.findall(text)) * _STRONG_PAUSE
    total += len(_WEAK_PAUSE_RE.findall(text)) * _WEAK_PAUSE

    if speed > 0 and speed != 1.0:
        total = total / speed

    return round(max(_MIN_DURATION, total), 4)


def is_short_sentence(text: str, language: str = "") -> bool:
    """判定是否为「不值得缩减」的短句。

    规则：
    - 含汉字（中/日文文本）：汉字少于 3 个视为短句
    - 纯词类语言（英/俄/阿等）：单词少于 2 个视为短句
    - 空文本视为短句
    """
    if not text or not str(text).strip():
        return True
    text = str(text)
    counts = _count_script_chars(text)

    if counts.get("han", 0) > 0 or counts.get("kana", 0) > 0:
        return counts.get("han", 0) + counts.get("kana", 0) < 3

    _, word_count = count_language_units(text)
    return word_count < 2


def detect_language(text: str, hint: str = "") -> str:
    """对外暴露的语言探测（主要语言），便于调用方记录日志。"""
    return _detect_primary_language(text, hint)
