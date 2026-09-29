"""sherpa-onnx 模型下载与定位。

模型托管在 HuggingFace（``csukuangfj/*``），国内默认走 hf-mirror；VAD 小模型
托管在 sherpa-onnx 的 GitHub release（``asr-models`` tag，已实测直连可用）。

缓存约定沿用项目既有做法（见 backend/asr/asr_moss.py / asr_funasr_nano.py）：
``MODEL_CACHE_DIR`` 环境变量优先，其次项目根 ``_model_cache``，本模块统一落到
``<cache>/sherpa-onnx/<model-id>/`` 下。

下载带断点续传（``.part`` 续传）与进度回调，失败不留半成品。
"""
import os
import shutil
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
    "dolphin-base-multi-lang": {
        "name": "Dolphin Base (多语种 CTC, 轻量)",
        "repo": "csukuangfj/sherpa-onnx-dolphin-base-ctc-multi-lang-int8-2025-04-02",
        "kind": "dolphin_ctc",
        "weights": {"int8": {"model": "model.int8.onnx"}},
        "languages": [],
        "sample_rate": 16000,
        "feature_dim": 80,
    },
    "fire-red-asr-large-zh_en": {
        "name": "FireRedASR Large (中文最强, 1.66GB)",
        "kind": "fire_red_asr",
        # 走 GitHub release 归档：hf-mirror 对 GB 级 LFS 文件限速严重（实测 60KB/s
        # vs GitHub 直连 3MB/s），归档内含 int8 encoder/decoder 与词表。
        "archive": {
            "url": f"{_GH_RELEASE}/sherpa-onnx-fire-red-asr-large-zh_en-2025-02-16.tar.bz2",
            "members": {
                "encoder": "encoder.int8.onnx",
                "decoder": "decoder.int8.onnx",
                "tokens": "tokens.txt",
            },
        },
        "languages": ["zh", "en"],
        "sample_rate": 16000,
        "feature_dim": 80,
        # 体积大：仅在用户显式选择时才下载（不做默认/预热下载）
        "optional": True,
        "size_hint": "约 1.66GB（归档 1.4GB，下载后解压）",
    },
    "whisper-small": {
        "name": "Whisper Small (多语种, 支持直接翻译成英文)",
        "repo": "csukuangfj/sherpa-onnx-whisper-small",
        "kind": "whisper",
        "tokens": "small-tokens.txt",
        # 官方导出未含 cross-attention，无法产出 token 级时间戳
        "token_timestamps": False,
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


def _download_once(url: str, dest: str, part: str,
                   callback: Optional[Callable] = None,
                   label: str = "", timeout: float = 180) -> str:
    """单次下载尝试（内部使用，由 _download 负责重试）。"""
    resume = os.path.getsize(part) if os.path.exists(part) else 0

    # 部分镜像/CDN 会拒绝无 User-Agent 的请求（实测 hf-mirror 返回 403）
    headers = {"User-Agent": "VideoLingoFlow/sherpa-onnx-downloader"}
    if resume > 0:
        headers["Range"] = f"bytes={resume}-"
    req = urllib.request.Request(url, headers=headers)

    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        # 服务器不支持续传时从头重下
        if resume > 0 and exc.code in (416, 501):
            resume = 0
            if os.path.exists(part):
                os.remove(part)
            resp = urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": headers["User-Agent"]}),
                timeout=timeout)
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
    return part


