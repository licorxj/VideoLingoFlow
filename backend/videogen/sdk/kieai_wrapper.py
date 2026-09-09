#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KIE AI 视频生成 wrapper，桥接到我们建设好的 KIE AI SDK。

本模块是视频生成工厂（``backend.videogen.videogen_factory.SDKVideoGen``）的
``sdk_function`` 入口。每次视频生成调用都委托给
:class:`backend.kieai_sdk.kieai.KieClient`，由其负责异步任务提交、轮询与结果下载/落盘。

密钥解析遵循 SDK 的三级回退（调用者 key -> ``secret://KIEAI_API_KEY`` ->
``KIEAI_API_KEY`` 环境变量）。视频工厂会把 ``sdk_api_key``（``secret://KIEAI_API_KEY``
引用）透传为 ``api_key``，而 KieClient 自身支持解析 ``secret://NAME``，因此无需工厂额外解析。

工厂契约（见 ``videogen_base.VideoGenBase.generate``）透传：
    prompt, output_dir, model, negative_prompt, resolution, ratio, duration,
    num_videos, ref_images, ref_videos, ref_audios, audio, mode
    （+ 自定义参数经 sdk_extra_args 传入，内含 api_key）。

注意：视频工厂同步调用 ``generate``（不像 imagegen 工厂会包裹 asyncio.run），
因此本模块以同步 ``generate`` 为入口，内部用 ``asyncio.run`` 驱动异步 SDK。
"""
import os
import asyncio
import base64
import logging
import mimetypes
import re

from backend.kieai_sdk.kieai import KieClient

logger = logging.getLogger(__name__)

# 余额查询主机
_KIE_API_BASE = "https://api.kie.ai"

# 各模态候选参数名（按模型实际声明的参数匹配，仅取模型支持的字段）
_SINGLE_IMAGE_PARAMS = ("first_frame_url", "last_frame_url")
_ARRAY_IMAGE_PARAMS = (
    "input_urls", "reference_image_urls", "image_url", "filesUrl",
    "fileUrl", "image", "input_image", "reference_url", "images",
)
_ARRAY_VIDEO_PARAMS = (
    "reference_video_urls", "reference_video_url", "video_url",
    "input_video_url", "video", "input_video",
)
_ARRAY_AUDIO_PARAMS = (
    "reference_audio_urls", "reference_audio_url", "audio_url",
    "input_audio_url", "input_audio", "audio",
)

# 分辨率档位映射：工厂传来大写（480P/720P/1080P/4K）-> SDK 小写
_RES_MAP = {"480P": "480p", "720P": "720p", "1080P": "1080p", "4K": "1080p", "2K": "720p"}

_DEFAULT_MODEL = "bytedance/seedance-1.5-pro"


# --------------------------------------------------------------------------- #
# 异步运行辅助（容忍调用方已有运行中的事件循环）
# --------------------------------------------------------------------------- #
def _run_async(coro):
    """在同步上下文驱动协程；调用方已有运行中的事件循环时改由独立线程执行。

    不使用 ``asyncio.get_event_loop()``：Python 3.12 在无当前事件循环的线程中
    会直接抛 ``RuntimeError: There is no current event loop in thread ...``
    （且该用法已废弃），这里改用 ``get_running_loop()`` 判断。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


# --------------------------------------------------------------------------- #
# 素材上传：本地文件 -> KIE 公开 URL
# --------------------------------------------------------------------------- #
async def _resolve_asset_urls(client: KieClient, items, kind: str) -> list:
    """上传本地素材并返回其公开下载 URL；HTTP URL 原样透传。"""
    urls: list = []
    for item in (items or []):
        if not isinstance(item, str):
            continue
        if item.startswith("http://") or item.startswith("https://"):
            urls.append(item)
            continue
        if not os.path.exists(item):
            logger.warning("KIE AI 视频: 跳过无效素材: %s", item)
            continue
        mime = mimetypes.guess_type(item)[0] or (
            "image/png" if kind == "images" else
            "video/mp4" if kind == "videos" else "audio/mpeg"
        )
        try:
            with open(item, "rb") as fh:
                b64 = base64.b64encode(fh.read()).decode()
            up = await client.upload(
                method="base64",
                base64Data=f"data:{mime};base64,{b64}",
                uploadPath=kind,
                fileName=os.path.basename(item),
            )
            url = up.get("downloadUrl") or up.get("url") or up.get("fileUrl")
            if url:
                urls.append(url)
            else:
                logger.warning("KIE AI 视频: 上传未返回 URL: %s", up)
        except Exception as e:  # noqa: BLE001
            logger.warning("KIE AI 视频: 上传失败 %s: %s", item, e)
    return urls


