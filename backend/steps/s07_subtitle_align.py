"""s07_subtitle_align: Split long translations and align with source text.

输入（严格按画布连线，不再按文件名扫描缓存）：
  - ``asr``      ASR 结构化 JSON（``{"segments": [{start, end, text, words: [{word, start, end}]}]}``
                 或等价的句子列表）。提供「句子级时间戳表」与「词级时间戳表」。
  - ``subtitle`` 翻译结果 JSON（逐句翻译产物，条目含 id/text/start/end 与 direct/reflect）。

处理流程：
  1. 从 ``asr`` 读入并展开为全局词级时间戳表；从 ``subtitle`` 读入逐句译文。
  2. 用「归一化文本精确子串匹配」把每句原文定位到词表上，得到该句的词区间
     （借鉴原始项目 step6 的全局词串 + 位置映射思路），保证严格单调、不重叠。
  3. 译文超长的句子：
     a. 先确定性地切分「源文」（标点优先 + 按语言权重均衡），源文分片必定是原文的
        连续子串，天然满足拼接还原；
     b. 再让 LLM 只负责把「译文」切成与源文分片对齐的若干份（借鉴原始项目
        step5 的 split-then-align 思路：只做一次决策，不修改内容）；
        LLM 失败时用本地标点/权重切分兜底。
     c. 分片时间戳由该句词区间内的词（按分片文本再次精确定位）直接得出。
  4. 最多迭代 ``MAX_ROUNDS`` 轮，直到所有分片都在长度限制内。每轮把「全句超长分片」
     的切分任务按字符预算打包成批次，**一次 LLM 请求处理多个切分任务**（组装模式，
     借鉴 subtitle_reduction 的批量思路）。请求量控制（避免瞬时打爆上游限速）：

     - 模型「拒绝切分」（返回整句 + 空片）或单片内容不合格 → 本地确定性切分，
       **不发任何请求**（同样的问法重试只会得到同样的回复）；
     - 仅「整批请求不可用」（异常 / 整批无法解析）才逐句重试，且每轮次数受
       ``DEFAULT_SINGLE_FALLBACK_BUDGET`` 预算限制，超出即本地切分；
     - 某轮 LLM 零命中即刻熔断，后续轮次全部本地切分；
     - 所有请求经节流闸（``llm.min_request_interval`` / 节点「请求最小间隔」），
       给上游限速留出确定性余量。

     节点设置可关闭批量对齐，回到「每句独立请求」的旧行为。
  5. 句内相邻分片间隔小于 ``GAP_FILL_LIMIT`` 时补齐（借鉴 step6 的去缝隙）。

输出：``cache/subtitle_aligned{_node_id}.json``，条目形如
``{"id", "src", "tr", "start", "end"}``。
"""
import os
import re
import json
import time
import difflib
import threading
from typing import Callable, Optional, List, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from backend.steps.base_step import BaseStep
from backend.config.config_manager import config
from backend.llm.llm_client import get_llm_client


# ── 常量 ─────────────────────────────────────────────────────────────

INPUT_PORT_SUBTITLE = "subtitle"
INPUT_PORT_ASR = "asr"
INPUT_PORT_LABELS = {
    INPUT_PORT_SUBTITLE: "翻译结果JSON",
    INPUT_PORT_ASR: "asr格式json",
}

MAX_ROUNDS = 3              # 每句最多迭代切分轮数（每轮把超长分片二切）
MIN_PART_DURATION = 0.12    # 单个条目最短时长（秒）
GAP_FILL_LIMIT = 1.0        # 同句内相邻分片间隔小于该值时补齐（秒）
ALIGN_SIMILARITY_FLOOR = 0.9  # 译文分片拼接与原文的相似度下限
DEFAULT_MAX_REQUEST_CHARS = 6000  # 批量对齐时单次请求的默认字符预算（回退值）
DEFAULT_REQUEST_INTERVAL = 0.5    # 两次 LLM 请求的最小间隔（秒）：并发下的硬速率上限
DEFAULT_SINGLE_FALLBACK_BUDGET = 8  # 每轮「整批不可用 → 逐句重试」的次数预算


class _RequestGate:
    """节流闸：限制在飞请求数 + 两次请求之间的最小间隔。

    组装模式会同时开多条线程发请求，逐句兜底又会叠加在它之上；没有闸门时瞬时
    QPS 只取决于并发数，很容易直接打爆上游限速（429）。闸门按配置组合在进程内
    共享，因此同一进程的多个节点实例共用同一个速率上限。
    """

    def __init__(self, max_in_flight: int, min_interval: float):
        self._sem = threading.BoundedSemaphore(max(1, int(max_in_flight)))
        self._interval = max(0.0, float(min_interval))
        self._lock = threading.Lock()
        self._next_slot = 0.0

    def __enter__(self):
        self._sem.acquire()
        if self._interval > 0:
            with self._lock:
                now = time.monotonic()
                wait = max(0.0, self._next_slot - now)
                self._next_slot = max(now, self._next_slot) + self._interval
            if wait > 0:
                time.sleep(wait)
        return self

    def __exit__(self, exc_type, exc, tb):
        self._sem.release()
        return False


_GATES: Dict[Tuple[int, float], "_RequestGate"] = {}
_GATES_LOCK = threading.Lock()


def _gate_for(max_in_flight: int, min_interval: float) -> "_RequestGate":
    """取（或建）按配置共享的节流闸。"""
    key = (max(1, int(max_in_flight)), round(max(0.0, float(min_interval)), 3))
    with _GATES_LOCK:
        gate = _GATES.get(key)
        if gate is None:
            gate = _RequestGate(key[0], key[1])
            _GATES[key] = gate
        return gate

# 归一化时剔除的标点/空白（词表与句子文本用同一套规则，保证可比）
_PUNCT_STRIP_RE = re.compile(
    r"[\s\-—–…·、，。！？；：,.!?;:\"'“”‘’()\[\]{}<>《》【】（）「」『』]"
)


# ── 语言权重 / 长度度量 ───────────────────────────────────────────────


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
    cfg = _load_language_weights_config()
    weights = cfg.get("weights", {})
    default_weight = cfg.get("default", 1.0)
    code = str(lang_code or "").strip().lower()
    if not code:
        return default_weight
    if code in weights:
        return weights[code]
    base = code.split("-")[0]
    if base in weights:
        return weights[base]
    return weights.get("_default", default_weight)


def calc_len(text: str) -> float:
    """Calculate weighted character count for subtitle length checking.

    Uses language-specific weights from backend/config/language_char_weights.json.
    CJK characters count as 1.0 (baseline), English/other languages have higher weights.
    """
    cfg = _load_language_weights_config()
    weights = cfg.get("weights", {})
    fullwidth_weight = cfg.get("fullwidth", 1.5)
    default_weight = cfg.get("default", 1.0)

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

    return sum(char_weight(c) for c in str(text or ""))


def _normalize_for_matching(text: str) -> str:
    """Normalize text for exact substring matching: drop punctuation/space, lowercase."""
    return _PUNCT_STRIP_RE.sub("", str(text or "")).lower()


# ── 词级时间戳表 ─────────────────────────────────────────────────────


class _WordIndex:
    """全局词级时间戳表：归一化拼串 + 字符位置 -> 词下标映射。

    借鉴原始项目 step6 ``get_sentence_timestamps`` 的做法：把全部词拼成一个
    去掉标点/空格的字符串，并记录每个字符位置属于哪个词，于是任意文本都能用
    「精确子串查找」映射回精确的词区间，比按字符数累积估算稳健得多。
    """

    def __init__(self, words: List[Dict]):
        self.words: List[Dict] = [
            w for w in (words or []) if isinstance(w, dict)
        ]
        self.text: str = ""
        self.pos_to_word: List[int] = []
        self.cum_end: List[int] = []  # cum_end[i] = 第 i 个词结束后的归一化字符数
        acc = 0
        for idx, word in enumerate(self.words):
            norm = _normalize_for_matching(word.get("word", ""))
            self.pos_to_word.extend([idx] * len(norm))
            self.text += norm
            acc += len(norm)
            self.cum_end.append(acc)

    def __len__(self) -> int:
        return len(self.words)

    def locate(self, needle: str, from_char: int = 0) -> Optional[Tuple[int, int, int]]:
        """在拼串中查找 ``needle``，返回 ``(起始词下标, 结束词下标, 结束后的字符位置)``。

        找不到时返回 ``None``。
        """
        if not needle:
            return None
        pos = self.text.find(needle, max(0, int(from_char)))
        if pos < 0:
            return None
        end_char = pos + len(needle) - 1
        if end_char >= len(self.pos_to_word):
            return None
        start_word = self.pos_to_word[pos]
        end_word = self.pos_to_word[end_char]
        # 吸收紧跟其后的纯标点词，保留分片收尾的句读符号
        while (
            end_word + 1 < len(self.words)
            and not _normalize_for_matching(self.words[end_word + 1].get("word", ""))
        ):
            end_word += 1
        return start_word, end_word, self.cum_end[end_word]