def _download(url: str, dest: str, callback: Optional[Callable] = None,
              label: str = "", retries: int = 4, timeout: float = 180) -> str:
    """流式下载到 dest（先写 .part），支持续传与自动重试，返回最终路径。

    慢速镜像（hf-mirror 对 LFS 大文件限速）常在读取阶段触发 socket 超时，
    因此读超时放宽到 180s，并在中断后利用 .part 续传重试。
    """
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    part = dest + ".part"
    last_err: Optional[Exception] = None

    for attempt in range(max(1, retries)):
        try:
            _download_once(url, dest, part, callback, label, timeout)
            last_err = None
            break
        except Exception as exc:  # noqa: BLE001 网络类异常统一重试
            last_err = exc
            got = os.path.getsize(part) / 1048576 if os.path.exists(part) else 0
            if attempt + 1 < retries:
                _emit(callback, 0,
                      f"下载中断（已 {got:.1f}MB），重试 {attempt + 2}/{retries} ...")
                time.sleep(1.5)

    if last_err is not None:
        raise RuntimeError(f"下载失败: {url} ({last_err})")

    if not os.path.exists(part) or os.path.getsize(part) == 0:
        if os.path.exists(part):
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
    # 大体积"可选"模型：首次使用前明确提示体积（不做默认/预热下载）
    if entry.get("optional"):
        pending = [
            f for f in list(weights.values()) + [tokens_name]
            if not (os.path.exists(os.path.join(model_dir, f))
                    and os.path.getsize(os.path.join(model_dir, f)) > 0)
        ]
        if pending:
            _emit(callback, int(lo),
                  f"首次使用 {model_id}，需下载 {entry.get('size_hint', '较大体积')}（{len(pending)} 个文件）")
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

    # 归档源（GB 级大模型走 GitHub release 的 tar.bz2，比 hf-mirror 快很多）
    archive = entry.get("archive")
    if archive:
        members: Dict[str, str] = dict(archive.get("members") or {})
        archive_missing = {
            r: s for r, s in members.items()
            if not (os.path.exists(os.path.join(model_dir, os.path.basename(s)))
                    and os.path.getsize(os.path.join(model_dir, os.path.basename(s))) > 0)
        }
        if archive_missing:
            extracted = _download_archive(archive, model_dir, callback, (lo, hi))
            out.update(extracted)
        else:
            for role, suffix in members.items():
                out[role] = os.path.join(model_dir, os.path.basename(suffix))
        still_missing = [r for r in members if not out.get(r)]
        if still_missing:
            raise RuntimeError(f"模型文件不完整: {model_dir} (缺失: {still_missing})")
        out.setdefault("model", "")
        return out

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
    members = (entry.get("archive") or {}).get("members")
    if members:
        files = [os.path.basename(s) for s in members.values()]
    else:
        files = list(_resolve_weights(entry, model_file=model_file).values())
        files.append(entry.get("tokens", "tokens.txt"))
    model_dir = os.path.join(SHERPA_MODEL_DIR, model_id)
    for fname in files:
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


def _download_archive(archive: dict, model_dir: str,
                      callback: Optional[Callable] = None,
                      progress_range: tuple = (0, 100)) -> Dict[str, str]:
    """从 tar.bz2 归档提取所需成员（用于 GitHub release 上的大模型）。

    archive = {"url": <tar.bz2 地址>, "members": {role: "成员名后缀"}}
    先流式下载归档到 `_archive.tar.bz2`（.part 续传，避免占内存），
    解压所需成员后删除归档。返回 {role: 本地路径}。

    实测：GitHub release 直连约 3MB/s，明显快于 hf-mirror 对 GB 级 LFS
    文件的限速，故大模型优先走归档源。
    """
    import tarfile

    members: Dict[str, str] = dict(archive.get("members") or {})
    lo, hi = progress_range
    tmp = os.path.join(model_dir, "_archive.tar.bz2")

    _download(_gh_url(archive["url"]), tmp,
              lambda p, m: _emit(callback, int(lo + (hi - lo) * 0.85 * p / 100), m),
              label=os.path.basename(archive["url"]))

    out: Dict[str, str] = {}
    try:
        with tarfile.open(tmp, "r:bz2") as tf:
            files = {m.name: m for m in tf.getmembers() if m.isfile()}
            for i, (role, suffix) in enumerate(members.items()):
                name = next((n for n in files if n.endswith(suffix)), None)
                if name is None:
                    raise RuntimeError(f"归档中未找到 {suffix}: {archive['url']}")
                dest = os.path.join(model_dir, os.path.basename(name))
                src = tf.extractfile(files[name])
                with open(dest + ".part", "wb") as f:
                    shutil.copyfileobj(src, f, 1024 * 512)
                os.replace(dest + ".part", dest)
                out[role] = dest
                _emit(callback,
                      int(lo + (hi - lo) * 0.85 + (hi - lo) * 0.15 * (i + 1) / max(len(members), 1)),
                      f"解压 {os.path.basename(name)}")
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return out


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


# ---------------------------------------------------------------------------
# 语音降噪 / 音源分离模型
# ---------------------------------------------------------------------------
_GH_ENHANCE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speech-enhancement-models"

