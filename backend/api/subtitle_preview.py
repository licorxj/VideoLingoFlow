"""字幕预览视频生成 API。
提供准备预览资源、生成预览视频和静态文件服务的接口。
"""
import asyncio
import os
import subprocess

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.utils.preview_resources import ensure_preview_resources
from backend.utils.subtitle_style_service import package_subtitles_to_ass

router = APIRouter()

# 项目根目录（从 backend/api/ 上溯三级）
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------- Pydantic 模型 ----------

class StyleParams(BaseModel):
    """ASS 样式参数。"""
    fontName: str = "Arial"
    fontSize: int = 48
    primaryColour: str = "&H00FFFFFF"
    secondaryColour: str = "&H000000FF"
    outlineColour: str = "&H00000000"
    backColour: str = "&H00000000"
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikeout: bool = False
    scaleX: int = 100
    scaleY: int = 100
    spacing: int = 0
    angle: float = 0
    borderStyle: int = 1
    outline: float = 2
    shadow: int = 1
    alignment: int = 2
    marginL: int = 10
    marginR: int = 10
    marginV: int = 30
    encoding: int = 1


class PreviewRequest(BaseModel):
    """预览生成请求。"""
    example: str  # "zh" | "en" | "bilingual"
    primary: StyleParams = StyleParams()
    secondary: StyleParams | None = None
    dualSubtitleEnabled: bool = False
    primaryOnTop: bool = False


# ---------- 路由 ----------

@router.get("/prepare")
async def prepare_preview():
    """准备预览资源，确保黑底视频和示例 SRT 文件存在。"""
    temp_dir = ensure_preview_resources(ROOT)
    return {
        "success": True,
        "videoUrl": "/temp/preview_bg_5s.mp4",
        "examples": ["zh", "en", "bilingual"],
    }


@router.post("/generate")
async def generate_preview(req: PreviewRequest):
    """生成带字幕的预览视频。"""
    # 确保预览资源存在
    temp_dir = ensure_preview_resources(ROOT)

    # 根据示例类型选择 SRT 文件
    srt_map = {
        "zh": os.path.join(temp_dir, "preview_zh.srt"),
        "en": os.path.join(temp_dir, "preview_en.srt"),
        "bilingual": os.path.join(temp_dir, "preview_bilingual.srt"),
    }
    if req.example not in srt_map:
        raise HTTPException(status_code=400, detail=f"不支持的示例类型: {req.example}")

    srt_path = srt_map[req.example]
    ass_path = os.path.join(temp_dir, "preview.ass")
    bg_video = os.path.join(temp_dir, "preview_bg_5s.mp4")
    output_path = os.path.join(temp_dir, "preview_output.mp4")

    def _render():
        try:
            package_subtitles_to_ass(
                primary_srt_path=srt_path,
                output_ass_path=ass_path,
                primary_style=req.primary.model_dump(),
                secondary_style=(req.secondary or StyleParams()).model_dump(),
                primary_on_top=req.primaryOnTop,
                force_bilingual=(req.example == "bilingual"),
            )

            # 使用 ffmpeg 将 ASS 字幕烧录到黑底视频
            # subtitles 滤镜支持标准冒号转义（用于 Windows 驱动器号）
            escaped_ass = ass_path.replace("\\", "/").replace(":", "\\:")
            cmd = [
                "ffmpeg", "-y",
                "-i", bg_video,
                "-vf", f"subtitles='{escaped_ass}'",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                output_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                raise HTTPException(status_code=500, detail=f"ffmpeg 执行失败: {result.stderr[:500]}")

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"预览生成失败: {str(e)}")

    await asyncio.to_thread(_render)

    return {"success": True, "videoUrl": "/temp/preview_output.mp4"}


@router.get("/video/{filename}")
async def serve_preview_video(filename: str):
    """从 temp/ 目录提供预览视频文件。"""
    # 防止路径穿越
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="非法文件名")

    file_path = os.path.join(ROOT, "temp", filename)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(file_path, media_type="video/mp4")
