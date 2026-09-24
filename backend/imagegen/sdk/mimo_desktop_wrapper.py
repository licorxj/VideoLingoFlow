#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MiMo Desktop 桌面生图反代服务 SDK 封装（云端类型）。

对接 MiMo Desktop 内置 AI 生图（``image_gen`` / ``image_edit``）的本地 HTTP 反代服务
（``mimo-api-service``，OpenAI Images 兼容 + 任务队列扩展，默认 ``http://127.0.0.1:8000``）。
本模块是 imagegen 工厂约定的 ``sdk_function`` 入口：``generate(...)`` 返回本地文件路径列表。

接口能力（详见《MiMo Desktop 生图 API 外部调用文档》）：
  * 生图 ``POST /v1/images/generations``：prompt / size / quality / output_format / background
  * 改图 ``POST /v1/images/edits``：image / image_url / image_urls（需服务进程可读的本地绝对路径）
  * 任务查询 ``GET /v1/images/jobs/{job_id}``（同步等待 504 后按 job_id 继续轮询）
  * 模型列表 ``GET /v1/models``、健康检查 ``GET /health``、下载 ``GET /files/{file_name}``

约束与处理：
  * ``n`` 仅支持 1 → 多图按 ``num_images`` 串行多次请求；
  * ``size`` 须为 16 的倍数且面积 ≥ 921600 → 由（分辨率档位, 宽高比）换算后对齐/放大；
  * 出图依赖 Desktop 会话排空队列，可能数十秒 → 同步 ``wait=true`` + 504 兜底轮询；
  * 服务响应里的 ``path`` 是**服务所在机器**的绝对路径：本机部署时直接拷贝，
    跨机部署时该路径不可用，自动回退按 ``url`` 走 ``/files/...`` 下载。

⚠ 服务端错误体结构与文档不一致（实测 ``mimo-api-service/main.py``）：504/502 由
``HTTPException(detail={...})`` 抛出，FastAPI 会序列化成 ``{"detail": {"job_id", "error",
"drain_hint"}}``，而文档写作顶层 ``{job_id, error, drain_hint}``。取 ``job_id`` 必须同时兼容
两种结构（见 ``_payload_of``），否则同步等待超时后拿不到 job_id、直接判失败——而此刻图片
往往已在 Desktop 侧生成中。