# 降噪（GTCRN 0.5MB 起；DPDFNet 8~14MB，质量更高）
DENOISE_REGISTRY: Dict[str, dict] = {
    "gtcrn_simple": {
        "file": "gtcrn_simple.onnx",
        "url": f"{_GH_ENHANCE}/gtcrn_simple.onnx",
        "kind": "gtcrn",
        "name": "GTCRN (轻量 0.5MB)",
    },
    "dpdfnet_baseline": {
        "file": "dpdfnet_baseline.onnx",
        "url": f"{_GH_ENHANCE}/dpdfnet_baseline.onnx",
        "kind": "dpdfnet",
        "name": "DPDFNet Baseline (8.4MB)",
    },
    "dpdfnet2": {
        "file": "dpdfnet2.onnx",
        "url": f"{_GH_ENHANCE}/dpdfnet2.onnx",
        "kind": "dpdfnet",
        "name": "DPDFNet 2 (9.8MB, 质量更好)",
    },
    "dpdfnet4": {
        "file": "dpdfnet4.onnx",
        "url": f"{_GH_ENHANCE}/dpdfnet4.onnx",
        "kind": "dpdfnet",
        "name": "DPDFNet 4 (11.2MB)",
    },
    "dpdfnet8": {
        "file": "dpdfnet8.onnx",
        "url": f"{_GH_ENHANCE}/dpdfnet8.onnx",
        "kind": "dpdfnet",
        "name": "DPDFNet 8 (13.9MB, 质量最好)",
    },
}
DEFAULT_DENOISE_MODEL = "gtcrn_simple"

# 音源分离（Spleeter 2stems：人声 + 伴奏，两个 onnx 分别推理）
SEPARATION_REGISTRY: Dict[str, dict] = {
    "spleeter-2stems": {
        "repo": "csukuangfj/sherpa-onnx-spleeter-2stems-int8",
        "files": {"vocals": "vocals.int8.onnx",
                  "accompaniment": "accompaniment.int8.onnx"},
        "name": "Spleeter 2stems (人声/伴奏, int8 ~46MB)",
    },
}
DEFAULT_SEPARATION_MODEL = "spleeter-2stems"


def ensure_denoise_model(model: str = DEFAULT_DENOISE_MODEL,
                         callback: Optional[Callable] = None,
                         progress_range: tuple = (0, 100)) -> dict:
    """确保降噪模型就绪，返回 {"path", "kind", "file"}。"""
    entry = DENOISE_REGISTRY.get(model)
    if not entry:
        raise ValueError(
            f"未知的降噪模型: {model}，可选: {', '.join(DENOISE_REGISTRY)}")
    dest = os.path.join(SHERPA_MODEL_DIR, "denoise", entry["file"])
    if not (os.path.exists(dest) and os.path.getsize(dest) > 0):
        lo, hi = progress_range
        _download(_gh_url(entry["url"]), dest,
                  lambda p, m, _lo=lo, _hi=hi: _emit(
                      callback, int(_lo + (_hi - _lo) * p / 100), m),
                  label=entry["file"])
    return {"path": dest, "kind": entry["kind"], "file": entry["file"],
            "model_id": model}


def ensure_separation_model(model: str = DEFAULT_SEPARATION_MODEL,
                            callback: Optional[Callable] = None,
                            progress_range: tuple = (0, 100)) -> Dict[str, str]:
    """确保音源分离模型就绪，返回 {角色: 本地路径}（如 vocals / accompaniment）。"""
    entry = SEPARATION_REGISTRY.get(model)
    if not entry:
        raise ValueError(
            f"未知的分离模型: {model}，可选: {', '.join(SEPARATION_REGISTRY)}")
    model_dir = os.path.join(SHERPA_MODEL_DIR, "separation", model)
    os.makedirs(model_dir, exist_ok=True)

    lo, hi = progress_range
    files = list(entry["files"].items())
    out: Dict[str, str] = {}
    for i, (role, fname) in enumerate(files):
        dest = os.path.join(model_dir, fname)
        if not (os.path.exists(dest) and os.path.getsize(dest) > 0):
            sub_lo = lo + (hi - lo) * i / max(len(files), 1)
            sub_hi = lo + (hi - lo) * (i + 1) / max(len(files), 1)
            _emit(callback, int(sub_lo), f"准备下载 {fname} ...")
            _download(_hf_url(entry["repo"], fname), dest,
                      lambda p, m, _l=sub_lo, _h=sub_hi: _emit(
                          callback, int(_l + (_h - _l) * p / 100), m),
                      label=fname)
        out[role] = dest
    out["model_id"] = model
    return out


if __name__ == "__main__":
    mid = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL
    info = ensure_model(mid, callback=lambda p, m: print(f"\r{p}% {m}", end=""))
    print()
    print(info)
