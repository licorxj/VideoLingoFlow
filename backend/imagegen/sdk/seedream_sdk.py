#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""火山引擎方舟 Seedream 生图 SDK（requests 直连）。

直连 POST https://ark.cn-beijing.volces.com/api/v3/images/generations
- 完全自定义请求体，可暴露 Seedream 全部专属参数（tools / sequential_image_generation /
  layer_decomposition / optimize_prompt_options / background 等）。
- 同时支持「非流式」与「流式（SSE）」两种输出模式。
- 鉴权：请求头 ``Authorization: Bearer <API Key>``。

本模块只负责「组装最终请求体 + 调用 + 解析响应 + 落盘」，不感知 VideoLingo 业务概念
（mode / 分辨率档位等由 seedream_wrapper 适配），便于单独复用与测试。
"""
import os
import json
import base64
import logging
import requests
from typing import Callable, Optional

logger = logging.getLogger(__name__)

SEEDREAM_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3/images/generations"

# 已知模型 ID（用户可在 UI 中替换为自己的 Model ID / Endpoint ID）
SEEDREAM_MODELS = [
    "doubao-seedream-5-0-pro-260128",
    "doubao-seedream-5-0-lite-260128",
    "doubao-seedream-4-5-251218",
    "doubao-seedream-4-0-250828",
]
DEFAULT_MODEL = "doubao-seedream-5-0-lite-260128"


def _get_api_key(api_key: str = "") -> str:
    """API Key 取值优先级: 函数参数 > 环境变量 ARK_API_KEY。"""
    return os.environ.get("ARK_API_KEY", "") or api_key


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _build_image_field(ref_images, api_key=None):
    """把 ref_images（本地路径 / http(s) URL / asset:// / data URI）解析为 Seedream 的 ``image`` 字段。

    返回 ``(image_value, error)``。``image_value`` 为 str 或 list[str]；无有效图时返回 ``(None, None)``。

    素材引用规则（Seedream /images/generations 的 image 参数仅接受 URL 或标准 data URI）：
      - http(s) URL / asset:// 原样透传。
      - 标准 ``data:image/<mime>;base64,...`` 原样透传（注意必须是带 image/ 前缀的完整 data URI）。
      - **本地图片读取后以标准 data URI 内联**（务必 `data:image/<mime>;base64,...`，
        缺 image/ 前缀会被接口判为 Invalid base64 image_url）。
    """
    payloads = []
    for img in (ref_images or []):
        if not isinstance(img, str):
            continue
        if (img.startswith("http://") or img.startswith("https://")
                or img.startswith("asset://") or img.startswith("data:image")):
            payloads.append(img)
        elif os.path.exists(img):
            try:
                ext = os.path.splitext(img)[1].lstrip(".").lower() or "png"
                mime = {
                    "jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp",
                    "bmp": "bmp", "gif": "gif", "tiff": "tiff", "heic": "heic",
                }.get(ext, "png")
                with open(img, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                # 注意：必须是 data:image/<mime>;base64,...（带 image/ 前缀），否则报 Invalid base64
                payloads.append(f"data:image/{mime};base64,{b64}")
            except Exception as e:
                logger.warning("Seedream: 读取参考图失败 %s: %s", img, e)
        else:
            logger.warning("Seedream: 忽略无效参考图 %s", img)
    if not payloads:
        return None, None
    return (payloads[0] if len(payloads) == 1 else payloads), None


def _guess_ext(raw: bytes) -> str:
    """根据文件头猜测图片扩展名。"""
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if raw[:3] == b"\xff\xd8\xff":
        return "jpg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return "png"


def _save_one(kind, payload, save_dir, index):
    """保存单张图片（url 或 b64），返回本地路径。"""
    os.makedirs(save_dir, exist_ok=True)
    if kind == "url":
        resp = requests.get(payload, timeout=120, stream=True)
        resp.raise_for_status()
        raw = resp.content
        ct = resp.headers.get("content-type", "")
        ext = ("jpg" if ("jpeg" in ct or "jpg" in ct)
               else "webp" if "webp" in ct else "png")
    else:
        raw = base64.b64decode(payload)
        ext = _guess_ext(raw)
    path = os.path.join(save_dir, f"output_{index}.{ext}")
    with open(path, "wb") as f:
        f.write(raw)
    logger.info("Seedream: 已保存 %s", path)
    return path


def _save_items(items, save_dir):
    """items: list of (kind, payload)，kind='url'|'b64'。落盘并返回路径列表。"""
    saved = []
    for i, (kind, payload) in enumerate(items):
        try:
            saved.append(_save_one(kind, payload, save_dir, i))
        except Exception as e:
            logger.error("Seedream: 保存第 %d 张失败: %s", i, e)
    return saved


def _parse_non_stream(resp, save_dir, layer_capture=False):
    """解析非流式 JSON 响应并落盘。

    layer_capture=True 时返回结构化图层列表（每项含 path / z_index / name /
    bounding_box / description），否则返回图片路径列表。
    """
    try:
        data = resp.json()
    except Exception as e:
        raise RuntimeError(f"Seedream: 响应非 JSON: {e}") from e

    if "error" in data and data["error"]:
        err = data["error"]
        raise RuntimeError(f"Seedream 错误 [{err.get('code')}]: {err.get('message')}")

    items = []
    for item in data.get("data", []) or []:
        if item.get("error"):
            logger.warning("Seedream: 单图失败 [%s] %s",
                           item["error"].get("code"), item["error"].get("message"))
            continue
        kind = None
        payload = None
        if item.get("url"):
            kind, payload = "url", item["url"]
        elif item.get("b64_json"):
            kind, payload = "b64", item["b64_json"]
        if not kind:
            continue
        path = _save_one(kind, payload, save_dir, len(items))
        meta = {
            "path": path,
            "z_index": item.get("z_index"),
            "name": item.get("name"),
            "bounding_box": item.get("bounding_box"),
            "description": item.get("description"),
            "size": item.get("size"),
        }
        items.append(meta)
    if not items:
        raise RuntimeError("Seedream: 响应中无有效图片（可能全部生成失败）")
    if layer_capture:
        return items
    return [it["path"] for it in items]


def _parse_stream(resp, save_dir, on_progress=None):
    """解析流式 SSE 响应，逐张收集成功图，忽略单图失败，遇 completed 结束。

    on_progress(message): 可选回调，每收到一个流式事件时上报一条消息（用于节点进度条下方实时显示）。
    """
    items = []
    count = 0
    for line in resp.iter_lines(decode_unicode=True):
        if not line:
            continue
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            evt = json.loads(payload)
        except Exception:
            continue

        etype = evt.get("type")
        if etype == "image_generation.partial_succeeded":
            count += 1
            if on_progress:
                on_progress(f"流式生成中…已收到第 {count} 张图片")
            if evt.get("url"):
                items.append(("url", evt["url"]))
            elif evt.get("b64_json"):
                items.append(("b64", evt["b64_json"]))
        elif etype == "image_generation.partial_failed":
            err_msg = evt.get("error", {}).get("message") or ""
            logger.warning("Seedream 流式单图失败 [%s]: %s",
                           evt.get("error", {}).get("code"), err_msg)
            if on_progress:
                on_progress(f"第 {count + 1} 张生成失败：{err_msg}")
        elif etype == "image_generation.completed":
            logger.info("Seedream 流式完成 usage=%s", evt.get("usage"))
            if on_progress:
                on_progress(f"流式生成完成（usage={evt.get('usage')}）")
            break
        elif "error" in evt and evt.get("error"):
            err = evt["error"]
            raise RuntimeError(f"Seedream 流式错误 [{err.get('code')}]: {err.get('message')}")
    if not items:
        raise RuntimeError("Seedream: 流式响应中未解析到任何图片")
    return _save_items(items, save_dir)


def generate_image(body: dict, api_key: str = "", stream: bool = False,
                   timeout: int = 120, save_dir: str = "",
                   on_progress: Optional[Callable[[str], None]] = None,
                   raise_on_error: bool = False):
    """底层调用：组装最终请求体、发送、解析响应并落盘。

    Args:
        body: 已组装好的完整请求体（model / prompt / size / ...）。
        api_key: 火山方舟 API Key（ARK_API_KEY 环境变量可兜底）。
        stream: 是否流式（SSE）。
        timeout: 请求超时（秒）。
        save_dir: 落盘目录。
        raise_on_error: 为 True 时任何异常直接抛出，便于节点层展示真实原因；
                        为 False（默认）保持旧行为，失败返回空列表。
    Returns:
        - 普通模式：本地文件路径列表（失败时按 raise_on_error 决定抛异常或返回空列表）。
        - 图层拆分模式（body 含 layer_decomposition=true）：返回 dict
          {"images": [...], "base": path|None, "layers": [{path,z_index,name,
           bounding_box,description}], "coords_path": path}。
    """
    api_key = _get_api_key(api_key)
    if not api_key:
        msg = "未配置 API Key（接口设置或环境变量 ARK_API_KEY）"
        if raise_on_error:
            raise RuntimeError(msg)
        logger.error("Seedream: %s", msg)
        return []

    body = dict(body)
    body["response_format"] = body.get("response_format", "url")
    body["stream"] = stream

    # 调试：打印每次请求的原始参数（剔除任何密钥字段）
    _debug_body = {k: v for k, v in body.items() if k not in ("api_key", "authorization")}
    logger.info(
        "Seedream 请求参数 model=%s endpoint=%s body=%s",
        body.get("model"), SEEDREAM_ENDPOINT,
        json.dumps(_debug_body, ensure_ascii=False),
    )

    try:
        resp = requests.post(
            SEEDREAM_ENDPOINT,
            headers=_headers(api_key),
            json=body,
            timeout=timeout,
            stream=stream,
        )
        if resp.status_code != 200:
            snip = resp.text[:500]
            raise RuntimeError(f"Seedream HTTP {resp.status_code}: {snip}")
        if stream:
            return _parse_stream(resp, save_dir, on_progress=on_progress)
        # 图层拆分：解析并落盘 底图 + 多图层 + 坐标，返回结构化结果
        # 官方契约参考（火山方舟 /api/v3/images/generations）：
        #   请求（输入图为 "image"，单张；layer_decomposition=true）：
        #     {"model":"doubao-seedream-5-0-pro-260628","prompt":"...","image":"https://...",
        #      "layer_decomposition":true,"size":"2K","output_format":"jpeg","response_format":"url","watermark":true}
        #   响应 data[]：
        #     - 底图：z_index=0，无 bounding_box / name / description
        #         {"url":"https://...","size":"2048x2048","output_format":"jpeg","z_index":0}
        #     - 图层：z_index>=1，带 bounding_box(absolute/normalized 均为 [x1,y1,x2,y2])、name、description
        #         {"url":"https://...","size":"1273x265","output_format":"png","z_index":1,
        #          "bounding_box":{"absolute":[383,120,1655,384],"normalized":[187,59,808,188]},
        #          "name":"Seedream标题文字","description":"黄色大号衬线字体的Seedream标题文字"}
        if body.get("layer_decomposition"):
            items = _parse_non_stream(resp, save_dir, layer_capture=True)
            # 底图：z_index==0 的整图项（官方响应中底图不带 bounding_box）；
            # 退化情况下取首个无 bounding_box 的项，再退化取首张
            base_item = next((it for it in items if it.get("z_index") == 0), None)
            if base_item is None:
                base_item = next((it for it in items if not it.get("bounding_box")), None)
            base_item = base_item or (items[0] if items else None)
            layers = [it for it in items if it is not base_item]
            coords = {
                "model": body.get("model"),
                "count": len(layers),
                "items": items,
            }
            coords_path = os.path.join(save_dir, "layers_coords.json")
            try:
                with open(coords_path, "w", encoding="utf-8") as f:
                    json.dump(coords, f, ensure_ascii=False, indent=2)
                logger.info("Seedream: 已保存图层坐标数据 %s", coords_path)
            except Exception as e:
                logger.error("Seedream: 保存坐标数据失败: %s", e)
                coords_path = ""
            return {
                "images": [it["path"] for it in items],
                "base": base_item["path"] if base_item else None,
                "layers": layers,
                "coords_path": coords_path,
            }
        return _parse_non_stream(resp, save_dir)
    except Exception as e:
        if raise_on_error:
            raise
        logger.error("Seedream: 调用失败: %s", e)
        import traceback
        traceback.print_exc()
        return []


def list_models(api_key: str = ""):
    """返回已知 Seedream 模型 ID 列表。"""
    return list(SEEDREAM_MODELS)
