#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agnes AI 生图接口封装（云端类型，OpenAI Images 兼容）。

对接 Agnes AI 的图像生成端点：

  * 生图/改图 ``POST /v1/images/generations``
      - 必填：``model``、``prompt``
      - 可选：``size``（如 ``1024x768``）、``n``、
        ``extra_body.image``（图生图输入图 URL 数组）、
        ``extra_body.response_format``（``url`` 返回图片 URL）
  * 鉴权：``Authorization: Bearer <API Key>``
  * 服务基址：``https://apihub.agnes-ai.com``（可用 ``AGNES_BASE_URL`` 覆盖）

本模块是 imagegen 工厂约定的 ``sdk_function`` 入口：``generate(...)`` 返回本地文件路径列表。

密钥取值优先级（从高到低）：

  1. 接口配置里显式填写的 ``sdk_api_key``（由工厂注入，可填 ``secret://AGNES_API_KEY`` 引用）；
  2. 系统环境变量 ``AGNES_API_KEY``（兼容 ``AGNES_API_TOKEN`` / ``APIHUB_AGNES_API_KEY``）；
  3. 项目密钥管理器（control-plane ``cp_credentials``）中的 ``AGNES_API_KEY``。

约束与处理：

  * 参考图（img2img）要求**URL**，本地路径无法被远端读取 → 自动转成 base64 data URI
    提交；``http(s)`` 链接原样透传。
  * Agnes 图像端点未声明 ``n`` 的多图语义，保守起见固定 ``n=1``，
    ``num_images>1`` 时按张串行多次请求（上限 ``MAX_IMAGES``）。
  * 图像端点未声明负向提示词字段，默认**不下发** ``negative_prompt``；
    如需尝试，可在接口 ``custom_params`` 里配 ``negative_field`` 指定字段名。
  * 宽高比服务端无独立参数，统一换算进 ``size``（16 的倍数）。

