#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Seedream 适配层：将 VideoLingo 生图调用映射为 Seedream 原生请求体。

VideoLingo 通过 imagegen_factory.SDKImageGen 调用本模块的 ``generate(...)``，约定签名与
kieai / bailian / wuli 等 wrapper 一致，返回本地文件路径列表。

支持的 mode（由上游传参决定）：
  txt2img   文生图（单图）
  img2img   图生图（单张参考图，单图）
  fusion    多图融合（多张参考图，单图）
  grid      文生组图（sequential_image_generation=auto）
  i2grid    单图生组图（sequential_image_generation=auto）
  refs2grid 多图生组图（sequential_image_generation=auto）
  websearch 联网搜索生图（tools=[{type:web_search}]）

专属参数（经 kwargs / extra_args 透传）：
  size / output_format / watermark / background / layer_decomposition /
  optimize_prompt_options_mode / stream
"""
import math
import logging

from backend.imagegen.sdk import seedream_sdk

logger = logging.getLogger(__name__)

# 组图类 mode
_GRID_MODES = {"grid", "i2grid", "refs2grid"}

# 各模型支持的分辨率档位，用于兜底修正不合法档位
_MODEL_SIZE_TIERS = {
    "doubao-seedream-5-0-pro": ["1K", "1.5K", "2K"],
    "doubao-seedream-5-0-lite": ["2K", "3K", "4K"],
    "doubao-seedream-4-5": ["2K", "4K"],
    "doubao-seedream-4-0": ["1K", "2K", "4K"],
}

# 所有常见宽高比（UI 展示 + 用于换算像素尺寸）
ALL_ASPECT_RATIOS = [
    "1:1", "16:9", "9:16", "4:3", "3:4",
    "3:2", "2:3", "21:9", "2:1", "1:2", "5:4", "4:5",
]

# Seedream 原生 size 像素约束（方式二：{宽}x{高}）
_MIN_PIXELS = 3_686_400   # 3686400
_MAX_PIXELS = 16_777_216  # 16777216

# 分辨率档位 -> 正方形基准边长（px）
_RESOLUTION_BASE = {
    "1K": 1024,
    "1.5K": 1536,
    "2K": 2048,
    "3K": 3072,
    "4K": 4096,
}


def _pick_size(model: str, resolution: str) -> str:
    """根据模型支持档位修正 resolution（避免 lite 收到 1K 之类非法值）。"""
    res = resolution or "2K"
    if not model:
        return res
    prefix = model
    for k in _MODEL_SIZE_TIERS:
        if model.startswith(k):
            prefix = k
            break
    tiers = _MODEL_SIZE_TIERS.get(prefix)
    if not tiers:
        return res
    if res in tiers:
        return res
    # 不在支持档位内时就近回落
    if res == "1K" and "1K" not in tiers:
        return tiers[0]
    if res == "4K" and "4K" not in tiers:
        return tiers[-1]
    return tiers[0]


def _parse_ratio(aspect_ratio: str):
    """解析 'a:b' 为 (a, b)，非法返回 (1, 1)。"""
    if not aspect_ratio or ":" not in aspect_ratio:
        return (1, 1)
    try:
        a, b = aspect_ratio.split(":")
        a, b = int(a), int(b)
        if a <= 0 or b <= 0:
            return (1, 1)
        return (a, b)
    except Exception:
        return (1, 1)


def _resolve_size(model: str, resolution: str, aspect_ratio: str) -> str:
    """把 (分辨率档位 + 宽高比) 换算为 Seedream 原生 size 像素字符串 'WxH'。

    Seedream 原生没有 aspect_ratio 参数，宽高比只能通过 size 的像素维度表达。
    返回如 '2848x1600'（2K 16:9）。超出像素总量限制时按比例缩放，保证合法。
    """
    tier = _pick_size(model, resolution or "2K")
    base = _RESOLUTION_BASE.get(tier, 2048)
    a, b = _parse_ratio(aspect_ratio)
    ratio = a / b
    w = base * math.sqrt(ratio)
    h = base / math.sqrt(ratio)
    # 约束到合法像素总量区间（保持比例不变地整体缩放）
    total = w * h
    if total < _MIN_PIXELS:
        scale = math.sqrt(_MIN_PIXELS / total)
        w *= scale
        h *= scale
    elif total > _MAX_PIXELS:
        scale = math.sqrt(_MAX_PIXELS / total)
        w *= scale
        h *= scale
    # 对齐到 16 的倍数（Seedream 推荐对齐粒度）
    w = max(64, int(round(w / 16.0) * 16))
    h = max(64, int(round(h / 16.0) * 16))
    return f"{w}x{h}"


def _raise_or_return(msg: str, raise_on_error: bool):
    if raise_on_error:
        raise RuntimeError(msg)
    logger.error("Seedream: %s", msg)
    return []


def generate(prompt, output_dir, model="", negative_prompt="", resolution="1K",
             aspect_ratio="1:1", num_images=1, ref_images=None, api_key="",
             mode="txt2img", on_progress=None, raise_on_error=False, **kwargs):
    """
    VideoLingo 生图统一入口（Seedream 适配）。

    Args:
        prompt: 文本提示词
        output_dir: 落盘目录
        model: Seedream 模型 ID（如 doubao-seedream-5-0-lite-260128）
        negative_prompt: 负向提示词（Seedream 原生不支持，忽略）
        resolution: 分辨率档位（1K/1.5K/2K 或 2K/3K/4K，按模型）
        aspect_ratio: 宽高比（如 16:9，会换算进 size 的像素维度，原生无独立参数）
        num_images: 期望生成数量（组图生效）
        ref_images: 参考图（本地路径 / http(s) URL / data URI 列表）
        api_key: 火山方舟 API Key（ARK_API_KEY 环境变量可兜底）
        mode: txt2img / img2img / fusion / grid / i2grid / refs2grid / websearch
        **kwargs: size / output_format / watermark / background /
                  layer_decomposition / optimize_prompt_options_mode / stream / timeout
    Returns:
        本地文件路径列表
    """
    api_key = seedream_sdk._get_api_key(api_key)
    if not api_key:
        return _raise_or_return(
            "未配置 API Key（接口设置或环境变量 ARK_API_KEY）", raise_on_error)

    model = model or seedream_sdk.DEFAULT_MODEL
    is_grid = mode in _GRID_MODES
    is_websearch = mode == "websearch"
    has_refs = bool(ref_images)

    body = {
        "model": model,
        "prompt": prompt,
        "size": _resolve_size(model, resolution, aspect_ratio),
    }

    # 参考图（img2img / fusion / i2grid / refs2grid）
    if has_refs:
        image_value, err = seedream_sdk._build_image_field(ref_images, api_key)
        if err:
            return _raise_or_return(str(err), raise_on_error)
        if image_value is None:
            return _raise_or_return("没有有效的参考图", raise_on_error)
        body["image"] = image_value

    # 组图
    if is_grid:
        body["sequential_image_generation"] = "auto"
        body["sequential_image_generation_options"] = {
            "max_images": max(1, min(int(num_images or 1), 15)),
        }

    # 联网搜索
    if is_websearch:
        body["tools"] = [{"type": "web_search"}]

    # 图层拆分（仅 5.0 pro，单图输入）
    if kwargs.get("layer_decomposition"):
        body["layer_decomposition"] = True
        if not body.get("size"):
            body["size"] = "auto"

    # 透明背景（仅 5.0 pro 图生图）
    bg = kwargs.get("background")
    if bg in ("transparent", "opaque"):
        body["background"] = bg

    # 输出格式 / 水印
    body["output_format"] = kwargs.get("output_format") or "png"
    body["watermark"] = bool(kwargs.get("watermark", False))

    # 提示词优化
    opm = kwargs.get("optimize_prompt_options_mode") or kwargs.get("optimize_prompt")
    if opm in ("standard", "fast"):
        body["optimize_prompt_options"] = {"mode": opm}
    elif opm is True or opm == "true":
        body["optimize_prompt_options"] = {"mode": "standard"}

    # 流式（5.0 lite / 4.5 / 4.0 支持；5.0 pro 不支持，强制关闭）
    stream = bool(kwargs.get("stream", False))
    if model.startswith("doubao-seedream-5-0-pro"):
        stream = False

    logger.info(
        "Seedream: mode=%s model=%s size=%s grid=%s websearch=%s stream=%s",
        mode, model, body["size"], is_grid, is_websearch, stream,
    )

    return seedream_sdk.generate_image(
        body,
        api_key=api_key,
        stream=stream,
        timeout=int(kwargs.get("timeout", 600) or 600),
        save_dir=output_dir,
        on_progress=on_progress,
        raise_on_error=raise_on_error,
    )


def list_models(api_key: str = ""):
    """返回已知 Seedream 模型 ID 列表。"""
    return seedream_sdk.list_models(api_key)
