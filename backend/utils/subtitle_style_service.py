"""Subtitle style packaging service.

统一处理以下能力：
1. 加载字幕样式预设
2. 构建主/副字幕样式参数
3. 识别双语 SRT
4. 将双语 SRT 拆分为主/副两个独立 SRT
5. 将字幕包装为 ASS，供预览和工作流节点复用
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

from backend.config.config_manager import config
from backend.utils import ass_wrapper


def load_subtitle_preset(preset_id: str) -> dict | None:
    """Load subtitle style preset from JSON file."""
    if not preset_id:
        return None
    presets_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config",
        "subtitle_presets",
    )
    path = os.path.join(presets_dir, f"{preset_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_primary_style(
    preset: dict | None = None,
    primary_style: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build primary style from defaults + preset + explicit overrides."""
    if preset and "primary" in preset:
        style = {**ass_wrapper.get_default_style_params(), **preset["primary"]}
    else:
        style = {
            **ass_wrapper.get_default_style_params(),
            "fontName": config.get("subtitle.font", "Arial"),
            "fontSize": config.get("subtitle.font_size", 24),
            "outline": config.get("subtitle.outline", 2),
            "shadow": config.get("subtitle.shadow", 1),
            "marginV": config.get("subtitle.margin_v", 30),
        }
    if primary_style:
        style.update(primary_style)
    return style


def build_secondary_style(
    primary_style: dict[str, Any],
    preset: dict | None = None,
    secondary_style: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build secondary style, inheriting from primary when not fully specified."""
    style = {**primary_style}
    if preset and "secondary" in preset:
        style.update(preset["secondary"])
    if secondary_style:
        style.update(secondary_style)
    return style


def is_bilingual_srt(srt_path: str) -> bool:
    """Detect whether an SRT contains two subtitle lines per block."""
    if not srt_path or not os.path.exists(srt_path):
        return False
    try:
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
    except Exception:
        return False

    if not content:
        return False

    for block in content.split("\n\n"):
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3:
            continue
        if len(lines[2:]) >= 2:
            return True
    return False


def split_bilingual_srt(
    bilingual_srt_path: str,
    temp_dir: str,
    output_prefix: str = "_styled",
) -> tuple[str, str]:
    """Split a bilingual SRT into primary and secondary SRT files.

    行序约定（由 subtitle_gen._entries_to_bilingual_srt 写入时确定）：
      - 第 1 行文本 = primary = 原文字幕（屏幕上方 / Default 样式）
      - 第 2 行文本 = secondary = 译文字幕（屏幕下方 / Secondary 样式）
    """
    with open(bilingual_srt_path, "r", encoding="utf-8") as f:
        content = f.read()

    blocks = content.strip().split("\n\n")
    primary_lines = []
    secondary_lines = []

    for block in blocks:
        lines = [line for line in block.strip().split("\n") if line.strip()]
        if len(lines) < 3:
            continue
        index_line = lines[0]
        time_line = lines[1]
        text_lines = lines[2:]
        primary_text = text_lines[0] if len(text_lines) >= 1 else ""
        secondary_text = text_lines[1] if len(text_lines) >= 2 else ""
        primary_lines.append(f"{index_line}\n{time_line}\n{primary_text}")
        secondary_lines.append(f"{index_line}\n{time_line}\n{secondary_text}")

    primary_path = os.path.join(temp_dir, f"{output_prefix}_primary.srt")
    secondary_path = os.path.join(temp_dir, f"{output_prefix}_secondary.srt")
    with open(primary_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(primary_lines) + "\n")
    with open(secondary_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(secondary_lines) + "\n")
    return primary_path, secondary_path


def package_subtitles_to_ass(
    primary_srt_path: str,
    output_ass_path: str,
    *,
    secondary_srt_path: str | None = None,
    preset_id: str = "",
    preset: dict | None = None,
    primary_style: Optional[dict[str, Any]] = None,
    secondary_style: Optional[dict[str, Any]] = None,
    primary_on_top: bool = False,
    force_bilingual: bool | None = None,
) -> dict[str, Any]:
    """Package SRT subtitle input(s) into an ASS file with resolved styles.

    Supports:
    - single SRT -> single ASS
    - bilingual SRT (two text lines per block) -> dual ASS
    - explicit primary + secondary SRT -> dual ASS
    """
    if not primary_srt_path or not os.path.exists(primary_srt_path):
        raise FileNotFoundError(f"未找到主字幕文件: {primary_srt_path}")

    os.makedirs(os.path.dirname(output_ass_path), exist_ok=True)
    temp_dir = os.path.dirname(output_ass_path)
    output_prefix = os.path.splitext(os.path.basename(output_ass_path))[0]

    loaded_preset = preset if preset is not None else load_subtitle_preset(preset_id)
    resolved_primary_style = build_primary_style(loaded_preset, primary_style)
    resolved_secondary_style = build_secondary_style(
        resolved_primary_style, loaded_preset, secondary_style
    )

    if secondary_srt_path and not os.path.exists(secondary_srt_path):
        raise FileNotFoundError(f"未找到副字幕文件: {secondary_srt_path}")

    dual_mode = bool(secondary_srt_path)
    if force_bilingual is not None:
        dual_mode = force_bilingual or dual_mode
    elif not dual_mode:
        dual_mode = is_bilingual_srt(primary_srt_path)

    split_primary_path = primary_srt_path
    split_secondary_path = secondary_srt_path
    if dual_mode and not split_secondary_path:
        split_primary_path, split_secondary_path = split_bilingual_srt(
            primary_srt_path,
            temp_dir=temp_dir,
            output_prefix=output_prefix,
        )

    if dual_mode and split_secondary_path:
        ass_wrapper.srt_to_ass_dual(
            primary_srt_path=split_primary_path,
            secondary_srt_path=split_secondary_path,
            primary_style=resolved_primary_style,
            secondary_style=resolved_secondary_style,
            output_ass_path=output_ass_path,
            primary_on_top=primary_on_top,
        )
        mode = "dual"
    else:
        ass_wrapper.srt_to_ass(
            srt_path=primary_srt_path,
            style_params=resolved_primary_style,
            output_ass_path=output_ass_path,
        )
        mode = "single"

    return {
        "ass_path": output_ass_path,
        "mode": mode,
        "primary_srt_path": split_primary_path,
        "secondary_srt_path": split_secondary_path,
        "preset_id": preset_id,
        "primary_style": resolved_primary_style,
        "secondary_style": resolved_secondary_style if mode == "dual" else None,
    }
