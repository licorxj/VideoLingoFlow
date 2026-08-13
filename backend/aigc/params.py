"""AIGC 节点公共参数解析：多图输入组装、分辨率/比例/生成数量解析。

供 aigc_comfyui / aigc_runninghub / aigc_jimeng 三个节点步骤共用，
保证三个接口的输入输出与参数行为一致。
"""
import os
import re

# 图片输入端口顺序（与 builtin_node_types.py 中三个节点 inputs 定义保持一致）
IMG_INPUT_KEYS = ["first_frame", "image2", "image3", "image4", "last_frame"]

# 参考视频输入端口（与三个节点 inputs 定义保持一致）
VIDEO_INPUT_KEYS = ["reference_video"]

# 分辨率预设（长边像素）
PRESET_RESOLUTIONS = {"1k": 1024, "2k": 2048, "3k": 3072, "4k": 4096}

# 常用比例
ASPECT_RATIO_CHOICES = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"]


def _resolve_image_path(value, task_dir: str = "") -> str:
    """将节点输入值解析为本地图片绝对路径。"""
    if not value or not isinstance(value, str):
        return ""
    candidate = value.strip()
    if os.path.isfile(candidate):
        return candidate
    if task_dir:
        rel = os.path.join(task_dir, candidate)
        if os.path.isfile(rel):
            return rel
    return ""


def resolve_image_inputs(step_inputs: dict, task_dir: str = "") -> list:
    """按 首帧→图片2→图片3→图片4→尾帧 顺序组装非空的图片绝对路径列表。

    空端口自动跳过，保证下游只拿到实际提供的图片。
    """
    images = []
    for key in IMG_INPUT_KEYS:
        path = _resolve_image_path(step_inputs.get(key), task_dir)
        if path:
            images.append(path)
    return images


def resolve_reference_video(step_inputs: dict, task_dir: str = "") -> str:
    """解析参考视频输入端口（reference_video）为本地视频绝对路径；未连接返回空串。"""
    for key in VIDEO_INPUT_KEYS:
        path = _resolve_image_path(step_inputs.get(key), task_dir)
        if path:
            return path
    return ""


def parse_aspect_ratio(value) -> float | None:
    """解析 '16:9' -> 16/9；空或非法返回 None。"""
    if not value:
        return None
    text = str(value).strip().lower()
    m = re.match(r"(\d+)[:x×](\d+)", text)
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    if h <= 0 or w <= 0:
        return None
    return w / h


def _resolution_preset_wh(preset: str, ratio: float | None, default_w: int, default_h: int) -> tuple:
    """预设 1K/2K/3K/4K：以预设值为长边，结合比例计算宽高。"""
    base = PRESET_RESOLUTIONS.get(str(preset).strip().lower())
    if not base:
        return default_w, default_h
    if not ratio or abs(ratio - 1.0) < 1e-6:
        return base, base
    if ratio >= 1.0:
        return base, max(1, round(base / ratio))
    return max(1, round(base * ratio)), base


def _parse_custom_resolution(text: str, ratio: float | None, default_w: int, default_h: int) -> tuple:
    """解析自定义分辨率文本：'1920x1080' / '1080p' / '1K' / '2k' 等。"""
    clean = str(text or "").strip().lower().replace("×", "x")
    if not clean:
        return default_w, default_h
    # 1K/2K/3K/4K
    m = re.fullmatch(r"(\d)k", clean)
    if m:
        return _resolution_preset_wh(f"{m.group(1)}k", ratio, default_w, default_h)
    # 1920x1080 / 1920 X 1080
    m = re.fullmatch(r"(\d+)\s*x\s*(\d+)", clean)
    if m:
        return int(m.group(1)), int(m.group(2))
    # 1080p / 720p / 4k
    m = re.fullmatch(r"(\d+)p", clean)
    if m:
        h = int(m.group(1))
        if not ratio:
            ratio = 16 / 9
        return max(1, round(h * ratio)), h
    return default_w, default_h


def resolve_resolution(
    cfg: dict,
    default_width: int = 1024,
    default_height: int = 1024,
) -> tuple:
    """根据节点配置解析出 (width, height)。

    支持三种模式（resolution_mode）：
      - preset:  直接选 1K/2K/3K/4K（resolution_preset）
      - size:    手动输入长宽（width / height）
      - custom:  自定义文本（resolution_custom），如 1920x1080 / 1080p / 1K
    比例（aspect_ratio）在非 size 模式下参与宽高换算。
    """
    ratio = parse_aspect_ratio(cfg.get("aspect_ratio"))
    mode = cfg.get("resolution_mode", "preset")
    if isinstance(mode, list):
        mode = mode[0] if mode else "preset"

    if mode == "size":
        try:
            w = int(cfg.get("width") or default_width)
        except (TypeError, ValueError):
            w = default_width
        try:
            h = int(cfg.get("height") or default_height)
        except (TypeError, ValueError):
            h = default_height
        return max(1, w), max(1, h)

    if mode == "custom":
        return _parse_custom_resolution(
            cfg.get("resolution_custom"), ratio, default_width, default_height
        )

    return _resolution_preset_wh(
        cfg.get("resolution_preset") or "1k", ratio, default_width, default_height
    )


def resolve_num_images(cfg: dict, default: int = 1) -> int:
    """生成数量；非法值回退默认。"""
    try:
        n = int(cfg.get("num_images") or default)
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, 10))


def resolution_label(width: int, height: int) -> str:
    """生成分辨率文本标签，如 '1024x1024'、'1080p'、'2k'。"""
    if width == height:
        for k, v in PRESET_RESOLUTIONS.items():
            if v == width:
                return k
    if width % 16 == 0 and height % 9 == 0 and width // 16 == height // 9:
        return f"{height}p"
    return f"{width}x{height}"