# --------------------------------------------------------------------------- #
# 参数归一化
# --------------------------------------------------------------------------- #
def _res_rank(value) -> int:
    """把分辨率写法归一为可比较的数值：720P/720p -> 720；1K/2K/4K -> 1080/1440/2160。"""
    s = str(value or "").strip().lower()
    m = re.match(r"^(\d+)\s*p$", s)
    if m:
        return int(m.group(1))
    m = re.match(r"^(\d+)\s*k$", s)
    if m:
        return {1: 1080, 2: 1440, 4: 2160}.get(int(m.group(1)), int(m.group(1)) * 540)
    m = re.match(r"^(\d+)$", s)
    if m:
        return int(m.group(1))
    return -1


def _norm_resolution(resolution: str, entry) -> str:
    """按模型实际声明的 resolution 枚举归一化（关键因素：大小写与档位）。

    各厂商枚举写法并不统一：wan/3-0-video 用大写 ``720P``，wan/2-6 用小写
    ``720p``，wan/2-7-image 用 ``1K/2K/4K``。此前统一转小写会让大写枚举的模型
    直接报 ``resolution is not within the range of allowed options``，因此这里
    一律以模型声明的枚举为准：
      1) 原样命中枚举 -> 直接采用
      2) 忽略大小写命中 -> 采用枚举中的原始写法
      3) 按数值档位取「不超过请求值」的最高档（4K/2K 请求自动收敛到模型上限）
      4) 兜底：参数默认值，其次枚举首项
    """
    rp = next((p for p in entry.params if p.name == "resolution"), None)
    if rp is None:
        return None

    enum = [str(v) for v in (rp.enum or []) if v is not None and str(v).strip()]
    req = str(resolution or "").strip()

    if not enum:
        return str(rp.default) if rp.default else _RES_MAP.get(req.upper(), "720p")

    for v in enum:
        if v == req:
            return v
    low = {v.lower(): v for v in enum}
    if req.lower() in low:
        return low[req.lower()]

    valid = [(v, r) for v, r in ((v, _res_rank(v)) for v in enum) if r > 0]
    req_rank = _res_rank(req)
    if valid and req_rank > 0:
        below = [item for item in valid if item[1] <= req_rank]
        return max(below, key=lambda x: x[1])[0] if below else min(valid, key=lambda x: x[1])[0]

    return str(rp.default) if rp.default else enum[0]


def _aspect_ratio(ratio: str, entry):
    """返回 (param_name, value)；模型不支持比例参数时返回 (None, None)。"""
    for name in ("aspect_ratio", "ratio"):
        for p in entry.params:
            if p.name == name:
                val = ratio or "16:9"
                if p.enum and val not in p.enum:
                    val = p.enum[0]
                return name, val
    return None, None


def _audio_bool(audio):
    """audio 参数 -> 布尔（None 表示不传，走模型默认）。"""
    if audio is None:
        return None
    s = str(audio).strip().lower()
    if s in ("off", "false", "0", "no", "关闭"):
        return False
    if s == "model_default":
        return None
    return True  # on / keep_original / true / 开启


# --------------------------------------------------------------------------- #
# 参考素材 -> 模型参数映射（按 mode）
# --------------------------------------------------------------------------- #
def _map_refs(params: dict, pnames: set, mode: str,
              img_urls: list, vid_urls: list, aud_urls: list) -> None:
    if mode == "txt2video":
        return

    if mode == "img2video":
        if "first_frame_url" in pnames and img_urls:
            params["first_frame_url"] = img_urls[0]
            return
        arr = next((n for n in _ARRAY_IMAGE_PARAMS if n in pnames), None)
        if arr and img_urls:
            params[arr] = img_urls[:1]
        return

    if mode == "flf2video":
        if ("first_frame_url" in pnames and "last_frame_url" in pnames
                and len(img_urls) >= 2):
            params["first_frame_url"] = img_urls[0]
            params["last_frame_url"] = img_urls[1]
            return
        arr = next((n for n in _ARRAY_IMAGE_PARAMS if n in pnames), None)
        if arr and len(img_urls) >= 2:
            params[arr] = img_urls[:2]
        elif arr and img_urls:
            params[arr] = img_urls[:1]  # 退化：仅首帧
        return

    if mode == "autovideo":
        if "reference_image_urls" in pnames and img_urls:
            params["reference_image_urls"] = img_urls
        else:
            arr = next((n for n in _ARRAY_IMAGE_PARAMS if n in pnames), None)
            if arr and img_urls:
                params[arr] = img_urls
        if "reference_video_urls" in pnames and vid_urls:
            params["reference_video_urls"] = vid_urls
        else:
            arr = next((n for n in _ARRAY_VIDEO_PARAMS if n in pnames), None)
            if arr and vid_urls:
                params[arr] = vid_urls
        if "reference_audio_urls" in pnames and aud_urls:
            params["reference_audio_urls"] = aud_urls
        else:
            arr = next((n for n in _ARRAY_AUDIO_PARAMS if n in pnames), None)
            if arr and aud_urls:
                params[arr] = aud_urls
        return


