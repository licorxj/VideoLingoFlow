"""图片格式转换节点：输入为 any（图片文件路径或 base64 图片数据），输出指定格式的图片文件。

自动识别输入：
- 若输入是（绝对 / 相对任务目录的）图片文件路径且文件存在，则按文件读取；
- 否则尝试按 base64 图片数据解析（兼容 ``data:image/...;base64,`` 前缀与纯 base64）；
- 两者都识别失败时抛出 ValueError，由运行时标记为节点失败。
"""
import os
import io
import base64

from PIL import Image

from backend.steps.base_step import BaseStep


# 目标格式 -> (PIL 保存格式名, 文件扩展名)
_TARGET_FORMATS = {
    "png": ("PNG", ".png"),
    "jpg": ("JPEG", ".jpg"),
    "jpeg": ("JPEG", ".jpg"),
    "webp": ("WEBP", ".webp"),
    "bmp": ("BMP", ".bmp"),
    "tiff": ("TIFF", ".tiff"),
    "gif": ("GIF", ".gif"),
}


class S_ImageFormatConvert(BaseStep):
    step_id = "s_image_format_convert"
    step_name = "图片格式转换"
    dependencies = []

    def _resolve_out_path(self, task_dir: str) -> str:
        node_id = getattr(self, "_node_id", "") or "image_format_convert"
        fmt = (getattr(self, "_node_config", {}) or {}).get("target_format", "png")
        ext = _TARGET_FORMATS.get(str(fmt).lower(), ("PNG", ".png"))[1]
        out_dir = os.path.join(task_dir, "output", node_id)
        return os.path.join(out_dir, f"converted_{node_id}{ext}")

    def check_artifact(self, task_dir: str) -> bool:
        out = self._resolve_out_path(task_dir)
        return bool(out) and os.path.isfile(out)

    def validate_inputs(self, task_dir: str) -> bool:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        return bool(step_inputs.get("input"))

    @staticmethod
    def _load_image(value, task_dir: str):
        """解析输入为 PIL Image；失败返回 (None, 错误信息)。"""
        # 兼容上游以对象形式传递（path / file / data / url 字段）
        if not isinstance(value, str):
            if isinstance(value, dict):
                for key in ("path", "file", "data", "url"):
                    candidate = value.get(key)
                    if isinstance(candidate, str):
                        value = candidate
                        break
            if not isinstance(value, str):
                return None, "输入既不是字符串路径，也不是 base64 图片数据"

        v = value.strip()
        if not v:
            return None, "输入为空"

        # 1) 优先按文件路径处理（绝对路径或相对任务目录）
        abs_path = os.path.isabs(v) and os.path.isfile(v)
        rel_path = os.path.isfile(os.path.join(task_dir, v))
        if abs_path or rel_path:
            p = v if abs_path else os.path.join(task_dir, v)
            try:
                return Image.open(p), None
            except Exception as e:
                return None, f"无法读取图片文件：{os.path.basename(p)}（{e}）"

        # 2) 尝试 base64（兼容 data URI 前缀）
        data = v
        if data.startswith("data:"):
            comma = data.find(",")
            if comma == -1:
                return None, "data URI 格式错误（缺少逗号分隔的 base64 数据）"
            data = data[comma + 1:]
        try:
            raw = base64.b64decode(data, validate=False)
        except Exception:
            return None, "输入既不是有效图片路径，也不是 base64 图片数据"
        try:
            return Image.open(io.BytesIO(raw)), None
        except Exception:
            return None, "base64 数据无法解析为图片（请确认是图片的 base64 编码）"

    def run(self, task_dir, callback=None, cancel_callback=None):
        node_id = getattr(self, "_node_id", "") or "image_format_convert"
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        raw = step_inputs.get("input")
        if not raw:
            raise ValueError("图片格式转换节点缺少输入：请连接上游「图片 / 文件路径 / any」输出。")

        img, err = self._load_image(raw, task_dir)
        if img is None:
            raise ValueError(err or "无法识别输入图片（既不是图片路径，也不是 base64 图片数据）。")

        target = str(node_config.get("target_format", "png")).lower()
        if target not in _TARGET_FORMATS:
            raise ValueError(f"不支持的目标格式：{target}")
        pil_fmt, ext = _TARGET_FORMATS[target]

        if callback:
            callback(30, f"已识别图片（{img.mode} {img.size}），准备转换为 {target.upper()}")

        # JPEG 不支持透明通道，转换为 RGB；其余格式保留原色彩模式
        if pil_fmt == "JPEG" and img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")

        out_path = self._resolve_out_path(task_dir)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        save_kwargs = {}
        # 有损格式默认较高画质；保留原图信息（如 PNG 的元数据由 PIL 默认处理）
        if pil_fmt in ("JPEG", "WEBP"):
            save_kwargs["quality"] = 95

        img.save(out_path, format=pil_fmt, **save_kwargs)

        rel = os.path.relpath(out_path, task_dir)
        self.artifacts = [rel]

        if callback:
            callback(100, f"已保存为 {target.upper()}：{os.path.basename(out_path)}")

        return {
            "artifacts": [rel],
            "outputs": {"image": rel},
        }
