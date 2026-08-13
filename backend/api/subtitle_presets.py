"""Subtitle presets CRUD API.
Stores ASS/SSA style presets as JSON files in config/subtitle_presets/.
"""
import json
import os
import re
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

router = APIRouter()

# 预设文件存储目录
PRESETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "subtitle_presets")


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


class SubtitlePresetCreate(BaseModel):
    """创建/更新字幕预设的请求体。"""
    name: str
    primary: StyleParams = StyleParams()
    secondary: StyleParams = StyleParams()
    dualSubtitleEnabled: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("预设名称不能为空")
        if not re.match(r'^[a-zA-Z0-9_\-\u4e00-\u9fff]+$', v):
            raise ValueError("预设名称只能包含字母、数字、下划线、连字符和中文")
        return v


class SubtitlePresetResponse(BaseModel):
    """字幕预设响应。"""
    name: str
    primary: StyleParams
    secondary: StyleParams
    dualSubtitleEnabled: bool


# ---------- 工具函数 ----------

def _ensure_presets_dir():
    """确保预设目录存在。"""
    os.makedirs(PRESETS_DIR, exist_ok=True)


def _preset_path(name: str) -> str:
    """获取预设文件的完整路径。"""
    return os.path.join(PRESETS_DIR, f"{name}.json")


def _read_preset(name: str) -> Optional[dict]:
    """读取指定名称的预设，不存在则返回 None。"""
    path = _preset_path(name)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_preset(name: str, data: dict):
    """将预设数据写入 JSON 文件。"""
    _ensure_presets_dir()
    with open(_preset_path(name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _delete_preset_file(name: str) -> bool:
    """删除预设文件，成功返回 True。"""
    path = _preset_path(name)
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False


# ---------- 路由 ----------

@router.get("", response_model=list[SubtitlePresetResponse])
async def list_presets():
    """获取所有预设列表。"""
    _ensure_presets_dir()
    presets = []
    for fname in os.listdir(PRESETS_DIR):
        if fname.endswith(".json"):
            name = fname[:-5]
            data = _read_preset(name)
            if data:
                presets.append(SubtitlePresetResponse(name=name, **data))
    return presets


@router.get("/{name}", response_model=SubtitlePresetResponse)
async def get_preset(name: str):
    """获取单个预设。"""
    data = _read_preset(name)
    if data is None:
        raise HTTPException(status_code=404, detail=f"预设 '{name}' 不存在")
    return SubtitlePresetResponse(name=name, **data)


@router.post("", response_model=SubtitlePresetResponse, status_code=201)
async def create_preset(req: SubtitlePresetCreate):
    """创建新预设。"""
    if _read_preset(req.name) is not None:
        raise HTTPException(status_code=409, detail=f"预设 '{req.name}' 已存在，请使用 PUT 更新")
    data = {
        "primary": req.primary.model_dump(),
        "secondary": req.secondary.model_dump(),
        "dualSubtitleEnabled": req.dualSubtitleEnabled,
    }
    _write_preset(req.name, data)
    return SubtitlePresetResponse(name=req.name, **data)


@router.put("/{name}", response_model=SubtitlePresetResponse)
async def update_preset(name: str, req: SubtitlePresetCreate):
    """更新已有预设。"""
    data = {
        "primary": req.primary.model_dump(),
        "secondary": req.secondary.model_dump(),
        "dualSubtitleEnabled": req.dualSubtitleEnabled,
    }
    _write_preset(name, data)
    return SubtitlePresetResponse(name=name, **data)


@router.delete("/{name}")
async def delete_preset(name: str):
    """删除预设。"""
    if not _delete_preset_file(name):
        raise HTTPException(status_code=404, detail=f"预设 '{name}' 不存在")
    return {"success": True, "name": name}
