#!/usr/bin/env python3
"""KIE AI Image Generation SDK wrapper.

International model proxy supporting Seedream, Grok, GPT-Image, Z-Image, Nano-Banana.
All tasks are async: create task → poll for result → download images.
API key priority: KIEAI_API_KEY env var > api_key parameter (from config).
"""
import os
import time
import base64
import mimetypes
import logging
import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.kie.ai"
UPLOAD_URL = "https://kieai.redpandaai.co/api/file-base64-upload"

# Map t2i model name → corresponding i2i model name
T2I_TO_I2I = {
    "seedream/5-lite-text-to-image": "seedream/5-lite-image-to-image",
    "grok-imagine/text-to-image": "grok-imagine/image-to-image",
    "gpt-image-2-text-to-image": "gpt-image-2-image-to-image",
}

# Map resolution shorthand → quality parameter
RESOLUTION_TO_QUALITY = {
    "1K": "basic",
    "2K": "basic",
    "4K": "high",
}


def _get_api_key(api_key=""):
    """Get API key: env var first, then parameter."""
    return os.environ.get("KIEAI_API_KEY", "") or api_key


def _headers(api_key):
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _upload_image(file_path, api_key):
    """Upload a local image file and return its download URL."""
    mime = mimetypes.guess_type(file_path)[0] or "image/png"
    with open(file_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    ext = os.path.splitext(file_path)[1].lstrip(".") or "png"
    file_name = os.path.basename(file_path)

    payload = {
        "base64Data": f"data:{mime};base64,{b64}",
        "uploadPath": "images/base64",
        "fileName": file_name,
    }

    resp = requests.post(
        UPLOAD_URL,
        json=payload,
        headers=_headers(api_key),
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Upload failed: HTTP {resp.status_code} - {resp.text[:200]}")

    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"Upload failed: {data.get('msg', 'unknown error')}")

    url = data.get("data", {}).get("downloadUrl", "")
    if not url:
        raise RuntimeError("Upload succeeded but no downloadUrl returned")
    return url


def _resolve_image_urls(ref_images, api_key):
    """Convert local file paths to URLs; pass through HTTP URLs as-is."""
    urls = []
    for img in (ref_images or []):
        if not isinstance(img, str):
            continue
        if img.startswith("http"):
            urls.append(img)
        elif os.path.exists(img):
            url = _upload_image(img, api_key)
            urls.append(url)
        else:
            logger.warning(f"KIE AI: skipping invalid ref_image: {img}")
    return urls


def _resolve_model(model, mode):
    """Resolve model name based on mode (t2i/i2i)."""
    if mode in ("img2img", "i2i"):
        i2i_model = T2I_TO_I2I.get(model)
        if i2i_model:
            return i2i_model
        # If model is already an i2i model or unknown, use as-is
        return model
    return model


def _create_task(api_key, model, prompt, aspect_ratio, quality,
                 image_urls=None, nsfw_checker=False):
    """Create an async generation task. Returns task_id."""
    body = {
        "model": model,
        "input": {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "quality": quality,
            "nsfw_checker": nsfw_checker,
        },
    }
    if image_urls:
        body["input"]["image_urls"] = image_urls

    resp = requests.post(
        f"{BASE_URL}/api/v1/jobs/createTask",
        json=body,
        headers=_headers(api_key),
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Create task failed: HTTP {resp.status_code} - {resp.text[:200]}")

    data = resp.json()
    if data.get("code") != 200:
        raise RuntimeError(f"Create task error: {data.get('code')} - {data.get('msg', '')}")

    task_id = data.get("data", {}).get("taskId", "")
    if not task_id:
        raise RuntimeError(f"No taskId in response: {data}")
    return task_id


def _poll_task(api_key, task_id, timeout=600):
    """Poll task until success/fail. Returns result URLs list."""
    start = time.time()
    interval = 2

    while time.time() - start < timeout:
        try:
            resp = requests.get(
                f"{BASE_URL}/api/v1/jobs/recordInfo",
                params={"taskId": task_id},
                headers=_headers(api_key),
                timeout=15,
            )
            if resp.status_code != 200:
                logger.warning(f"KIE AI poll: HTTP {resp.status_code}")
                time.sleep(interval)
                continue

            data = resp.json()
            task_data = data.get("data", {})
            state = task_data.get("state", "")

            if state == "success":
                result_json = task_data.get("resultJson", "{}")
                import json
                try:
                    result = json.loads(result_json)
                except (json.JSONDecodeError, TypeError):
                    result = {}
                urls = result.get("resultUrls", [])
                if urls:
                    logger.info(f"KIE AI: task {task_id} completed, {len(urls)} images")
                    return urls
                logger.warning(f"KIE AI: task success but no resultUrls: {result_json[:200]}")
                return []

            if state == "fail":
                fail_msg = task_data.get("failMsg", "unknown")
                fail_code = task_data.get("failCode", "")
                raise RuntimeError(f"Task failed: [{fail_code}] {fail_msg}")

            # Still processing: waiting / queuing / generating
            elapsed = time.time() - start
            if elapsed < 30:
                interval = 3
            elif elapsed < 120:
                interval = 7
            else:
                interval = 20

            time.sleep(interval)

        except requests.exceptions.RequestException as e:
            logger.warning(f"KIE AI poll error: {e}")
            time.sleep(interval)

    raise RuntimeError(f"Task {task_id} timed out after {timeout}s")


def _download_image(url, save_path):
    """Download image from URL to local file."""
    resp = requests.get(url, timeout=120, stream=True)
    resp.raise_for_status()
    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    with open(save_path, "wb") as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)
    return save_path


def generate(prompt, output_dir, model="", negative_prompt="", resolution="1K",
             aspect_ratio="1:1", num_images=1, ref_images=None, api_key="", **kwargs):
    """
    Generate images using KIE AI international model proxy.

    Args:
        prompt: Text prompt for image generation
        output_dir: Directory to save generated images
        model: Model ID (e.g. 'seedream/5-lite-text-to-image', 'grok-imagine/text-to-image')
        negative_prompt: Not used (KIE API does not support)
        resolution: "1K" (basic/2K) or "4K" (high/3K-4K)
        aspect_ratio: "1:1", "16:9", "21:9", "2:3", "3:2", "3:4", "4:3", "9:16"
        num_images: Number of images (model dependent, usually 1)
        ref_images: List of reference image paths or URLs (for img2img)
        api_key: KIE AI API key (KIEAI_API_KEY env takes priority)
        **kwargs: Extra params (quality, nsfw_checker, poll_timeout)

    Returns:
        List of generated image file paths
    """
    api_key = _get_api_key(api_key)
    if not api_key:
        logger.error("KIE AI: no API key. Set KIEAI_API_KEY env or configure in interface settings.")
        return []

    model = model or "seedream/5-lite-text-to-image"
    is_img2img = bool(ref_images)
    mode = "img2img" if is_img2img else "txt2img"

    # Resolve model name for mode
    resolved_model = _resolve_model(model, mode)

    # Resolve quality from resolution
    quality = kwargs.get("quality") or RESOLUTION_TO_QUALITY.get(resolution, "basic")
    nsfw_checker = kwargs.get("nsfw_checker", False)
    poll_timeout = kwargs.get("poll_timeout", 600)

    try:
        # Upload reference images if needed
        image_urls = None
        if is_img2img:
            image_urls = _resolve_image_urls(ref_images, api_key)
            if not image_urls:
                logger.error("KIE AI: img2img requires valid image URLs, none provided.")
                return []

        # Create task
        logger.info(f"KIE AI: creating task model={resolved_model} quality={quality} ratio={aspect_ratio}")
        task_id = _create_task(
            api_key, resolved_model, prompt, aspect_ratio, quality,
            image_urls=image_urls, nsfw_checker=nsfw_checker,
        )
        logger.info(f"KIE AI: task created: {task_id}")

        # Poll for result
        result_urls = _poll_task(api_key, task_id, timeout=poll_timeout)
        if not result_urls:
            return []

        # Download images
        os.makedirs(output_dir, exist_ok=True)
        saved = []
        for i, url in enumerate(result_urls[:num_images]):
            try:
                path = os.path.join(output_dir, f"output_{i}.png")
                _download_image(url, path)
                saved.append(path)
                logger.info(f"KIE AI: saved image {i} -> {path}")
            except Exception as dl_err:
                logger.error(f"KIE AI: download image {i} failed: {dl_err}")

        return saved

    except Exception as e:
        logger.error(f"KIE AI: generate error: {e}")
        import traceback
        traceback.print_exc()
        return []


def get_balance(api_key=""):
    """Get remaining credits/points balance."""
    api_key = _get_api_key(api_key)
    if not api_key:
        return None
    try:
        resp = requests.get(
            f"{BASE_URL}/api/v1/chat/credit",
            headers=_headers(api_key),
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 200:
                return data.get("data")
        return None
    except Exception as e:
        logger.error(f"KIE AI: get balance error: {e}")
        return None


def list_models(api_key=""):
    """List available models."""
    return [
        "seedream/5-lite-text-to-image",
        "seedream/5-lite-image-to-image",
        "z-image",
        "nano-banana-2",
        "grok-imagine/text-to-image",
        "grok-imagine/image-to-image",
        "gpt-image-2-text-to-image",
        "gpt-image-2-image-to-image",
    ]
