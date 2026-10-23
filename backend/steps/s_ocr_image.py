# -*- coding: utf-8 -*-
"""OCR 图片识别步骤：走 OCR 接口工厂（backend/ocr）对单张图片做文字识别。

与 s_pdf_ocr / s_ocr_table 的「直连 indra_ocr」不同，本步骤经接口管理器
（`get_ocr_engine`）加载引擎：节点面板可选 OCR 接口（rapidocr / indra_ocr）
与 RapidOCR 专属模型覆盖，接口配置在「接口管理 → OCR」维护，节点不绑定具体实现。

能力：
- 输入图片（png/jpg/jpeg/bmp/tif/tiff/webp）：本地路径（绝对/相对）、
  http(s) URL 自动下载、data URI / 整段 base64 落盘，均做图片魔数校验；
- 识别结果按 output_type 输出 JSON / Markdown / 纯 TXT：
  JSON 含每行文本、置信度、四点坐标与轴对齐 bbox；Markdown 为表格；
  纯 TXT 每行一条文本；
- 同时在原图上以**红色字体**绘制每行识别文本与检测框，输出标注图片端口；
- 节点级「置信度过滤」对识别结果统一后过滤（RapidOCR 引擎阈值在加载时
  固定为 0.5，调低未必能找回被引擎丢弃的低置信行）；
- 节点级「数学公式」开关覆盖接口配置（仅 Indra OCR 支持，按需重建引擎）。
"""
import base64
import binascii
import json
import os
import time
import urllib.request
from typing import Callable, Dict, List, Optional, Tuple

from backend.ocr.ocr_factory import get_ocr_engine
from backend.steps.base_step import BaseStep, find_artifact, step_check_cancel
from backend.steps.s_pdf_ocr import _log, _unwrap_input

# 常见图片文件头（长度递减匹配）
_IMG_MAGICS = (
    b"\x89PNG\r\n\x1a\n",   # PNG
    b"\xff\xd8\xff",        # JPEG
    b"GIF87a",              # GIF
    b"GIF89a",              # GIF
    b"II*\x00",             # TIFF (little-endian)
    b"MM\x00*",             # TIFF (big-endian)
    b"BM",                  # BMP
    b"RIFF",                # WEBP（需再校验 WEBP 标记）
)

# 节点级 RapidOCR 模型覆盖键（与 subtitle_position_search 一致）
_OVERRIDE_KEYS = ("ocr_version", "model_type", "custom_model_name")

# output_type → (文件扩展名, 说明)
OUTPUT_EXTS = {
    "json": ".json",
    "markdown": ".md",
    "text": ".txt",
}

# PIL 红色标注字体候选（与 video_tools 的中文字体解析一致，取到文件路径为止）
_FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyh.ttf",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
)
_RED = (255, 0, 0)


def _looks_like_image(head: bytes) -> bool:
    for magic in _IMG_MAGICS:
        if head.startswith(magic):
            if magic == b"RIFF":
                return b"WEBP" in head[:16]
            return True
    return False


def _img_ext(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith(b"BM"):
        return ".bmp"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return ".tiff"
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return ".webp"
    return ".bin"


def _ensure_image_bytes(data: bytes, where: str = "输入") -> None:
    if _looks_like_image(data):
        return
    raise ValueError(f"{where}不是受支持的图片（png/jpg/jpeg/bmp/tif/tiff/webp）")


def _is_abs(path: str) -> bool:
    return path.startswith(("/", "\\")) or (len(path) > 1 and path[1] == ":")


def _write_b64_image(payload: str, task_dir: str, node_id: str) -> str:
    try:
        data = base64.b64decode(payload.strip(), validate=False)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"base64 解码失败：{e}")
    _ensure_image_bytes(data)
    dst = os.path.join(task_dir, "input")
    os.makedirs(dst, exist_ok=True)
    path = os.path.join(dst, f"{node_id}_input{_img_ext(data)}")
    with open(path, "wb") as fp:
        fp.write(data)
    return os.path.abspath(path)


def _download_image(url: str, task_dir: str, node_id: str, timeout: int = 180) -> str:
    dst = os.path.join(task_dir, "input")
    os.makedirs(dst, exist_ok=True)
    tmp = os.path.join(dst, f"{node_id}_input.bin")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 VideoLingoLc/OCR-Image"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp, "wb") as fp:
        fp.write(resp.read())
    with open(tmp, "rb") as fp:
        head = fp.read(1024)
    if not _looks_like_image(head):
        os.remove(tmp)
        raise ValueError(f"下载的内容不是受支持的图片：{url}")
    path = os.path.join(dst, f"{node_id}_input{_img_ext(head)}")
    os.replace(tmp, path)
    return os.path.abspath(path)


