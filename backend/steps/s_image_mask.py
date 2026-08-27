"""图片蒙版节点：根据前端绘制的蒙版数据（画笔 / 矩形），在图片上合成蒙版。

前端传递的蒙版数据（config.mask）采用归一化坐标（0~1，相对图片尺寸）：
    {
      "strokes": [{"points": [[x, y], ...], "size": <归一化半径>}, ...],
      "rects":   [{"x":, "y":, "w":, "h":}, ...],  # x,y 为左上角，w/h 为尺寸
      "color":   "#ff3b30",
      "alpha":   0.5
    }

后端据此在图片实际分辨率上绘制黑白蒙版，并叠加上半透明彩色蒙版，
输出：
    - image：蒙版合成图（原图叠加半透明蒙版）
    - mask ：黑白蒙版图（白=蒙版区域）
"""
import os
import logging

from PIL import Image, ImageDraw
from backend.steps.base_step import BaseStep

logger = logging.getLogger(__name__)


class S_ImageMask(BaseStep):
    type = "image_mask"
    name = "图片蒙版"
    category = "image"
    description = "上游输入图片，在卡片上用画笔/矩形绘制蒙版，后端合成蒙版图并输出蒙版合成图与黑白蒙版。"

    step_id = "s_image_mask"
    artifacts = ["image_mask.png", "image_masked.png"]

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        out_dir = os.path.join(task_dir, "output", node_id) if node_id else ""
        if node_id and os.path.isfile(os.path.join(out_dir, "image_masked.png")):
            return True
        # 兼容未带 node_id 的旧产物命名
        if os.path.isfile(os.path.join(task_dir, "output", "image_masked.png")):
            return True
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        return bool(step_inputs.get("image"))

    def run(self, task_dir, callback=None, cancel_callback=None):
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        node_id = getattr(self, "_node_id", "image_mask") or "image_mask"

        image_path = step_inputs.get("image")
        if not image_path:
            raise ValueError("图片蒙版节点缺少输入图片，请连接上游图片输出。")
        src = image_path if os.path.isabs(image_path) else os.path.join(task_dir, image_path)
        if not os.path.isfile(src):
            raise FileNotFoundError(f"找不到输入图片：{src}")

        mask = node_config.get("mask") or {}
        strokes = mask.get("strokes") or []
        rects = mask.get("rects") or []
        color = mask.get("color") or "#ff3b30"
        alpha = float(mask.get("alpha") if mask.get("alpha") is not None else 0.5)
        alpha = max(0.0, min(1.0, alpha))

        rgb = self._hex_to_rgb(color)

        img = Image.open(src).convert("RGB")
        W, H = img.size
        base_min = min(W, H)

        # 黑白蒙版（白=蒙版区域）
        mask_img = Image.new("L", (W, H), 0)
        draw = ImageDraw.Draw(mask_img)

        for r in rects:
            x0 = max(0, int(round(r["x"] * W)))
            y0 = max(0, int(round(r["y"] * H)))
            x1 = min(W, int(round((r["x"] + r["w"]) * W)))
            y1 = min(H, int(round((r["y"] + r["h"]) * H)))
            if x1 > x0 and y1 > y0:
                draw.rectangle([x0, y0, x1, y1], fill=255)

        for s in strokes:
            pts = s.get("points") or []
            size = float(s.get("size") or 0.02)
            width = max(1, int(round(size * 2 * base_min)))
            px_pts = [
                (max(0, min(W, int(round(p[0] * W)))), max(0, min(H, int(round(p[1] * H)))))
                for p in pts
            ]
            if len(px_pts) == 1:
                draw.ellipse(
                    [px_pts[0][0] - width // 2, px_pts[0][1] - width // 2,
                     px_pts[0][0] + width // 2, px_pts[0][1] + width // 2],
                    fill=255,
                )
            elif len(px_pts) > 1:
                for i in range(1, len(px_pts)):
                    draw.line([px_pts[i - 1], px_pts[i]], fill=255, width=width, joint="curve")
                for p in px_pts:
                    draw.ellipse(
                        [p[0] - width // 2, p[1] - width // 2, p[0] + width // 2, p[1] + width // 2],
                        fill=255,
                    )

        out_dir = os.path.join(task_dir, "output", node_id)
        os.makedirs(out_dir, exist_ok=True)

        mask_path = os.path.join(out_dir, "image_mask.png")
        mask_img.save(mask_path)

        # 彩色半透明蒙版叠加到原图
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        odraw.bitmap((0, 0), mask_img, fill=(rgb[0], rgb[1], rgb[2], int(round(alpha * 255))))
        base = img.convert("RGBA")
        composited = Image.alpha_composite(base, overlay).convert("RGB")
        masked_path = os.path.join(out_dir, "image_masked.png")
        composited.save(masked_path)

        return {
            "outputs": {
                "image": os.path.relpath(masked_path, task_dir),
                "mask": os.path.relpath(mask_path, task_dir),
            }
        }

    @staticmethod
    def _hex_to_rgb(hex_color):
        h = (hex_color or "#ff3b30").lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        h = (h + "000000")[:6]
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
