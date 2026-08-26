"""标点恢复处理器（Punctuation Restoration）。

ASR 后处理流水线的最后阶段，为无标点能力引擎的输出做智能兜底：
先做语言门控（仅 zh/en）与标点密度检测，缺标点时才调用 FunASR CT-Punc
模型逐 segment 恢复标点。只回写 segment 文本，不改动 words/时间戳/说话人。
"""

import os
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 语言归一化：各引擎的语言表示不统一（"zh"/"Chinese"/"China"/"zh-CN"、
# "en"/"English"/"EN" 等），统一归一为 ISO 码后再做门控。
# ---------------------------------------------------------------------------

_LANG_ALIASES: Dict[str, str] = {
    # 中文系
    "zh": "zh",
    "chinese": "zh",
    "china": "zh",
    "mandarin": "zh",
    "zh-cn": "zh",
    "zh_cn": "zh",
    "zh-hans": "zh",
    "zh-hant": "zh",
    "cn": "zh",
    # 英文系
    "en": "en",
    "english": "en",
    "eng": "en",
    "en-us": "en",
    "en_us": "en",
    "en-gb": "en",
    "en-au": "en",
}


def normalize_lang_code(language: Optional[str]) -> str:
    """把任意来源的语言表示归一为小写 ISO 码；auto/空返回 ""。"""
    if not language:
        return ""
    lang = str(language).strip().lower()
    if not lang or lang in ("auto", "detect", "from_input"):
        return ""
    if lang in _LANG_ALIASES:
        return _LANG_ALIASES[lang]
    # BCP47 变体前缀匹配：zh-TW -> zh、en-CA -> en
    prefix = lang.replace("_", "-").split("-")[0]
    if prefix in ("zh", "en"):
        return prefix
    return lang


# ---------------------------------------------------------------------------
# 标点密度检测：判断 ASR 文本是否缺少标点（智能兜底的入口条件）
# ---------------------------------------------------------------------------

_PUNCT_CHARS = set("。！？，、；：,.!?;:")


def _needs_punctuation(segments: List[dict], threshold: float = 0.005) -> bool:
    """标点字符占比低于 threshold（默认 0.5%）判定为缺标点，需要恢复。"""
    total_chars = 0
    punct_chars = 0
    for seg in segments:
        text = seg.get("text") or ""
        total_chars += len(text)
        punct_chars += sum(1 for ch in text if ch in _PUNCT_CHARS)
    if total_chars == 0:
        return False
    return punct_chars / total_chars < threshold


# ---------------------------------------------------------------------------
# CT-Punc 处理器
# ---------------------------------------------------------------------------

PUNC_MODEL_ID = "ct-punc"
PUNC_LOCAL_SUBPATH = "punc_ct-transformer_cn-en-common-vocab471067-large"

# 模块级模型缓存：ct-punc 约 1GB，跨任务复用避免重复加载
_MODEL_CACHE: Dict[str, Any] = {}


def _resolve_local_punc_model() -> Optional[str]:
    """解析本地缓存的 CT-Punc 模型路径（与 funasr_nano 的约定一致）。"""
    cache_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "_model_cache",
    )
    local = os.path.join(cache_dir, "models", "iic", PUNC_LOCAL_SUBPATH)
    if os.path.isdir(local) and os.listdir(local):
        return os.path.abspath(local)
    return None


class PunctuationProcessor:
    """标点恢复处理器基类。"""

    def restore(self, segments: List[dict], language: str = "") -> List[dict]:
        """对 segments 恢复标点（原地修改 text 字段）并返回 segments。"""
        raise NotImplementedError


class CtPuncPunctuationProcessor(PunctuationProcessor):
    """FunASR CT-Punc 标点恢复处理器（中英，纯文本模型、无需音频）。"""

    def __init__(self, **options):
        self.options = options or {}

    def restore(self, segments: List[dict], language: str = "") -> List[dict]:
        lang = normalize_lang_code(language)
        if lang not in ("zh", "en"):
            print(f"[Punctuation] Language '{language or 'unknown'}' not supported by ct-punc, skipping", flush=True)
            return segments

        if not _needs_punctuation(segments):
            print("[Punctuation] Text already has sufficient punctuation, skipping", flush=True)
            return segments

        model = self._get_model()
        print(f"[Punctuation] Restoring punctuation for {len(segments)} segment(s)", flush=True)
        for idx, seg in enumerate(segments):
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            # CT-Punc 对超长文本会卡死/OOM（模型上限约 512 token），
            # 按句号/问号/感叹号切分为不超过 MAX_CHARS 的片段分别处理
            MAX_CHARS = 200
            try:
                restored_parts: List[str] = []
                chunks = self._split_text(text, MAX_CHARS)
                for chunk in chunks:
                    if not chunk.strip():
                        continue
                    print(f"[Punctuation]   seg[{idx}] chunk({len(chunk)} chars): {chunk[:40]}...", flush=True)
                    res = model.generate(input=chunk, )
                    print(f"[Punctuation]   seg[{idx}] chunk done", flush=True)
                    restored = self._extract_text(res)
                    restored_parts.append(restored or chunk)
                restored_text = "".join(restored_parts) if lang == "zh" else " ".join(restored_parts)
                if restored_text:
                    seg["text"] = restored_text
            except Exception as e:
                print(f"[Punctuation] Segment {idx} restore failed ({len(text)} chars), keeping original: {e}", flush=True)
                continue
        return segments

    @staticmethod
    def _split_text(text: str, max_chars: int) -> List[str]:
        """把长文本切分为不超过 max_chars 的片段，优先在标点/空格处断开。"""
        if len(text) <= max_chars:
            return [text]
        chunks: List[str] = []
        remaining = text
        while len(remaining) > max_chars:
            # 在 max_chars 范围内找最后一个空格（英文）或标点（中英）
            cut = remaining[:max_chars]
            # 从后往前找断点：优先标点，其次空格
            split_pos = -1
            for i in range(len(cut) - 1, 0, -1):
                if cut[i] in "，。！？、；：,.!?;:":
                    split_pos = i + 1
                    break
                if split_pos < 0 and cut[i] == " ":
                    split_pos = i + 1
            if split_pos <= 0:
                split_pos = max_chars  # 找不到断点，硬切
            chunks.append(remaining[:split_pos])
            remaining = remaining[split_pos:]
        if remaining:
            chunks.append(remaining)
        return chunks

    def _get_model(self):
        model_name = self.options.get("model") or _resolve_local_punc_model() or PUNC_MODEL_ID
        if model_name in _MODEL_CACHE:
            return _MODEL_CACHE[model_name]
        try:
            from funasr import AutoModel
        except ImportError:
            raise ImportError("funasr package required for 'ct_punc' punctuation engine")
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[Punctuation] Loading CT-Punc model: {model_name} (device={device})", flush=True)
        print(f"[Punctuation]   calling AutoModel(model={model_name})...", flush=True)
        model = AutoModel(model=model_name, device=device, disable_update=True)
        print(f"[Punctuation]   AutoModel loaded OK", flush=True)
        _MODEL_CACHE[model_name] = model
        return model

    @staticmethod
    def _extract_text(res: Any) -> str:
        """从 FunASR generate 返回值中提取文本。"""
        try:
            item = res[0] if isinstance(res, (list, tuple)) else res
            if isinstance(item, dict):
                return str(item.get("text", "")).strip()
            return str(item).strip()
        except Exception:
            return ""
