#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KIE AI image-generation wrapper, bridged to our built KIE AI SDK.

This module is the ``sdk_function`` entry point consumed by the image-generation
factory (``backend.imagegen.imagegen_factory.SDKImageGen``).  Every image
generation call is delegated to :class:`backend.kieai_sdk.kieai.KieClient`,
which handles async task submission, polling and result download/persistence.

Key resolution follows the SDK's 3-tier fallback (caller key ->
``secret://KIEAI_API_KEY`` -> ``KIEAI_API_KEY`` env var).  The factory already
resolves ``secret://KIEAI_API_KEY`` and forwards the real key via ``api_key``,
but the fallback keeps the wrapper usable in any context.

The factory contract (see ``ImageGenBase.generate``) passes:
    prompt, output_dir, model, negative_prompt, resolution, aspect_ratio,
    num_images, ref_images, mode, api_key (+ custom_params via sdk_extra_args).

Proxy handling: the SDK creates ``aiohttp.ClientSession()`` internally, which
defaults to ``trust_env=False`` and therefore ignores both the proxy environment
variables and the Windows system proxy (Internet Options).  KIE is an overseas
service that usually needs a local proxy (Clash etc.), so this wrapper injects
its own ``trust_env=True`` session via the SDK's ``session=`` parameter.
"""
import os
import asyncio
import base64
import logging
import mimetypes
import urllib.request
from contextlib import asynccontextmanager

from backend.kieai_sdk.kieai import KieClient

logger = logging.getLogger(__name__)

# Host used for the (optional) balance query.
_KIE_API_BASE = "https://api.kie.ai"

# Map resolution shorthand -> quality parameter, for models that take ``quality``
# instead of ``resolution`` (e.g. Seedream 5-lite).
RESOLUTION_TO_QUALITY = {
    "1K": "basic",
    "2K": "basic",
    "4K": "high",
}

# Candidate image-input parameter names, used to detect img2img / edit models
# and to map uploaded reference images onto the model's expected field.
_IMAGE_PARAMS = (
    "input_urls", "image_urls", "image_url", "image_input", "input_image",
    "reference_image_urls", "filesUrl", "fileUrl", "image", "input",
)

_DEFAULT_MODEL = "seedream/5-lite-text-to-image"


def _effective_proxy() -> str:
    """解析出网应使用的代理 URL（无则空串）：环境变量优先，其次 Windows 系统代理。

    ``urllib.request.getproxies()`` 是「环境变量 **OR** 注册表」的短路取值：只要环境里存在
    **任何**以 ``_proxy`` 结尾的变量——连 ``NO_PROXY`` 都算（被收成 ``{'no': ...}``）——它就
    只返回环境代理、**不再读取系统代理**（Internet 选项）。于是会出现「明明开着 Clash 系统
    代理，程序却直连超时」的怪象。这里显式合并两层，绕开该遮蔽。
    """
    try:
        env = urllib.request.getproxies_environment()
    except Exception:  # noqa: BLE001
        env = {}
    for key in ("https", "http", "all"):
        if env.get(key):
            return env[key]
    # 注册表读取函数仅在 Windows 存在
    registry_getter = getattr(urllib.request, "getproxies_registry", None)
    if registry_getter is not None:
        try:
            registry = registry_getter()
        except Exception:  # noqa: BLE001
            registry = {}
        for key in ("https", "http"):
            if registry.get(key):
                return registry[key]
    return ""


def _build_session():
    """构造尊重代理的 aiohttp 会话。

    KIE SDK 内部用默认的 ``aiohttp.ClientSession()``（``trust_env=False``），既不认代理
    环境变量、也不认 Windows 系统代理，导致直连海外站点超时，因此由调用方注入会话。
    代理地址由 :func:`_effective_proxy` 显式解析后传入：既避免上述 ``getproxies()`` 遮蔽，
    也不再依赖 ``NO_PROXY`` 的绕过逻辑——KIE SDK 只访问外部主机（api.kie.ai 与结果 CDN），
    无需本机绕过。未配置任何代理时行为与默认一致（直连）。
    """
    import aiohttp

    proxy = _effective_proxy()
    if proxy:
        logger.info("KIE AI: 经代理出网 %s", proxy)
    return aiohttp.ClientSession(trust_env=True, proxy=proxy or None)


@asynccontextmanager
async def _kie_client(api_key: str):
    """KieClient + 尊重代理的会话（会话由本模块创建，退出时关闭）。

    ``KieClient`` 仅在未注入 session 时负责关闭（``_owns_session``），
    因此这里必须自己 close。
    """
    session = _build_session()
    try:
        async with KieClient(api_key=api_key or None, session=session) as client:
            yield client
    finally:
        await session.close()


async def _resolve_ref_urls(client: KieClient, ref_images) -> list:
    """Upload local reference images and return their public download URLs."""
    urls: list = []
    for img in (ref_images or []):
        if not isinstance(img, str):
            continue
        if img.startswith("http"):
            urls.append(img)
            continue
        if not os.path.exists(img):
            logger.warning("KIE AI: skipping invalid ref_image: %s", img)
            continue
        mime = mimetypes.guess_type(img)[0] or "image/png"
        try:
            with open(img, "rb") as fh:
                b64 = base64.b64encode(fh.read()).decode()
            up = await client.upload(
                method="base64",
                base64Data=f"data:{mime};base64,{b64}",
                uploadPath="images",
                fileName=os.path.basename(img),
            )
            url = up.get("downloadUrl") or up.get("url") or up.get("fileUrl")
            if url:
                urls.append(url)
            else:
                logger.warning("KIE AI: upload returned no URL: %s", up)
        except Exception as e:  # noqa: BLE001
            logger.warning("KIE AI: upload failed for %s: %s", img, e)
    return urls


def _build_params(entry, *, prompt, aspect_ratio, resolution, negative_prompt,
                  nsfw_checker, num_images, img_param, ref_urls,
                  background="") -> dict:
    """Map factory args onto the SDK model's accepted parameters only."""
    pnames = {p.name for p in entry.params}
    params = {"prompt": prompt}

    # aspect ratio / image size
    if "aspect_ratio" in pnames:
        params["aspect_ratio"] = aspect_ratio
    elif "image_size" in pnames:
        params["image_size"] = aspect_ratio

    # resolution / quality
    if "resolution" in pnames:
        params["resolution"] = resolution
    elif "quality" in pnames:
        params["quality"] = RESOLUTION_TO_QUALITY.get(resolution, "basic")

    if "negative_prompt" in pnames and negative_prompt:
        params["negative_prompt"] = negative_prompt

    if "nsfw_checker" in pnames:
        params["nsfw_checker"] = bool(nsfw_checker)

    # 背景输出模式（transparent / opaque / auto），仅模型支持时透传
    if "background" in pnames and background:
        params["background"] = background

    for np_name in ("num_images", "n", "max_images"):
        if np_name in pnames:
            params[np_name] = num_images
            break

    if img_param and ref_urls:
        params[img_param] = ref_urls if img_param.endswith("s") else ref_urls[0]

    return params


