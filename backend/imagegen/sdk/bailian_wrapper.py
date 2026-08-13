#!/usr/bin/env python3
"""Alibaba Bailian (DashScope) Image Generation SDK wrapper.

Supports Wan (万相) and Qwen (千问) model families via dashscope Python SDK.
API key priority: DASHSCOPE_API_KEY env var > api_key parameter (from config).
"""
import os
import base64
import mimetypes
import logging
import requests

logger = logging.getLogger(__name__)

# Models that support shorthand size (1K/2K/4K)
WAN_SIZE_SHORTHAND = {"wan2.7-image-pro", "wan2.7-image"}

# Fixed size presets for qwen-image-max / qwen-image-plus / qwen-image
QWEN_FIXED_SIZES = {
    "16:9": "1664*928",
    "4:3": "1472*1104",
    "1:1": "1328*1328",
    "3:4": "1104*1472",
    "9:16": "928*1664",
}

RESOLUTION_BASE = {"1K": 1024, "2K": 2048, "4K": 4096}


def _get_api_key(api_key=""):
    """Get API key: env var first, then parameter."""
    return os.environ.get("DASHSCOPE_API_KEY", "") or api_key


def _is_wan_model(model):
    """Check if model belongs to Wan (万相) family."""
    return model.startswith("wan")


