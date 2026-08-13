"""ASS/SSA wrapper: convert SRT to ASS with full style control.
Uses pysubs2 library for SRT reading and ASS file generation.
"""
import math
import pysubs2


def hex_to_ass_color(hex_color: str, alpha: int = 0) -> str:
    """将 #RRGGBB 或 #RRGGBBAA 格式的十六进制颜色转换为 ASS 格式 &HAABBGGRR。

    Args:
        hex_color: 十六进制颜色字符串，如 "#FFFFFF" 或 "#FFFFFF00"
        alpha: 透明度 (0=完全不透明, 255=完全透明)，默认 0

    Returns:
        ASS 格式的颜色字符串，如 "&H00FFFFFF"
    """
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 8:
        # #RRGGBBAA 格式
        r = hex_color[0:2]
        g = hex_color[2:4]
        b = hex_color[4:6]
        a = int(hex_color[6:8], 16)
    elif len(hex_color) == 6:
        # #RRGGBB 格式
        r = hex_color[0:2]
        g = hex_color[2:4]
        b = hex_color[4:6]
        a = alpha
    else:
        raise ValueError(f"不支持的颜色格式: #{hex_color}")

    return f"&H{a:02X}{b}{g}{r}"


def get_default_style_params() -> dict:
    """返回所有 ASS 样式参数的默认值。"""
    return {
        "fontName": "Arial",
        "fontSize": 48,
        "primaryColour": "&H00FFFFFF",       # 白色
        "secondaryColour": "&H000000FF",     # 红色
        "outlineColour": "&H00000000",       # 黑色
        "backColour": "&H00000000",          # 黑色
        "bold": False,
        "italic": False,
        "underline": False,
        "strikeout": False,
        "scaleX": 100,
        "scaleY": 100,
        "spacing": 0,
        "angle": 0.0,
        "borderStyle": 1,
        "outline": 2.0,
        "shadow": 1,
        "alignment": 2,                      # 底部居中，ASS 1-9
        "marginL": 10,
        "marginR": 10,
        "marginV": 30,
        "encoding": 1,
    }


def _build_style(params: dict, name: str = "Default") -> pysubs2.SSAStyle:
    """根据参数字典构建 pysubs2 SSAStyle 对象。"""
    p = {**get_default_style_params(), **params}
    style = pysubs2.SSAStyle()
    style.fontname = p["fontName"]
    style.fontsize = p["fontSize"]
    style.primarycolor = pysubs2.Color(*_parse_ass_color(p["primaryColour"]))
    style.secondarycolor = pysubs2.Color(*_parse_ass_color(p["secondaryColour"]))
    style.outlinecolor = pysubs2.Color(*_parse_ass_color(p["outlineColour"]))
    style.backcolor = pysubs2.Color(*_parse_ass_color(p["backColour"]))
    style.bold = p["bold"]
    style.italic = p["italic"]
    style.underline = p["underline"]
    style.strikeout = p["strikeout"]
    style.scalex = p["scaleX"]
    style.scaley = p["scaleY"]
    style.spacing = p["spacing"]
    style.angle = p["angle"]
    style.borderstyle = p["borderStyle"]
    style.outline = p["outline"]
    style.shadow = p["shadow"]
    style.alignment = p["alignment"]
    style.marginl = p["marginL"]
    style.marginr = p["marginR"]
    style.marginv = p["marginV"]
    style.encoding = p["encoding"]
    return style


def _alignment_family(alignment: int) -> str:
    """Return rough vertical family for ASS alignment."""
    if alignment in (7, 8, 9):
        return "top"
    if alignment in (4, 5, 6):
        return "middle"
    return "bottom"


def _estimate_dual_track_gap(primary_params: dict, secondary_params: dict) -> int:
    """Estimate a reasonable vertical gap between two subtitle tracks."""
    primary_size = float(primary_params.get("fontSize", 48) or 48)
    secondary_size = float(secondary_params.get("fontSize", 48) or 48)
    primary_outline = float(primary_params.get("outline", 2) or 2)
    secondary_outline = float(secondary_params.get("outline", 2) or 2)
    primary_shadow = float(primary_params.get("shadow", 1) or 1)
    secondary_shadow = float(secondary_params.get("shadow", 1) or 1)
    max_size = max(primary_size, secondary_size)
    max_outline = max(primary_outline, secondary_outline)
    max_shadow = max(primary_shadow, secondary_shadow)
    return int(math.ceil(max_size * 1.2 + max_outline * 2 + max_shadow + 8))


