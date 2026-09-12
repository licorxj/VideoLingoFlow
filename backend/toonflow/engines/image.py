# -*- coding: utf-8 -*-
"""生图引擎适配：Toonflow `imageRequest(config, model)` → 本项目 imagegen 工厂。

源 ImageConfig：{prompt, referenceList, size: "1K"|"2K"|"4K", aspectRatio, ...}
本项目：imagegen_engine.generate(prompt, output_dir, mode=, resolution=, aspect_ratio=,
                                   ref_images=, num_images=, negative_prompt=, model=)

模式映射：referenceList 空 → txt2img；非空 → img2img（与本项目能力一致）。
"""
import uuid
from pathlib import Path

from backend.toonflow.engines.base import (
    EngineOutput, normalize_refs, pick_enabled, resolve_capability, task_record,
)


def run(config: dict, *, project_id: int | None = None,
        interface: str = "", model: str = "") -> EngineOutput:
    """生成图片并落盘 oss。

    config 键（对齐源 ImageConfig，兼容本项目侧命名）：
        prompt           生图提示词（必填）
        referenceList    参考图列表（路径/URL/dataURI 混合）
        size | resolution 输出档位 1K/2K/4K，默认 1K
        aspectRatio      比例，默认 1:1
        num | count      张数，默认 1
        negativePrompt   反向提示词
    """
    from backend.imagegen.imagegen_factory import get_imagegen_engine
    from backend.imagegen.imagegen_interface_manager import get_imagegen_interface_manager

    prompt = str(config.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("生图缺少 prompt")
    out_dir = Path(config.get("output_dir") or Path("data") / "toonflow" / "tmp" / f"img_{uuid.uuid4().hex[:8]}")
    out_dir.mkdir(parents=True, exist_ok=True)

    refs = normalize_refs(config.get("referenceList"), out_dir)
    mode = "img2img" if refs else "txt2img"
    resolution = str(config.get("resolution") or config.get("size") or "1K")
    aspect_ratio = str(config.get("aspectRatio") or "1:1")
    num = int(config.get("num") or config.get("count") or 1)
    negative = str(config.get("negativePrompt") or "")

    # 画布设置按模式配置「接口+模型」（t2i=文生图 / i2i=图生图），显式入参优先
    cfg_iface, cfg_model = resolve_capability("imagegen", "t2i" if mode == "txt2img" else "i2i")
    iface = pick_enabled(get_imagegen_interface_manager, interface or cfg_iface)
    engine = get_imagegen_engine(iface)
    with task_record("图片生成", "image", project_id):
        paths = engine.generate(
            prompt, str(out_dir), mode=mode, resolution=resolution,
            aspect_ratio=aspect_ratio, ref_images=refs or None,
            num_images=num, negative_prompt=negative,
            model=str(model or config.get("model") or cfg_model),
        ) or []
    if not paths:
        raise RuntimeError(f"生图未返回结果（接口 {iface}，模式 {mode}）")
    return EngineOutput(paths)