def _calc_size(resolution, aspect_ratio):
    """Calculate pixel size string 'W*H' from resolution shorthand and aspect ratio."""
    base = RESOLUTION_BASE.get(resolution, 1024)
    ratio_map = {
        "1:1": (1, 1), "16:9": (16, 9), "9:16": (9, 16),
        "4:3": (4, 3), "3:4": (3, 4), "3:2": (3, 2), "2:3": (2, 3),
    }
    rw, rh = ratio_map.get(aspect_ratio, (1, 1))
    if rw >= rh:
        w, h = base, int(base * rh / rw)
    else:
        h, w = base, int(base * rw / rh)
    w = max(512, (w // 64) * 64)
    h = max(512, (h // 64) * 64)
    return f"{w}*{h}"


def _get_size(model, resolution, aspect_ratio):
    """Get the size string for API call based on model capabilities."""
    # Wan 2.7 models support shorthand for 1:1
    if model in WAN_SIZE_SHORTHAND and aspect_ratio == "1:1":
        return resolution  # "1K", "2K", "4K"
    # Wan 2.7 models with non-1:1 ratio use shorthand (model handles it)
    if model in WAN_SIZE_SHORTHAND:
        return resolution
    # qwen-image-max/plus/image use fixed presets
    if model in ("qwen-image-max", "qwen-image-plus", "qwen-image"):
        return QWEN_FIXED_SIZES.get(aspect_ratio, "1328*1328")
    # Others: calculate from resolution + aspect_ratio
    return _calc_size(resolution, aspect_ratio)


def _build_messages(prompt, ref_images=None):
    """Build messages array for DashScope API."""
    content = [{"text": prompt}]
    if ref_images:
        for img_path in ref_images:
            if isinstance(img_path, str) and os.path.exists(img_path):
                mime = mimetypes.guess_type(img_path)[0] or "image/png"
                with open(img_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                content.insert(0, {"image": f"data:{mime};base64,{b64}"})
            elif isinstance(img_path, str) and img_path.startswith("http"):
                content.insert(0, {"image": img_path})
    return [{"role": "user", "content": content}]


def _download_image(url, save_path):
    """Download image from URL to local file."""
    resp = requests.get(url, timeout=120, stream=True)
    resp.raise_for_status()
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    with open(save_path, "wb") as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)
    return save_path


def _extract_image_urls(response):
    """Extract image URLs from DashScope response object."""
    urls = []
    try:
        output = response.output
        choices = getattr(output, "choices", []) or []
        for choice in choices:
            msg = getattr(choice, "message", None)
            if not msg:
                continue
            content = getattr(msg, "content", []) or []
            for item in content:
                if isinstance(item, dict):
                    url = item.get("image", "")
                    if url:
                        urls.append(url)
                else:
                    url = getattr(item, "image", "")
                    if url:
                        urls.append(url)
    except Exception as e:
        logger.error(f"Bailian: extract URLs error: {e}")
    return urls


def _call_wan(api_key, model, messages, size_str, num_images, **kwargs):
    """Call Wan (万相) model via ImageGeneration API."""
    from dashscope.aigc.image_generation import ImageGeneration

    params = {
        "model": model,
        "api_key": api_key,
        "messages": messages,
        "n": min(num_images, 4),
        "size": size_str,
    }

    # Wan 2.7 specific params
    if model in ("wan2.7-image-pro", "wan2.7-image"):
        params["thinking_mode"] = kwargs.get("thinking_mode", True)
        params["enable_sequential"] = False

    logger.info(f"Bailian Wan: {model} size={size_str} n={num_images}")
    response = ImageGeneration.call(**params)

    if response.status_code != 200:
        logger.error(f"Bailian Wan error: {response.code} - {response.message}")
        return []

    return _extract_image_urls(response)


def _call_qwen(api_key, model, messages, size_str, num_images, negative_prompt, **kwargs):
    """Call Qwen (千问) model via MultiModalConversation API."""
    from dashscope import MultiModalConversation

    params = {
        "api_key": api_key,
        "model": model,
        "messages": messages,
        "stream": False,
        "watermark": kwargs.get("watermark", False),
        "size": size_str,
    }

    if negative_prompt:
        params["negative_prompt"] = negative_prompt

    # prompt_extend for non-edit models
    if not model.startswith("qwen-image-edit"):
        params["prompt_extend"] = kwargs.get("prompt_extend", True)

    # n param (not for max/plus/image base)
    if model not in ("qwen-image-max", "qwen-image-plus", "qwen-image", "qwen-image-edit"):
        params["n"] = min(num_images, 6)

    logger.info(f"Bailian Qwen: {model} size={size_str} n={num_images}")
    response = MultiModalConversation.call(**params)

    if response.status_code != 200:
        logger.error(f"Bailian Qwen error: {response.code} - {response.message}")
        return []

    return _extract_image_urls(response)


def generate(prompt, output_dir, model="", negative_prompt="", resolution="1K",
             aspect_ratio="1:1", num_images=1, ref_images=None, api_key="", **kwargs):
    """
    Generate images using Alibaba Bailian (DashScope) API.

    Args:
        prompt: Text prompt for image generation
        output_dir: Directory to save generated images
        model: Model ID (e.g. 'wan2.7-image-pro', 'qwen-image-2.0-pro')
        negative_prompt: Negative prompt (mainly for Qwen models)
        resolution: "1K", "2K", or "4K"
        aspect_ratio: "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"
        num_images: Number of images to generate (1-4 for Wan, 1-6 for Qwen)
        ref_images: List of reference image paths or URLs (for img2img)
        api_key: DashScope API key (DASHSCOPE_API_KEY env takes priority)
        **kwargs: Extra params (prompt_extend, watermark, thinking_mode, base_url)

    Returns:
        List of generated image file paths
    """
    api_key = _get_api_key(api_key)
    if not api_key:
        logger.error("Bailian: no API key. Set DASHSCOPE_API_KEY env or configure in interface settings.")
        return []

    model = model or "wan2.7-image-pro"
    size_str = _get_size(model, resolution, aspect_ratio)
    messages = _build_messages(prompt, ref_images or [])

    try:
        import dashscope
        dashscope.base_http_api_url = kwargs.get(
            "base_url", "https://dashscope.aliyuncs.com/api/v1"
        )

        if _is_wan_model(model):
            image_urls = _call_wan(api_key, model, messages, size_str, num_images, **kwargs)
        else:
            image_urls = _call_qwen(
                api_key, model, messages, size_str, num_images, negative_prompt, **kwargs
            )

        if not image_urls:
            logger.warning("Bailian: no images returned from API.")
            return []

        # Download images to output_dir
        os.makedirs(output_dir, exist_ok=True)
        saved = []
        for i, url in enumerate(image_urls):
            try:
                ext = "png"
                path = os.path.join(output_dir, f"output_{i}.{ext}")
                _download_image(url, path)
                saved.append(path)
                logger.info(f"Bailian: saved image {i} -> {path}")
            except Exception as dl_err:
                logger.error(f"Bailian: download image {i} failed: {dl_err}")

        return saved

    except ImportError:
        logger.error("Bailian: 'dashscope' package not installed. Run: pip install dashscope")
        return []
    except Exception as e:
        logger.error(f"Bailian: generate error: {e}")
        import traceback
        traceback.print_exc()
        return []


def list_models(api_key=""):
    """List available models (static list from docs)."""
    return [
        "wan2.7-image-pro",
        "wan2.7-image",
        "z-image-turbo",
        "qwen-image-2.0-pro",
        "qwen-image-2.0",
        "qwen-image-max",
        "qwen-image-plus",
        "qwen-image-edit-max",
        "qwen-image-edit-plus",
    ]