def _word_time(word: Dict, key: str, default: float = 0.0) -> float:
    try:
        return float(word.get(key, default) or default)
    except (TypeError, ValueError):
        return float(default)


def _range_bounds(words: List[Dict], start_idx: int, end_idx: int) -> Optional[Tuple[float, float]]:
    """把词区间换算为 ``(start, end)``；区间内没有有效时间戳时返回 None。"""
    if not words or start_idx is None or end_idx is None:
        return None
    lo = max(0, min(int(start_idx), len(words) - 1))
    hi = max(lo, min(int(end_idx), len(words) - 1))
    selected = words[lo:hi + 1]
    starts = [_word_time(w, "start") for w in selected]
    ends = [_word_time(w, "end") for w in selected]
    if not starts or not ends:
        return None
    start = min(starts)
    end = max(ends)
    if end < start:
        end = start
    return start, end


# ── 提示词 ───────────────────────────────────────────────────────────


def _get_align_system_prompt(src_lang: str = "source", tgt_lang: str = "target") -> str:
    return f"""### Role
You are a professional Netflix subtitle alignment expert fluent in both {src_lang} and {tgt_lang}.

### Core Task
The {src_lang} source text has ALREADY been split into fixed parts.
Split ONLY the {tgt_lang} translation into the same number of aligned parts.

### ABSOLUTE RULES - VIOLATION = FAILURE
1. **ONLY CUT, NEVER MODIFY** - never change, rewrite, add or remove any word of the translation.
2. **DO NOT touch the source parts** - they are already fixed. Only cut the translation.
3. **Split at the same semantic positions as the source parts** so the audience reads them in sync.
4. **Punctuation stays with the preceding text** - a comma/period must never start a part.
5. **Every part must contain REAL text** - no placeholders like "(part of...)" or "[continued]".
6. Never merge, summarise, duplicate or drop content.

### Output Format in JSON
{{
    "analysis": "brief note about where and why you cut the translation",
    "target_parts": ["aligned_part1", "aligned_part2"]
}}

### Your Answer: provide ONLY a valid JSON object, no extra explanation.
"""


def _build_align_prompt(
    source_text: str,
    translation: str,
    source_parts: List[str],
    word_limit: float,
    src_lang: str = "source",
    tgt_lang: str = "target",
) -> dict:
    """构造「源文已切好、只切译文」的对齐提示词。"""
    num_parts = len(source_parts)
    parts_block = "\n".join(
        f"{i + 1}. {part}" for i, part in enumerate(source_parts)
    )
    try:
        from backend.prompts.prompt_service import get_prompt_service
        svc = get_prompt_service()
        result = svc.assemble_prompt("s07_subtitle_align", {
            "src_lang": src_lang,
            "tgt_lang": tgt_lang,
            "num_parts": num_parts,
            "word_limit": f"{word_limit:.0f}",
            "source_text": source_text,
            "source_parts": parts_block,
            "translation": translation,
        })
        if result.get("found") and result.get("user_prompt"):
            return {
                "system_prompt": result.get("system_prompt") or _get_align_system_prompt(src_lang, tgt_lang),
                "user_prompt": result.get("user_prompt"),
            }
    except Exception as exc:  # 模板服务不可用时回退内置提示词
        print(f"[SubtitleAlign] Prompt template unavailable, using builtin prompt: {exc}")

    return {
        "system_prompt": _get_align_system_prompt(src_lang, tgt_lang),
        "user_prompt": f"""### Task
Split the {tgt_lang} translation into exactly {num_parts} parts, aligned with the
already-split {src_lang} source parts.

### Already-split {src_lang} source parts (FIXED, do not change them)
{parts_block}

### Full {src_lang} source text
{source_text}

### Full {tgt_lang} translation (cut this one)
{translation}

### Hard Requirements
1. Return exactly {num_parts} target parts, in order, no empty string.
2. The concatenation of the target parts MUST equal the full translation
   (only the cut positions change, not a single character).
3. Cut at the position that corresponds to the source part boundary;
   punctuation stays at the END of the preceding part.
4. Each target part should be at most about {word_limit:.0f} characters.
5. No placeholders, no explanations, no duplicated content.

### Return this JSON object exactly
{{
    "analysis": "brief note about the cut position",
    "target_parts": {json.dumps(["part%d" % (i + 1) for i in range(num_parts)], ensure_ascii=False)}
}}
""",
    }


def _build_retry_prompt(
    source_text: str,
    translation: str,
    source_parts: List[str],
    word_limit: float,
    issues: List[str],
    previous_result: Any,
    src_lang: str = "source",
    tgt_lang: str = "target",
) -> dict:
    issue_lines = "\n".join(f"- {issue}" for issue in issues) or "- unknown validation failure"
    previous_json = json.dumps(previous_result, ensure_ascii=False)[:800]
    prompt_data = _build_align_prompt(
        source_text, translation, source_parts, word_limit, src_lang, tgt_lang
    )
    prompt_data["user_prompt"] += (
        "\n\n### Your previous answer was INVALID\n"
        f"Validation errors:\n{issue_lines}\n\n"
        f"Previous invalid JSON:\n{previous_json}\n\n"
        f"Fix it and return a new JSON object with exactly {len(source_parts)} target parts."
    )
    return prompt_data


def _get_align_batch_system_prompt(num_tasks: int, src_lang: str = "source", tgt_lang: str = "target") -> str:
    """组装模式系统提示词：一次请求处理多个彼此独立的切分任务。"""
    return f"""### Role
You are a professional Netflix subtitle alignment expert fluent in both {src_lang} and {tgt_lang}.

### Core Task
You receive {num_tasks} INDEPENDENT alignment task(s). For EACH task, the {src_lang} source
text has ALREADY been split into fixed parts. Split ONLY the {tgt_lang} translation of that
task into the same number of aligned parts.

### ABSOLUTE RULES - VIOLATION = FAILURE
1. **ONLY CUT, NEVER MODIFY** - never change, rewrite, add or remove any word of a translation.
2. **DO NOT touch the source parts** - they are already fixed. Only cut the translation.
3. **Split at the same semantic positions as the source parts** so the audience reads them in sync.
4. **Punctuation stays with the preceding text** - a comma/period must never start a part.
5. **Every part must contain REAL text** - no placeholders like "(part of...)" or "[continued]".
6. Never merge, summarise, duplicate or drop content.
7. **Each task is isolated** - never let one task's text leak into another task's parts.

### Output Format in JSON
{{
    "results": [
        {{"index": 0, "target_parts": ["aligned_part1", "aligned_part2"]}},
        {{"index": 1, "target_parts": ["aligned_part1", "aligned_part2"]}}
    ]
}}

### Your Answer: provide ONLY a valid JSON object, no extra explanation.
"""


