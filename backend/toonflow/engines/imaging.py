# -*- coding: utf-8 -*-
"""图像处理适配：源系统 sharp 沙盒工具（vm.ts）→ Pillow，行为逐条对齐。

    zip_image(data, size)              压缩到目标字节内（JPEG quality 从 80 步进 -10，下限 10）
    zip_image_resolution(data, w, h)   缩放到指定分辨率（sharp resize 默认 cover 裁切）
    merge_images(list, max_size)       横向拼接（等高、按宽高比定宽、白底、q90），并压缩到限额
    compress_to_size(buf, max_bytes)   拼接压缩（quality 90 步进 -10，耗尽后 scale×0.8 循环）
    url_to_base64(path_or_url)         本地路径/URL → 有头 base64

输入兼容：本地路径 / data URI / http(s) URL（经 engines.base.materialize_input 物化）。
"""
import base64
import io
import re
from pathlib import Path

from PIL import Image

from backend.toonflow.engines.base import materialize_input


def _load_image(data) -> Image.Image:
    """加载输入：data URI / 本地路径 / URL。"""
    v = str(data)
    if v.startswith("data:"):
        b64 = v.split(",", 1)[1]
        return Image.open(io.BytesIO(base64.b64decode(b64)))
    if v.startswith(("http://", "https://")) or Path(v).is_file():
        return Image.open(materialize_input(v, Path("data") / "toonflow" / "tmp"))
    raise ValueError(f"无法识别的图片输入: {v[:60]}")


def _to_data_uri(img: Image.Image, quality: int = 90) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _parse_size(size: str) -> int:
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(kb|mb|gb|b)?$", (size or "").lower())
    if not m:
        raise ValueError(f"无效的大小格式: {size}")
    value = float(m.group(1))
    unit = (m.group(2) or "b")
    multiplier = {"b": 1, "kb": 1024, "mb": 1024 * 1024, "gb": 1024 * 1024 * 1024}[unit]
    return int(value * multiplier)


def zip_image(data, size: int) -> str:
    """压缩图片到不高于 size 字节（quality 80 → 步进 -10，下限 10）。对齐源 zipImage。"""
    img = _load_image(data)
    quality = 80
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    while buf.tell() > size and quality > 10:
        quality -= 10
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def zip_image_resolution(data, width: int, height: int) -> str:
    """缩放到指定分辨率（cover 裁切语义，对齐 sharp .resize(w, h)）。"""
    img = _load_image(data)
    resized = img.resize((int(width), int(height)), Image.LANCZOS)
    return _to_data_uri(resized)


def url_to_base64(data) -> str:
    """本地路径/URL/data URI → 有头 base64（保留原始格式）。"""
    v = str(data)
    if v.startswith("data:"):
        return v
    if v.startswith(("http://", "https://")):
        import requests

        resp = requests.get(v, timeout=60)
        resp.raise_for_status()
        mime = resp.headers.get("content-type", "image/jpeg").split(";")[0]
        return f"data:{mime};base64," + base64.b64encode(resp.content).decode()
    p = Path(v)
    if not p.is_file():
        raise ValueError(f"文件不存在: {v}")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "webp": "image/webp", "gif": "image/gif"}.get(p.suffix.lower().lstrip("."), "image/jpeg")
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


def compress_to_size(img: Image.Image, max_bytes: int, width: int, height: int):
    """压缩到限额：quality 90 步进 -10，耗尽后回 90 并 scale×0.8（对齐源实现）。"""
    quality, scale = 90, 1.0
    while True:
        target = (max(1, round(width * scale)), max(1, round(height * scale)))
        buf = io.BytesIO()
        img.resize(target, Image.LANCZOS).convert("RGB").save(buf, format="JPEG", quality=quality)
        if buf.tell() <= max_bytes:
            return buf.getvalue()
        if quality > 10:
            quality -= 10
        else:
            quality = 90
            scale *= 0.8


def merge_images(data_list: list, max_size: str = "10mb") -> str:
    """多图横向等高拼接（按宽高比定宽、白底、fit cover），并压缩到限额。

    返回无头 base64（对齐源 mergeImages 返回值）。
    """
    if not data_list:
        raise ValueError("图片列表不能为空")
    max_bytes = _parse_size(max_size)
    images = [_load_image(d) for d in data_list]
    max_height = max(im.height for im in images)
    widths = [round(max_height * (im.width / max(im.height, 1))) for im in images]
    total_width = sum(widths)

    canvas = Image.new("RGBA", (total_width, max_height), (255, 255, 255, 255))
    x = 0
    for im, w in zip(images, widths):
        piece = im.resize((w, max_height), Image.LANCZOS)  # cover：比例不变 + 居中裁切
        if piece.width != w or piece.height != max_height:
            piece = im.resize((max(w, 1), max_height), Image.LANCZOS)
        canvas.paste(piece.convert("RGBA"), (x, 0))
        x += w

    data = compress_to_size(canvas, max_bytes, total_width, max_height)
    return base64.b64encode(data).decode()