云端标识：模块级 ``CLOUD = True`` —— 反代外壳虽跑在本机（localhost），实际生图算力在
MiMo Desktop 侧，不占本机 GPU；调度层据此按「云端接口」处理、免 gpu 令牌
（与 TTS/ASR 引擎的 CLOUD 标记一致）。
"""
import os
import math
import time
import base64
import shutil
import logging
from urllib.parse import urlparse

from backend.imagegen.imagegen_retry import request_with_retry

logger = logging.getLogger(__name__)

# 云端接口标识：不占本机 GPU（详见模块 docstring）。
CLOUD = True

# ── 服务端约定 ────────────────────────────────────────────────────────────────
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
GEN_ENDPOINT = "/v1/images/generations"
EDIT_ENDPOINT = "/v1/images/edits"
JOBS_ENDPOINT = "/v1/images/jobs"
MODELS_ENDPOINT = "/v1/models"
HEALTH_ENDPOINT = "/health"

# MiMo Desktop 的两个内置能力（与 /v1/models 返回一致）
GEN_MODEL = "desktop/image_gen"
EDIT_MODEL = "desktop/image_edit"
MODEL_OPTIONS = [GEN_MODEL, EDIT_MODEL]
DEFAULT_MODEL = GEN_MODEL

# ── 参数默认值与约束 ─────────────────────────────────────────────────────────
# 分辨率档位 → 正方形基准边长（px）
RESOLUTION_BASE = {"1K": 1024, "2K": 2048, "4K": 4096}
# 服务端尺寸约束：16 的倍数，面积 ≥ 921600
_SIZE_ALIGN = 16
_MIN_PIXELS = 921600
DEFAULT_QUALITY = "medium"          # low | medium | high
QUALITY_OPTIONS = ("low", "medium", "high")
DEFAULT_OUTPUT_FORMAT = "png"       # png | jpeg | webp
DEFAULT_BACKGROUND = "opaque"       # opaque | transparent | auto
DEFAULT_TIMEOUT = 180               # 同步等待秒数（对应服务端 IMAGE_TIMEOUT）
DEFAULT_POLL_INTERVAL = 2.0         # 504 后按 job_id 轮询间隔（秒）
DEFAULT_POLL_TIMEOUT = 600          # job 轮询总时长（秒）；Desktop 排空队列可能数分钟
MAX_IMAGES = 4                      # n 仅支持 1，多图串行次数上限
# 轮询期间连续 404 容忍次数：Desktop Agent 把任务从 pending 移到 done/failed 的瞬间
# 可能两边都查不到，属瞬时状态，不应立即判失败（按 2s 间隔 ≈ 30s）。
_MAX_NOT_FOUND_STREAK = 15

_IMAGE_EXTS = ("png", "jpg", "jpeg", "webp", "gif")


# ── 基础工具 ─────────────────────────────────────────────────────────────────
def _get_base_url(base_url: str = "") -> str:
    """反代服务地址：参数 > 环境变量 MIMO_DESKTOP_BASE_URL > 默认本机 8000。"""
    return (
        (base_url or "").strip()
        or (os.environ.get("MIMO_DESKTOP_BASE_URL", "") or "").strip()
        or DEFAULT_BASE_URL
    ).rstrip("/")


def _no_proxy_arg(base_url: str) -> dict:
    """构造 requests 的 ``no_proxy``，避免系统代理（Clash 等）劫持本机/内网反代。

    ``trust_env`` 在共享重试层不可用，故显式传入 ``proxies={'no_proxy': ...}``：
    其中包含回环地址、调用方环境变量 NO_PROXY 以及本次目标主机。
    """
    hosts = ["127.0.0.1", "localhost", "::1"]
    env_no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    for item in env_no_proxy.split(","):
        item = item.strip()
        if item and item not in hosts:
            hosts.append(item)
    try:
        host = (urlparse(base_url).hostname or "").strip()
    except Exception:  # noqa: BLE001
        host = ""
    if host and host not in hosts:
        hosts.append(host)
    return {"no_proxy": ",".join(hosts)}


def _ext_of(*candidates) -> str:
    """从文件名/路径中取图片扩展名，取不到按 png。"""
    for value in candidates:
        if not value:
            continue
        suffix = os.path.splitext(str(value))[1].lstrip(".").lower()
        if suffix in _IMAGE_EXTS:
            return suffix
    return "png"


def _guess_ext_from_bytes(raw: bytes) -> str:
    """按魔数判断图片类型（b64_json 响应兜底）。"""
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if raw[:3] == b"\xff\xd8\xff":
        return "jpg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return "png"


def _parse_ratio(aspect_ratio: str):
    """解析 'a:b' 为 (a, b)，非法返回 (1, 1)。"""
    if not aspect_ratio or ":" not in str(aspect_ratio):
        return (1, 1)
    try:
        a, b = str(aspect_ratio).split(":")
        a, b = int(a), int(b)
        if a <= 0 or b <= 0:
            return (1, 1)
        return (a, b)
    except Exception:  # noqa: BLE001
        return (1, 1)


def _resolve_size(resolution: str, aspect_ratio: str) -> str:
    """把（分辨率档位 + 宽高比）换算为服务端要求的 ``宽x高``。

    服务端无 aspect_ratio 参数，宽高比只能通过像素尺寸表达；同时必须满足
    「16 的倍数 + 面积 ≥ 921600」。返回空串表示「不传 size，用服务端默认值」。
    """
    res = str(resolution or "").strip().upper()
    if not res or res == "AUTO":
        return ""
    base = RESOLUTION_BASE.get(res)
    if not base:
        if res.isdigit():          # 兼容直接传基准边长
            base = int(res)
        else:
            logger.warning("MiMo Desktop: 无法识别的分辨率档位 %s，改用服务端默认尺寸", resolution)
            return ""

    a, b = _parse_ratio(aspect_ratio if str(aspect_ratio).strip().lower() != "auto" else "1:1")
    ratio = a / b
    w = base * math.sqrt(ratio)
    h = base / math.sqrt(ratio)

    total = w * h
    if total < _MIN_PIXELS:        # 面积不足按比例整体放大（保持宽高比）
        scale = math.sqrt(_MIN_PIXELS / total)
        w *= scale
        h *= scale

    w = max(_SIZE_ALIGN, int(math.ceil(w / _SIZE_ALIGN)) * _SIZE_ALIGN)
    h = max(_SIZE_ALIGN, int(math.ceil(h / _SIZE_ALIGN)) * _SIZE_ALIGN)
    return f"{w}x{h}"


def _request(method: str, url: str, *, base_url: str, timeout: float, **kwargs):
    """统一发起 HTTP 请求（带传输层重试 + 绕过本机代理）。"""
    return request_with_retry(
        method, url, timeout=timeout, proxies=_no_proxy_arg(base_url), **kwargs
    )


def _payload_of(resp) -> dict:
    """解析 JSON 响应体，并**解开 FastAPI 的 ``detail`` 包装**。

    服务端 ``main.py`` 的超时/失败分支写作::

        raise HTTPException(status_code=504, detail={"job_id": ..., "error": ..., "drain_hint": ...})

    FastAPI 会序列化成 ``{"detail": {"job_id": ...}}``（错误码 502/400 同理），
    而文档描述为顶层 ``{job_id, error, drain_hint}``。此处两种结构都兼容，
    并统一补一个 ``message`` 便于上层拼错误信息。
    """
    try:
        body = resp.json()
    except ValueError:
        return {}
    if not isinstance(body, dict):
        return {}
    detail = body.get("detail")
    if isinstance(detail, dict):
        merged = dict(detail)
        merged.setdefault("message", detail.get("error") or "")
        return merged
    if detail is not None:
        body.setdefault("message", detail)
    return body


def _download(url: str, dst: str, *, base_url: str, timeout: float) -> str:
    """流式下载图片到 dst（4xx 视为永久失败直接抛错，5xx/瞬断由重试层处理）。"""
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    resp = _request("GET", url, base_url=base_url, timeout=timeout, stream=True)
    if resp.status_code >= 400:
        resp.close()
        raise RuntimeError(f"下载失败 HTTP {resp.status_code}: {url}")
    with open(dst, "wb") as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)
    return dst


def _materialize(item: dict, output_dir: str, index: int, *, base_url: str, timeout: float) -> str:
    """把服务端返回的一条结果落盘为 output_dir/output_{index}.{ext}，返回本地路径。"""
    if not isinstance(item, dict):
        return ""
    # 1) 本机绝对路径（服务与调用方同机时才可用）
    raw_path = item.get("path") or item.get("image_path") or ""
    if raw_path and os.path.isfile(raw_path):
        dst = os.path.join(output_dir, f"output_{index}.{_ext_of(raw_path, item.get('file_name'))}")
        if os.path.abspath(raw_path) != os.path.abspath(dst):
            shutil.copyfile(raw_path, dst)
        return dst
    # 2) 相对 url → GET /files/{file_name}
    url = item.get("url") or ""
    if url:
        full = url if str(url).startswith("http") else f"{base_url}/{str(url).lstrip('/')}"
        dst = os.path.join(output_dir, f"output_{index}.{_ext_of(urlparse(full).path)}")
        _download(full, dst, base_url=base_url, timeout=timeout)
        return dst
    # 3) b64_json
    b64 = item.get("b64_json")
    if b64:
        raw = base64.b64decode(b64)
        dst = os.path.join(output_dir, f"output_{index}.{_guess_ext_from_bytes(raw)}")
        with open(dst, "wb") as f:
            f.write(raw)
        return dst
    return ""


def _drain_hint(base_url: str, timeout: float = 10.0) -> str:
    """取队列处理提示词（失败返回空串）；用于超时报错时告诉用户怎么让 Desktop 排空队列。"""
    try:
        resp = _request("GET", f"{base_url}{JOBS_ENDPOINT}", base_url=base_url, timeout=timeout)
        if resp.status_code == 200:
            return str((resp.json() or {}).get("drain_hint") or "")
    except Exception:  # noqa: BLE001
        pass
    return ""


def _poll_job(job_id: str, *, base_url: str, timeout: float, poll_interval: float,
              poll_timeout: float, headers: dict) -> list:
    """轮询 ``GET /v1/images/jobs/{job_id}`` 直到终态，返回结果条目列表。

    首次查询**不等待**：同步等待超时（504）时任务往往刚好完成，可直接命中，
    避免无谓等待一个轮询周期。
    """
    interval = max(0.5, float(poll_interval or DEFAULT_POLL_INTERVAL))
    deadline = time.time() + max(1.0, float(poll_timeout or DEFAULT_POLL_TIMEOUT))
    not_found = 0
    first = True
    while time.time() < deadline:
        if not first:
            time.sleep(interval)
        first = False
        resp = _request(
            "GET", f"{base_url}{JOBS_ENDPOINT}/{job_id}",
            base_url=base_url, timeout=min(60.0, timeout), headers=headers,
        )
        if resp.status_code == 404:
            # 服务端只在 done/failed 命中；Desktop Agent 正在移动文件时可能两边都查不到
            not_found += 1
            if not_found >= _MAX_NOT_FOUND_STREAK:
                raise RuntimeError(f"MiMo Desktop: 任务不存在或已被清理 job_id={job_id}")
            logger.warning("MiMo Desktop: 任务暂未命中(%d/%d) job_id=%s",
                           not_found, _MAX_NOT_FOUND_STREAK, job_id)
            continue
        if resp.status_code != 200:
            logger.warning("MiMo Desktop: 任务查询异常 %s job_id=%s", resp.status_code, job_id)
            continue
        not_found = 0
        data = _payload_of(resp)
        status = str(data.get("status") or "").lower()
        if status == "done":
            image_path = data.get("image_path") or data.get("path") or ""
            if not image_path:
                logger.warning("MiMo Desktop: 任务已完成但未返回 image_path job_id=%s", job_id)
                return []
            return [{"path": image_path}]
        if status == "failed":
            raise RuntimeError(f"MiMo Desktop: 任务失败 job_id={job_id} error={data.get('error')}")
    hint = _drain_hint(base_url)
    raise TimeoutError(
        f"MiMo Desktop: 任务轮询超时(>{poll_timeout}s) job_id={job_id}"
        + (f"。{hint}" if hint else "")
    )


def _generate_once(payload: dict, endpoint: str, *, base_url: str, timeout: float,
                   headers: dict, poll_interval: float, poll_timeout: float) -> list:
    """提交一次生图/改图请求（同步等待 + 504 兜底轮询），返回结果条目列表。"""
    resp = _request(
        "POST", f"{base_url}{endpoint}",
        base_url=base_url, timeout=timeout + 30, headers=headers, json=payload,
    )

    if resp.status_code == 504:
        # 同步等待超时：任务已入队，按响应里的 job_id 继续轮询
        # （注意服务端 FastAPI 会把它放在 detail 里，_payload_of 已兼容两种结构）
        info = _payload_of(resp)
        job_id = info.get("job_id") or ""
        if not job_id:
            raise TimeoutError(
                "MiMo Desktop: 同步等待超时，且响应未返回 job_id。"
                "请在 MiMo Desktop 中要求「处理生图队列」。"
                + (f" {info.get('drain_hint')}" if info.get("drain_hint") else "")
            )
        logger.warning("MiMo Desktop: 同步等待超时，改为轮询 job_id=%s", job_id)
        return _poll_job(
            job_id, base_url=base_url, timeout=timeout,
            poll_interval=poll_interval, poll_timeout=poll_timeout, headers=headers,
        )

    if resp.status_code != 200:
        info = _payload_of(resp)
        detail = info.get("error") or info.get("message") or (resp.text or "")[:300]
        # 502 = Desktop 出图失败 / 结果文件丢失；400 = 参数或源图不合法
        raise RuntimeError(
            f"MiMo Desktop: HTTP {resp.status_code} {detail}"
            + (f" (job_id={info['job_id']})" if info.get("job_id") else "")
        )

    body = _payload_of(resp)
    if not body:
        raise RuntimeError(f"MiMo Desktop: 响应不是合法 JSON: {(resp.text or '')[:200]}")

    if body.get("data"):
        return list(body.get("data") or [])

    status = str(body.get("status") or "").lower()
    if status == "done":
        return list(body.get("data") or [])
    job_id = body.get("job_id") or ""
    if job_id:
        if status and status != "pending":
            logger.warning("MiMo Desktop: 非预期状态 %s，仍按 job_id 轮询", status)
        return _poll_job(
            job_id, base_url=base_url, timeout=timeout,
            poll_interval=poll_interval, poll_timeout=poll_timeout, headers=headers,
        )
    raise RuntimeError(f"MiMo Desktop: 响应中既无 data 也无 job_id: {str(body)[:200]}")


def _build_headers(api_key: str) -> dict:
    """JSON 请求头（中文 prompt 必须 UTF-8）；服务端启用网关密钥时带 Bearer。"""
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _resolve_ref_image(ref: str, output_dir: str, *, base_url: str, timeout: float) -> str:
    """把参考图统一成服务进程可读的本地绝对路径（http(s) 先下载到本地）。"""
    if not isinstance(ref, str) or not ref.strip():
        return ""
    ref = ref.strip()
    if ref.startswith("http"):
        ref_dir = os.path.join(output_dir, "_refs")
        dst = os.path.join(ref_dir, f"ref_{abs(hash(ref)) % (10 ** 10)}.{_ext_of(urlparse(ref).path)}")
        if not os.path.isfile(dst):
            _download(ref, dst, base_url=base_url, timeout=timeout)
        return os.path.abspath(dst)
    if not os.path.isfile(ref):
        logger.warning("MiMo Desktop: 参考图不存在，已忽略: %s", ref)
        return ""
    return os.path.abspath(ref)


# ── 工厂入口 ─────────────────────────────────────────────────────────────────
def generate(prompt, output_dir, model="", negative_prompt="", resolution="1K",
             aspect_ratio="1:1", num_images=1, ref_images=None, api_key="",
             mode="txt2img", **kwargs):
    """MiMo Desktop 反代生图统一入口（供 imagegen 工厂调用）。

    Args:
        prompt: 文本提示词（中英文均可）
        output_dir: 落盘目录
        model: ``desktop/image_gen``（生图）或 ``desktop/image_edit``（改图）；服务端仅作兼容字段
        negative_prompt: 负向提示词（服务端不支持，忽略）
        resolution: 分辨率档位 ``1K`` / ``2K`` / ``4K``（或 ``auto`` 交服务端默认）
        aspect_ratio: 宽高比（如 ``16:9``），换算进 size 的像素维度（服务端无独立参数）
        num_images: 期望张数（服务端 n 仅支持 1 → 串行多次调用，上限 4）
        ref_images: 参考图（本地路径 / http(s) URL）；存在时走改图接口
        api_key: 网关密钥（当前服务端未启用，留空即可；也可用接口配置的 SDK API Key）
        mode: ``txt2img`` / ``img2img``（``img2img`` 或带参考图 → 走 /v1/images/edits）
        **kwargs: base_url / quality / output_format / background / timeout /
                  poll_interval / poll_timeout（由接口 sdk_extra_args 透传）

    Returns:
        本地文件路径列表（均落在 output_dir 下）；失败返回空列表。
    """
    base_url = _get_base_url(kwargs.get("base_url", ""))
    quality = str(kwargs.get("quality") or DEFAULT_QUALITY).strip().lower()
    if quality not in QUALITY_OPTIONS:
        quality = DEFAULT_QUALITY
    output_format = str(kwargs.get("output_format") or DEFAULT_OUTPUT_FORMAT).strip().lower()
    background = str(kwargs.get("background") or DEFAULT_BACKGROUND).strip().lower()
    timeout = float(kwargs.get("timeout") or DEFAULT_TIMEOUT)
    poll_interval = float(kwargs.get("poll_interval") or DEFAULT_POLL_INTERVAL)
    poll_timeout = float(kwargs.get("poll_timeout") or DEFAULT_POLL_TIMEOUT)

    ref_images = [r for r in (ref_images or []) if r]
    model = (model or "").strip()
    use_edit = bool(ref_images) or str(mode or "").lower() in ("img2img", "edit", "fusion") \
        or model == EDIT_MODEL
    endpoint = EDIT_ENDPOINT if use_edit else GEN_ENDPOINT

    try:
        os.makedirs(output_dir, exist_ok=True)
        refs: list = []

        if use_edit:
            if not ref_images:
                logger.error("MiMo Desktop: 改图模式未提供参考图（服务端要求至少一张源图）")
                return []
            refs = [p for p in (
                _resolve_ref_image(r, output_dir, base_url=base_url, timeout=timeout)
                for r in ref_images
            ) if p]
            if not refs:
                logger.error("MiMo Desktop: 参考图全部无效，无法改图")
                return []

        headers = _build_headers(api_key)
        count = max(1, min(int(num_images or 1), MAX_IMAGES))

        payload = {
            "prompt": prompt,
            "n": 1,
            "quality": quality,
            "output_format": output_format,
            "wait": True,
            "timeout": timeout,
        }
        if background:
            payload["background"] = background
        if model:
            payload["model"] = model
        size = _resolve_size(resolution, aspect_ratio)
        if size:
            payload["size"] = size
        if use_edit:
            payload["image"] = refs[0] if len(refs) == 1 else refs

        logger.info(
            "MiMo Desktop: %s base=%s size=%s quality=%s refs=%d n=%d",
            "改图" if use_edit else "生图", base_url, size or "auto", quality, len(ref_images), count,
        )

        saved = []
        for _ in range(count):
            items = _generate_once(
                dict(payload), endpoint,
                base_url=base_url, timeout=timeout, headers=headers,
                poll_interval=poll_interval, poll_timeout=poll_timeout,
            )
            if not items:
                logger.warning("MiMo Desktop: 本次请求未返回图片，停止后续请求")
                break
            for item in items:
                path = _materialize(
                    item, output_dir, len(saved), base_url=base_url, timeout=timeout,
                )
                if path:
                    saved.append(path)
        return saved

    except Exception as e:  # noqa: BLE001
        logger.error("MiMo Desktop: 生图失败: %s", e)
        import traceback
        traceback.print_exc()
        return []


# ── 辅助能力（供接口设置页/节点使用）──────────────────────────────────────────
def health(base_url="", api_key="", **kwargs) -> dict:
    """查询反代服务健康状态（``status=ok`` 仅表示服务在跑，不代表队列已排空）。"""
    base = _get_base_url(base_url)
    try:
        resp = _request("GET", f"{base}{HEALTH_ENDPOINT}", base_url=base, timeout=15,
                        headers=_build_headers(api_key))
        if resp.status_code != 200:
            return {"status": "error", "http_status": resp.status_code, "text": resp.text[:200]}
        return resp.json() or {}
    except Exception as e:  # noqa: BLE001
        logger.warning("MiMo Desktop: 健康检查失败: %s", e)
        return {"status": "error", "error": str(e), "base_url": base}


def list_models(api_key="", base_url="", **kwargs):
    """返回可用模型（优先读服务 ``/v1/models``，失败回退内置列表）。"""
    base = _get_base_url(base_url)
    try:
        resp = _request("GET", f"{base}{MODELS_ENDPOINT}", base_url=base, timeout=15,
                        headers=_build_headers(api_key))
        if resp.status_code == 200:
            data = (resp.json() or {}).get("data") or []
            models = [d.get("id") for d in data if isinstance(d, dict) and d.get("id")]
            if models:
                return models
    except Exception as e:  # noqa: BLE001
        logger.warning("MiMo Desktop: 拉取模型列表失败（回退内置列表）: %s", e)
    return list(MODEL_OPTIONS)
