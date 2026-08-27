"""视频生成接口 API 路由（结构镜像 imagegen_interfaces.py，增加视频生成参数）。"""
import os
import uuid
import asyncio
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Body
from fastapi import UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.videogen.videogen_interface_manager import get_videogen_interface_manager

logger = logging.getLogger(__name__)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic 模型
# ─────────────────────────────────────────────────────────────────────────────
class VideoGenInterfaceCreate(BaseModel):
    id: str
    name: str
    type: str = "sdk"
    description: str = ""
    api_source_url: str = ""
    model_docs_url: str = ""
    config: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    builtin: bool = False


class VideoGenInterfaceUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None
    api_source_url: Optional[str] = None
    model_docs_url: Optional[str] = None
    enabled: Optional[bool] = None
    config: Optional[Dict[str, Any]] = None
    balance: Optional[Any] = None


class VideoGenModelAddRequest(BaseModel):
    model_name: str
    modes: List[str] = Field(default_factory=list)
    price: str = ""
    resolutions: List[str] = Field(default_factory=list)
    durations: List[int] = Field(default_factory=list)
    max_ref_images: int = 0
    max_ref_videos: int = 0
    supports_audio: bool = False
    default_audio: str = "model_default"


class VideoGenTestRequest(BaseModel):
    interface_id: Optional[str] = None
    prompt: str = "一只橘猫在窗台上晒太阳，毛发光泽，阳光温暖"
    negative_prompt: str = ""
    resolution: str = "720P"
    duration: int = 5
    num_videos: int = 1
    ref_images: List[str] = Field(default_factory=list)
    ref_videos: List[str] = Field(default_factory=list)
    audio: Optional[Any] = None
    model: str = ""
    mode: str = "txt2video"
    output_dir: Optional[str] = None
    extra_args: Optional[Dict[str, Any]] = None


class VideoGenModesMap(BaseModel):
    txt2video: Dict[str, Any] = Field(default_factory=dict)
    img2video: Dict[str, Any] = Field(default_factory=dict)
    flf2video: Dict[str, Any] = Field(default_factory=dict)
    autovideo: Dict[str, Any] = Field(default_factory=dict)


class VideoGenBalanceUpdate(BaseModel):
    balance: Optional[float] = None
    data: Optional[Any] = None


class VideoGenTestVideoRequest(BaseModel):
    path: str = Field(..., description="视频绝对路径")


# ─────────────────────────────────────────────────────────────────────────────
# 接口 CRUD
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/")
async def list_videogen_interfaces():
    mgr = get_videogen_interface_manager()
    return {"interfaces": mgr.list_all()}


@router.get("/enabled")
async def list_enabled_videogen_interfaces():
    mgr = get_videogen_interface_manager()
    return {"interfaces": mgr.get_enabled()}


@router.get("/{iface_id}")
async def get_videogen_interface(iface_id: str):
    mgr = get_videogen_interface_manager()
    iface = mgr.get(iface_id)
    if not iface:
        raise HTTPException(status_code=404, detail="接口不存在")
    return iface


@router.post("/reload")
async def reload_videogen_interfaces():
    mgr = get_videogen_interface_manager()
    ids = mgr.reload()
    return {"success": True, "interfaces": ids}


@router.post("/{iface_id}/refresh-balance")
async def refresh_videogen_balance(iface_id: str):
    mgr = get_videogen_interface_manager()
    if not mgr.get(iface_id):
        raise HTTPException(status_code=404, detail="接口不存在")
    return {
        "success": True,
        "balance": mgr.get(iface_id)["balance"],
    }


@router.post("/")
async def create_videogen_interface(data: VideoGenInterfaceCreate):
    mgr = get_videogen_interface_manager()
    try:
        iface = mgr.create(data.dict())
        return {"success": True, "interface": iface}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{iface_id}")
async def update_videogen_interface(iface_id: str, data: VideoGenInterfaceUpdate):
    mgr = get_videogen_interface_manager()
    try:
        iface = mgr.update(iface_id, data.dict(exclude_unset=True))
        return {"success": True, "interface": iface}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{iface_id}")
