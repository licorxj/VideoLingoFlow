"""sherpa-onnx 模型下载与定位。

模型托管在 HuggingFace（``csukuangfj/*``），国内默认走 hf-mirror；VAD 小模型
托管在 sherpa-onnx 的 GitHub release（``asr-models`` tag，已实测直连可用）。

缓存约定沿用项目既有做法（见 backend/asr/asr_moss.py / asr_funasr_nano.py）：
``MODEL_CACHE_DIR`` 环境变量优先，其次项目根 ``_model_cache``，本模块统一落到
``<cache>/sherpa-onnx/<model-id>/`` 下。

下载带断点续传（``.part`` 续传）与进度回调，失败不留半成品。
"""
import os
import sys
import time
import urllib.request
import urllib.error
from typing import Callable, Dict, List, Optional

# ---------------------------------------------------------------------------
# 缓存根目录
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MODEL_CACHE_DIR = os.environ.get("MODEL_CACHE_DIR") or os.path.join(_PROJECT_ROOT, "_model_cache")
SHERPA_MODEL_DIR = os.path.join(MODEL_CACHE_DIR, "sherpa-onnx")

# HF 镜像：国内直连 huggingface.co 常失败，默认 hf-mirror.com（已实测可达）。
HF_ENDPOINT = (os.environ.get("HF_ENDPOINT") or "https://hf-mirror.com").rstrip("/")
# GitHub release 镜像前缀（可选，如 https://gh-proxy.com/）。
GH_MIRROR = (os.environ.get("SHERPA_GH_MIRROR") or "").rstrip("/")

_GH_RELEASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"

# ---------------------------------------------------------------------------
# 模型注册表
#   key      -> 前端下拉里展示的模型 ID（同时作为缓存目录名）
#   repo     -> HuggingFace 仓库
#   kind     -> sherpa-onnx 的识别器构造分支
#   weights  -> 权重变体：variant -> {role: 文件名}
#               单文件模型 role 固定为 "model"（sense_voice / paraformer / dolphin）
#               多文件模型为 "encoder" + "decoder"（whisper / fire-red-asr）
#   tokens   -> 词表文件名（默认 tokens.txt）
# ---------------------------------------------------------------------------
MODEL_REGISTRY: Dict[str, dict] = {
    "sense-voice-zh-en-ja-ko-yue": {
        "name": "SenseVoiceSmall (中/英/日/韩/粤)",
        "repo": "csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
        "kind": "sense_voice",
        "weights": {
            "int8": {"model": "model.int8.onnx"},
            "fp32": {"model": "model.onnx"},
        },
        "languages": ["auto", "zh", "en", "ja", "ko", "yue"],
        "sample_rate": 16000,
        "feature_dim": 80,
    },
    "sense-voice-funasr-nano": {
        "name": "FunASR-Nano (ONNX 版, 中/英/日)",
        "repo": "csukuangfj/sherpa-onnx-sense-voice-funasr-nano-int8-2025-12-17",
        "kind": "sense_voice",
        "weights": {"int8": {"model": "model.int8.onnx"}},
        "languages": ["auto", "zh", "en", "ja"],
        "sample_rate": 16000,
        "feature_dim": 80,
    },
    "paraformer-zh": {
        "name": "Paraformer 中文(大, 字级时间戳)",
        "repo": "csukuangfj/sherpa-onnx-paraformer-zh-2024-03-09",
        "kind": "paraformer",
        "weights": {
            "int8": {"model": "model.int8.onnx"},
            "fp32": {"model": "model.onnx"},
        },
        "languages": ["zh"],
        "sample_rate": 16000,
        "feature_dim": 80,
    },
    "paraformer-zh-small": {
        "name": "Paraformer 中文(小, 字级时间戳)",
        "repo": "csukuangfj/sherpa-onnx-paraformer-zh-small-2024-03-09",
        "kind": "paraformer",
        "weights": {"int8": {"model": "model.int8.onnx"}},
        "languages": ["zh"],
        "sample_rate": 16000,
        "feature_dim": 80,
    },
    "dolphin-base-multi-lang": {
        "name": "Dolphin Base (多语种 CTC, 轻量)",
        "repo": "csukuangfj/sherpa-onnx-dolphin-base-ctc-multi-lang-int8-2025-04-02",
        "kind": "dolphin_ctc",
        "weights": {"int8": {"model": "model.int8.onnx"}},
        "languages": [],
        "sample_rate": 16000,
        "feature_dim": 80,
    },
    "whisper-small": {
        "name": "Whisper Small (多语种, 支持直接翻译成英文)",
        "repo": "csukuangfj/sherpa-onnx-whisper-small",
        "kind": "whisper",
        "tokens": "small-tokens.txt",
        "weights": {
            "int8": {"encoder": "small-encoder.int8.onnx",
                     "decoder": "small-decoder.int8.onnx"},
            "fp32": {"encoder": "small-encoder.onnx", "decoder": "small-decoder.onnx"},
        },
        "languages": ["auto", "zh", "en", "ja", "ko", "fr", "de", "es", "ru"],
        "sample_rate": 16000,
        "feature_dim": 80,
        "supports_translate": True,
    },
}