def _resolve_image_path(raw, task_dir: str, node_id: str, log) -> str:
    """把输入值解析为本地图片绝对路径（支持路径/URL/data URI/base64）。"""
    text = _unwrap_input(raw)
    if text.lower().startswith("data:"):
        header, _, payload = text.partition(",")
        if "base64" not in header.lower():
            raise ValueError("仅支持 base64 编码的 data URI（图片）")
        return _write_b64_image(payload, task_dir, node_id)
    if text.lower().startswith(("http://", "https://")):
        _log(log, f"下载图片: {text}")
        return _download_image(text, task_dir, node_id)

    candidates = [text] if _is_abs(text) else [
        os.path.join(task_dir, text),
        os.path.join(task_dir, "cache", text),
        text,
    ]
    for cand in candidates:
        if os.path.isfile(cand):
            with open(cand, "rb") as fp:
                head = fp.read(1024)
            if _looks_like_image(head):
                return os.path.abspath(cand)
            raise ValueError(f"不是受支持的图片文件：{cand}"
                             "（支持 png/jpg/jpeg/bmp/tif/tiff/webp）")
    # 整段 base64 兜底（PNG 前缀 "iVBOR"、JPEG "/9j/"、GIF "R0lGOD"）
    if text.startswith(("iVBOR", "/9j/", "R0lGOD", "UklGR", "Qk0", "SUkq", "TU0A")):
        return _write_b64_image(text, task_dir, node_id)
    raise FileNotFoundError(f"图片文件不存在：{text}（已尝试：{candidates}）")


# ── 接口解析（与字幕识别节点同一套优先级） ───────────────────────

def _resolve_interface_id(model: str) -> str:
    """接口：节点选择 > 全局配置 ocr.method > rapidocr。"""
    if model and str(model).strip():
        return str(model).strip()
    try:
        from backend.config import config

        global_method = config.get("ocr.method")
        if global_method and str(global_method).strip():
            return str(global_method).strip()
    except Exception:
        pass
    return "rapidocr"


def _build_overrides(cfg: dict) -> Optional[dict]:
    """RapidOCR 模型覆盖（ocr_version/model_type/custom_model_name），空值剔除。"""
    overrides = {}
    for key in _OVERRIDE_KEYS:
        v = cfg.get(key)
        if v is not None and str(v).strip():
            overrides[key] = str(v).strip()
    return overrides or None


# ── 坐标工具 ─────────────────────────────────────────────────────

def _norm_points(box) -> Optional[List[Tuple[float, float]]]:
    """把检测框归一成 [(x, y), ...]；非法/空返回 None（如 use_det=False 时无框）。"""
    if box is None:
        return None
    try:
        pts = [(float(p[0]), float(p[1])) for p in box if p is not None and len(p) >= 2]
    except (TypeError, ValueError, IndexError):
        return None
    return pts or None


def _bbox_of(points: Optional[List[Tuple[float, float]]]) -> Optional[List[float]]:
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


# ── 红色标注渲染 ─────────────────────────────────────────────────

def _load_font(size: int):
    """按候选列表加载 TrueType 字体，全部失败时退回 PIL 默认字体。"""
    from PIL import ImageFont

    for path in _FONT_CANDIDATES:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default(size)
    except TypeError:  # 老版本 Pillow 的 load_default 不接受尺寸
        return ImageFont.load_default()


def _annotate_image(img_path: str, lines: List[Dict], out_path: str) -> Tuple[int, int]:
    """在原图上以红色绘制检测框与「文本 置信度」标签，保存为 PNG。

    lines: [{"text", "score", "points": [(x,y)*4]}, ...]；points 为 None 时跳过绘制。
    返回图片宽高。
    """
    from PIL import Image, ImageDraw

    img = Image.open(img_path).convert("RGB")
    W, H = img.size
    scale = max(W, H) / 1280.0
    font_size = max(12, min(72, int(round(20 * scale))))
    line_w = max(1, min(6, int(round(2 * scale))))
    font = _load_font(font_size)
    draw = ImageDraw.Draw(img)

    for ln in lines:
        pts = ln.get("points")
        text = (ln.get("text") or "").strip()
        if pts and len(pts) >= 3:
            draw.polygon(pts, outline=_RED, width=line_w)
        if not text:
            continue
        label = f"{text} {float(ln.get('score') or 0.0):.2f}"
        # 标签置于框上方（无框时置于左上角），并夹取在画布内
        if pts:
            tx, ty = min(p[0] for p in pts), min(p[1] for p in pts) - font_size - 4
        else:
            tx, ty = 4, 4
        try:
            tw = draw.textlength(label, font=font)
        except Exception:
            tw = len(label) * font_size // 2
        tx = max(2, min(tx, W - tw - 2))
        ty = max(2, min(ty, H - font_size - 2))
        draw.text((tx, ty), label, fill=_RED, font=font, stroke_width=1, stroke_fill=_RED)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    img.save(out_path)
    return W, H


