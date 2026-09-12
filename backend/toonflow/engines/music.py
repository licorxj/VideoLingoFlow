# -*- coding: utf-8 -*-
"""音乐引擎适配：Toonflow 音乐能力（源 MiniMax vendor）→ 本项目 musicgen 工厂。

本项目 musicgen：musicgen_engine.generate(prompt, output_dir, model=, mode="txt2music", **kwargs)。
源 vendor 只有"按描述生成音乐"一种用法 → 默认 mode=txt2music，其余模式透传。
"""
import uuid
from pathlib import Path

from backend.toonflow.engines.base import EngineOutput, pick_enabled, task_record


def run(config: dict, *, project_id: int | None = None,
        interface: str = "", model: str = "") -> EngineOutput:
    """生成音乐并落盘。

    config 键：prompt（曲风/情绪/主题描述，必填）、model、mode(默认 txt2music)、
               style(风格标签)、title(曲名)、instrumental(bool)、durationHint 等 mode 专属参数经 extra 透传
    """
    from backend.musicgen.musicgen_factory import get_musicgen_engine
    from backend.musicgen.musicgen_interface_manager import get_musicgen_interface_manager

    prompt = str(config.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("音乐生成缺少 prompt")
    out_dir = Path(config.get("output_dir") or Path("data") / "toonflow" / "tmp" / f"mus_{uuid.uuid4().hex[:8]}")
    out_dir.mkdir(parents=True, exist_ok=True)

    extra = {k: v for k, v in config.items() if k in ("style", "title", "instrumental", "durationHint", "negativeTags")}
    if "durationHint" in extra:
        extra["duration"] = extra.pop("durationHint")
    if "negativeTags" in extra:
        extra["negative_tags"] = extra.pop("negativeTags")

    iface = pick_enabled(get_musicgen_interface_manager, interface)
    engine = get_musicgen_engine(iface)
    with task_record("音乐生成", "music", project_id):
        paths = engine.generate(
            prompt, str(out_dir),
            model=str(model or config.get("model") or ""),
            mode=str(config.get("mode") or "txt2music"),
            **extra,
        ) or []
    if not paths:
        raise RuntimeError(f"音乐生成未返回结果（接口 {iface}）")
    return EngineOutput(paths)