def _build_align_batch_prompt(payloads: List[Dict], src_lang: str = "source", tgt_lang: str = "target") -> dict:
    """构造「多任务合并」的对齐提示词。

    优先使用 ``s07_subtitle_align_batch`` 提示词模板（可在提示词管理中自定义），
    模板缺失时用内置提示词；与单任务的 ``s07_subtitle_align`` 是同一套语义。
    """
    payload_json = json.dumps(payloads, ensure_ascii=False, indent=2)
    example_results = [
        {
            "index": index,
            "target_parts": [f"part{i + 1}" for i in range(int(item.get("num_parts") or 2))],
        }
        for index, item in enumerate(payloads)
    ]
    try:
        from backend.prompts.prompt_service import get_prompt_service
        svc = get_prompt_service()
        result = svc.assemble_prompt("s07_subtitle_align_batch", {
            "src_lang": src_lang,
            "tgt_lang": tgt_lang,
            "count": len(payloads),
            "tasks": payload_json,
            "results_example": json.dumps(example_results, ensure_ascii=False),
        })
        if result.get("found") and result.get("user_prompt"):
            return {
                "system_prompt": result.get("system_prompt")
                or _get_align_batch_system_prompt(len(payloads), src_lang, tgt_lang),
                "user_prompt": result.get("user_prompt"),
            }
    except Exception as exc:  # 模板服务不可用时回退内置提示词
        print(f"[SubtitleAlign] Batch prompt template unavailable, using builtin prompt: {exc}")

    return {
        "system_prompt": _get_align_batch_system_prompt(len(payloads), src_lang, tgt_lang),
        "user_prompt": f"""### Task
For EACH of the {len(payloads)} tasks below, split the {tgt_lang} translation into exactly
that task's `num_parts` parts, aligned with that task's already-split {src_lang} source parts.
Each task is independent: never mix content between tasks.

### Tasks (JSON array)
{payload_json}

### Hard Requirements
1. Return exactly one result per task, keeping the same `index`, in the same order.
2. `target_parts` must contain exactly `num_parts` non-empty strings for that task.
3. The concatenation of a task's `target_parts` MUST equal that task's full `translation`
   (only the cut positions change, not a single character).
4. Cut at the position that corresponds to the source part boundary;
   punctuation stays at the END of the preceding part.
5. Each part should be at most about that task's `word_limit` characters.
6. No placeholders, no explanations, no duplicated content.

### Return this JSON object exactly
{{
    "results": {json.dumps(example_results, ensure_ascii=False)}
}}
""",
    }