async def delete_videogen_interface(iface_id: str):
    mgr = get_videogen_interface_manager()
    try:
        mgr.delete(iface_id)
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{iface_id}/toggle")
async def toggle_videogen_interface(iface_id: str, data: dict = Body(...)):
    mgr = get_videogen_interface_manager()
    enabled = data.get("enabled", True)
    try:
        mgr.toggle(iface_id, enabled)
        return {"success": True, "enabled": enabled}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# 模型管理
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/{iface_id}/models")
async def get_videogen_models(iface_id: str):
    mgr = get_videogen_interface_manager()
    if not mgr.get(iface_id):
        raise HTTPException(status_code=404, detail="接口不存在")
    return {"models": mgr.get_models(iface_id)}


@router.get("/{iface_id}/models-for-node")
async def get_videogen_models_for_node(
    iface_id: str,
    mode: str = Query("t2v", description="节点模式: t2v / i2v / flf / v2v"),
):
    """供节点使用的模型列表与参数 schema（按模式过滤支持的模型）。"""
    mgr = get_videogen_interface_manager()
    iface = mgr.get(iface_id)
    if not iface:
        raise HTTPException(status_code=404, detail="接口不存在")
    config = iface.get("config", {})
    metadata = config.get("model_metadata", {})
    mode_map = {"t2v": "txt2video", "i2v": "img2video", "flf": "flf2video", "v2v": "autovideo"}
    target_mode = mode_map.get(mode, mode)
    models = config.get("model_options", [])
    supported = [m for m in models if target_mode in (metadata.get(m, {}).get("modes", []))]
    sample_meta = metadata.get(supported[0], {}) if supported else {}
    param_schema = {
        "model": {
            "type": "string", "description": "模型名称", "source": "select",
            "options": supported, "default": supported[0] if supported else "",
        },
        "prompt": {"type": "string", "description": "提示词", "source": "text", "default": ""},
        "negative_prompt": {"type": "string", "description": "反向提示词", "source": "text", "default": ""},
        "resolution": {
            "type": "string", "description": "分辨率", "source": "select",
            "options": sample_meta.get("resolutions", []), "default": (sample_meta.get("resolutions") or ["720P"])[0],
        },
        "duration": {
            "type": "integer", "description": "时长(秒)", "source": "select",
            "options": sample_meta.get("durations", []), "default": (sample_meta.get("durations") or [5])[0],
        },
        "num_videos": {"type": "integer", "description": "数量", "source": "number", "default": 1},
        "ref_images": {"type": "array", "description": "参考图 / 首帧", "source": "image", "default": []},
        "ref_videos": {"type": "array", "description": "参考视频", "source": "video", "default": []},
        "audio": {
            "type": "string", "description": "声音(on/off/keep_original)", "source": "select",
            "options": ["on", "off", "keep_original"], "default": "on",
        },
    }
    return {"models": supported, "param_schema": param_schema, "mode": target_mode}


@router.get("/{iface_id}/params/{model}")
async def get_videogen_model_params(iface_id: str, model: str):
    """返回模型支持的分辨率 / 时长 / 生成类型 / 参考限制 / 声音配置。"""
    mgr = get_videogen_interface_manager()
    if not mgr.get(iface_id):
        raise HTTPException(status_code=404, detail="接口不存在")
    meta = mgr.get_model_metadata(iface_id).get(model, {})
    return {
        "model": model,
        "modes": meta.get("modes", []),
        "resolutions": meta.get("resolutions", []),
        "durations": meta.get("durations", []),
        "max_ref_images": meta.get("max_ref_images", 0),
        "max_ref_videos": meta.get("max_ref_videos", 0),
        "supports_audio": meta.get("supports_audio", False),
        "default_audio": meta.get("default_audio", "model_default"),
    }


@router.post("/{iface_id}/models")
async def add_videogen_model(iface_id: str, data: VideoGenModelAddRequest):
    mgr = get_videogen_interface_manager()
    try:
        metadata = {
            "modes": data.modes,
            "price": data.price,
            "resolutions": data.resolutions,
            "durations": data.durations,
            "max_ref_images": data.max_ref_images,
            "max_ref_videos": data.max_ref_videos,
            "supports_audio": data.supports_audio,
            "default_audio": data.default_audio,
        }
        models = mgr.add_model(iface_id, data.model_name, metadata=metadata)
        return {"success": True, "models": models}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{iface_id}/models/{model_name}")
