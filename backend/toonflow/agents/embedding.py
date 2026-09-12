# -*- coding: utf-8 -*-
"""向量化后端 —— 复用 Toonflow 自带的本地 ONNX 模型 all-MiniLM-L6-v2（384 维）。

后端优先级（惰性初始化，失败自动降级）：
    1. local-onnx : onnxruntime + tokenizers，模型在 models/all-MiniLM-L6-v2（与源系统同一模型，
       embedding 与 Toonflow 存量数据互通；mean-pooling + L2 归一化，对齐 sentence-transformers）
    2. hash       : 确定性哈希词袋（无任何依赖的兜底，词法级相似度，保证记忆系统可用）

对齐源 utils/agent/embedding.ts 的 getEmbedding / cosineSimilarity 契约。
"""
import math
import re
import threading
from pathlib import Path

import numpy as np

MODEL_DIR = Path(__file__).resolve().parents[1] / "models" / "all-MiniLM-L6-v2"
DIM = 384
_MAX_TOKENS = 256  # MiniLM 上限 512，记忆摘要场景 256 足够且更快

_lock = threading.Lock()
_backend = None  # ("onnx", session, tokenizer) | ("hash", None)


def _try_onnx():
    try:
        import onnxruntime
        from tokenizers import Tokenizer
    except Exception:  # noqa: BLE001
        return None
    model_file = MODEL_DIR / "onnx" / "model_fp16.onnx"
    tok_file = MODEL_DIR / "tokenizer.json"
    if not model_file.is_file() or not tok_file.is_file():
        return None
    try:
        session = onnxruntime.InferenceSession(str(model_file), providers=["CPUExecutionProvider"])
        tokenizer = Tokenizer.from_file(str(tok_file))
        tokenizer.enable_truncation(max_length=_MAX_TOKENS)
        tokenizer.enable_padding()
        return ("onnx", session, tokenizer)
    except Exception:  # noqa: BLE001
        return None


def _get_backend():
    global _backend
    if _backend is None:
        with _lock:
            if _backend is None:
                _backend = _try_onnx() or ("hash", None)
    return _backend


def _onnx_encode(session, tokenizer, texts: list[str]) -> list[list[float]]:
    encodings = tokenizer.encode_batch(texts)
    ids = np.array([e.ids for e in encodings], dtype=np.int64)
    mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
    feed = {"input_ids": ids, "attention_mask": mask}
    names = {i.name for i in session.get_inputs()}
    if "token_type_ids" in names:
        feed["token_type_ids"] = np.zeros_like(ids)
    hidden = session.run(None, feed)[0]  # (batch, seq, 384) last_hidden_state
    mask_f = mask[:, :, None].astype(np.float32)
    summed = (hidden * mask_f).sum(axis=1)
    counts = np.clip(mask_f.sum(axis=1), 1e-9, None)
    mean = summed / counts
    norm = np.linalg.norm(mean, axis=1, keepdims=True)
    norm = np.clip(norm, 1e-12, None)
    return (mean / norm).tolist()


def _hash_encode(texts: list[str]) -> list[list[float]]:
    """确定性哈希词袋（DIM 维、L2 归一化）：无依赖兜底，提供词法级相似度。"""
    out = []
    for text in texts:
        vec = [0.0] * DIM
        for token in re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+", (text or "").lower()):
            h = hash(token) % DIM
            vec[h] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        out.append([v / norm for v in vec])
    return out


def get_embedding(text: str) -> list[float]:
    return get_embeddings([text])[0]


def get_embeddings(texts: list[str]) -> list[list[float]]:
    backend = _get_backend()
    if backend[0] == "onnx":
        _, session, tokenizer = backend
        try:
            return _onnx_encode(session, tokenizer, texts)
        except Exception:  # noqa: BLE001
            pass
    return _hash_encode(texts)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-12
    nb = math.sqrt(sum(y * y for y in b)) or 1e-12
    return dot / (na * nb)
