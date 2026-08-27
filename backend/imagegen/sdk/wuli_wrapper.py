#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""呜哩创作平台 (Wuli Creation Platform) 图像生成 SDK 封装。

官方文档: https://platform.wuli.art
鉴权方式: 请求头 ``Authorization: Bearer <API Token>``

暴露能力:
  * 文生图 (text_to_image): POST /api/v1/platform/predict/submit (mediaType=IMAGE, predictType=TXT_2_IMG)
  * 图生图 (image_to_image): POST /api/v1/platform/predict/submit (mediaType=IMAGE, predictType=REF_2_IMG)
  * 文件上传 (upload_file):      GET  /api/v1/platform/image/getUploadUrl + PUT 上传

任务为异步模式: 先提交 (submit) 拿到 recordId, 再轮询 (query) 直到终态, 最后下载结果图。
"""
import os
import time
import logging
import urllib.parse
import requests

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────────────────────────────────
WULI_BASE_URL = "https://platform.wuli.art"

SUBMIT_ENDPOINT = "/api/v1/platform/predict/submit"
QUERY_ENDPOINT = "/api/v1/platform/predict/query"
NO_WATERMARK_ENDPOINT = "/api/v1/platform/predict/noWatermarkImage"
UPLOAD_URL_ENDPOINT = "/api/v1/platform/image/getUploadUrl"

# 任务终态
TERMINAL_STATUSES = {"SUCCEED", "FAILED", "REVIEWFAILED", "TIMEOUT", "CANCELLED"}

# 轮询相关
DEFAULT_POLL_INTERVAL = 3        # 秒
DEFAULT_POLL_TIMEOUT = 600       # 秒 (任务最长等待时间)

# 平台支持的图像模型（官方「图像」标签下列出的常用模型）
WULI_IMAGE_MODELS = [
    "智能IMAGE 2",
    "全能图片 2",
    "全能图片 Pro",
    "通义万相 2.7",
    "Qwen Image 2.0",
    "Qwen Image Turbo",
    "Seedream 5.0 Lite",
    "Seedream 4.5",
    "Seedream 4.0",
]
DEFAULT_MODEL = "Qwen Image 2.0"

# 平台通用比例
WULI_ASPECT_RATIOS = [
    "1:1", "3:2", "2:3", "4:3", "3:4",
    "16:9", "9:16", "2:1", "1:2", "5:4", "4:5",
]


# ──────────────────────────────────────────────────────────────────────────────
# 基础工具
# ──────────────────────────────────────────────────────────────────────────────
def _get_api_key(api_key: str = "") -> str:
    """API Key 取值优先级: 函数参数 > 环境变量 WULI_API_KEY。"""
    if api_key:
        return api_key
    return os.environ.get("WULI_API_KEY", "")


def _api_request(method: str, endpoint: str, api_key: str, base_url: str = WULI_BASE_URL,
                 json_body: dict = None, params: dict = None) -> dict:
    """统一请求封装, 自动处理鉴权头与通用响应体。返回 data 字段(dict)。"""
    url = (base_url or WULI_BASE_URL).rstrip("/") + endpoint
    headers = {"Authorization": f"Bearer {api_key}"}
    if method.upper() == "GET":
        resp = requests.get(url, headers=headers, params=params, timeout=60)
    else:
        headers["Content-Type"] = "application/json"
        resp = requests.post(url, headers=headers, json=json_body, timeout=120)

    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        snippet = resp.text[:300] if resp is not None else ""
        raise RuntimeError(f"Wuli HTTP {resp.status_code}: {snippet}") from e

    data = resp.json()
    if not data.get("success", False):
        raise RuntimeError(
            f"Wuli API error code={data.get('code')} msg={data.get('msg')} "
            f"requestId={data.get('requestId')}"
        )
    return data.get("data", {}) or {}


def _image_dimensions(data: bytes):
    """解析图片宽高 (width, height)。支持 PNG / JPEG；缺失时返回 (None, None)。"""
    import struct
    # PNG
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        width, height = struct.unpack(">II", data[16:24])
        return width, height
    # JPEG
    if len(data) >= 4 and data[:2] == b"\xff\xd8":
        i = 2
        n = len(data)
        while i < n - 9:
            if data[i] != 0xFF:
                break
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                if i + 9 <= n:
                    height, width = struct.unpack(">HH", data[i + 5:i + 9])
                    return width, height
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7 or marker == 0x01:
                i += 2
                continue
            if i + 4 > n:
                break
            (length,) = struct.unpack(">H", data[i + 2:i + 4])
            i += 2 + length
    # 尝试 PIL 兜底 (WebP / GIF 等)
    try:
        from PIL import Image
        import io
        with Image.open(io.BytesIO(data)) as img:
            return img.size
    except Exception:
        return None, None


def _resolve_file(file_path_or_url: str):
    """将路径或远程 URL 解析为 (bytes, filename)。"""
    if isinstance(file_path_or_url, str) and file_path_or_url.startswith("http"):
        resp = requests.get(file_path_or_url, timeout=120)
        resp.raise_for_status()
        filename = os.path.basename(urllib.parse.urlparse(file_path_or_url).path) or "upload.bin"
        return resp.content, filename
    path = file_path_or_url
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with open(path, "rb") as f:
        data = f.read()
    return data, os.path.basename(path)


# ──────────────────────────────────────────────────────────────────────────────
# 文件上传能力
# ──────────────────────────────────────────────────────────────────────────────
def upload_file(file_path_or_url: str, api_key: str = "", base_url: str = WULI_BASE_URL) -> str:
    """文件上传: 获取预签名地址后 PUT 上传, 返回可用于 inputImageList 的公开 URL。

    第三方 URL 需先下载再上传 (平台不支持直接引用外链)。
    """
    api_key = _get_api_key(api_key)
    if not api_key:
        raise RuntimeError("Wuli: 上传文件需要 API Key (配置接口或设置环境变量 WULI_API_KEY)")

    file_bytes, filename = _resolve_file(file_path_or_url)

    # 1) 获取预签名上传地址
    data = _api_request(
        "GET", UPLOAD_URL_ENDPOINT, api_key,
        base_url=base_url, params={"filename": filename},
    )
    upload_url = data.get("uploadUrl")
    if not upload_url:
        raise RuntimeError(f"Wuli: 获取上传地址失败, data={data}")

    # 2) PUT 上传二进制内容
    put_resp = requests.put(
        upload_url,
        data=file_bytes,
        headers={"Content-Type": "application/octet-stream"},
        timeout=120,
    )
    put_resp.raise_for_status()

    # 3) 去掉 query 参数即为公开访问地址
    parsed = urllib.parse.urlparse(upload_url)
    public_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return public_url


# ──────────────────────────────────────────────────────────────────────────────
# 任务提交流程
# ──────────────────────────────────────────────────────────────────────────────
def _submit(payload: dict, api_key: str, base_url: str) -> str:
    data = _api_request("POST", SUBMIT_ENDPOINT, api_key, base_url=base_url, json_body=payload)
    record_id = data.get("recordId")
    if not record_id:
        raise RuntimeError(f"Wuli: 提交任务未返回 recordId, data={data}")
    return record_id


def _poll(record_id: str, api_key: str, base_url: str, timeout: int = DEFAULT_POLL_TIMEOUT):
    """轮询任务状态, 返回成功的结果列表 (list[dict])。"""
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
                ok = [r for r in results if r.get("status") == "SUCCEED" and r.get("imageUrl")]
                return ok if ok else [r for r in results if r.get("imageUrl")]
            err = "; ".join([str(r.get("errorMsg", "")) for r in results if r.get("errorMsg")])
            raise RuntimeError(f"Wuli 任务失败[{status}]" + (f": {err}" if err else ""))
        time.sleep(DEFAULT_POLL_INTERVAL)
        waited += DEFAULT_POLL_INTERVAL
    raise TimeoutError(f"Wuli 任务轮询超时 (>{timeout}s), recordId={record_id}")


def _fetch_no_watermark(resource_ids: list, api_key: str, base_url: str) -> list:
    """通过 resourceId 获取无水印地址。"""
    if not resource_ids:
        return []
    data = _api_request(
        "POST", NO_WATERMARK_ENDPOINT, api_key,
        base_url=base_url, json_body={"resourceIdList": resource_ids},
    )
    urls = list(data.get("urlList", []) or [])
    if data.get("url"):
        urls.insert(0, data["url"])
    return urls


def _download_all(urls: list, output_dir: str) -> list:
    os.makedirs(output_dir, exist_ok=True)
    saved = []
    for i, url in enumerate(urls):
        try:
            resp = requests.get(url, timeout=120, stream=True)
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "").lower()
            ext = "png"
            if "jpeg" in ct or "jpg" in ct:
                ext = "jpg"
            elif "webp" in ct:
                ext = "webp"
            path = os.path.join(output_dir, f"output_{i}.{ext}")
            with open(path, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)
            saved.append(path)
        except Exception as e:
            logger.error("Wuli: 下载结果图 %s 失败: %s", i, e)
    return saved


# ──────────────────────────────────────────────────────────────────────────────
# 文生图 / 图生图 能力
# ──────────────────────────────────────────────────────────────────────────────
def text_to_image(prompt: str, output_dir: str, model: str = "", negative_prompt: str = "",
                  resolution: str = "2K", aspect_ratio: str = "1:1", num_images: int = 1,
                  api_key: str = "", base_url: str = WULI_BASE_URL, **kwargs) -> list:
    """文生图 (Text-to-Image)。返回本地文件列表。"""
    api_key = _get_api_key(api_key)
    if not api_key:
        logger.error("Wuli: 未配置 API Key, 无法生成图像。")
        return []
    model = model or DEFAULT_MODEL

    payload = {
        "modelName": model,
        "prompt": prompt,
        "mediaType": "IMAGE",
        "predictType": "TXT_2_IMG",
        "aspectRatio": aspect_ratio,
        "resolution": resolution,
        "n": max(1, min(int(num_images), 4)),
        "optimizePrompt": kwargs.get("optimize_prompt", True),
    }
    if negative_prompt:
        payload["negativePrompt"] = negative_prompt
    if kwargs.get("quality"):
        payload["quality"] = kwargs["quality"]
    if kwargs.get("seed") is not None:
        payload["seed"] = kwargs["seed"]

    record_id = _submit(payload, api_key, base_url)
    logger.info("Wuli 文生图任务提交成功 recordId=%s", record_id)
    results = _poll(record_id, api_key, base_url, kwargs.get("poll_timeout", DEFAULT_POLL_TIMEOUT))

    urls = [r["imageUrl"] for r in results if r.get("imageUrl")]
    if kwargs.get("no_watermark"):
        resource_ids = [r.get("imageId") for r in results if r.get("imageId")]
        urls = _fetch_no_watermark(resource_ids, api_key, base_url) or urls

    return _download_all(urls, output_dir)


def image_to_image(prompt: str, ref_images: list, output_dir: str, model: str = "",
                   negative_prompt: str = "", resolution: str = "2K", aspect_ratio: str = "1:1",
                   num_images: int = 1, api_key: str = "", base_url: str = WULI_BASE_URL,
                   **kwargs) -> list:
    """图生图 (Image-to-Image)。ref_images 支持本地路径或 http(s) URL。返回本地文件列表。"""
    api_key = _get_api_key(api_key)
    if not api_key:
        logger.error("Wuli: 未配置 API Key, 无法生成图像。")
        return []
    if not ref_images:
        logger.error("Wuli 图生图: 未提供参考图。")
        return []
    model = model or DEFAULT_MODEL

    input_image_list = []
    for img in ref_images:
        if isinstance(img, dict) and img.get("imageUrl"):
            input_image_list.append(img)
            continue
        public_url = upload_file(img, api_key, base_url)
        width, height = _image_dimensions(_resolve_file(img)[0]) if not (
            isinstance(img, dict)) else (None, None)
        item = {"imageUrl": public_url}
        if width and height:
            item["width"] = width
            item["height"] = height
        input_image_list.append(item)

    payload = {
        "modelName": model,
        "prompt": prompt,
        "mediaType": "IMAGE",
        "predictType": "REF_2_IMG",
        "aspectRatio": aspect_ratio,
        "resolution": resolution,
        "n": max(1, min(int(num_images), 4)),
        "inputImageList": input_image_list,
        "optimizePrompt": kwargs.get("optimize_prompt", True),
    }
    if negative_prompt:
        payload["negativePrompt"] = negative_prompt
    if kwargs.get("quality"):
        payload["quality"] = kwargs["quality"]
    if kwargs.get("seed") is not None:
        payload["seed"] = kwargs["seed"]

    record_id = _submit(payload, api_key, base_url)
    logger.info("Wuli 图生图任务提交成功 recordId=%s", record_id)
    results = _poll(record_id, api_key, base_url, kwargs.get("poll_timeout", DEFAULT_POLL_TIMEOUT))

    urls = [r["imageUrl"] for r in results if r.get("imageUrl")]
    if kwargs.get("no_watermark"):
        resource_ids = [r.get("imageId") for r in results if r.get("imageId")]
        urls = _fetch_no_watermark(resource_ids, api_key, base_url) or urls

    return _download_all(urls, output_dir)


def list_models(api_key: str = "") -> list:
    """返回平台支持的图像模型名称列表。"""
    return list(WULI_IMAGE_MODELS)


def generate(prompt: str, output_dir: str, model: str = "", negative_prompt: str = "",
             resolution: str = "1K", aspect_ratio: str = "1:1", num_images: int = 1,
             ref_images: list = None, api_key: str = "", **kwargs) -> list:
    """统一入口: 存在参考图走图生图, 否则文生图。供 imagegen 引擎调度。"""
    api_key = _get_api_key(api_key)
    if not api_key:
        logger.error("Wuli: 未配置 API Key (接口设置或环境变量 WULI_API_KEY), 无法生成图像。")
        return []
    ref_images = ref_images or []
    if ref_images:
        return image_to_image(
            prompt, ref_images, output_dir, model=model, negative_prompt=negative_prompt,
            resolution=resolution, aspect_ratio=aspect_ratio, num_images=num_images,
            api_key=api_key, **kwargs,
        )
    return text_to_image(
        prompt, output_dir, model=model, negative_prompt=negative_prompt,
        resolution=resolution, aspect_ratio=aspect_ratio, num_images=num_images,
        api_key=api_key, **kwargs,
    )