# --------------------------------------------------------------------------- #
# 核心异步生成
# --------------------------------------------------------------------------- #
async def _generate_async(prompt, output_dir, model, negative_prompt, resolution,
                          ratio, duration, num_videos, ref_images, ref_videos,
                          ref_audios, audio, mode, api_key, **kwargs):
    model = model or _DEFAULT_MODEL
    mode = mode or "txt2video"
    ref_images = ref_images or []
    ref_videos = ref_videos or []
    ref_audios = ref_audios or []
    num_videos = max(1, min(int(num_videos or 1), 10))

    async with KieClient(api_key=api_key or None) as client:
        try:
            entry = client.catalog.get(model)
        except Exception as e:  # noqa: BLE001
            logger.error("KIE AI 视频: 模型未找到: %s (%s)", model, e)
            return []

        pnames = {p.name for p in entry.params}

        # 能力前置校验
        if mode in ("img2video", "flf2video") and not ref_images:
            logger.error("KIE AI 视频: %s 需要至少 1 张参考图", mode)
            return []
        if mode == "autovideo" and not (ref_images or ref_videos or ref_audios):
            logger.error("KIE AI 视频: autovideo 需要至少 1 个参考素材（图/视频/音频）")
            return []

        # 上传参考素材
        img_urls = await _resolve_asset_urls(client, ref_images, "images") if ref_images else []
        vid_urls = await _resolve_asset_urls(client, ref_videos, "videos") if ref_videos else []
        aud_urls = await _resolve_asset_urls(client, ref_audios, "audios") if ref_audios else []

        params = {"prompt": prompt}

        # 宽高比
        ar_name, ar_val = _aspect_ratio(ratio, entry)
        if ar_name:
            params[ar_name] = ar_val

        # 分辨率（按模型枚举归一化，避免大小写/档位不匹配）
        res = _norm_resolution(resolution, entry)
        if res:
            params["resolution"] = res

        # 时长
        if "duration" in pnames:
            try:
                params["duration"] = int(duration)
            except (TypeError, ValueError):
                pass

        # 声音
        ab = _audio_bool(audio)
        if ab is not None and "generate_audio" in pnames:
            params["generate_audio"] = ab

        # 负向提示（视频模型多数不支持，仅支持时透传）
        if "negative_prompt" in pnames and negative_prompt:
            params["negative_prompt"] = negative_prompt

        # 参考素材映射
        if mode in ("img2video", "flf2video", "autovideo"):
            _map_refs(params, pnames, mode, img_urls, vid_urls, aud_urls)

        # 内容安全开关
        nsfw = kwargs.get("nsfw_checker")
        if "nsfw_checker" in pnames and nsfw is not None:
            params["nsfw_checker"] = bool(nsfw)

        # 通配透传：其余声明参数直接在 kwargs 中给出时一并带上
        for k, v in kwargs.items():
            if k in pnames and k not in params and v is not None:
                params[k] = v

        # 轮询超时
        poll_timeout = int(kwargs.get("poll_timeout", 600) or 600)
        if poll_timeout:
            client.max_poll = max(1, int(poll_timeout / max(client.poll_interval, 0.1)))

        all_paths: list = []
        for _ in range(num_videos):
            try:
                result = await client.generate(model, output_path=output_dir, **params)
            except Exception as e:  # noqa: BLE001
                logger.error("KIE AI 视频: 生成失败: %s", e)
                import traceback
                traceback.print_exc()
                continue
            paths = result.get("local_paths") or []
            all_paths.extend(paths)
        return all_paths


