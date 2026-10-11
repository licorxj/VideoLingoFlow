#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agnes AI 生视频接口封装（OpenAI Videos 兼容，异步任务）。

对接 Agnes Video 2.5 / 2.5 Flash（默认 ``agnes-video-2.5-flash``）：

  * 创建任务 ``POST {base}/videos``      （base 形如 ``https://apihub.agnes-ai.com/v1``）
      - 必填：``model``、``prompt``、``mode``（``text`` / ``keyframe`` / ``reference``）
      - 常用：``seconds``（字符串 "4"–"12"，默认 5）、``size``、``aspect_ratio``、``seed``、``n``（固定 1）
      - keyframe：``first_frame`` / ``last_frame``
      - reference：``images[]`` / ``audios[]``（Flash 不支持 ``videos``）
  * 查询任务 ``GET {站点根}/agnesapi?video_id=<VIDEO_ID>&model_name=<MODEL>``
    （注意查询走站点根路径，**不带 ``/v1``**；``keyframe`` / ``reference`` 必须带 ``model_name``）
  * 鉴权：``Authorization: Bearer <API Key>``

本模块是 videogen 工厂约定的 ``sdk_function`` 入口：``generate(...)`` 返回本地文件路径列表。

密钥取值优先级（从高到低）：

  1. 接口配置显式填写的 ``sdk_api_key``（工厂注入，可填 ``secret://AGNES_API_KEY`` 引用）；
  2. 系统环境变量 ``AGNES_API_KEY``（兼容 ``AGNES_API_TOKEN`` / ``APIHUB_AGNES_API_KEY``）；
  3. 项目密钥管理器（control-plane ``cp_credentials``）中的 ``AGNES_API_KEY``。

约束与处理：

  * Flash 专属限制：``size`` 仅 ``720P``、``images`` ≤ 5、``audios`` ≤ 3、不支持 ``videos``。
    非 720P 会被强制改写为 720P；超限素材截断并告警；传入参考视频直接报错并提示改用
    ``agnes-video-2.5``（Flash 会返回 400）。
  * 服务端要求媒体 URL **可公网访问**，而桌面端素材多为本地文件，故按下述顺序处理：
    1. ``http(s)`` 链接 / data URI：原样透传；
    2. 配了 ``upload_endpoint``（自定义上传网关）→ multipart 上传换公开 URL；
    3. 否则按 ``media_fallback`` 兜底，默认 ``data_uri``：**base64 内联提交**
       （与 Agnes 生图接口一致）。图片超过 3MB 会先等比压缩（最长边 1536、无 alpha 转 JPEG），
       内联 payload 上限 12MB；音频/视频不做压缩，超限直接报错并提示改用公网 URL。
    可选：``media_fallback=error`` 强制走上传网关/公网 URL，``ignore`` 静默丢弃本地素材。
  * ``n`` 固定 1，``num_videos>1`` 时串行多次创建任务（上限 ``MAX_VIDEOS``）。
  * 服务端无负向提示词与音频开关字段：``negative_prompt`` / ``audio`` 忽略（仅日志）。
  * 轮询遇到 ``429`` 退避重试（创建任务同理），``503`` 亦重试。
