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
            print(f"[Punctuation] Language '{language or 'unknown'}' not supported by ct-punc, skipping")
            return segments

        if not _needs_punctuation(segments):
            print("[Punctuation] Text already has sufficient punctuation, skipping")
            return segments

        model = self._get_model()
        print(f"[Punctuation] Restoring punctuation for {len(segments)} segment(s)")
        for seg in segments:
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            try:
                res = model.generate(input=text)
            except Exception as e:
                print(f"[Punctuation] Segment restore failed, keeping original text: {e}")
                continue
            restored = self._extract_text(res)
            if restored:
                seg["text"] = restored
        return segments

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
        print(f"[Punctuation] Loading CT-Punc model: {model_name} (device={device})")
        model = AutoModel(model=model_name, device=device, disable_update=True)
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
