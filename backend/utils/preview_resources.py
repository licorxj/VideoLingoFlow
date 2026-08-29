"""字幕预览资源管理。
在 temp/ 目录下生成黑底视频和示例 SRT 文件，供字幕预览使用。
"""
import os
import subprocess


# 示例 SRT 内容
_PREVIEW_SRT_ZH = """\
1
00:00:00,500 --> 00:00:02,000
欢迎使用 VideoLingo 字幕系统

2
00:00:02,000 --> 00:00:03,500
这是一个字幕预览示例

3
00:00:03,500 --> 00:00:04,500
支持多种字体和样式
"""

_PREVIEW_SRT_EN = """\
1
00:00:00,500 --> 00:00:02,000
Welcome to VideoLingo Subtitle System

2
00:00:02,000 --> 00:00:03,500
This is a subtitle preview example

3
00:00:03,500 --> 00:00:04,500
Supports various fonts and styles
"""

_PREVIEW_SRT_BILINGUAL = """\
1
00:00:00,500 --> 00:00:02,000
欢迎使用 VideoLingo 字幕系统
Welcome to VideoLingo Subtitle System

2
00:00:02,000 --> 00:00:03,500
这是一个字幕预览示例
This is a subtitle preview example

3
00:00:03,500 --> 00:00:04,500
支持多种字体和样式
Supports various fonts and styles
"""


def ensure_preview_resources(project_root: str) -> str:
    """确保预览资源存在，返回 temp/ 目录路径。

    1. 创建 temp/ 目录
    2. 生成 black_5s.mp4 黑底视频（如不存在）
    3. 生成三种示例 SRT 文件（如不存在）

    Args:
        project_root: 项目根目录路径

    Returns:
        temp/ 目录的绝对路径
    """
    temp_dir = os.path.join(project_root, "temp")
    os.makedirs(temp_dir, exist_ok=True)

    # 生成左右拼色预览背景视频（左浅灰、右深灰），避免纯黑背景看不清字幕
    bg_video = os.path.join(temp_dir, "preview_bg_5s.mp4")
    if not os.path.isfile(bg_video):
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=0xD3D3D3:s=960x1080:d=5",
            "-f", "lavfi", "-i", "color=c=0x404040:s=960x1080:d=5",
            "-filter_complex", "[0:v][1:v]hstack=2[bg]",
            "-map", "[bg]",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            bg_video,
        ]
        subprocess.run(cmd, capture_output=True, timeout=60)

    # 兼容旧版纯黑背景文件：如果存在则删除，避免后续复用
    legacy_black_video = os.path.join(temp_dir, "black_5s.mp4")
    if os.path.isfile(legacy_black_video):
        os.remove(legacy_black_video)

    # 生成示例 SRT 文件
    _write_if_missing(os.path.join(temp_dir, "preview_zh.srt"), _PREVIEW_SRT_ZH)
    _write_if_missing(os.path.join(temp_dir, "preview_en.srt"), _PREVIEW_SRT_EN)
    _write_if_missing(os.path.join(temp_dir, "preview_bilingual.srt"), _PREVIEW_SRT_BILINGUAL)

    return temp_dir


def _write_if_missing(path: str, content: str):
    """文件不存在时写入内容。"""
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