def generate(prompt, output_dir, model="", negative_prompt="", resolution="720P",
             ratio="16:9", duration=5, num_videos=1, ref_images=None, ref_videos=None,
             ref_audios=None, audio=None, mode="txt2video", api_key="", **kwargs):
    """通过 KIE AI SDK 生成视频，返回本地文件路径列表。

    Args:
        prompt: 文本提示词。
        output_dir: 视频落盘目录。
        model: SDK catalog 视频模型 id（如 ``bytedance/seedance-1.5-pro``）。
        negative_prompt: 仅模型支持时透传。
        resolution: 480P / 720P / 1080P / 4K（按模型支持映射到小写档位）。
        ratio: 宽高比，如 16:9（图生视频首/尾帧场景由模型按首帧自动适配）。
        duration: 时长（秒）。
        num_videos: 生成数量（>1 时循环提交多个任务）。
        ref_images: 参考图（本地路径 / HTTP URL），用于图生视频 / 参考生视频。
        ref_videos: 参考视频（本地路径 / HTTP URL），用于参考生视频。
        ref_audios: 参考音频（本地路径 / HTTP URL），用于参考生视频。
        audio: 声音开关（None 走模型默认 / True / False / "on"/"off"/"keep_original"/"model_default"）。
        mode: txt2video / img2video / flf2video / autovideo。
        api_key: KIE AI API key（SDK 回退到 secret/env 否则）。
        **kwargs: nsfw_checker / fixed_lens / seed / callback_url / poll_timeout 等，
                  凡模型声明的参数均会透传。

    Returns:
        生成的视频文件本地路径列表。
    """
    return _run_async(_generate_async(
        prompt, output_dir, model, negative_prompt, resolution, ratio, duration,
        num_videos, ref_images, ref_videos, ref_audios, audio, mode, api_key, **kwargs
    ))


# --------------------------------------------------------------------------- #
# 文件上传（供接口管理器的 /upload 端点使用）
# --------------------------------------------------------------------------- #
async def _upload_file_async(path: str, kind: str, api_key: str) -> str:
    async with KieClient(api_key=api_key or None) as client:
        urls = await _resolve_asset_urls(client, [path], kind)
        return urls[0] if urls else ""


def upload_file(file_path_or_url, api_key="", **kwargs):
    """上传本地文件（或原样返回 URL）到 KIE AI，返回公开 URL。"""
    if isinstance(file_path_or_url, str) and file_path_or_url.startswith("http"):
        return file_path_or_url
    ext = os.path.splitext(file_path_or_url)[1].lower() if isinstance(file_path_or_url, str) else ""
    if ext in (".mp4", ".mov", ".webm", ".mkv", ".avi"):
        kind = "videos"
    elif ext in (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"):
        kind = "audios"
    else:
        kind = "images"
    return _run_async(_upload_file_async(file_path_or_url, kind, api_key))


# --------------------------------------------------------------------------- #
# 可选辅助（供接口管理器 API 使用）
# --------------------------------------------------------------------------- #
def list_models(api_key: str = ""):
    """返回 SDK catalog 中视频生成模型 id 列表。"""
    try:
        client = KieClient(api_key=api_key or None)
        return [
            m.id for m in client.catalog.models
            if (m.category or "").lower() == "video" and _has_prompt(m)
        ]
    except Exception as e:  # noqa: BLE001
        logger.warning("KIE AI 视频: list_models 失败: %s", e)
        return []


async def _fetch_balance(api_key: str):
    async with KieClient(api_key=api_key or None) as client:
        url = f"{_KIE_API_BASE}/api/v1/chat/credit"
        try:
            data = await client._get_json(url)
        except Exception as e:  # noqa: BLE001
            logger.warning("KIE AI 视频: 余额查询失败: %s", e)
            return None
        if isinstance(data, dict) and data.get("code") == 200:
            return data.get("data")
        return None


def get_balance(api_key: str = ""):
    """返回剩余积分/点数余额（失败返回 None）。"""
    try:
        return _run_async(_fetch_balance(api_key))
    except Exception as e:  # noqa: BLE001
        logger.warning("KIE AI 视频: get_balance 失败: %s", e)
        return None


def _has_prompt(model) -> bool:
    return any(p.name == "prompt" for p in model.params)