async def remove_videogen_model(iface_id: str, model_name: str):
    mgr = get_videogen_interface_manager()
    try:
        models = mgr.remove_model(iface_id, model_name)
        return {"success": True, "models": models}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{iface_id}/fetch-models")
async def fetch_videogen_models(iface_id: str):
    """从接口拉取模型列表（若接口支持）。"""
    mgr = get_videogen_interface_manager()
    if not mgr.get(iface_id):
        raise HTTPException(status_code=404, detail="接口不存在")
    return {"success": False, "message": "该接口暂不支持自动拉取模型"}


# ─────────────────────────────────────────────────────────────────────────────
# 文件上传
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/{iface_id}/upload")
async def upload_videogen_file(
    iface_id: str,
    file: UploadFile = File(...),
    api_key: str = Form(""),
    purpose: str = Form("reference"),
):
    """上传文件到接口平台的 OSS，返回公开访问 URL。

    可用于项目其它模块上传参考图 / 参考视频 / 任意素材，供视频生成或外部使用。
    """
    mgr = get_videogen_interface_manager()
    iface = mgr.get(iface_id)
    if not iface:
        raise HTTPException(status_code=404, detail="接口不存在")

    from backend.videogen.videogen_factory import get_videogen_engine
    engine = get_videogen_engine(iface_id)
    if engine is None or not hasattr(engine, "upload_file"):
        raise HTTPException(status_code=400, detail="该接口不支持文件上传")

    tmp_dir = os.path.join("static", "videogen_uploads", str(uuid.uuid4()))
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_path = os.path.join(tmp_dir, file.filename or "upload.bin")
    try:
        content = await file.read()
        with open(tmp_path, "wb") as f:
            f.write(content)
        loop = asyncio.get_event_loop()
        url = await loop.run_in_executor(None, engine.upload_file, tmp_path, api_key)
    except Exception as e:
        logger.error("Video file upload failed: %s", e)
        raise HTTPException(status_code=500, detail=f"上传失败: {e}")
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    return {"success": True, "url": url, "filename": file.filename, "purpose": purpose}


# ─────────────────────────────────────────────────────────────────────────────
# 测试生成
# ─────────────────────────────────────────────────────────────────────────────
def _run_generate_sync(iface_id: str, kwargs: dict):
    from backend.videogen.videogen_factory import get_videogen_engine
    engine = get_videogen_engine(iface_id)
    return engine.generate(**kwargs)


def _extract_uploaded_filename(path: str):
    parts = path.replace("\\", "/").split("/")
    filename = parts[-1]
    subdir = parts[-2] if len(parts) >= 2 else ""
    return subdir, filename


@router.post("/{iface_id}/test")
async def test_videogen_interface(iface_id: str, req: VideoGenTestRequest):
    mgr = get_videogen_interface_manager()
    if not mgr.get(iface_id):
        raise HTTPException(status_code=404, detail="接口不存在")

    output_dir = req.output_dir or os.path.join("static", "videogen_test", str(uuid.uuid4()))
    os.makedirs(output_dir, exist_ok=True)

    kwargs = dict(
        prompt=req.prompt,
        output_dir=output_dir,
        model=req.model,
        negative_prompt=req.negative_prompt,
        resolution=req.resolution,
        duration=req.duration,
        num_videos=req.num_videos,
        ref_images=req.ref_images,
        ref_videos=req.ref_videos,
        audio=req.audio,
        mode=req.mode,
        api_key="",
    )
    if req.extra_args:
        kwargs.update(req.extra_args)

    try:
        loop = asyncio.get_event_loop()
        videos = await loop.run_in_executor(None, _run_generate_sync, iface_id, kwargs)
    except Exception as e:
        logger.error("Video interface test failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    return {"success": True, "videos": videos, "output_dir": output_dir, "count": len(videos)}


@router.post("/test/video")
async def serve_test_video(req: VideoGenTestVideoRequest):
    """按绝对路径返回测试生成的视频文件。"""
    path = req.path
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="文件不存在")
    media_type = "video/mp4"
    ext = path.lower().rsplit(".", 1)[-1]
    if ext in ("webm",):
        media_type = "video/webm"
    elif ext in ("mov",):
        media_type = "video/quicktime"
    return FileResponse(path, media_type=media_type, filename=os.path.basename(path))