# ── 输出渲染 ─────────────────────────────────────────────────────

def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _render_markdown(lines: List[Dict], meta: Dict) -> str:
    head = [
        "# OCR 识别结果",
        "",
        f"- 文件：{meta['file']}（{meta['width']}×{meta['height']}）",
        f"- 接口：{meta['interface']}",
        f"- 识别到 {len(lines)} 行文本（置信度 ≥ {meta['text_score']:g}"
        + ("，含数学公式" if meta.get("math") else "") + "）",
        "",
        "| # | 文本 | 置信度 | 坐标(x0,y0,x1,y1) |",
        "| --- | --- | --- | --- |",
    ]
    for i, ln in enumerate(lines, start=1):
        bbox = ln.get("bbox") or []
        coord = ",".join(str(int(round(v))) for v in bbox) if bbox else "-"
        head.append(f"| {i} | {_md_escape(ln['text'])} | {float(ln['score']):.2f} | {coord} |")
    return "\n".join(head) + "\n"


def _render_txt(lines: List[Dict]) -> str:
    return "\n".join(ln["text"] for ln in lines) + ("\n" if lines else "")


class S_OcrImage(BaseStep):
    """OCR 图片识别：经接口工厂识别单张图片文字，输出文本结果 + 红色标注图。"""

    step_id = "s_ocr_image"
    step_name = "OCR图片识别"
    dependencies = []
    artifacts = []

    INPUT_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
    OUTPUT_EXTS = set(OUTPUT_EXTS.values())

    def check_artifact(self, task_dir: str) -> bool:
        """结果文件（任一扩展名）+ 标注图片均存在才算完成。"""
        out_dir = os.path.join(task_dir, "output", self._node_id)
        if not any(find_artifact(out_dir, f"ocr_image_result{ext}") for ext in OUTPUT_EXTS.values()):
            return False
        return bool(find_artifact(out_dir, "ocr_image_annotated.png"))

    def validate_inputs(self, **kwargs) -> bool:
        raw = (getattr(self, "_step_inputs", None) or {}).get("image")
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            raise ValueError("未提供图片输入：请连接 image 类型的上游端口（图片路径）")
        return True

    def run(self, task_dir, callback: Optional[Callable[[int, str], None]] = None,
            cancel_callback: Optional[Callable[[], bool]] = None, **kwargs):
        started = time.time()
        log = kwargs.get("log")

        def report(p: int, msg: str):
            if callback:
                try:
                    callback(p, msg)
                except Exception:
                    pass

        raw = (getattr(self, "_step_inputs", None) or {}).get("image")
        cfg = getattr(self, "_node_config", None) or {}
        node_id = getattr(self, "_node_id", None) or "node"

        # ── 1. 解析输入图片 ──────────────────────────────────────
        report(2, "解析图片输入")
        img_path = _resolve_image_path(raw, task_dir, node_id, log)
        img_name = os.path.basename(img_path)
        _log(log, f"图片输入：{img_path}")

        # ── 2. 识别参数 ─────────────────────────────────────────
        output_type = str(cfg.get("output_type") or "json").strip().lower()
        if output_type not in OUTPUT_EXTS:
            raise ValueError(f"output_type 不支持：{output_type}（可选：{'/'.join(OUTPUT_EXTS)}）")
        text_score = float(cfg.get("text_score") if cfg.get("text_score") is not None else 0.5)
        if not 0.0 <= text_score <= 1.0:
            raise ValueError(f"text_score 超出范围（0~1）：{text_score}")
        math = bool(cfg.get("math", False))
        iface_id = _resolve_interface_id(cfg.get("model"))
        overrides = _build_overrides(cfg)
        _log(log, f"识别参数：接口={iface_id} 覆盖={overrides or '无'} 输出={output_type} "
                  f"置信度≥{text_score:g} 公式={math}")

        # ── 3. 经工厂加载引擎并识别 ─────────────────────────────
        report(5, f"加载 OCR 引擎（{iface_id}）")

        def engine_cb(p, msg):
            # 引擎进度 0~100 映射到步骤 15~80；不吞异常，取消由框架回调向上传播
            if callback:
                try:
                    pv = int(p or 0)
                except (TypeError, ValueError):
                    pv = 0
                callback(15 + int(0.65 * max(0, min(100, pv))), str(msg or ""))

        try:
            engine = get_ocr_engine(iface_id, overrides)
        except Exception as e:
            raise RuntimeError(f"OCR 引擎加载失败（接口 {iface_id}）：{e}") from e

        step_check_cancel(cancel_callback)
        report(10, "正在识别图片文本...")
        result = engine.recognize(img_path, engine_cb, text_score=text_score, math=math)
        step_check_cancel(cancel_callback)

        txts = list(result.get("txts") or [])
        boxes = list(result.get("boxes") or [])
        scores = list(result.get("scores") or [])
        # 节点级置信度过滤（引擎可能已在加载时固定阈值，这里统一后过滤兜底）
        lines: List[Dict] = []
        dropped = 0
        for i, text in enumerate(txts):
            text = (text or "").strip()
            if not text:
                continue
            score = float(scores[i]) if i < len(scores) and scores[i] is not None else 0.0
            if text_score > 0 and score < text_score:
                dropped += 1
                continue
            pts = _norm_points(boxes[i] if i < len(boxes) else None)
            lines.append({
                "text": text,
                "score": round(score, 4),
                "box": [[round(x, 1), round(y, 1)] for x, y in pts] if pts else None,
                "bbox": [round(v, 1) for v in _bbox_of(pts)] if pts else None,
                "points": pts,
            })
        if not lines:
            hint = "可尝试调低置信度过滤阈值" if dropped else "请确认图片包含文字或更换识别接口"
            raise RuntimeError(f"未识别到任何文字（接口 {iface_id}，{hint}）")
        if dropped:
            _log(log, f"置信度过滤：丢弃 {dropped} 行（阈值 {text_score:g}），保留 {len(lines)} 行")
        elapsed_ms = int((result.get("elapse") or 0.0) * 1000) or int((time.time() - started) * 1000)

        # ── 4. 红色标注渲染 ─────────────────────────────────────
        report(85, "渲染红色标注图片...")
        out_dir = os.path.join(task_dir, "output", node_id)
        os.makedirs(out_dir, exist_ok=True)
        annotated_path = os.path.join(out_dir, "ocr_image_annotated.png")
        W, H = _annotate_image(img_path, lines, annotated_path)
        _log(log, f"标注图片已生成：{annotated_path}（{W}×{H}，红色字体）")

        # ── 5. 组装文本结果 ─────────────────────────────────────
        report(92, "生成输出文件")
        meta = {
            "file": img_name,
            "width": W,
            "height": H,
            "interface": iface_id,
            "text_score": text_score,
            "math": math,
        }
        ext = OUTPUT_EXTS[output_type]
        result_path = os.path.join(out_dir, f"ocr_image_result{ext}")
        if output_type == "json":
            payload = dict(meta)
            payload.update({
                "count": len(lines),
                "elapsed_ms": elapsed_ms,
                "lines": [{k: v for k, v in ln.items() if k != "points"} for ln in lines],
            })
            with open(result_path, "w", encoding="utf-8") as fp:
                json.dump(payload, fp, ensure_ascii=False, indent=2)
        elif output_type == "markdown":
            with open(result_path, "w", encoding="utf-8") as fp:
                fp.write(_render_markdown(lines, meta))
        else:
            with open(result_path, "w", encoding="utf-8") as fp:
                fp.write(_render_txt(lines))

        rel_result = os.path.relpath(result_path, task_dir)
        rel_image = os.path.relpath(annotated_path, task_dir)
        self.artifacts = [rel_result, rel_image]
        elapsed = time.time() - started
        _log(log, f"OCR图片识别完成：{len(lines)} 行文本，输出 {result_path} + {annotated_path}"
                  f"（{elapsed:.1f}s）")
        report(100, f"完成（{len(lines)} 行文本 / {elapsed:.1f}s）")

        return {
            "outputs": {"result": result_path, "image": annotated_path},
            "artifacts": [rel_result, rel_image],
        }