云端标识：模块级 ``CLOUD = True`` —— 生图算力在 Agnes 服务端，不占本机 GPU；
调度层据此按「云端接口」处理、免 gpu 令牌（与 TTS/ASR 引擎的 CLOUD 标记一致）。
"""
import os
import math
import base64
import logging
from urllib.parse import urlparse

from backend.imagegen.imagegen_retry import request_with_retry, download_with_retry

logger = logging.getLogger(__name__)

# 云端接口标识：不占本机 GPU（详见模块 docstring）。
CLOUD = True

# ── 服务端约定 ────────────────────────────────────────────────────────────────
DEFAULT_BASE_URL = "https://apihub.agnes-ai.com"
GEN_ENDPOINT = "/v1/images/generations"

# 内置模型（当前仅一个对外模型；后续新增模型在此登记并同步接口配置）
MODEL_OPTIONS = ["agnes-image-2.5-flash"]
DEFAULT_MODEL = MODEL_OPTIONS[0]

# 密钥名：环境变量与项目密钥管理器共用
API_KEY_ENV = "AGNES_API_KEY"
# 兼容的环境变量别名（按顺序尝试）
API_KEY_ENV_ALIASES = ("AGNES_API_KEY", "AGNES_API_TOKEN", "APIHUB_AGNES_API_KEY")

# ── 参数默认值与约束 ─────────────────────────────────────────────────────────
RESOLUTION_BASE = {"1K": 1024, "2K": 2048, "4K": 4096}
_SIZE_ALIGN = 16                  # 尺寸对齐步长
DEFAULT_SIZE = ""# 为空表示不下发 size，用服务端默认
DEFAULT_TIMEOUT = 180             # 单次请求超时（秒）
DEFAULT_RESPONSE_FORMAT = "url"   # 显式要求返回 URL（避免部分网关默认返回 b64）
MAX_IMAGES = 4                    # num_images 串行次数上限
_IMAGE_EXTS = ("png", "jpg", "jpeg", "webp", "gif")
_MIME_BY_EXT = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}


# ── 基础工具 ─────────────────────────────────────────────────────────────────
def _get_base_url(base_url: str = "") -> str:
    """服务基址：参数 > 环境变量 ``AGNES_BASE_URL`` > 默认公网地址。"""
    return (
        (base_url or "").strip()
        or (os.environ.get("AGNES_BASE_URL", "") or "").strip()
        or DEFAULT_BASE_URL
    ).rstrip("/")


def _get_api_key(api_key: str = "") -> str:
    """API Key 取值优先级：显式参数 > 系统环境变量 > 项目密钥管理器。

    显式参数来自接口配置的 ``sdk_api_key``（工厂注入，可能是 ``secret://AGNES_API_KEY``
    已解析的明文）；环境变量优先于密钥管理器，便于部署机直接注入而不落库。
    """
    if api_key and str(api_key).strip():
        return str(api_key).strip()

    for name in API_KEY_ENV_ALIASES:
        value = (os.environ.get(name, "") or "").strip()
        if value:
            return value

    # 回落项目密钥管理器（control-plane cp_credentials）
    try:
        from backend.config.credential_store import get_raw

        value = (get_raw(API_KEY_ENV) or "").strip()
        if value:
            return value
    except Exception as e:  # noqa: BLE001
        logger.warning("Agnes: 读取密钥管理器中的 %s 失败: %s", API_KEY_ENV, e)
    return ""


def _build_headers(api_key: str) -> dict:
    """JSON 请求头（中文 prompt 必须 UTF-8）。"""
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _ext_of(*candidates) -> str:
    """从文件名/路径/URL 中取图片扩展名，取不到按 png。"""
    for value in candidates:
        if not value:
            continue
        suffix = os.path.splitext(str(value).split("?")[0])[1].lstrip(".").lower()
        if suffix in _IMAGE_EXTS:
            return "jpg" if suffix == "jpeg" else suffix
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
    """解析 ``a:b`` 为 (a, b)，非法回退 (1, 1)。"""
    text = str(aspect_ratio or "").strip()
    if not text or text.lower() == "auto" or ":" not in text:
        return (1, 1)
    try:
        a, b = text.split(":")
        a, b = int(a), int(b)
        if a <= 0 or b <= 0:
            return (1, 1)
        return (a, b)
    except Exception:  # noqa: BLE001
        return (1, 1)


def _resolve_size(resolution: str, aspect_ratio: str) -> str:
    """把（分辨率档位 + 宽高比）换算为 ``宽x高``；返回空串表示不下发 size。

    服务端无 aspect_ratio 参数，宽高比只能通过像素尺寸表达；同时按 16 对齐，
    避免触发部分模型对尺寸的整除校验。
    """
    res = str(resolution or "").strip().upper()
    if not res or res == "AUTO":
        return ""
    base = RESOLUTION_BASE.get(res)
    if not base:
        if res.isdigit():          # 兼容直接传基准边长
            base = int(res)
        else:
            logger.warning("Agnes: 无法识别的分辨率档位 %s，改用服务端默认尺寸", resolution)
            return ""

    a, b = _parse_ratio(aspect_ratio)
    ratio = a / b
    w = base * math.sqrt(ratio)
    h = base / math.sqrt(ratio)
    w = max(_SIZE_ALIGN, int(math.ceil(w / _SIZE_ALIGN)) * _SIZE_ALIGN)
    h = max(_SIZE_ALIGN, int(math.ceil(h / _SIZE_ALIGN)) * _SIZE_ALIGN)
    return f"{w}x{h}"


def _ref_to_remote(ref: str) -> str:
    """把参考图转换为远端可读的形式。

    * ``http(s)`` 链接：原样透传；
    * 本地文件：转成 base64 data URI（服务端只接受 URL，不接受本机路径）；
    * data URI：原样透传。
    """
    text = str(ref or "").strip()
    if not text:
        return ""
    if text.startswith("http") or text.startswith("data:"):
        return text
    if not os.path.isfile(text):
        logger.warning("Agnes: 参考图不存在，已忽略: %s", text)
        return ""
    ext = _ext_of(text)
    mime = _MIME_BY_EXT.get(ext, "image/png")
    with open(text, "rb") as f:
        payload = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def _collect_items(data) -> list:
    """从 JSON 响应中提取 (kind, payload) 列表。

    kind 为 ``url`` 或 ``b64``；兼容 OpenAI 风格的 ``data[].url|b64_json``、
    以及部分网关的 ``images[]`` / ``results[]`` 嵌套。
    """
    if not isinstance(data, dict):
        return []
    items = []
    for key in ("data", "images", "results"):
        arr = data.get(key)
        if not isinstance(arr, list):
            continue
        for item in arr:
            if isinstance(item, str):
                items.append(("url", item))
            elif isinstance(item, dict):
                url = item.get("url") or item.get("image_url") or ""
                b64 = item.get("b64_json") or item.get("image_base64") or ""
                if url:
                    items.append(("url", url))
                elif b64:
                    items.append(("b64", b64))
        if items:
            break
    return items


def _error_detail(resp) -> str:
    """从错误响应里取出可读原因（兼容 OpenAI error 包装与服务端自定义结构）。"""
    text = (resp.text or "")[:300]
    try:
        body = resp.json()
    except ValueError:
        return text
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("code") or err)[:300]
        if err:
            return str(err)[:300]
        for key in ("message", "detail", "msg"):
            if body.get(key):
                return str(body[key])[:300]
    return text


def _save_items(resp, output_dir: str, start_index: int) -> list:
    """把一条响应里的图片落盘为 ``output_{i}.{ext}``，返回新增的本地路径列表。"""
    saved = []
    items = _collect_items(resp.json())
    for kind, payload in items:
        index = start_index + len(saved)
        try:
            if kind == "url":
                ext = _ext_of(urlparse(payload).path)
                dst = os.path.join(output_dir, f"output_{index}.{ext}")
                download_with_retry(payload, dst, timeout=120)
            else:
                raw = base64.b64decode(payload)
                dst = os.path.join(output_dir, f"output_{index}.{_guess_ext_from_bytes(raw)}")
                with open(dst, "wb") as f:
                    f.write(raw)
            saved.append(dst)
        except Exception as e:  # noqa: BLE001
            logger.error("Agnes: 保存第 %d 张图失败: %s", index, e)
    return saved


# ── 工厂入口 ─────────────────────────────────────────────────────────────────
def generate(prompt, output_dir, model="", negative_prompt="", resolution="1K",
             aspect_ratio="1:1", num_images=1, ref_images=None, api_key="",
             mode="txt2img", **kwargs):
    """Agnes AI 生图统一入口（供 imagegen 工厂调用）。

    Args:
        prompt: 文本提示词（建议英文，稳定性更好）
        output_dir: 落盘目录
        model: 模型名，默认 ``agnes-image-2.5-flash``
        negative_prompt: 负向提示词（服务端未声明该字段，默认不下发）
        resolution: 分辨率档位 ``1K`` / ``2K`` / ``4K``（或 ``auto`` 用服务端默认）
        aspect_ratio: 宽高比（如 ``16:9``），换算进 size 的像素维度
        num_images: 期望张数（固定 ``n=1`` 串行多次调用，上限 4）
        ref_images: 参考图列表（本地路径 / http(s) URL / data URI）
        api_key: 接口配置的密钥；为空时按环境变量 → 密钥管理器回落
        mode: ``txt2img`` / ``img2img``（仅用于日志与参考图分支判断）
        **kwargs: base_url / size / timeout / negative_field
                  （由接口 ``custom_params`` / ``sdk_extra_args`` 透传）

    Returns:
        本地文件路径列表（均落在 output_dir 下）；失败返回空列表。
    """
    base_url = _get_base_url(kwargs.get("base_url", ""))
    timeout = float(kwargs.get("timeout") or DEFAULT_TIMEOUT)
    negative_field = str(kwargs.get("negative_field") or "").strip()

    key = _get_api_key(api_key)
    if not key:
        logger.error(
            "Agnes: 未配置 API Key。请设置环境变量 %s，"
            "或在项目密钥管理器中添加同名密钥，或在接口设置里填写 API Key。",
            API_KEY_ENV,
        )
        return []

    ref_images = [r for r in (ref_images or []) if r]
    model = (model or "").strip() or DEFAULT_MODEL
    count = max(1, min(int(num_images or 1), MAX_IMAGES))

    size = str(kwargs.get("size") or "").strip() or _resolve_size(resolution, aspect_ratio)

    payload = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "extra_body": {"response_format": DEFAULT_RESPONSE_FORMAT},
    }
    if size:
        payload["size"] = size
    if negative_prompt and negative_field:
        payload["extra_body"][negative_field] = negative_prompt
    elif negative_prompt:
        logger.debug("Agnes: 服务端未声明负向提示词字段，已忽略 negative_prompt")

    if ref_images:
        refs = [u for u in (_ref_to_remote(r) for r in ref_images) if u]
        if not refs:
            logger.error("Agnes: 参考图全部无效，无法图生图")
            return []
        payload["extra_body"]["image"] = refs

    url = f"{base_url}{GEN_ENDPOINT}"
    headers = _build_headers(key)

    logger.info(
        "Agnes: 生图 model=%s size=%s refs=%d n=%d base=%s",
        model, size or "auto", len(ref_images), count, base_url,
    )

    try:
        os.makedirs(output_dir, exist_ok=True)
        saved = []
        for _ in range(count):
            resp = request_with_retry("POST", url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code != 200:
                logger.error(
                    "Agnes: 生图失败 HTTP %s %s", resp.status_code, _error_detail(resp),
                )
                break
            before = len(saved)
            saved.extend(_save_items(resp, output_dir, before))
            if len(saved) == before:
                logger.warning("Agnes: 本次请求未返回图片，停止后续请求")
                break
        return saved
    except Exception as e:  # noqa: BLE001
        logger.error("Agnes: 生图异常: %s", e)
        import traceback
        traceback.print_exc()
        return []


# ── 辅助能力（供接口设置页/节点使用）──────────────────────────────────────────
def list_models(api_key: str = "", **kwargs) -> list:
    """返回可用模型列表。

    Agnes 图像端点未提供模型列举接口，故返回内置清单（与接口配置保持一致）。
    """
    return list(MODEL_OPTIONS)


def health(api_key: str = "", **kwargs) -> dict:
    """轻量探活：检查密钥是否可用配置（不发起生图，避免产生费用）。"""
    key = _get_api_key(api_key)
    return {
        "status": "ok" if key else "error",
        "base_url": _get_base_url(kwargs.get("base_url", "")),
        "model": DEFAULT_MODEL,
        "api_key_configured": bool(key),
    }