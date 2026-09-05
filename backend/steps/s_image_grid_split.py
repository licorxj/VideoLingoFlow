"""s_image_grid_split: 图片宫格切割。

把一张宫格组合图（如 AI 生成的 2×2 / 3×3 组合图）按 N×N 切成单张图片：

- ``grid``：宫格数，仅支持 4(2×2) / 9(3×3) / 16(4×4) / 25(5×5)
- ``outer_shrink``：外框收缩像素，切割前先把整图四边向内收掉若干像素（去外框）
- ``inner_shrink``：内部切割收缩像素，每个内部切缝两侧各向内收若干像素（去格间
  拼接缝）；与图片外边缘重合的边不收缩

切割结果写入 ``cache/image_grid_{node_id}/``，按行优先序号命名（01、02…），
扩展名与输入图片保持一致；输出端口为图片相对路径列表。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable, Optional

from backend.steps.base_step import BaseStep

# 宫格数 -> 每边格数
_GRID_CHOICES = {4: 2, 9: 3, 16: 4, 25: 5}

# 可保持原格式的扩展名（PIL 按扩展名推断保存格式）；其余一律回退 png
_KEEP_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


def _node_id(step: object) -> str:
    return getattr(step, "_node_id", "") or "node"


def _first_value(raw) -> str:
    """连线输入可能是字符串或多级列表，取第一个非空项。"""
    if isinstance(raw, (list, tuple)):
        for item in raw:
            text = _first_value(item)
            if text:
                return text
        return ""
    return str(raw).strip() if raw is not None else ""


def _as_int(value, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _resolve_image_path(task_dir: str, raw) -> Optional[Path]:
    """把连线输入解析为存在的图片绝对路径。"""
    text = _first_value(raw)
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = Path(task_dir) / path
    return path if path.is_file() else None


def _boundaries(total: int, n: int) -> list:
    """N 等分边界：首尾贴合 0 和 total，保证分块无缝铺满整图。"""
    return [round(i * total / n) for i in range(n + 1)]


class S_ImageGridSplit(BaseStep):
    step_id = "image_grid_split"
    step_name = "图片宫格切割"
    dependencies: list = []
    artifacts: list = []

    # ---------------- BaseStep 接口 ----------------
    def _output_dir(self, task_dir: str) -> Path:
        return Path(task_dir) / "cache" / f"image_grid_{_node_id(self)}"

    def _result_path(self, task_dir: str) -> Path:
        return Path(task_dir) / "cache" / f"image_grid_{_node_id(self)}.json"

    def check_artifact(self, task_dir: str) -> bool:
        result = self._result_path(task_dir)
        if not result.is_file():
            return False
        try:
            payload = json.loads(result.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        files = payload.get("files") or []
        return bool(files) and all((Path(task_dir) / f).is_file() for f in files)

    def validate_inputs(self, task_dir: str) -> bool:
        inputs = getattr(self, "_step_inputs", {}) or {}
        return bool(_first_value(inputs.get("image")))

    def rollback(self, task_dir: str) -> None:
        result = self._result_path(task_dir)
        if result.is_file():
            result.unlink()
        out_dir = self._output_dir(task_dir)
        if out_dir.is_dir():
            shutil.rmtree(out_dir, ignore_errors=True)

    # ---------------- 执行 ----------------
    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        config = getattr(self, "_node_config", {}) or {}
        inputs = getattr(self, "_step_inputs", {}) or {}
        node_id = _node_id(self)

        grid = _as_int(config.get("grid"), 4)
        if grid not in _GRID_CHOICES:
            raise ValueError(f"不支持的宫格数：{grid}（仅支持 4 / 9 / 16 / 25）")
        n = _GRID_CHOICES[grid]
        outer = max(0, _as_int(config.get("outer_shrink"), 0))
        inner = max(0, _as_int(config.get("inner_shrink"), 5))

        image_path = _resolve_image_path(task_dir, inputs.get("image"))
        if image_path is None:
            raise FileNotFoundError(
                "图片宫格切割需要图片输入：请把上游图片端口连接到本节点"
            )

        try:
            from PIL import Image
        except ImportError as exc:  # pragma: no cover - 部署环境缺依赖
            raise RuntimeError("图片宫格切割需要 Pillow 库（pip install Pillow）") from exc

        if callback:
            callback(10, f"读取图片：{image_path.name}")
        img = Image.open(image_path)
        img.load()

        ext = image_path.suffix.lower()
        if ext not in _KEEP_EXTS:
            ext = ".png"

        width, height = img.size
        if outer:
            if width - 2 * outer < 1 or height - 2 * outer < 1:
                raise RuntimeError(
                    f"外框收缩像素过大：图片 {width}x{height}，无法收缩 {outer}px"
                )
            img = img.crop((outer, outer, width - outer, height - outer))
            width, height = img.size

        out_dir = self._output_dir(task_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        xs = _boundaries(width, n)
        ys = _boundaries(height, n)
        cell_w, cell_h = xs[1] - xs[0], ys[1] - ys[0]
        total = n * n
        files: list = []
        for r in range(n):
            for c in range(n):
                if cancel_callback and cancel_callback():
                    raise RuntimeError("任务已取消")
                left = xs[c] + (inner if c > 0 else 0)
                top = ys[r] + (inner if r > 0 else 0)
                right = xs[c + 1] - (inner if c < n - 1 else 0)
                bottom = ys[r + 1] - (inner if r < n - 1 else 0)
                if right - left < 1 or bottom - top < 1:
                    raise RuntimeError(
                        f"内部切割收缩像素过大：单格尺寸 {cell_w}x{cell_h}，"
                        f"无法向内收缩 {inner}px"
                    )
                piece = img.crop((left, top, right, bottom))
                index = r * n + c + 1
                name = f"{index:02d}{ext}"
                piece.save(out_dir / name)
                files.append(f"cache/image_grid_{node_id}/{name}")
                if callback:
                    callback(10 + int(80 * index / total), f"已切割 {index}/{total} 格")

        result = {
            "source": str(image_path),
            "grid": grid,
            "outer_shrink": outer,
            "inner_shrink": inner,
            "size": [width, height],
            "count": len(files),
            "files": files,
        }
        result_path = self._result_path(task_dir)
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        if callback:
            callback(100, f"宫格切割完成：共 {len(files)} 张")
        return {
            "artifacts": [f"cache/image_grid_{node_id}.json", *files],
            "outputs": {"images": files},
        }