def _coerce_align_results(result: Any) -> Optional[Dict[str, List[str]]]:
    """把批量返回规整为 ``{批次内序号: target_parts}``；无法解析时返回 None。"""
    if isinstance(result, str):
        text = result.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
        try:
            result = json.loads(text)
        except Exception:
            return None

    if isinstance(result, dict):
        items = None
        for key in ("results", "data", "items"):
            if isinstance(result.get(key), list):
                items = result[key]
                break
        if items is None:
            # 兼容模型退化成「单任务」返回形态
            parts = result.get("target_parts")
            if isinstance(parts, list):
                return {"0": [str(p).strip() for p in parts]}
            return None
    elif isinstance(result, list):
        items = result
    else:
        return None

    out: Dict[str, List[str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        key = item.get("index")
        parts = item.get("target_parts") or item.get("parts")
        if key is None or not isinstance(parts, list):
            continue
        # 保留空片位：空片是「模型拒绝切分」的信号，滤掉会被误判成「数量不符」
        out[str(key)] = [str(p).strip() for p in parts]
    return out


def _pack_align_batches(tasks: List[Dict], max_request_chars: int) -> List[List[Dict]]:
    """按字符预算把切分任务打包（组装模式下 1 批 = 1 次 LLM 请求）。"""
    overhead = len(_build_align_batch_prompt([])["user_prompt"]) + len(_get_align_batch_system_prompt(0))
    budget = max(800, int(max_request_chars) - overhead - 200)

    def _task_chars(task: Dict) -> int:
        """单个任务在请求体中占用的近似字符数（与 ``_task_payload`` 字段保持一致）。"""
        return len(json.dumps({
            "index": 0,
            "num_parts": len(task.get("src_parts") or []),
            "word_limit": "0000",
            "source_parts": list(task.get("src_parts") or []),
            "source_text": str(task.get("src_text") or ""),
            "translation": str(task.get("translation") or ""),
        }, ensure_ascii=False))

    batches: List[List[Dict]] = []
    current: List[Dict] = []
    current_chars = 0
    for task in tasks:
        size = _task_chars(task)
        if current and current_chars + size > budget:
            batches.append(current)
            current = []
            current_chars = 0
        current.append(task)
        current_chars += size
    if current:
        batches.append(current)
    return batches


# ── 校验 ─────────────────────────────────────────────────────────────


_PLACEHOLDER_PATTERNS = (
    "this is part of",
    "[continued]",
    "[part of",
    "(continued)",
    "(see part",
    "(combined clause",
    "part of the",
    "part of #",
    "(part ",
)

_PUNCTUATION_ONLY = set("。！？，、；：""''【】《》（）…—,.!?;:\"'()[]{}")


def _has_placeholder(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return any(pattern in lowered for pattern in _PLACEHOLDER_PATTERNS)


def _looks_like_refusal(raw_parts: Any, translation: str) -> bool:
    """模型「拒绝切分」的两种形态：分片数够但存在空片，或只有一片且就是整句。

    这不是格式错误——再问一次通常还是同样的回复，所以应直接走本地确定性切分，
    而不是白白再花 1~2 次请求重试（这是请求量失控的主因之一）。
    """
    if not isinstance(raw_parts, list) or not raw_parts:
        return False
    stripped = [str(p).strip() for p in raw_parts]
    if any(not p for p in stripped) and any(stripped):
        return True
    if len(stripped) == 1 and stripped[0]:
        return _normalize_for_matching(stripped[0]) == _normalize_for_matching(translation)
    return False


def _validate_target_parts(
    target_parts: List[str],
    num_parts: int,
    translation: str,
    max_length: float,
) -> List[str]:
    """校验 LLM 返回的译文分片；返回问题列表（空表示通过）。"""
    issues: List[str] = []
    if len(target_parts) != num_parts:
        issues.append(f"target part count mismatch: got {len(target_parts)}, expected {num_parts}")
        return issues
    if any(not str(p).strip() for p in target_parts):
        issues.append("empty target part detected")

    for idx, part in enumerate(target_parts):
        stripped = str(part).strip()
        if _has_placeholder(stripped):
            issues.append(f"placeholder text in target part {idx + 1}: '{stripped[:40]}'")
        if stripped and all(c in _PUNCTUATION_ONLY for c in stripped):
            issues.append(f"punctuation-only target part {idx + 1}: '{stripped}'")

    seen = set()
    for idx, part in enumerate(target_parts):
        key = str(part).strip()
        if key in seen:
            issues.append(f"duplicate target content in part {idx + 1}: '{key[:30]}'")
        seen.add(key)

    # 拼接还原校验（忽略标点/空白差异；允许极小的排版偏差）
    original_norm = _normalize_for_matching(translation)
    joined_norm = _normalize_for_matching("".join(str(p) for p in target_parts))
    if original_norm != joined_norm:
        ratio = difflib.SequenceMatcher(None, original_norm, joined_norm).ratio()
        if ratio < ALIGN_SIMILARITY_FLOOR:
            issues.append(
                f"target parts don't reconstruct the translation "
                f"(similarity {ratio:.2f} < {ALIGN_SIMILARITY_FLOOR})"
            )
        else:
            print(
                f"[SubtitleAlign] Target parts differ slightly from the translation "
                f"(similarity {ratio:.3f}), accepted"
            )

    too_long = [
        f"part {i + 1} ({len(str(p))} chars, limit {max_length:.0f})"
        for i, p in enumerate(target_parts)
        if len(str(p)) > max_length
    ]
    if too_long and num_parts > 1:
        print(f"[SubtitleAlign] Target parts over limit (kept for another round): {'; '.join(too_long)}")

    return issues


# ── 本地（无 LLM）切分 ────────────────────────────────────────────────


_STRONG_PUNCT = "。！？!?…"
_WEAK_PUNCT = "，、；：,;:"


# 各候选切分点的偏好惩罚（相对整句权重的比例）：句末标点 > 从句标点/空格 > 括号短横
_SPLIT_RANK_PENALTY = (0.0, 0.02, 0.02, 0.06)


def _find_split_index(text: str, target_weight: float) -> int:
    """返回最接近 ``target_weight`` 的切分位置，优先落在标点/词边界之后。"""
    if not text:
        return 0
    text = str(text)
    if len(text) < 2:
        return 0
    middle = len(text) / 2.0
    total_weight = max(calc_len(text), 1e-6)
    best: Optional[Tuple[float, int, float, int]] = None
    for idx in range(1, len(text)):
        prev_char, curr_char = text[idx - 1], text[idx]
        if prev_char in _STRONG_PUNCT:
            rank = 0
        elif prev_char in _WEAK_PUNCT:
            rank = 1
        elif curr_char.isspace():
            rank = 2
        elif prev_char in "-/)]}\"" or curr_char in "([{":
            rank = 3
        else:
            continue
        weight = calc_len(text[:idx])
        # 归一化距离为主，标点偏好为辅：避免为了「刚好均衡」而切进单词内部
        score = abs(weight - target_weight) / total_weight + _SPLIT_RANK_PENALTY[rank]
        candidate = (score, rank, abs(idx - middle), idx)
        if best is None or candidate < best:
            best = candidate

    if best is not None:
        return best[3]

    cumulative = 0.0
    for idx, char in enumerate(text, start=1):
        cumulative += calc_len(char)
        if cumulative >= target_weight:
            return max(1, min(idx, len(text) - 1))
    return max(1, min(len(text) - 1, len(text) // 2))


def _split_text_locally(text: str, num_parts: int) -> List[str]:
    """按标点 + 语言权重把文本均分为 ``num_parts`` 份（确定性兜底）。"""
    text = str(text or "").strip()
    if num_parts <= 1 or not text:
        return [text]

    parts: List[str] = []
    remaining = text
    remaining_parts = num_parts
    while remaining_parts > 1 and remaining:
        target_weight = calc_len(remaining) / remaining_parts
        split_idx = _find_split_index(remaining, target_weight)
        left = remaining[:split_idx].strip()
        right = remaining[split_idx:].strip()
        if not left or not right:
            break
        parts.append(left)
        remaining = right
        remaining_parts -= 1

    if remaining.strip():
        parts.append(remaining.strip())

    if len(parts) != num_parts or any(not p for p in parts):
        return [text]
    return parts


# ── Step ─────────────────────────────────────────────────────────────


class S07SubtitleAlign(BaseStep):
    step_id = "s07_subtitle_align"
    step_name = "译文断句和双语对齐"
    dependencies = ["s05_translate"]
    artifacts = ["cache/subtitle_aligned.json"]

    # ── 配置 ─────────────────────────────────────────────────────────

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

    # ── 输入解析（严格按连线端口，不做文件名扫描）──────────────────────

    def _require_input_path(self, task_dir: str, port: str) -> str:
        """按输入端口取上游产物绝对路径；缺失/不存在时抛出明确错误。"""
        label = INPUT_PORT_LABELS.get(port, port)
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        raw = step_inputs.get(port)
        if isinstance(raw, (list, tuple)):
            raw = next((v for v in raw if str(v or "").strip()), "")
        raw = str(raw or "").strip()
        if not raw:
            raise ValueError(
                f"「{self.step_name}」缺少必需输入「{label}」（端口 {port}）："
                f"请在画布上把上游节点连到该输入点后重试"
            )
        path = raw if os.path.isabs(raw) else os.path.join(task_dir, raw)
        if not os.path.isfile(path):
            raise FileNotFoundError(
                f"「{self.step_name}」输入「{label}」指向的文件不存在：{path}"
            )
        print(f"[SubtitleAlign] Input {port} ({label}) -> {path}")
        return path

    @staticmethod
    def _read_json(path: str) -> Any:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _load_translation_items(self, path: str) -> List[Dict]:
        """读取翻译结果（列表，或含 segments/sentences/items 的 dict）。"""
        data = self._read_json(path)
        if isinstance(data, dict):
            for key in ("segments", "sentences", "items", "results"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
            else:
                data = []
        if not isinstance(data, list):
            raise ValueError(
                f"「{self.step_name}」翻译结果 JSON 结构无法识别（期望数组）：{path}"
            )
        return [item for item in data if isinstance(item, dict)]

    def _load_asr_result(self, path: str) -> Tuple[List[Dict], List[Dict], str]:
        """读取 ASR 结构化 JSON，返回 (句子级时间戳表 segments, 词级时间戳表 words, language)。"""
        data = self._read_json(path)
        language = ""

        if isinstance(data, dict):
            language = str(data.get("language") or "")
            segments = data.get("segments")
            if not isinstance(segments, list):
                for key in ("sentences", "items", "results"):
                    if isinstance(data.get(key), list):
                        segments = data[key]
                        break
            if not isinstance(segments, list):
                segments = []
        elif isinstance(data, list):
            segments = data
        else:
            raise ValueError(
                f"「{self.step_name}」asr格式json 结构无法识别（期望对象或数组）：{path}"
            )

        segments = [seg for seg in segments if isinstance(seg, dict)]
        words: List[Dict] = []
        for seg in segments:
            seg_words = seg.get("words")
            if not isinstance(seg_words, list):
                continue
            for word in seg_words:
                if isinstance(word, dict) and str(word.get("word", "")).strip():
                    words.append(word)

        # 兼容「直接给出全局词表」的输入形态
        if not words and isinstance(data, dict) and isinstance(data.get("words"), list):
            words = [w for w in data["words"] if isinstance(w, dict) and str(w.get("word", "")).strip()]

        print(
            f"[SubtitleAlign] ASR table: {len(segments)} segments, {len(words)} words, "
            f"language={language or '(unknown)'}"
        )
        return segments, words, language

    # ── 句子 ↔ 词区间 ────────────────────────────────────────────────

    def _build_sentences(
        self,
        translations: List[Dict],
        segments: List[Dict],
        word_index: _WordIndex,
    ) -> List[Dict]:
        """把翻译条目与 ASR 词级时间戳表关联起来。"""
        seg_by_id: Dict[int, Dict] = {}
        for seg in segments:
            try:
                seg_by_id[int(seg.get("id"))] = seg
            except (TypeError, ValueError):
                continue

        sentences: List[Dict] = []
        for idx, item in enumerate(translations, start=1):
            try:
                sid: Any = int(item.get("id"))
            except (TypeError, ValueError):
                sid = item.get("id", idx)

            src_text = str(item.get("text") or item.get("src") or item.get("origin") or "").strip()
            translation = str(
                item.get("reflect") or item.get("direct") or item.get("tr") or ""
            ).strip()

            start, end = self._item_window(item)
            if (start is None or end is None) and sid in seg_by_id:
                seg = seg_by_id[sid]
                start, end = self._window_of(seg, default_start=start, default_end=end)

            sentences.append({
                "id": sid,
                "src": src_text,
                "tr": translation,
                "start": start,
                "end": end,
                "words": [],
                "src_index": idx - 1,
            })

        self._attach_word_ranges(sentences, word_index)
        return sentences

    @staticmethod
    def _window_of(seg: Dict, default_start=None, default_end=None) -> Tuple[Optional[float], Optional[float]]:
        start, end = default_start, default_end
        try:
            s = float(seg.get("start"))
            e = float(seg.get("end"))
            if e > s:
                start, end = s, e
        except (TypeError, ValueError):
            pass
        return start, end

    def _item_window(self, item: Dict) -> Tuple[Optional[float], Optional[float]]:
        try:
            start = float(item.get("start"))
            end = float(item.get("end"))
        except (TypeError, ValueError):
            return None, None
        if end <= start:
            return None, None
        return start, end

    def _attach_word_ranges(self, sentences: List[Dict], word_index: _WordIndex) -> None:
        """按「文本精确匹配优先、时间窗兜底」为每句分配词区间（严格单调不重叠）。"""
        words = word_index.words
        total = len(words)
        char_cursor = 0
        word_ptr = 0
        missing: List[Dict] = []

        for position, sent in enumerate(sentences):
            needle = _normalize_for_matching(sent.get("src", ""))
            located = word_index.locate(needle, char_cursor) if needle else None

            if located:
                start_idx, end_idx, next_char = located
                # 允许少量回溯（上游文本可能被清洗过），但不允许跨过已消费的词
                if start_idx < word_ptr:
                    start_idx = word_ptr
                if end_idx < start_idx:
                    end_idx = start_idx
                char_cursor = max(char_cursor, next_char)
                word_ptr = end_idx + 1
                sent["words"] = words[start_idx:end_idx + 1]
                continue

            # 文本匹配失败：用句子时间窗在词表上顺扫
            start, end = sent.get("start"), sent.get("end")
            if start is not None and end is not None:
                j = word_ptr
                while j < total and _word_time(words[j], "end") <= start - 0.05:
                    j += 1
                k = j
                while k < total and _word_time(words[k], "start") < end - 0.05:
                    k += 1
                if k > j:
                    sent["words"] = words[j:k]
                    word_ptr = k
                    char_cursor = word_index.cum_end[k - 1]
                    continue

            missing.append(sent)

        # 仍然没分到词的句子：按剩余文本占比瓜分剩余词表，保证后续句不被饿死
        if missing and word_ptr < total:
            remaining_chars = sum(max(len(s.get("src", "")), 1) for s in missing) or 1
            pool = words[word_ptr:]
            taken = 0
            for sent in missing:
                share = max(len(sent.get("src", "")), 1) / remaining_chars
                take = max(1, int(round(share * len(pool))))
                chunk = pool[taken:taken + take]
                if not chunk:
                    break
                sent["words"] = chunk
                taken += take
            word_ptr += taken

        attached = sum(1 for s in sentences if s.get("words"))
        print(f"[SubtitleAlign] Word ranges attached: {attached}/{len(sentences)} sentences")

    # ── 文案切分 ─────────────────────────────────────────────────────

    def _split_source(self, src_text: str, num_parts: int = 2) -> List[str]:
        """确定性切分源文（标点优先 + 权重均衡），失败时返回单片。"""
        parts = _split_text_locally(src_text, num_parts)
        if len(parts) != num_parts:
            return [src_text]
        return parts

    def _align_translation(
        self,
        llm,
        sid: Any,
        src_text: str,
        translation: str,
        src_parts: List[str],
        max_length: float,
        src_lang: str,
        tgt_lang: str,
    ) -> Tuple[List[str], bool]:
        """让 LLM 把译文切成与源文分片对齐的若干份；失败时本地兜底。

        返回 ``(译文分片, 是否由 LLM 产出)``。模型明确「拒绝切分」时**不再重试**：
        同样的问法只会得到同样的回复，重试纯属浪费配额（也正是请求量失控的推手）。
        """
        num_parts = len(src_parts)
        last_issues: List[str] = []
        last_result: Any = None

        for attempt in range(2):
            if attempt == 0:
                prompt = _build_align_prompt(
                    src_text, translation, src_parts, max_length, src_lang, tgt_lang
                )
            else:
                prompt = _build_retry_prompt(
                    src_text, translation, src_parts, max_length,
                    last_issues, last_result, src_lang, tgt_lang,
                )

            result = self._chat(llm, prompt)
            last_result = result

            if not isinstance(result, dict):
                last_issues = ["LLM returned invalid response (not a dict)"]
                print(f"[SubtitleAlign] id={sid} attempt {attempt + 1}: {last_issues[0]}")
                continue

            raw_parts = result.get("target_parts")
            if not isinstance(raw_parts, list):
                raw_parts = []
            if _looks_like_refusal(raw_parts, translation):
                print(f"[SubtitleAlign] id={sid}: LLM 未切分（含空片或原样返回），跳过重试")
                break

            target_parts = [str(p).strip() for p in raw_parts]
            issues = _validate_target_parts(target_parts, num_parts, translation, max_length)
            if not issues:
                return target_parts, True

            last_issues = issues
            print(f"[SubtitleAlign] id={sid} attempt {attempt + 1} failed: {'; '.join(issues)}")

        local_parts = _split_text_locally(translation, num_parts)
        if len(local_parts) == num_parts:
            print(f"[SubtitleAlign] id={sid}: LLM alignment unavailable, used local punctuation split")
            return local_parts, False
        print(f"[SubtitleAlign] id={sid}: LLM alignment unavailable, kept translation unsplit")
        return [translation], False

    # ── 时间戳 ───────────────────────────────────────────────────────

    def _part_timestamps(
        self,
        src_text: str,
        src_parts: List[str],
        words: List[Dict],
        sent_start: Optional[float],
        sent_end: Optional[float],
    ) -> List[Optional[Tuple[float, float]]]:
        """用词级时间戳表给出每个源文分片的时间区间。

        在句子内部的词子表上做归一化子串定位（与全局定位同一套逻辑），
        因此分片边界即使落在词中间也能映射到对应的词。
        """
        stamps: List[Optional[Tuple[float, float]]] = [None] * len(src_parts)
        if not src_parts:
            return stamps

        if words:
            local = _WordIndex(words)
            cursor = 0
            for idx, part in enumerate(src_parts):
                needle = _normalize_for_matching(part)
                located = local.locate(needle, cursor) if needle else None
                if located:
                    start_idx, end_idx, cursor = located
                    bounds = _range_bounds(local.words, start_idx, end_idx)
                    if bounds:
                        stamps[idx] = bounds

        # 未定位到的分片：在相邻已定位分片/句子窗口之间按权重插值
        window_start = sent_start
        window_end = sent_end
        if window_start is None and stamps:
            window_start = next((s[0] for s in stamps if s), None)
        if window_end is None and stamps:
            window_end = next((s[1] for s in reversed(stamps) if s), None)
        if window_start is None or window_end is None or window_end <= window_start:
            return stamps

        # 逐段补齐：以已定位分片为锚点，未定位区间按权重均分
        anchor_positions = [i for i, s in enumerate(stamps) if s]
        if not anchor_positions:
            return self._distribute_by_weight(src_parts, window_start, window_end)

        result = self._distribute_by_weight(src_parts, window_start, window_end)
        for i in anchor_positions:
            result[i] = stamps[i]

        # 修正锚点之间的单调性
        prev_end = window_start
        for i in range(len(result)):
            start, end = result[i]
            start = max(start, prev_end)
            end = max(end, start + MIN_PART_DURATION)
            if end > window_end:
                end = max(start + MIN_PART_DURATION, window_end)
            result[i] = (round(start, 4), round(end, 4))
            prev_end = result[i][1]
        return result

    @staticmethod
    def _distribute_by_weight(
        parts: List[str], window_start: float, window_end: float
    ) -> List[Tuple[float, float]]:
        """按语言权重把时间窗分配给各分片（无词级数据的兜底）。"""
        span = max(float(window_end) - float(window_start), MIN_PART_DURATION * len(parts))
        weights = [max(calc_len(p), 1e-6) for p in parts]
        total = sum(weights) or 1.0
        out: List[Tuple[float, float]] = []
        current = float(window_start)
        for idx, weight in enumerate(weights):
            share = span * weight / total
            start = current
            end = float(window_end) if idx == len(weights) - 1 else current + share
            end = max(end, start + MIN_PART_DURATION)
            out.append((round(start, 4), round(end, 4)))
            current = end
        return out

    # ── 批量 / 逐句模式解析 ──────────────────────────────────────────

    def _resolve_batch_align(self) -> bool:
        """是否启用组装模式（多句合并请求）。默认开启，可在节点设置中关闭。"""
        raw = (getattr(self, "_node_config", {}) or {}).get("batch_align")
        if raw is None or raw == "":
            return True
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in ("1", "true", "yes", "on")

    def _resolve_max_request_chars(self) -> int:
        """单次批量请求的字符预算：节点设置 > 全局 ``llm.max_request_chars`` > 默认值。"""
        raw = (getattr(self, "_node_config", {}) or {}).get("max_request_chars")
        for candidate in (raw, config.get("llm.max_request_chars")):
            try:
                value = int(float(candidate))
            except (TypeError, ValueError):
                continue
            if value > 0:
                return value
        return DEFAULT_MAX_REQUEST_CHARS

    def _resolve_request_interval(self) -> float:
        """两次 LLM 请求的最小间隔：节点设置 > 全局 ``llm.min_request_interval`` > 默认值。"""
        raw = (getattr(self, "_node_config", {}) or {}).get("request_interval")
        for candidate in (raw, config.get("llm.min_request_interval")):
            try:
                value = float(candidate)
            except (TypeError, ValueError):
                continue
            if value >= 0:
                return value
        return DEFAULT_REQUEST_INTERVAL

    def _chat(self, llm, prompt: Dict) -> Any:
        """本节点唯一的 LLM 出口：统一经节流闸，避免瞬时打爆上游限速。

        组装模式会并发发多批请求、逐句兜底又叠加在其上，若不收敛速率，峰值 QPS
        只由并发数决定（默认 10），很容易触发上游 429。
        """
        self._request_count = getattr(self, "_request_count", 0) + 1
        gate = getattr(self, "_gate", None)
        if gate is None:
            gate = _gate_for(
                int(config.get("llm.max_concurrent") or 10),
                self._resolve_request_interval(),
            )
            self._gate = gate
        with gate:
            return llm.chat(
                self.step_id,
                prompt.get("user_prompt") or "",
                system_prompt=prompt.get("system_prompt") or "",
                response_json=True,
            )

    @staticmethod
    def _entry_over_limit(entry: Dict, max_length: float) -> bool:
        """条目是否仍需切分：超出长度限制，或残留占位符。"""
        text = str(entry.get("tr", "") or "")
        return len(text) > max_length or _has_placeholder(text)

    # ── 逐句模式（旧行为）────────────────────────────────────────────

    def _process_sentences_concurrent(
        self,
        llm,
        to_process: List[Dict],
        max_length: float,
        src_lang: str,
        tgt_lang: str,
        max_workers: int,
        callback: Optional[Callable],
    ) -> Dict[int, List[Dict]]:
        """每句一次独立请求（含其自身的多轮切分），按 ``llm.max_concurrent`` 并发。"""
        processed_map: Dict[int, List[Dict]] = {}
        total = len(to_process)

        def _worker(sentence: Dict) -> Tuple[int, List[Dict]]:
            parts = self._process_sentence(llm, sentence, max_length, src_lang, tgt_lang)
            return sentence.get("src_index", -1), parts

        with ThreadPoolExecutor(max_workers=max(1, min(int(max_workers), total))) as executor:
            futures = {executor.submit(_worker, s): s for s in to_process}
            done_count = 0
            for future in as_completed(futures):
                sentence = futures[future]
                try:
                    idx, parts = future.result()
                    processed_map[idx] = parts
                except Exception as exc:
                    raise RuntimeError(
                        f"「{self.step_name}」断句对齐失败（id={sentence.get('id', '')}）：{exc}"
                    ) from exc
                done_count += 1
                if callback:
                    pct = int(15 + 60 * done_count / total)
                    callback(min(pct, 75), f"已处理 {done_count}/{total} 句")
        return processed_map

    # ── 组装模式（批量请求）──────────────────────────────────────────

    @staticmethod
    def _task_payload(index: int, task: Dict, word_limit: float) -> Dict:
        """批次内单个切分任务的请求载荷（``index`` 为批次内序号）。"""
        return {
            "index": index,
            "num_parts": len(task.get("src_parts") or []),
            "word_limit": f"{word_limit:.0f}",
            "source_parts": list(task.get("src_parts") or []),
            "source_text": str(task.get("src_text") or ""),
            "translation": str(task.get("translation") or ""),
        }

    def _run_align_batch(
        self,
        llm,
        batch: List[Dict],
        max_length: float,
        src_lang: str,
        tgt_lang: str,
    ) -> Tuple[Dict[str, List[str]], List[Dict], List[Dict], bool]:
        """执行单个批次：1 次请求处理整批切分任务。

        返回 ``(命中, 需本地切分, 不合格, 整批不可用)``：

        - 命中：LLM 给出且通过校验的译文分片
        - 需本地切分：模型「拒绝切分」的任务 → 本地标点切分，**不再发请求**
        - 不合格：数量/占位符/相似度等问题 → 同样本地切分（单任务重试通常是白费）
        - 整批不可用：请求异常或整批返回无法解析 → 交调用方「有预算地」逐句重试
        """
        payloads = [self._task_payload(i, task, max_length) for i, task in enumerate(batch)]
        prompt = _build_align_batch_prompt(payloads, src_lang, tgt_lang)
        try:
            raw = self._chat(llm, prompt)
        except Exception as exc:  # 批量异常不致命：交回调用方决定
            print(f"[SubtitleAlign] 批量请求异常：{exc}")
            return {}, [], [], True

        parsed = _coerce_align_results(raw)
        if parsed is None:
            print("[SubtitleAlign] 批量返回无法解析为 results 列表")
            return {}, [], [], True

        accepted: Dict[str, List[str]] = {}
        refused: List[Dict] = []
        invalid: List[Dict] = []
        for position, task in enumerate(batch):
            raw_parts = parsed.get(str(position))
            if raw_parts is None:
                invalid.append(task)
                continue
            if _looks_like_refusal(raw_parts, task.get("translation") or ""):
                print(
                    f"[SubtitleAlign] 批量结果 id={task.get('sid', '')} 模型未切分"
                    f"（{len(raw_parts)} 片且有空片），改用本地切分"
                )
                refused.append(task)
                continue
            issues = _validate_target_parts(
                list(raw_parts),
                len(task.get("src_parts") or []),
                task.get("translation") or "",
                max_length,
            )
            if issues:
                print(
                    f"[SubtitleAlign] 批量结果 id={task.get('sid', '')} 未通过校验，"
                    f"改用本地切分：{'；'.join(issues)}"
                )
                invalid.append(task)
                continue
            accepted[task["key"]] = list(raw_parts)
        return accepted, refused, invalid, False

    @staticmethod
    def _local_split_task(task: Dict) -> Optional[List[str]]:
        """本地确定性切分单个任务；切不动时返回 None（调用方保持原片）。"""
        num_parts = len(task.get("src_parts") or [])
        parts = _split_text_locally(str(task.get("translation") or ""), num_parts)
        return parts if len(parts) == num_parts else None

    def _align_tasks_in_batches(
        self,
        llm,
        tasks: List[Dict],
        max_request_chars: int,
        max_length: float,
        src_lang: str,
        tgt_lang: str,
        log: Optional[Callable] = None,
        use_llm: bool = True,
        single_budget: int = DEFAULT_SINGLE_FALLBACK_BUDGET,
    ) -> Tuple[Dict[str, List[str]], int]:
        """批量对齐一轮内的全部切分任务，返回 ``(译文分片表, LLM 命中数)``。

        降级策略的核心是**不放大请求量**：

        - 模型拒绝切分 / 单片内容不合格 → 本地确定性切分（0 次请求）
        - 仅「整批不可用」才逐句重试，且每轮受 ``single_budget`` 次数限制
        - ``use_llm=False``（上一轮已判定模型不可用）→ 全部本地切分，一次请求都不发
        """
        results: Dict[str, List[str]] = {}
        hits = 0
        if not tasks:
            return results, hits

        if not use_llm:
            if log:
                log(f"本轮 {len(tasks)} 个切分任务改用本地切分（不再请求 LLM）")
            for task in tasks:
                parts = self._local_split_task(task)
                if parts is not None:
                    results[task["key"]] = parts
            return results, hits

        batches = _pack_align_batches(tasks, max_request_chars)
        if log:
            log(f"本轮 {len(tasks)} 个切分任务合并为 {len(batches)} 次批量请求")

        max_workers = int(config.get("llm.max_concurrent") or 10)
        local_tasks: List[Dict] = []
        wholesale: List[Dict] = []
        with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(batches)))) as executor:
            futures = {
                executor.submit(self._run_align_batch, llm, batch, max_length, src_lang, tgt_lang): batch
                for batch in batches
            }
            for future in as_completed(futures):
                try:
                    accepted, refused, invalid, is_wholesale = future.result()
                except Exception as exc:  # 单批异常只影响该批
                    print(f"[SubtitleAlign] 批量执行异常：{exc}")
                    wholesale.extend(futures[future])
                    continue
                results.update(accepted)
                hits += len(accepted)
                local_tasks.extend(refused)
                local_tasks.extend(invalid)
                if is_wholesale:
                    wholesale.extend(futures[future])

        for task in local_tasks:
            parts = self._local_split_task(task)
            if parts is not None:
                results[task["key"]] = parts

        # 整批不可用：整批 1 次请求都没用上才值得按句重试，且受预算约束
        if wholesale:
            if single_budget < len(wholesale):
                print(
                    f"[SubtitleAlign] {len(wholesale)} 个任务来自不可用批次，"
                    f"按预算只逐句重试 {max(0, single_budget)} 个（其余本地切分）"
                )
            if log:
                log(f"{len(wholesale)} 个任务来自不可用批次，按预算逐句重试")
            for task in wholesale:
                expected = len(task.get("src_parts") or [])
                if single_budget <= 0:
                    parts = self._local_split_task(task)
                    if parts is not None:
                        results[task["key"]] = parts
                    continue
                single_budget -= 1
                parts, used_llm = self._align_translation(
                    llm, task.get("sid", ""), task.get("src_text", ""), task.get("translation", ""),
                    list(task.get("src_parts") or []), max_length, src_lang, tgt_lang,
                )
                if used_llm and len(parts) == expected:
                    hits += 1
                if len(parts) == expected:
                    results[task["key"]] = list(parts)
        return results, hits

    def _process_sentences_batched(
        self,
        llm,
        to_process: List[Dict],
        max_length: float,
        src_lang: str,
        tgt_lang: str,
        max_request_chars: int,
        callback: Optional[Callable],
    ) -> Dict[int, List[Dict]]:
        """组装模式：跨句按轮次收集切分任务 → 批次请求 → 回填（失败降级逐句）。

        与逐句模式的差异只在「请求怎么发」：切分决策、时间戳映射、兜底策略复用同一套
        函数，因此两种模式产出的结构完全一致。
        """
        entries_map: Dict[int, List[Dict]] = {}
        windows: Dict[int, Tuple[Optional[float], Optional[float]]] = {}
        for sentence in to_process:
            key = sentence.get("src_index", -1)
            entries_map[key] = [{
                "id": sentence.get("id", ""),
                "src": str(sentence.get("src", "") or ""),
                "tr": str(sentence.get("tr", "") or ""),
                "words": list(sentence.get("words") or []),
                "start": sentence.get("start"),
                "end": sentence.get("end"),
            }]
            windows[key] = (sentence.get("start"), sentence.get("end"))

        total = max(1, len(entries_map))

        def report(message: str, done: Optional[int] = None) -> None:
            if not callback:
                return
            finished = done if done is not None else sum(
                1 for entries in entries_map.values()
                if not any(self._entry_over_limit(entry, max_length) for entry in entries)
            )
            callback(min(75, 15 + int(60 * finished / total)), message)

        use_llm = True  # 熔断开关：某轮 LLM 零命中后就地关闭，后续轮次全走本地切分
        for round_num in range(MAX_ROUNDS):
            tasks: List[Dict] = []
            for key, entries in entries_map.items():
                for entry_index, entry in enumerate(entries):
                    if not self._entry_over_limit(entry, max_length):
                        continue
                    src_parts = self._split_source(str(entry.get("src", "") or ""), 2)
                    if len(src_parts) != 2:
                        print(
                            f"[SubtitleAlign] id={entry.get('id', '')}: "
                            f"cannot split source further, keeping part as-is"
                        )
                        continue
                    tasks.append({
                        "key": f"{key}:{entry_index}",
                        "sent_key": key,
                        "entry_index": entry_index,
                        "sid": entry.get("id", ""),
                        "src_text": str(entry.get("src", "") or ""),
                        "translation": str(entry.get("tr", "") or ""),
                        "src_parts": src_parts,
                    })
            if not tasks:
                break

            report(f"第 {round_num + 1} 轮：{len(tasks)} 个切分任务准备批量请求")
            aligned, hits = self._align_tasks_in_batches(
                llm, tasks, max_request_chars, max_length, src_lang, tgt_lang,
                log=report, use_llm=use_llm,
            )
            if use_llm and hits == 0:
                # 熔断：这一轮一次有效分片都没切出来，再问下一轮大概率也是白花配额
                print(
                    f"[SubtitleAlign] 第 {round_num + 1} 轮 LLM 零命中，"
                    f"后续轮次改用本地切分（不再请求 LLM）"
                )
                use_llm = False

            by_sentence: Dict[int, List[Dict]] = {}
            for task in tasks:
                by_sentence.setdefault(task["sent_key"], []).append(task)

            for sent_key, sent_tasks in by_sentence.items():
                entries = entries_map[sent_key]
                # 逆序回填：同句内多个分片被替换时，小下标不受大下标替换影响
                for task in sorted(sent_tasks, key=lambda item: item["entry_index"], reverse=True):
                    parts = aligned.get(task["key"]) or []
                    entry_index = task["entry_index"]
                    if len(parts) != 2 or entry_index >= len(entries):
                        continue
                    entry = entries[entry_index]
                    timestamps = self._part_timestamps(
                        task["src_text"], task["src_parts"], list(entry.get("words") or []),
                        entry.get("start"), entry.get("end"),
                    )
                    split_entries: List[Dict] = []
                    for i, (src_part, tr_part) in enumerate(zip(task["src_parts"], parts)):
                        ts = timestamps[i] if i < len(timestamps) else None
                        split_entries.append({
                            "id": entry.get("id", ""),
                            "src": src_part,
                            "tr": tr_part,
                            "words": [],
                            "start": ts[0] if ts else entry.get("start"),
                            "end": ts[1] if ts else entry.get("end"),
                        })
                    # 分片时间戳建不出来时，别再往下切（否则时间轴会退化）
                    if any(e["start"] is None or e["end"] is None for e in split_entries):
                        print(
                            f"[SubtitleAlign] id={entry.get('id', '')}: "
                            f"no word timestamps for split parts, keeping part as-is"
                        )
                        continue
                    entries[entry_index:entry_index + 1] = split_entries

            report(f"第 {round_num + 1} 轮完成")

        processed_map: Dict[int, List[Dict]] = {}
        for key, entries in entries_map.items():
            window = windows.get(key) or (None, None)
            self._fill_missing_timestamps(entries, window[0], window[1])
            processed_map[key] = [self._finalize_entry(entry) for entry in entries]
        return processed_map

    # ── 单句处理 ─────────────────────────────────────────────────────

    def _process_sentence(
        self,
        llm,
        sentence: Dict,
        max_length: float,
        src_lang: str = "source",
        tgt_lang: str = "target",
    ) -> List[Dict]:
        """把一句话迭代切分到长度限制内（最多 ``MAX_ROUNDS`` 轮，每轮二切）。"""
        sid = sentence.get("id", "")
        src_text = str(sentence.get("src", "") or "")
        translation = str(sentence.get("tr", "") or "")
        words = list(sentence.get("words") or [])
        sent_start = sentence.get("start")
        sent_end = sentence.get("end")

        entries = [{
            "id": sid,
            "src": src_text,
            "tr": translation,
            "words": words,
            "start": sent_start,
            "end": sent_end,
        }]

        if not translation or len(translation) <= max_length:
            return [self._finalize_entry(entries[0])]

        for round_num in range(MAX_ROUNDS):
            over_limit = [
                idx for idx, entry in enumerate(entries)
                if len(entry.get("tr", "")) > max_length
                or _has_placeholder(entry.get("tr", ""))
            ]
            if not over_limit:
                break

            print(
                f"[SubtitleAlign] id={sid} round {round_num + 1}: "
                f"{len(over_limit)} part(s) still over limit"
            )

            new_entries = list(entries)
            for entry_idx in reversed(over_limit):
                entry = new_entries[entry_idx]
                src_part_text = str(entry.get("src", "") or "")
                tr_part_text = str(entry.get("tr", "") or "")

                src_parts = self._split_source(src_part_text, 2)
                if len(src_parts) != 2:
                    print(f"[SubtitleAlign] id={sid}: cannot split source further, keeping part as-is")
                    continue

                tr_parts, _ = self._align_translation(
                    llm, sid, src_part_text, tr_part_text, src_parts,
                    max_length, src_lang, tgt_lang,
                )
                if len(tr_parts) != 2:
                    continue

                timestamps = self._part_timestamps(
                    src_part_text, src_parts, list(entry.get("words") or []),
                    entry.get("start"), entry.get("end"),
                )

                split_entries: List[Dict] = []
                for i, (sp, tp) in enumerate(zip(src_parts, tr_parts)):
                    ts = timestamps[i] if i < len(timestamps) else None
                    split_entries.append({
                        "id": sid,
                        "src": sp,
                        "tr": tp,
                        "words": [],
                        "start": ts[0] if ts else entry.get("start"),
                        "end": ts[1] if ts else entry.get("end"),
                    })

                # 分片时间戳建不出来时，别再往下切（否则时间轴会退化）
                if any(e["start"] is None or e["end"] is None for e in split_entries):
                    print(f"[SubtitleAlign] id={sid}: no word timestamps for split parts, keeping part as-is")
                    continue

                new_entries[entry_idx:entry_idx + 1] = split_entries

            entries = new_entries

        # 未纳入 words 的兜底时间轴
        self._fill_missing_timestamps(entries, sent_start, sent_end)
        return [self._finalize_entry(entry) for entry in entries]

    def _fill_missing_timestamps(
        self,
        entries: List[Dict],
        sent_start: Optional[float],
        sent_end: Optional[float],
    ) -> None:
        """给缺时间戳的条目按位置补齐，并保证同句内单调不重叠。"""
        if not entries:
            return
        if sent_start is None or sent_end is None or sent_end <= sent_start:
            # 无句子窗口：以已有时间戳/0 为起点按权重顺延
            cursor = 0.0
            for entry in entries:
                if entry.get("start") is None or entry.get("end") is None:
                    duration = max(MIN_PART_DURATION, len(entry.get("tr", "")) * 0.12)
                    entry["start"] = round(cursor, 4)
                    entry["end"] = round(cursor + duration, 4)
                else:
                    entry["start"] = round(float(entry["start"]), 4)
                    entry["end"] = round(float(entry["end"]), 4)
                cursor = entry["end"]
            return

        missing = [i for i, e in enumerate(entries) if e.get("start") is None or e.get("end") is None]
        if missing:
            distributed = self._distribute_by_weight(
                [str(e.get("tr", "")) for e in entries], float(sent_start), float(sent_end)
            )
            for i in missing:
                entries[i]["start"], entries[i]["end"] = distributed[i]

        prev_end = float(sent_start)
        for entry in entries:
            start = max(float(entry["start"]), prev_end)
            end = max(float(entry["end"]), start + MIN_PART_DURATION)
            entry["start"] = round(start, 4)
            entry["end"] = round(end, 4)
            prev_end = entry["end"]

    def _finalize_entry(self, entry: Dict) -> Dict:
        return {
            "id": entry.get("id", ""),
            "src": entry.get("src", ""),
            "tr": entry.get("tr", ""),
            "start": round(float(entry.get("start") or 0.0), 4),
            "end": round(float(entry.get("end") or 0.0), 4),
        }

    @staticmethod
    def _fill_intra_sentence_gaps(entries: List[Dict], group_keys: List[Any]) -> None:
        """同句内相邻分片间隔小于 ``GAP_FILL_LIMIT`` 时把前一片延伸到后一片起点。"""
        for i in range(len(entries) - 1):
            if group_keys[i] != group_keys[i + 1]:
                continue
            gap = float(entries[i + 1]["start"]) - float(entries[i]["end"])
            if 0 < gap < GAP_FILL_LIMIT:
                entries[i]["end"] = entries[i + 1]["start"]

    # ── Artifact checks ──────────────────────────────────────────────

    def check_artifact(self, task_dir: str) -> bool:
        node_suffix = f"_{self._node_id}" if self._node_id else ""
        return os.path.exists(os.path.join(task_dir, "cache", f"subtitle_aligned{node_suffix}.json"))

    def validate_inputs(self, task_dir: str) -> bool:
        try:
            self._require_input_path(task_dir, INPUT_PORT_SUBTITLE)
            self._require_input_path(task_dir, INPUT_PORT_ASR)
        except (ValueError, FileNotFoundError) as exc:
            print(f"[SubtitleAlign] validate_inputs failed: {exc}")
            return False
        return True

    # ── 主流程 ───────────────────────────────────────────────────────

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        if callback:
            callback(3, "读取输入（翻译结果 + ASR 时间戳表）...")
        node_suffix = f"_{self._node_id}" if self._node_id else ""

        subtitle_path = self._require_input_path(task_dir, INPUT_PORT_SUBTITLE)
        asr_path = self._require_input_path(task_dir, INPUT_PORT_ASR)

        translations = self._load_translation_items(subtitle_path)
        if not translations:
            raise ValueError(f"「{self.step_name}」翻译结果为空：{subtitle_path}")

        segments, words, asr_language = self._load_asr_result(asr_path)
        if not segments and not words:
            raise ValueError(
                f"「{self.step_name}」asr格式json 中既没有 segments 也没有 words：{asr_path}"
            )

        word_index = _WordIndex(words)
        if not words:
            print("[SubtitleAlign] Warning: ASR input has no word-level timestamps; "
                  "falling back to sentence windows / weighted distribution")

        sentences = self._build_sentences(translations, segments, word_index)

        if callback:
            callback(12, f"已关联 {len(sentences)} 句（词级词表 {len(words)} 个词）")

        # 长度限制：节点配置按「中文字符单位」，其他语言按语言权重放大
        src_lang, tgt_lang = self._resolve_languages_from_input(task_dir)
        if asr_language and asr_language not in ("auto", ""):
            src_lang = src_lang if src_lang != "auto" else asr_language
        base_max_length = float(self._get_param("max_subtitle_length", 30))
        tgt_lang_weight = get_language_weight(tgt_lang)
        max_length = base_max_length * tgt_lang_weight

        print(
            f"[SubtitleAlign] languages: {src_lang} -> {tgt_lang}, "
            f"max_length={max_length:.0f} (base={base_max_length:.0f} * weight={tgt_lang_weight})"
        )

        to_process = [s for s in sentences if len(s.get("tr", "")) > max_length]
        batch_align = self._resolve_batch_align()
        max_request_chars = self._resolve_max_request_chars()
        if callback:
            mode = "批量" if batch_align else "逐句"
            callback(
                15,
                f"{len(to_process)}/{len(sentences)} 句超过 {max_length:.0f} 字符，"
                f"开始断句对齐（{mode}模式）...",
            )

        llm = get_llm_client()
        max_workers = int(config.get("llm.max_concurrent") or 10)
        self._request_count = 0
        self._request_interval = self._resolve_request_interval()
        # 节流闸：批量并发 + 逐句兜底叠加时，瞬时 QPS 会直接打爆上游限速
        self._gate = _gate_for(max_workers, self._request_interval)
        processed_map: Dict[int, List[Dict]] = {}

        if to_process:
            if batch_align:
                # 组装模式：跨句收集切分任务 → 按字符预算打包请求（失败自动降级逐句）
                processed_map = self._process_sentences_batched(
                    llm, to_process, max_length, src_lang, tgt_lang,
                    max_request_chars, callback,
                )
            else:
                # 逐句模式：每句独立请求（保留旧行为，便于对比与排障）
                processed_map = self._process_sentences_concurrent(
                    llm, to_process, max_length, src_lang, tgt_lang, max_workers, callback,
                )

        if callback:
            callback(80, "汇总对齐结果...")

        full_result: List[Dict] = []
        group_keys: List[Any] = []
        for idx, sentence in enumerate(sentences):
            if idx in processed_map:
                for entry in processed_map[idx]:
                    full_result.append(dict(entry))
                    group_keys.append(sentence.get("id", idx))
            else:
                full_result.append({
                    "id": sentence.get("id", ""),
                    "src": sentence.get("src", ""),
                    "tr": sentence.get("tr", ""),
                    "start": round(float(sentence.get("start") or 0.0), 4),
                    "end": round(float(sentence.get("end") or 0.0), 4),
                })
                group_keys.append(sentence.get("id", idx))

        # 兜底：极端情况下（无词级数据且无句子窗口）补齐零时长条目
        last_end = 0.0
        for entry in full_result:
            if entry["end"] <= entry["start"]:
                duration = max(MIN_PART_DURATION, len(entry.get("tr", "")) * 0.12)
                entry["start"] = round(max(entry["start"], last_end), 4)
                entry["end"] = round(entry["start"] + duration, 4)
            last_end = max(last_end, entry["end"])

        self._fill_intra_sentence_gaps(full_result, group_keys)

        still_over = [e for e in full_result if len(e.get("tr", "")) > max_length]
        if still_over:
            ids = [str(e.get("id", "")) for e in still_over[:10]]
            print(
                f"[SubtitleAlign] Warning: {len(still_over)} entries still over limit after "
                f"{MAX_ROUNDS} rounds, packaged as-is: {', '.join(ids)}"
            )

        print(
            f"[SubtitleAlign] LLM 请求共 {self._request_count} 次"
            f"（模式：{'批量' if batch_align else '逐句'}，最小间隔 {self._request_interval}s）"
        )

        if callback:
            callback(95, "保存结果...")

        self._save_output(task_dir, full_result)

        if callback:
            callback(
                100,
                f"对齐完成：{len(full_result)} 条字幕（来自 {len(sentences)} 句）",
            )

        return {
            "artifacts": [f"cache/subtitle_aligned{node_suffix}.json"],
            "outputs": {
                "subtitle": f"cache/subtitle_aligned{node_suffix}.json",
            },
        }

    def _save_output(self, task_dir: str, data: List[Dict]):
        """Save aligned subtitle data to cache."""
        node_suffix = f"_{self._node_id}" if self._node_id else ""
        output_path = os.path.join(task_dir, "cache", f"subtitle_aligned{node_suffix}.json")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[SubtitleAlign] Saved {len(data)} aligned entries -> {output_path}")