async def generate(prompt, output_dir, model="", negative_prompt="", resolution="1K",
                   aspect_ratio="1:1", num_images=1, ref_images=None, api_key="", **kwargs):
    """
    Generate images via the KIE AI SDK and return local file paths.

    Args:
        prompt: Text prompt for image generation.
        output_dir: Directory to save generated images.
        model: SDK catalog model id (e.g. ``seedream/5-lite-text-to-image``,
            ``flux-2/pro-image-to-image``). Resolved against the catalog.
        negative_prompt: Forwarded only if the model supports it.
        resolution: "1K" / "2K" / "4K" (or mapped to ``quality`` per model).
        aspect_ratio: e.g. "1:1", "16:9", "9:16" ...
        num_images: Number of images (honoured only if the model supports it).
        ref_images: Local paths or HTTP URLs used for img2img / edit models.
        api_key: KIE AI API key (SDK falls back to secret/env otherwise).
        **kwargs: ``nsfw_checker``, ``poll_timeout`` (from sdk_extra_args).

    Returns:
        List of generated image file paths (saved under ``output_dir``).
    """
    model = model or _DEFAULT_MODEL
    nsfw_checker = kwargs.get("nsfw_checker", False)
    background = kwargs.get("background", "")
    poll_timeout = int(kwargs.get("poll_timeout", 600) or 600)

    async with _kie_client(api_key) as client:
        try:
            entry = client.catalog.get(model)
        except Exception as e:  # noqa: BLE001
            logger.error("KIE AI: model not found: %s (%s)", model, e)
            return []

        pnames = {p.name for p in entry.params}
        img_param = next((n for n in _IMAGE_PARAMS if n in pnames), None)

        ref_urls: list = []
        if ref_images and img_param:
            ref_urls = await _resolve_ref_urls(client, ref_images)
            if not ref_urls:
                logger.error("KIE AI: img2img requested but no valid ref images resolved.")
                return []

        params = _build_params(
            entry,
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            negative_prompt=negative_prompt,
            nsfw_checker=nsfw_checker,
            num_images=num_images,
            img_param=img_param,
            ref_urls=ref_urls,
            background=background,
        )

        if poll_timeout:
            client.max_poll = max(1, int(poll_timeout / max(client.poll_interval, 0.1)))

        try:
            result = await client.generate(model, output_path=output_dir, **params)
        except Exception as e:  # noqa: BLE001
            logger.error("KIE AI: generate error: %s", e)
            import traceback
            traceback.print_exc()
            return []

        paths = result.get("local_paths") or []
        if num_images and num_images > 0:
            paths = paths[:num_images]
        return paths


# --------------------------------------------------------------------------- #
# Optional helpers (used by the interface-manager API)
# --------------------------------------------------------------------------- #
def list_models(api_key=""):
    """Return the SDK catalog's image-generation model ids."""
    try:
        client = KieClient(api_key=api_key or None)
        return [
            m.id for m in client.catalog.models
            if (m.category or "").lower() == "image"
        ]
    except Exception as e:  # noqa: BLE001
        logger.warning("KIE AI: list_models failed: %s", e)
        return []


async def _fetch_balance(api_key: str):
    async with _kie_client(api_key) as client:
        url = f"{_KIE_API_BASE}/api/v1/chat/credit"
        try:
            data = await client._get_json(url)
        except Exception as e:  # noqa: BLE001
            logger.warning("KIE AI: balance query failed: %s", e)
            return None
        if isinstance(data, dict) and data.get("code") == 200:
            return data.get("data")
        return None


def get_balance(api_key=""):
    """Return remaining credits/points balance (or ``None`` on failure)."""
    try:
        return asyncio.run(_fetch_balance(api_key))
    except Exception as e:  # noqa: BLE001
        logger.warning("KIE AI: get_balance failed: %s", e)
        return None