def _apply_dual_role_positions(primary_params: dict, secondary_params: dict) -> tuple[dict, dict]:
    """Ensure primary/secondary roles occupy different vertical tracks.

    Rule:
    - Default(primary role) is treated as the upper track
    - Secondary(secondary role) is treated as the lower track

    This makes role switching deterministic: swapping which text uses which role
    also swaps the actual rendered position, not just the style.
    """
    primary = {**get_default_style_params(), **primary_params}
    secondary = {**get_default_style_params(), **secondary_params}

    primary_alignment = int(primary.get("alignment", 2) or 2)
    secondary_alignment = int(secondary.get("alignment", 2) or 2)
    primary_family = _alignment_family(primary_alignment)
    secondary_family = _alignment_family(secondary_alignment)
    gap = _estimate_dual_track_gap(primary, secondary)

    if primary_family == secondary_family == "bottom":
        primary_margin = int(primary.get("marginV", 30) or 30)
        secondary_margin = int(secondary.get("marginV", 30) or 30)
        if primary_margin <= secondary_margin:
            primary["marginV"] = secondary_margin + gap
    elif primary_family == secondary_family == "top":
        primary_margin = int(primary.get("marginV", 30) or 30)
        secondary_margin = int(secondary.get("marginV", 30) or 30)
        if primary_margin >= secondary_margin:
            secondary["marginV"] = primary_margin + gap
    elif primary_family == secondary_family == "middle":
        primary_margin = int(primary.get("marginV", 30) or 30)
        secondary_margin = int(secondary.get("marginV", 30) or 30)
        if primary_margin >= secondary_margin:
            secondary["marginV"] = primary_margin + gap

    return primary, secondary


def _parse_ass_color(color_str: str) -> tuple:
    """解析 ASS 颜色字符串 &HAABBGGRR 为 (r, g, b, a) 元组。"""
    color_str = color_str.lstrip("&H").lstrip("H")
    if len(color_str) == 8:
        a = int(color_str[0:2], 16)
        b = int(color_str[2:4], 16)
        g = int(color_str[4:6], 16)
        r = int(color_str[6:8], 16)
        return (r, g, b, a)
    raise ValueError(f"不支持的 ASS 颜色格式: {color_str}")


def srt_to_ass(
    srt_path: str,
    style_params: dict,
    output_ass_path: str,
    play_res_x: int = 1920,
    play_res_y: int = 1080,
) -> str:
    """将 SRT 文件转换为 ASS 文件，使用指定的样式参数。

    Args:
        srt_path: SRT 文件路径
        style_params: ASS 样式参数字典
        output_ass_path: 输出 ASS 文件路径
        play_res_x: 播放分辨率宽度，默认 1920
        play_res_y: 播放分辨率高度，默认 1080

    Returns:
        输出 ASS 文件的路径
    """
    subs = pysubs2.load(srt_path, encoding="utf-8")

    # 清除原有样式，创建新样式
    subs.styles.clear()
    default_style = _build_style(style_params, "Default")
    subs.styles["Default"] = default_style

    # 确保所有对话行使用 "Default" 样式
    for event in subs.events:
        event.style = "Default"

    # 设置播放分辨率
    subs.info["PlayResX"] = str(play_res_x)
    subs.info["PlayResY"] = str(play_res_y)

    subs.save(output_ass_path, encoding="utf-8")
    return output_ass_path


def srt_to_ass_dual(
    primary_srt_path: str,
    secondary_srt_path: str,
    primary_style: dict,
    secondary_style: dict,
    output_ass_path: str,
    play_res_x: int = 1920,
    play_res_y: int = 1080,
    primary_on_top: bool = True,
) -> str:
    """将两个 SRT 文件（原文字幕 + 译文字幕）合并转换为双语 ASS 文件。

    Args:
        primary_srt_path: 主字幕（原文字幕）SRT 文件路径
        secondary_srt_path: 副字幕（译文字幕）SRT 文件路径
        primary_style: 主字幕样式参数
        secondary_style: 副字幕样式参数
        output_ass_path: 输出 ASS 文件路径
        play_res_x: 播放分辨率宽度，默认 1920
        play_res_y: 播放分辨率高度，默认 1080
        primary_on_top: True=原文作为主字幕(Default样式，屏幕上半部分)，译文作为副字幕(Secondary样式，屏幕下半部分)
                        False=原文作为副字幕，译文作为主字幕

    Returns:
        输出 ASS 文件的路径
    """
    primary_subs = pysubs2.load(primary_srt_path, encoding="utf-8")
    secondary_subs = pysubs2.load(secondary_srt_path, encoding="utf-8")

    # 创建新 ASS 文件
    ass = pysubs2.SSAFile()

    # 固定主/副字幕轨道位置。这样切换"译文角色"时，文本会同时切换样式和轨道位置。
    primary_role_style, secondary_role_style = _apply_dual_role_positions(
        primary_style, secondary_style
    )
    ass.styles["Default"] = _build_style(primary_role_style, "Default")
    ass.styles["Secondary"] = _build_style(secondary_role_style, "Secondary")

    # 根据 primary_on_top 决定原文/译文使用哪套样式
    # primary_on_top=True: 原文→Default（上方）, 译文→Secondary（下方）
    # primary_on_top=False: 原文→Secondary（下方）, 译文→Default（上方）
    orig_style = "Default" if primary_on_top else "Secondary"
    trans_style = "Secondary" if primary_on_top else "Default"

    # 添加主字幕轨事件（primary SRT = 原文字幕）
    for event in primary_subs.events:
        event.style = orig_style
        ass.events.append(event)

    # 添加副字幕轨事件（secondary SRT = 译文字幕）
    for event in secondary_subs.events:
        event.style = trans_style
        ass.events.append(event)

    # 设置播放分辨率
    ass.info["PlayResX"] = str(play_res_x)
    ass.info["PlayResY"] = str(play_res_y)

    ass.save(output_ass_path, encoding="utf-8")
    return output_ass_path