DEFAULT_MODEL = "sense-voice-zh-en-ja-ko-yue"

# VAD 模型（GitHub release，2.2MB，实测直连可用）
VAD_REGISTRY: Dict[str, dict] = {
    "silero_vad_v5": {
        "file": "silero_vad_v5.onnx",
        "url": f"{_GH_RELEASE}/silero_vad_v5.onnx",
    },
    "silero_vad_v4": {
        "file": "silero_vad_v4.onnx",
        "url": f"{_GH_RELEASE}/silero_vad_v4.onnx",
    },
}
DEFAULT_VAD_MODEL = "silero_vad_v5"


def list_models() -> List[str]:
    return list(MODEL_REGISTRY.keys())


def model_languages(model_id: str) -> List[str]:
    entry = MODEL_REGISTRY.get(model_id)
    return list(entry["languages"]) if entry else ["auto"]


# ---------------------------------------------------------------------------
# 下载
# ---------------------------------------------------------------------------
def _emit(callback: Optional[Callable], percent: int, message: str) -> None:
    if callback:
        try:
            callback(int(percent), message)
        except Exception:
            pass


def _download(url: str, dest: str, callback: Optional[Callable] = None,
              label: str = "") -> str:
    """流式下载到 dest（先写 .part）。支持续传；返回最终路径。"""
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    part = dest + ".part"
    resume = 0
    if os.path.exists(part):
        resume = os.path.getsize(part)

    # 部分镜像/CDN 会拒绝无 User-Agent 的请求（实测 hf-mirror 返回 403）
    headers = {"User-Agent": "VideoLingoFlow/sherpa-onnx-downloader"}
    if resume > 0:
        headers["Range"] = f"bytes={resume}-"
    req = urllib.request.Request(url, headers=headers)

    try:
        resp = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as exc:  # noqa: F821
        # 服务器不支持续传时从头重下
        if resume > 0 and exc.code in (416, 501):
            resume = 0
            os.remove(part)
            resp = urllib.request.urlopen(urllib.request.Request(url), timeout=60)
        else:
            raise

    total = resp.headers.get("Content-Length")
    total = int(total) + resume if total else 0
    mode = "ab" if resume > 0 else "wb"

    last_report = 0.0
    got = resume
    try:
        with open(part, mode) as f:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                now = time.time()
                if callback and (now - last_report) > 0.5:
                    last_report = now
                    if total:
                        pct = int(got * 100 / total)
                        _emit(callback, pct,
                              f"下载 {label or os.path.basename(dest)} "
                              f"{got / 1048576:.1f}/{total / 1048576:.1f} MB")
    finally:
        try:
            resp.close()
        except Exception:
            pass

    if os.path.getsize(part) == 0:
        os.remove(part)
        raise RuntimeError(f"下载失败（空文件）: {url}")
    os.replace(part, dest)
    return dest


def _hf_url(repo: str, filename: str) -> str:
    return f"{HF_ENDPOINT}/{repo}/resolve/main/{filename}"


def _gh_url(url: str) -> str:
    """应用可选的 GitHub 镜像前缀。"""
    if GH_MIRROR:
        return f"{GH_MIRROR}/{url}"
    return url


def _resolve_weights(entry: dict, variant: Optional[str] = None,
                     model_file: Optional[str] = None) -> Dict[str, str]:
    """解析权重文件：{role: 文件名}。

    优先级：显式 model_file（仅单文件模型） > 显式 variant > 条目默认变体。
    默认取 int8（存在时），否则取第一个变体。
    """
    if model_file:
        return {"model": model_file}
    weights = entry.get("weights") or {}
    if variant and variant in weights:
        return dict(weights[variant])
    if "int8" in weights:
        return dict(weights["int8"])
    if weights:
        return dict(next(iter(weights.values())))
    return {"model": entry.get("default_file", "model.onnx")}