"""
import os
import re
import time
import base64
import logging
from urllib.parse import urlparse

from backend.imagegen.imagegen_retry import request_with_retry, download_with_retry

logger = logging.getLogger(__name__)

# ── 服务端约定 ────────────────────────────────────────────────────────────────
DEFAULT_BASE_URL = "https://apihub.agnes-ai.com/v1"
CREATE_ENDPOINT = "/videos"
QUERY_PATH = "/agnesapi"          # 查询走站点根路径（不带 /v1）

# 内置模型（Flash 限时免费；需要非 Flash 时把接口默认模型改成agnes-video-2.5）
FLASH_MODEL = "agnes-video-2.5-flash"
MODEL_OPTIONS = [FLASH_MODEL]
DEFAULT_MODEL = FLASH_MODEL

# 密钥名：环境变量与项目密钥管理器共用
API_KEY_ENV = "AGNES_API_KEY"
API_KEY_ENV_ALIASES = ("AGNES_API_KEY", "AGNES_API_TOKEN", "APIHUB_AGNES_API_KEY")

# ── 参数默认值与约束 ─────────────────────────────────────────────────────────
DEFAULT_SIZE = "720P"              # Flash 仅支持 720P
SIZE_OPTIONS = ("720P",)
ASPECT_RATIOS = ("21:9", "16:9", "4:3", "1:1", "3:4", "9:16")
SECONDS_MIN, SECONDS_MAX, SECONDS_DEFAULT = 4, 12, 5

# Flash 专属上限
FLASH_MAX_IMAGES = 5
FLASH_MAX_AUDIOS = 3

DEFAULT_TIMEOUT = 180# 单次 HTTP 请求超时（秒）
DEFAULT_POLL_INTERVAL = 3.0         # 轮询间隔（文档建议 1–2s，本项目默认 3s 降低限流风险）
DEFAULT_POLL_TIMEOUT = 1800         # 轮询总时长（秒）
MAX_VIDEOS = 3                     # num_videos 串行创建任务次数上限
RETRY_BACKOFF_CAP = 30.0           # 429/503 退避上限（秒）

# 本地素材兜底策略（Agnes 要求媒体 URL 可公网访问，但桌面端素材多为本地文件）：
# 默认与 Agnes 生图接口对齐用 base64 data URI 提交，开箱即用；
# 若服务端不接受内联数据，可改error（强制走 upload_endpoint/公网 URL）或 ignore。
DEFAULT_MEDIA_FALLBACK = "data_uri"
FALLBACK_OPTIONS = ("data_uri", "error", "ignore")

# data URI 内联约束：图片超阈值先压缩；内联 payload 上限（base64 后）
INLINE_IMAGE_COMPRESS_BYTES = 3 * 1024 * 1024   # 图片大于此值先等比压缩
INLINE_IMAGE_MAX_SIDE = 1536                     # 压缩后的最长边
INLINE_MAX_BYTES = 12 * 1024 * 1024              # data URI 上限（含 base64 膨胀约 4/3）

_VIDEO_EXTS = ("mp4", "webm", "mov", "mkv")
_IMAGE_EXTS = ("png", "jpg", "jpeg", "webp", "gif", "bmp")
_AUDIO_EXTS = ("mp3", "wav", "m4a", "aac", "flac", "ogg")
_MIME_BY_EXT = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "webp": "image/webp", "gif": "image/gif", "bmp": "image/bmp",
    "mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime",
    "mkv": "video/x-matroska",
    "mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4",
    "aac": "audio/aac", "flac": "audio/flac", "ogg": "audio/ogg",
}
# 上传网关响应里可能出现的 URL 字段名
_UPLOAD_URL_KEYS = ("url", "public_url", "download_url", "file_url", "src", "link")
# 素材类型 → 中文标签（日志与提示文案）
_KIND_LABEL = {"image": "图片", "audio": "音频", "video": "视频"}


# ── 基础工具 ─────────────────────────────────────────────────────────────────
def _get_base_url(base_url: str = "") -> str:
    """服务基址：参数 > 环境变量 ``AGNES_BASE_URL`` > 默认 ``.../v1``。"""
    return (
        (base_url or "").strip()
        or (os.environ.get("AGNES_BASE_URL", "") or "").strip()
        or DEFAULT_BASE_URL
    ).rstrip("/")


def _site_base(api_base: str) -> str:
    """把 API 基址还原为站点根地址（查询端点 ``/agnesapi`` 不带 ``/v1``）。

    ``https://apihub.agnes-ai.com/v1`` → ``https://apihub.agnes-ai.com``
    """
    base = _get_base_url(api_base)
    for suffix in ("/v1", "/V1"):
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


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
    """从路径/URL 中取扩展名，取不到按 ``mp4``（视频）/ ``png``（图片）。"""
    for value in candidates:
        if not value:
            continue
        suffix = os.path.splitext(str(value).split("?")[0])[1].lstrip(".").lower()
        if suffix in _VIDEO_EXTS or suffix in _IMAGE_EXTS or suffix in _AUDIO_EXTS:
            return suffix
    return ""


def _is_url_like(text: str) -> bool:
    return str(text).startswith(("http://", "https://", "data:"))


def _upload_media(path: str, upload_endpoint: str, api_key: str, timeout: float) -> str:
    """把本地文件上传到自定义上传网关，返回公开可访问 URL。"""
    filename = os.path.basename(path)
    with open(path, "rb") as f:
        files = {"file": (filename, f, _MIME_BY_EXT.get(_ext_of(path) or "png", "application/octet-stream"))}
    resp = request_with_retry("POST", upload_endpoint, files=files, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"Agnes: 上传 {filename} 失败 HTTP {resp.status_code} {resp.text[:200]}")
    try:
        body = resp.json()
    except ValueError:
        raise RuntimeError("Agnes: 上传网关未返回 JSON，无法解析媒体 URL")
    data = body.get("data") if isinstance(body, dict) else None
    for holder in (body, data) if isinstance(data, dict) else (body,):
        if not isinstance(holder, dict):
            continue
        for key in _UPLOAD_URL_KEYS:
            value = holder.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
    raise RuntimeError(f"Agnes: 上传网关响应中没有可用 URL 字段: {str(body)[:200]}")


def _compress_image(path: str):
    """等比压缩图片以控制 data URI 体积。

    返回 ``(raw_bytes, mime)``；Pillow 不可用或压缩失败时返回 ``None``（调用方回落原文件）。

    * 无 alpha 通道 → 转JPEG（体积最小，视频参考场景无透明需求）
    * 含 alpha 通道 → 缩放后保持 PNG，避免透明区变黑
    """
    try:
        from io import BytesIO
        from PIL import Image
    except Exception:  # noqa: BLE001
        return None

    try:
        with Image.open(path) as im:
            im.load()
            has_alpha = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
            if max(im.size) > INLINE_IMAGE_MAX_SIDE:
                ratio = INLINE_IMAGE_MAX_SIDE / max(im.size)
                im = im.resize((max(1, int(im.width * ratio)), max(1, int(im.height * ratio))),
                               Image.LANCZOS)
            buf = BytesIO()
            if has_alpha:
                im.convert("RGBA").save(buf, format="PNG", optimize=True)
                return buf.getvalue(), "image/png"
            im.convert("RGB").save(buf, format="JPEG", quality=88)
            return buf.getvalue(), "image/jpeg"
    except Exception as e:  # noqa: BLE001
        logger.warning("Agnes: 压缩参考图失败，将使用原文件: %s (%s)", path, e)
        return None


def _to_data_uri(path: str, kind: str = "image") -> str:
    """本地文件转 base64 data URI（``media_fallback=data_uri`` 时使用）。

    图片超过阈值先等比压缩；音频/视频不做处理，仅做体积上限校验（超限直接报错，
    因为内联几十 MB 音视频既不现实也会被服务端拒绝）。
    """
    ext = _ext_of(path) or "png"
    raw = None
    mime = _MIME_BY_EXT.get(ext, "application/octet-stream")

    if kind == "image":
        size = os.path.getsize(path)
        if size > INLINE_IMAGE_COMPRESS_BYTES:
            compressed = _compress_image(path)
            if compressed:
                raw, mime = compressed
                logger.info("Agnes: 参考图 %s 由 %.1fMB 压缩至 %.1fMB 后内联",
                            os.path.basename(path), size / 1048576, len(raw) / 1048576)

    if raw is None:
        with open(path, "rb") as f:
            raw = f.read()

    payload = base64.b64encode(raw)
    if len(payload) > INLINE_MAX_BYTES:
        raise RuntimeError(
            f"Agnes: 参考{_KIND_LABEL.get(kind, kind)} {os.path.basename(path)} 内联后体积 "
            f"{len(payload) / 1048576:.1f}MB 超过上限 {INLINE_MAX_BYTES / 1048576:.0f}MB，"
            "无法用 base64 提交。请改用 http(s) 公网 URL，"
            "或在接口设置中配置 upload_endpoint（multipart 上传网关）。"
        )
    return f"data:{mime};base64,{payload.decode('ascii')}"


def _resolve_media(ref, *, kind: str, upload_endpoint: str, fallback: str,
                    api_key: str, timeout: float) -> str:
    """把参考素材转换为服务端可访问的 URL（或 data URI）。

    优先级：``http(s)``/data URI 原样透传 → 本地文件走 ``upload_endpoint`` 上传 →
    按 ``fallback`` 兜底（默认 ``data_uri``，base64 内联）。

    Args:
        ref: 本地路径 / http(s) URL / data URI
        kind: ``image`` / ``audio`` / ``video``，决定压缩策略与提示文案
        upload_endpoint: 自定义上传网关；为空则不尝试上传
        fallback: 本地文件无法上传时的策略：``data_uri``（默认）/ ``error`` / ``ignore``
    """
    label = _KIND_LABEL.get(kind, kind)
    text = str(ref or "").strip()
    if not text:
        return ""
    if _is_url_like(text):
        return text

    if not os.path.isfile(text):
        logger.warning("Agnes: 参考%s不存在，已忽略: %s", label, text)
        return ""

    if upload_endpoint:
        url = _upload_media(text, upload_endpoint, api_key, timeout)
        logger.info("Agnes: 参考%s已上传换得 URL: %s", label, url)
        return url

    if fallback == "ignore":
        logger.warning("Agnes: 未配置 upload_endpoint，参考%s被忽略", label)
        return ""

    if fallback == "data_uri":
        logger.info("Agnes: 未配置 upload_endpoint，参考%s改用 base64 data URI 内联提交", label)
        return _to_data_uri(text, kind)

    raise RuntimeError(
        f"Agnes: 参考{label}是本地文件，而 Agnes 要求媒体 URL 可公网访问。"
        "请先将素材上传到对象存储/CDN 后以 http(s) URL 传入，"
        "或在接口设置中配置 upload_endpoint（multipart 上传网关），"
        "或将 media_fallback 设为 data_uri（默认，用 base64 内联提交）。"
    )


def _error_detail(resp) -> str:
    """从错误响应里取可读原因（兼容 ``detail`` / ``error.message`` / 纯文本）。"""
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
        for key in ("detail", "message", "msg"):
            if body.get(key):
                return str(body[key])[:300]
    return text


def _report(on_progress, progress, status: str) -> None:
    """进度回调（可选，异常不影响生成）。"""
    if not callable(on_progress):
        return
    try:
        on_progress(progress, status)
    except Exception as e:  # noqa: BLE001
        logger.debug("Agnes: on_progress 回调异常: %s", e)


def _post_json_with_backoff(url: str, headers: dict, payload: dict, timeout: float,
                           retries: int = 3) -> "object":
    """创建任务；对 ``429``（账号速率/额度限制）与 ``503``（服务繁忙）分别退避重试。

    * 503：短退避 3s → 6s（服务端瞬时过载，很快恢复）
    * 429：长退避 15s → 45s（免费账号存在速率限制，需等配额窗口刷新）
    """
    last_resp = None
    for attempt in range(max(1, retries)):
        resp = request_with_retry("POST", url, headers=headers, json=payload, timeout=timeout)
        if resp.status_code == 503:
            reason, wait = "服务繁忙", min(RETRY_BACKOFF_CAP, 3.0 * (2 ** attempt))
        elif resp.status_code == 429:
            reason, wait = "触发速率/额度限制", min(RETRY_BACKOFF_CAP * 6, 15.0 * (3 ** attempt))
        else:
            return resp
        last_resp = resp
        if attempt < retries - 1:
            logger.warning("Agnes: 创建任务%s(HTTP %s)，%.0fs 后重试(%d/%d)",
                           reason, resp.status_code, wait, attempt + 1, retries)
            time.sleep(wait)
    return last_resp


def _create_task(url: str, headers: dict, payload: dict, timeout: float) -> str:
    """创建异步任务，返回 ``video_id``。"""
    resp = _post_json_with_backoff(url, headers, payload, timeout)
    if resp.status_code != 200:
        detail = _error_detail(resp)
        hint = ""
        if resp.status_code == 429:
            hint = ("（服务端按账号限流：免费账号有速率/额度上限，"
                    "建议降低接口并发、稍后重试，或升级 Token Plan）")
        elif resp.status_code == 503:
            hint = "（服务端繁忙，可稍后重试）"
        elif resp.status_code in (400, 422) and re.search(r"url|image|media|file", detail, re.I):
            # 本地素材走 base64 内联时最可能踩的坑：服务端只认真公网 URL
            hint = ("（若错误与素材 URL/图片有关，说明服务端未接受 base64 内联："
                    "请在接口设置中配置 upload_endpoint 走对象存储上传，"
                    "或改用 http(s) 公网 URL 传入参考素材）")
        raise RuntimeError(
            f"Agnes: 创建视频任务失败 HTTP {resp.status_code} {detail}{hint}"
        )
    body = resp.json() or {}
    video_id = body.get("video_id") or body.get("id") or body.get("task_id") or ""
    if not video_id:
        raise RuntimeError(f"Agnes: 创建任务响应中无 video_id: {str(body)[:200]}")
    logger.info("Agnes: 任务已创建 video_id=%s status=%s", video_id, body.get("status"))
    return str(video_id)


def _poll_task(api_base: str, video_id: str, model: str, headers: dict, *,
               timeout: float, poll_interval: float, poll_timeout: float,
               on_progress=None) -> str:
    """轮询任务直到终态，返回成品视频 URL。"""
    query_url = f"{_site_base(api_base)}{QUERY_PATH}"
    interval = max(1.0, float(poll_interval or DEFAULT_POLL_INTERVAL))
    deadline = time.time() + max(10.0, float(poll_timeout or DEFAULT_POLL_TIMEOUT))
    seen_progress = -1
    poll_429 = poll_503 = 0

    while time.time() < deadline:
        resp = request_with_retry(
            "GET", query_url,
            params={"video_id": video_id, "model_name": model},
            headers=headers, timeout=min(60.0, timeout),
        )
        if resp.status_code == 429:
            wait = min(RETRY_BACKOFF_CAP * 4, 15.0 * (2 ** min(3, poll_429)))
            poll_429 += 1
            logger.warning("Agnes: 查询触发速率限制(HTTP 429)，%.0fs 后重试", wait)
        elif resp.status_code == 503:
            wait = min(RETRY_BACKOFF_CAP, 3.0 * (2 ** min(3, poll_503)))
            poll_503 += 1
            logger.warning("Agnes: 查询时服务繁忙(HTTP 503)，%.0fs 后重试", wait)
        else:
            wait = 0
        if wait:
            time.sleep(wait)
            continue
        if resp.status_code == 404:
            raise RuntimeError(f"Agnes: 视频任务不存在 video_id={video_id}")
        if resp.status_code != 200:
            raise RuntimeError(f"Agnes: 查询任务失败 HTTP {resp.status_code} {_error_detail(resp)}")

        data = resp.json() or {}
        status = str(data.get("status") or "").lower()
        progress = int(data.get("progress") or 0)
        if progress != seen_progress:
            _report(on_progress, progress, status or "running")
            seen_progress = progress

        if status == "completed":
            url = data.get("url") or ""
            if not url:
                raise RuntimeError(f"Agnes: 任务已完成但未返回 url: {str(data)[:200]}")
            return str(url)
        if status == "failed":
            err = data.get("error")
            if isinstance(err, dict):
                detail = err.get("message") or str(err)
            else:
                detail = str(err or "")
            raise RuntimeError(f"Agnes: 视频生成失败{': ' + detail if detail else ''}")

        time.sleep(interval)

    raise TimeoutError(f"Agnes: 视频任务轮询超时(>{poll_timeout}s) video_id={video_id}")


def _download(url: str, output_dir: str, index: int) -> str:
    """下载成品视频到 ``output_dir/output_{index}.{ext}``。"""
    ext = _ext_of(urlparse(url).path) or "mp4"
    dst = os.path.join(output_dir, f"output_{index}.{ext}")
    download_with_retry(url, dst, timeout=300)
    return dst


# ── 参数归一化 ───────────────────────────────────────────────────────────────
def _norm_size(resolution: str, model: str) -> str:
    """分辨率归一化：Flash 仅支持 720P，其他值强制改写并告警。"""
    value = str(resolution or "").strip().upper()
    if not value:
        return DEFAULT_SIZE
    if value in SIZE_OPTIONS:
        return value
    if model == FLASH_MODEL or value not in ("720P", "1080P", "1K", "2K"):
        logger.warning("Agnes: 模型 %s 仅支持 %s，已把分辨率 %s 改写为 %s",
                       model, DEFAULT_SIZE, value, DEFAULT_SIZE)
        return DEFAULT_SIZE
    return value


def _norm_ratio(ratio: str) -> str:
    """画幅比例归一化：白名单外回落 16:9。"""
    value = str(ratio or "").strip()
    if not value or value.lower() == "auto":
        return "16:9"
    if value not in ASPECT_RATIOS:
        logger.warning("Agnes: 不支持的画幅比例 %s，回落 16:9（支持: %s）",
                       value, ", ".join(ASPECT_RATIOS))
        return "16:9"
    return value


def _norm_seconds(duration) -> str:
    """时长归一化：服务端要求字符串 "4"–"12"。"""
    try:
        value = int(float(duration))
    except (TypeError, ValueError):
        value = SECONDS_DEFAULT
    value = max(SECONDS_MIN, min(SECONDS_MAX, value))
    return str(value)


def _plan_mode(mode: str, ref_images, ref_videos, ref_audios) -> str:
    """把项目 mode 映射为 Agnes mode，并校验模式与素材是否匹配。

    ``txt2video`` → ``text``；``img2video`` → ``keyframe``（首帧）；
    ``flf2video`` → ``keyframe``（首+尾）；``autovideo`` → ``reference``。
    """
    has_img = bool(ref_images)
    has_vid = bool(ref_videos)
    has_audio = bool(ref_audios)
    normalized = str(mode or "").strip().lower()

    if normalized in ("txt2video", "text", ""):
        # 显式文生视频却带了参考图：按首帧图生视频处理，避免素材被静默丢弃
        if has_img:
            logger.info("Agnes: mode=%s 但提供了 %d 张参考图，自动按 keyframe（首帧）处理",
                        normalized or "txt2video", len(ref_images or []))
            return "keyframe"
        if has_vid or has_audio:
            logger.warning("Agnes: 文生视频模式不接收参考视频/音频，已忽略（%d 视频 / %d 音频）",
                           len(ref_videos or []), len(ref_audios or []))
        return "text"

    if normalized in ("img2video", "keyframe", "flf2video", "flf2v"):
        if not has_img:
            raise RuntimeError(
                f"Agnes: 模式 {normalized} 需要首帧/尾帧图片，请先上传参考图。"
            )
        return "keyframe"

    if normalized in ("autovideo", "reference", "v2v"):
        if has_vid:
            raise RuntimeError(
                "Agnes: Flash 模型不支持参考视频（服务端会返回 videos is not supported）。"
                "请改用图片/音频参考，或把接口模型切换为 agnes-video-2.5。"
            )
        if not (has_img or has_audio):
            raise RuntimeError("Agnes: reference 模式需要至少一张参考图或一段参考音频。")
        return "reference"

    # 未知mode：有图走 keyframe，有音/视频走 reference，否则 text
    if has_img:
        return "keyframe"
    if has_vid or has_audio:
        return "reference"
    return "text"


def _kind_of(path: str) -> str:
    """按扩展名推断素材类型（``image`` / ``audio`` / ``video``），用于压缩策略与文案。"""
    ext = _ext_of(path)
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _AUDIO_EXTS:
        return "audio"
    return "video"


def _clean_refs(refs) -> list:
    """过滤掉列表中的空值/None。"""
    return [r for r in (refs or []) if r]


# ── 工厂入口 ─────────────────────────────────────────────────────────────────
def generate(prompt, output_dir, model="", negative_prompt="", resolution="720P",
             ratio="16:9", duration=5, num_videos=1, ref_images=None, ref_videos=None,
             ref_audios=None, audio=None, mode="txt2video", api_key="", **kwargs):
    """Agnes AI 生视频统一入口（供 videogen 工厂调用）。

    Args:
        prompt: 文本提示词（建议英文，稳定性更好；reference 模式可用 ``<Picture 1>`` / ``<Audio 1>`` 占位）
        output_dir: 落盘目录
        model: 模型名，默认 ``agnes-video-2.5-flash``
        negative_prompt: 负向提示词（服务端未声明该字段，忽略）
        resolution: 分辨率档位；Flash 固定 ``720P``（其他值自动改写）
        ratio: 画幅比例 ``21:9/16:9/4:3/1:1/3:4/9:16``
        duration: 时长（秒），服务端范围 4–12
        num_videos: 生成数量（``n`` 固定 1，多张串行创建任务，上限 3）
        ref_images: 参考图 / 首帧 / 尾帧（本地路径或 http(s) URL）
        ref_videos: 参考视频（**Flash 不支持**，传入会报错）
        ref_audios: 参考音频（Flash 最多 3 段）
        audio: 声音开关（服务端无此字段，忽略）
        mode: ``txt2video`` / ``img2video`` / ``flf2video`` / ``autovideo``
        api_key: 接口配置的密钥；为空时按环境变量 → 密钥管理器回落
        **kwargs: base_url / poll_interval / poll_timeout / upload_endpoint /
                  media_fallback / seed / on_progress（由接口 ``custom_params``
                  或 ``sdk_extra_args`` 透传）

    Returns:
        本地文件路径列表（均落在 output_dir 下）；失败返回空列表。
    """
    api_base = _get_base_url(kwargs.get("base_url", ""))
    timeout = float(kwargs.get("timeout") or DEFAULT_TIMEOUT)
    poll_interval = float(kwargs.get("poll_interval") or DEFAULT_POLL_INTERVAL)
    poll_timeout = float(kwargs.get("poll_timeout") or DEFAULT_POLL_TIMEOUT)
    upload_endpoint = str(kwargs.get("upload_endpoint") or "").strip()
    fallback = str(kwargs.get("media_fallback") or DEFAULT_MEDIA_FALLBACK).strip().lower()
    if fallback not in FALLBACK_OPTIONS:
        logger.warning("Agnes: 非法 media_fallback=%r，回落 %s", fallback, DEFAULT_MEDIA_FALLBACK)
        fallback = DEFAULT_MEDIA_FALLBACK
    on_progress = kwargs.get("on_progress")

    key = _get_api_key(api_key)
    if not key:
        logger.error(
            "Agnes: 未配置 API Key。请设置环境变量 %s，"
            "或在项目密钥管理器中添加同名密钥，或在接口设置里填写 API Key。",
            API_KEY_ENV,
        )
        return []

    ref_images = [r for r in (ref_images or []) if r]
    ref_videos = _clean_refs(ref_videos)
    ref_audios = [a for a in (ref_audios or []) if a]
    model = (model or "").strip() or DEFAULT_MODEL

    try:
        agnes_mode = _plan_mode(mode, ref_images, ref_videos, ref_audios)
        size = _norm_size(resolution, model)
        aspect_ratio = _norm_ratio(ratio)
        seconds = _norm_seconds(duration)
        count = max(1, min(int(num_videos or 1), MAX_VIDEOS))

        if negative_prompt:
            logger.debug("Agnes: 服务端未声明负向提示词字段，已忽略 negative_prompt")
        if audio is not None:
            logger.debug("Agnes: 服务端无音频开关字段（音频经 reference 传入），已忽略 audio")

        # ── 素材解析（本地文件需转公网 URL 或内联 data URI） ──
        first_frame = last_frame = ""
        images: list = []
        audios: list = []
        if agnes_mode == "keyframe":
            first_frame = _resolve_media(ref_images[0], kind="image", upload_endpoint=upload_endpoint,
                                         fallback=fallback, api_key=key, timeout=timeout)
            if not first_frame:
                logger.error("Agnes: 首帧图无效，无法提交 keyframe 任务")
                return []
            if len(ref_images) > 1:
                last_frame = _resolve_media(ref_images[1], kind="image", upload_endpoint=upload_endpoint,
                                            fallback=fallback, api_key=key, timeout=timeout)
        else:
            for item in ref_images[:FLASH_MAX_IMAGES]:
                url = _resolve_media(item, kind="image", upload_endpoint=upload_endpoint,
                                     fallback=fallback, api_key=key, timeout=timeout)
                if url:
                    images.append(url)
            if len(ref_images) > FLASH_MAX_IMAGES:
                logger.warning("Agnes: %s 参考图最多 %d 张，已截断（多余 %d 张忽略）",
                               model, FLASH_MAX_IMAGES, len(ref_images) - FLASH_MAX_IMAGES)
            for item in ref_audios[:FLASH_MAX_AUDIOS]:
                url = _resolve_media(item, kind="audio", upload_endpoint=upload_endpoint,
                                     fallback=fallback, api_key=key, timeout=timeout)
                if url:
                    audios.append(url)
            if len(ref_audios) > FLASH_MAX_AUDIOS:
                logger.warning("Agnes: %s 参考音频最多 %d 段，已截断（多余 %d 段忽略）",
                               model, FLASH_MAX_AUDIOS, len(ref_audios) - FLASH_MAX_AUDIOS)

        payload = {
            "model": model,
            "prompt": prompt,
            "mode": agnes_mode,
            "seconds": seconds,
            "size": size,
            "aspect_ratio": aspect_ratio,
            "n": 1,
        }
        if kwargs.get("seed") is not None:
            try:
                payload["seed"] = int(kwargs["seed"])
            except (TypeError, ValueError):
                logger.warning("Agnes: 非法 seed %r，已忽略", kwargs.get("seed"))
        if agnes_mode == "keyframe":
            payload["first_frame"] = first_frame
            if last_frame:
                payload["last_frame"] = last_frame
        elif agnes_mode == "reference":
            if images:
                payload["images"] = images
            if audios:
                payload["audios"] = audios

        create_url = f"{api_base}{CREATE_ENDPOINT}"
        headers = _build_headers(key)
        logger.info(
            "Agnes: 生视频 model=%s mode=%s size=%s ratio=%s seconds=%s "
            "imgs=%d audios=%d n=%d base=%s",
            model, agnes_mode, size, aspect_ratio, seconds,
            len(images) + (1 if first_frame else 0) + (1 if last_frame else 0),
            len(audios), count, api_base,
        )

        os.makedirs(output_dir, exist_ok=True)
        saved = []
        for index in range(count):
            video_id = _create_task(create_url, headers, payload, timeout)
            video_url = _poll_task(
                api_base, video_id, model, headers,
                timeout=timeout, poll_interval=poll_interval,
                poll_timeout=poll_timeout, on_progress=on_progress,
            )
            saved.append(_download(video_url, output_dir, len(saved)))
        return saved

    except Exception as e:  # noqa: BLE001
        logger.error("Agnes: 生视频失败: %s", e)
        import traceback
        traceback.print_exc()
        return []


# ── 辅助能力（供接口设置页/节点使用）──────────────────────────────────────────
def upload_file(file_path_or_url, api_key: str = "", base_url: str = "", **kwargs) -> str:
    """把本地素材转换为服务端可访问的 URL（供 ``POST /{iface_id}/upload`` 端点调用）。

    * http(s) URL / data URI：原样返回；
    * 本地文件：按 ``upload_endpoint`` 上传换 URL；未配置时按 ``media_fallback``
      决定返回 base64 data URI（默认）还是抛错。
    """
    text = str(file_path_or_url or "").strip()
    if not text:
        return ""
    if _is_url_like(text):
        return text
    if not os.path.isfile(text):
        raise FileNotFoundError(text)

    timeout = float(kwargs.get("timeout") or DEFAULT_TIMEOUT)
    endpoint = str(kwargs.get("upload_endpoint") or "").strip()
    fallback = str(kwargs.get("media_fallback") or DEFAULT_MEDIA_FALLBACK).strip().lower()
    key = _get_api_key(api_key)
    if endpoint:
        return _upload_media(text, endpoint, key, timeout)
    if fallback == "ignore":
        return ""
    if fallback == "data_uri":
        return _to_data_uri(text, _kind_of(text))
    raise RuntimeError(
        "Agnes: 素材需公网可访问的 URL。请先上传到对象存储/CDN，"
        "或在接口设置中配置 upload_endpoint。"
    )


def list_models(api_key: str = "", **kwargs) -> list:
    """返回可用模型列表（Flash 免费；服务端无模型列举接口，返回内置清单）。"""
    return list(MODEL_OPTIONS)


def health(api_key: str = "", base_url: str = "", **kwargs) -> dict:
    """轻量探活：检查密钥是否可用配置（不创建任务，避免产生费用）。"""
    key = _get_api_key(api_key)
    api_base = _get_base_url(base_url)
    return {
        "status": "ok" if key else "error",
        "api_base": api_base,
        "site_base": _site_base(api_base),
        "model": DEFAULT_MODEL,
        "api_key_configured": bool(key),
    }