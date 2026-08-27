#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""呜哩创作平台 (Wuli) 视频生成 SDK 封装。

官方文档: https://platform.wuli.art
鉴权方式: 请求头 ``Authorization: Bearer <API Token>``

暴露能力:
  * 文生视频 (text_to_video):     POST /api/v1/platform/predict/submit (mediaType=VIDEO, predictType=TXT_2_VIDEO)
  * 图生视频 (image_to_video):     POST /api/v1/platform/predict/submit (predictType=FF_2_VIDEO / FLF_2_VIDEO)
  * 参考视频生视频 (video_to_video): POST /api/v1/platform/predict/submit (predictType=AUTO_VIDEO)

任务为异步模式: 先提交 (submit) 拿到 recordId, 再轮询 (query) 直到终态, 最后下载结果视频。
参考图/参考视频通过文件上传能力 (upload_file) 上传到平台 OSS 后注入 inputImageList / inputVideoList。
"""
import os
import time
import logging

from backend.imagegen.sdk.wuli_wrapper import (
    WULI_BASE_URL, TERMINAL_STATUSES, SUBMIT_ENDPOINT, QUERY_ENDPOINT,
    NO_WATERMARK_ENDPOINT, _get_api_key, _api_request, _image_dimensions,
    _resolve_file, upload_file, _submit,
)

logger = logging.getLogger(__name__)

# 平台支持的图像/视频模型（官方「视频生成模型」表格列出的接入模型）
WULI_VIDEO_MODELS = [
    "通义万相 2.7", "Happy Horse 1.1", "Happy Horse 1.0", "通义万相 2.2 Turbo",
    "通义万相 2.6 Flash", "通义万相 2.6", "可灵 3.0 Omni", "可灵 O1", "可灵 3.0",
    "可灵 2.6", "可灵 2.5 Turbo", "Seedance 1.5 Pro", "Seedance 1.0 Pro",
    "MiniMax Hailuo 2.3", "MiniMax Hailuo 2.3 Fast",
]
DEFAULT_MODEL = "可灵 3.0"

# 生成类型映射: 前端模式 -> 平台 predictType
PREDICT_TYPE_MAP = {
    "txt2video": "TXT_2_VIDEO",
    "img2video": "FF_2_VIDEO",
    "flf2video": "FLF_2_VIDEO",
    "autovideo": "AUTO_VIDEO",
}

DEFAULT_POLL_INTERVAL = 5         # 秒
DEFAULT_POLL_TIMEOUT = 1200       # 秒 (视频生成更长)


def _resolve_sound(audio):
    """将 audio 参数统一为布尔 (None 表示不传, 走模型默认)。"""
    if audio is None:
        return None
    if isinstance(audio, bool):
        return audio
    s = str(audio).strip().lower()
    if s in ("off", "false", "0", "no", "关闭"):
        return False
    return True  # on / keep_original / true / 开启


def _poll_video(record_id: str, api_key: str, base_url: str, timeout: int = DEFAULT_POLL_TIMEOUT):
    """轮询视频任务状态, 返回成功结果列表 (list[dict], 含 videoUrl)。"""
    waited = 0
    while waited <= timeout:
        data = _api_request(
            "GET", QUERY_ENDPOINT, api_key,
            base_url=base_url, params={"recordId": record_id},
        )
        status = data.get("recordStatus")
        if status in TERMINAL_STATUSES:
            results = data.get("results", []) or []
            if status == "SUCCEED":
                ok = [r for r in results if r.get("status") == "SUCCEED" and (r.get("videoUrl") or r.get("imageUrl"))]
                return ok if ok else [r for r in results if (r.get("videoUrl") or r.get("imageUrl"))]
            err = "; ".join([str(r.get("errorMsg", "")) for r in results if r.get("errorMsg")])
            raise RuntimeError(f"Wuli 视频任务失败[{status}]" + (f": {err}" if err else ""))
        time.sleep(DEFAULT_POLL_INTERVAL)
        waited += DEFAULT_POLL_INTERVAL
    raise TimeoutError(f"Wuli 视频任务轮询超时 (>{timeout}s), recordId={record_id}")


def _download_all(urls: list, output_dir: str) -> list:
    import requests as _req
    os.makedirs(output_dir, exist_ok=True)
    saved = []
    for i, url in enumerate(urls):
        try:
            resp = _req.get(url, timeout=300, stream=True)
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "").lower()
            ext = "mp4"
            if "webm" in ct:
                ext = "webm"
            elif "mov" in ct:
                ext = "mov"
            path = os.path.join(output_dir, f"output_{i}.{ext}")
            with open(path, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)
            saved.append(path)
        except Exception as e:
            logger.error("Wuli: 下载结果视频 %s 失败: %s", i, e)
    return saved


def _build_ref_images(ref_images, api_key, base_url):
    """上传参考图并构造 inputImageList (含 width/height)。"""
    items = []
    for img in (ref_images or []):
        if isinstance(img, dict) and img.get("imageUrl"):
            items.append(img)
            continue
        public_url = upload_file(img, api_key, base_url)
        data, _ = _resolve_file(img)
        width, height = _image_dimensions(data)
        item = {"imageUrl": public_url}
        if width and height:
            item["width"] = width
            item["height"] = height
        items.append(item)
    return items


def _build_ref_videos(ref_videos, api_key, base_url):
    """上传参考视频并构造 inputVideoList。"""
    items = []
    for vid in (ref_videos or []):
        if isinstance(vid, dict) and vid.get("videoUrl"):
            items.append(vid)
            continue
        public_url = upload_file(vid, api_key, base_url)
        items.append({"videoUrl": public_url})
    return items


def text_to_video(prompt: str, output_dir: str, model: str = "", negative_prompt: str = "",
                  resolution: str = "720P", duration: int = 5, num_videos: int = 1,
                  audio=None, api_key: str = "", base_url: str = WULI_BASE_URL, **kwargs) -> list:
    """文生视频 (Text-to-Video)。"""
    api_key = _get_api_key(api_key)
    if not api_key:
        logger.error("Wuli: 未配置 API Key, 无法生成视频。")
        return []
    model = model or DEFAULT_MODEL

    payload = {
        "modelName": model,
        "prompt": prompt,
        "mediaType": "VIDEO",
        "predictType": "TXT_2_VIDEO",
        "resolution": resolution,
        "duration": int(duration),
        "n": max(1, min(int(num_videos), 4)),
        "optimizePrompt": kwargs.get("optimize_prompt", True),
    }
    sound = _resolve_sound(audio)
    if sound is not None:
        payload["sound"] = sound
    if negative_prompt:
        payload["negativePrompt"] = negative_prompt
    if kwargs.get("seed") is not None:
        payload["seed"] = kwargs["seed"]

    record_id = _submit(payload, api_key, base_url)
    logger.info("Wuli 文生视频任务提交成功 recordId=%s", record_id)
    results = _poll_video(record_id, api_key, base_url, kwargs.get("poll_timeout", DEFAULT_POLL_TIMEOUT))
    urls = [r.get("videoUrl") or r.get("imageUrl") for r in results if (r.get("videoUrl") or r.get("imageUrl"))]
    return _download_all(urls, output_dir)


def image_to_video(prompt: str, ref_images: list, output_dir: str, model: str = "",
                   negative_prompt: str = "", resolution: str = "720P", duration: int = 5,
                   num_videos: int = 1, audio=None, predict_type: str = "FF_2_VIDEO",
                   api_key: str = "", base_url: str = WULI_BASE_URL, **kwargs) -> list:
    """图生视频 (首帧图生视频 FF_2_VIDEO / 首尾帧图生视频 FLF_2_VIDEO)。

    ref_images: 首帧图 (FF_2_VIDEO) 或 [首帧, 尾帧] (FLF_2_VIDEO)。
    """
    api_key = _get_api_key(api_key)
    if not api_key:
        logger.error("Wuli: 未配置 API Key, 无法生成视频。")
        return []
    if not ref_images:
        logger.error("Wuli 图生视频: 未提供参考图。")
        return []
    model = model or DEFAULT_MODEL

    input_image_list = _build_ref_images(ref_images, api_key, base_url)
    payload = {
        "modelName": model,
        "prompt": prompt,
        "mediaType": "VIDEO",
        "predictType": predict_type,
        "resolution": resolution,
        "duration": int(duration),
        "n": max(1, min(int(num_videos), 4)),
        "inputImageList": input_image_list,
        "optimizePrompt": kwargs.get("optimize_prompt", True),
    }
    sound = _resolve_sound(audio)
    if sound is not None:
        payload["sound"] = sound
    if negative_prompt:
        payload["negativePrompt"] = negative_prompt
    if kwargs.get("seed") is not None:
        payload["seed"] = kwargs["seed"]

    record_id = _submit(payload, api_key, base_url)
    logger.info("Wuli 图生视频任务提交成功 recordId=%s predictType=%s", record_id, predict_type)
    results = _poll_video(record_id, api_key, base_url, kwargs.get("poll_timeout", DEFAULT_POLL_TIMEOUT))
    urls = [r.get("videoUrl") or r.get("imageUrl") for r in results if (r.get("videoUrl") or r.get("imageUrl"))]
    return _download_all(urls, output_dir)


def video_to_video(prompt: str, ref_videos: list, output_dir: str, model: str = "",
                   negative_prompt: str = "", resolution: str = "720P", duration: int = 5,
                   num_videos: int = 1, audio=None, ref_images: list = None,
                   api_key: str = "", base_url: str = WULI_BASE_URL, **kwargs) -> list:
    """参考视频生视频 (AUTO_VIDEO): 使用参考视频 (可附带参考图)。"""
    api_key = _get_api_key(api_key)
    if not api_key:
        logger.error("Wuli: 未配置 API Key, 无法生成视频。")
        return []
    if not ref_videos and not ref_images:
        logger.error("Wuli 视频生视频: 未提供参考视频或参考图。")
        return []
    model = model or DEFAULT_MODEL

    payload = {
        "modelName": model,
        "prompt": prompt,
        "mediaType": "VIDEO",
        "predictType": "AUTO_VIDEO",
        "resolution": resolution,
        "duration": int(duration),
        "n": max(1, min(int(num_videos), 4)),
        "optimizePrompt": kwargs.get("optimize_prompt", True),
    }
    input_video_list = _build_ref_videos(ref_videos, api_key, base_url)
    if input_video_list:
        payload["inputVideoList"] = input_video_list
    input_image_list = _build_ref_images(ref_images, api_key, base_url)
    if input_image_list:
        payload["inputImageList"] = input_image_list
    sound = _resolve_sound(audio)
    if sound is not None:
        payload["sound"] = sound
    if negative_prompt:
        payload["negativePrompt"] = negative_prompt
    if kwargs.get("seed") is not None:
        payload["seed"] = kwargs["seed"]

    record_id = _submit(payload, api_key, base_url)
    logger.info("Wuli 视频生视频任务提交成功 recordId=%s", record_id)
    results = _poll_video(record_id, api_key, base_url, kwargs.get("poll_timeout", DEFAULT_POLL_TIMEOUT))
    urls = [r.get("videoUrl") or r.get("imageUrl") for r in results if (r.get("videoUrl") or r.get("imageUrl"))]
    return _download_all(urls, output_dir)


def list_models(api_key: str = "") -> list:
    """返回平台支持的视频模型名称列表。"""
    return list(WULI_VIDEO_MODELS)


def generate(prompt: str, output_dir: str, model: str = "", negative_prompt: str = "",
             resolution: str = "720P", duration: int = 5, num_videos: int = 1,
             ref_images: list = None, ref_videos: list = None, audio=None,
             mode: str = "txt2video", api_key: str = "", **kwargs) -> list:
    """统一入口: 根据 mode 分发到不同生成类型。供 videogen 引擎调度。"""
    api_key = _get_api_key(api_key)
    if not api_key:
        logger.error("Wuli: 未配置 API Key (接口设置或环境变量 WULI_API_KEY), 无法生成视频。")
        return []
    ref_images = ref_images or []
    ref_videos = ref_videos or []
    mode = mode or "txt2video"

    if mode == "img2video":
        return image_to_video(
            prompt, ref_images, output_dir, model=model, negative_prompt=negative_prompt,
            resolution=resolution, duration=duration, num_videos=num_videos, audio=audio,
            predict_type="FF_2_VIDEO", api_key=api_key, **kwargs,
        )
    if mode == "flf2video":
        return image_to_video(
            prompt, ref_images, output_dir, model=model, negative_prompt=negative_prompt,
            resolution=resolution, duration=duration, num_videos=num_videos, audio=audio,
            predict_type="FLF_2_VIDEO", api_key=api_key, **kwargs,
        )
    if mode == "autovideo":
        return video_to_video(
            prompt, ref_videos, output_dir, model=model, negative_prompt=negative_prompt,
            resolution=resolution, duration=duration, num_videos=num_videos, audio=audio,
            ref_images=ref_images, api_key=api_key, **kwargs,
        )
    # 默认 txt2video
    return text_to_video(
        prompt, output_dir, model=model, negative_prompt=negative_prompt,
        resolution=resolution, duration=duration, num_videos=num_videos, audio=audio,
        api_key=api_key, **kwargs,
    )