def ensure_model(model_id: str, model_file: Optional[str] = None,
                 callback: Optional[Callable] = None,
                 progress_range: tuple = (0, 100),
                 variant: Optional[str] = None) -> dict:
    """确保模型文件已就绪。

    返回 {"dir", "kind", "model"/"encoder"/"decoder"(按 role 平铺), "tokens",
          "model_id", "variant", ...}。多文件模型（whisper / fire-red）会给
    "encoder" 与 "decoder" 两个路径。
    """
    entry = MODEL_REGISTRY.get(model_id)
    if not entry:
        raise ValueError(
            f"未知的 sherpa-onnx 模型: {model_id}，可选: {', '.join(list_models())}")

    weights = _resolve_weights(entry, variant=variant, model_file=model_file)
    resolved_variant = variant or ("int8" if "int8" in (entry.get("weights") or {}) else "")
    tokens_name = entry.get("tokens", "tokens.txt")
    model_dir = os.path.join(SHERPA_MODEL_DIR, model_id)
    os.makedirs(model_dir, exist_ok=True)

    lo, hi = progress_range
    # 进度按"权重文件 + 词表"平均切分
    slots = list(weights.items()) + [("__tokens__", tokens_name)]
    n = len(slots)

    out = {
        "dir": model_dir,
        "kind": entry["kind"],
        "sample_rate": entry.get("sample_rate", 16000),
        "feature_dim": entry.get("feature_dim", 80),
        "tokens": "",
        "model_id": model_id,
        "variant": resolved_variant,
        "model_file": next(iter(weights.values()), ""),
        "supports_translate": bool(entry.get("supports_translate", False)),
    }

    for i, (role, fname) in enumerate(slots):
        dest = os.path.join(model_dir, fname)
        if not os.path.exists(dest) or os.path.getsize(dest) == 0:
            sub_lo = lo + (hi - lo) * i / max(n, 1)
            sub_hi = lo + (hi - lo) * (i + 1) / max(n, 1)
            _emit(callback, int(sub_lo), f"准备下载 {fname} ...")
            _download(_hf_url(entry["repo"], fname), dest,
                      lambda p, m, _lo=sub_lo, _hi=sub_hi: _emit(
                          callback, int(_lo + (_hi - _lo) * p / 100), m),
                      label=fname)
        if role == "__tokens__":
            out["tokens"] = dest
        else:
            out[role] = dest

    missing = [r for r, _ in weights.items() if not out.get(r)]
    if missing or not out["tokens"]:
        raise RuntimeError(f"模型文件不完整: {model_dir} (缺失: {missing})")
    # 单文件模型沿用 "model" 字段名，多文件模型名为 "model" 的字段不存在，保持为空
    out.setdefault("model", "")
    return out


def ensure_vad_model(vad_model: str = DEFAULT_VAD_MODEL,
                     callback: Optional[Callable] = None,
                     progress_range: tuple = (0, 100)) -> str:
    """确保 VAD 模型已就绪，返回本地路径。"""
    entry = VAD_REGISTRY.get(vad_model)
    if not entry:
        raise ValueError(
            f"未知的 VAD 模型: {vad_model}，可选: {', '.join(VAD_REGISTRY)}")
    dest = os.path.join(SHERPA_MODEL_DIR, "vad", entry["file"])
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest

    lo, hi = progress_range
    _emit(callback, int(lo), f"准备下载 VAD 模型 {entry['file']} ...")
    _download(_gh_url(entry["url"]), dest,
              lambda p, m: _emit(callback, int(lo + (hi - lo) * p / 100), m),
              label=entry["file"])
    return dest


def is_cached(model_id: str, model_file: Optional[str] = None) -> bool:
    """模型是否已在本地缓存（不触发下载）。"""
    entry = MODEL_REGISTRY.get(model_id)
    if not entry:
        return False
    weights = _resolve_weights(entry, model_file=model_file)
    model_dir = os.path.join(SHERPA_MODEL_DIR, model_id)
    tokens_name = entry.get("tokens", "tokens.txt")
    if not os.path.exists(os.path.join(model_dir, tokens_name)):
        return False
    for fname in weights.values():
        if not (os.path.exists(os.path.join(model_dir, fname))
                and os.path.getsize(os.path.join(model_dir, fname)) > 0):
            return False
    return True


# ---------------------------------------------------------------------------
# 后处理配套模型（标点恢复 / 说话人分离）
# ---------------------------------------------------------------------------
_GH_SPEAKER_SEG = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models"
_GH_SPEAKER_EMB = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models"

PUNCT_REPO = "csukuangfj/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12"
PUNCT_FILE = "model.onnx"

# 说话人分割（pyannote 3.0，tar.bz2 内取 int8 权重）与声纹（3D-Speaker eres2net）
SPEAKER_SEG_URL = f"{_GH_SPEAKER_SEG}/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
SPEAKER_SEG_MEMBER = "model.int8.onnx"
SPEAKER_EMB_URL = f"{_GH_SPEAKER_EMB}/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"


def _download_tar_member(url: str, dest: str, member_hint: str,
                         callback: Optional[Callable] = None,
                         progress_range: tuple = (0, 100)) -> str:
    """下载 tar.bz2 并只解出包含 member_hint 的 .onnx 成员。"""
    import io
    import tarfile

    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    lo, hi = progress_range

    _emit(callback, int(lo), "下载说话人分割模型 ...")
    req = urllib.request.Request(url, headers={"User-Agent": "VideoLingoFlow/sherpa-onnx-downloader"})
    resp = urllib.request.urlopen(req, timeout=60)
    total = int(resp.headers.get("Content-Length") or 0)
    buf = io.BytesIO()
    got = 0
    last = 0.0
    while True:
        chunk = resp.read(1024 * 256)
        if not chunk:
            break
        buf.write(chunk)
        got += len(chunk)
        now = time.time()
        if callback and total and (now - last) > 0.5:
            last = now
            _emit(callback, int(lo + (hi - lo) * 0.7 * got / total),
                  f"下载 {got / 1048576:.1f}/{total / 1048576:.1f} MB")
    resp.close()

    buf.seek(0)
    tmp = dest + ".part"
    with tarfile.open(fileobj=buf, mode="r:bz2") as tf:
        target = None
        for m in tf.getmembers():
            if m.isfile() and m.name.endswith(".onnx") and member_hint in m.name:
                target = m
                break
        if target is None:
            raise RuntimeError(f"压缩包中未找到 {member_hint}: {url}")
        src = tf.extractfile(target)
        with open(tmp, "wb") as f:
            f.write(src.read())
    os.replace(tmp, dest)
    return dest


def ensure_punct_model(callback: Optional[Callable] = None,
                       progress_range: tuple = (0, 100)) -> str:
    """CT-Transformer 标点恢复模型（中英）。"""
    dest = os.path.join(SHERPA_MODEL_DIR, "punct", PUNCT_FILE)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest
    _download(_hf_url(PUNCT_REPO, PUNCT_FILE), dest,
              lambda p, m, _lo=progress_range[0], _hi=progress_range[1]: _emit(
                  callback, int(_lo + (_hi - _lo) * p / 100), m),
              label="标点模型 " + PUNCT_FILE)
    return dest


def ensure_speaker_models(callback: Optional[Callable] = None,
                          progress_range: tuple = (0, 100)) -> Dict[str, str]:
    """返回 {"segmentation": path, "embedding": path}。"""
    lo, hi = progress_range
    seg_dir = os.path.join(SHERPA_MODEL_DIR, "speaker")
    os.makedirs(seg_dir, exist_ok=True)

    seg_path = os.path.join(seg_dir, "pyannote-segmentation-3-0.onnx")
    emb_path = os.path.join(seg_dir, "3dspeaker-eres2net.onnx")

    if not (os.path.exists(seg_path) and os.path.getsize(seg_path) > 0):
        _download_tar_member(_gh_url(SPEAKER_SEG_URL), seg_path, SPEAKER_SEG_MEMBER,
                             callback=callback, progress_range=(lo, lo + (hi - lo) * 0.6))
    if not (os.path.exists(emb_path) and os.path.getsize(emb_path) > 0):
        _download(_gh_url(SPEAKER_EMB_URL), emb_path,
                  lambda p, m, _lo=lo + (hi - lo) * 0.6, _hi=hi: _emit(
                      callback, int(_lo + (_hi - _lo) * p / 100), m),
                  label="声纹模型 3dspeaker")
    return {"segmentation": seg_path, "embedding": emb_path}


if __name__ == "__main__":
    mid = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL
    info = ensure_model(mid, callback=lambda p, m: print(f"\r{p}% {m}", end=""))
    print()
    print(info)
