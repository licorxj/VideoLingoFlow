"""音乐生成接口 API 路由（结构镜像 videogen_interfaces.py，针对音乐生成参数）。"""
import os
import uuid
import asyncio
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.musicgen.musicgen_interface_manager import get_musicgen_interface_manager

logger = logging.getLogger(__name__)

from backend.config.credential_store import mask_deep

router = APIRouter()

MUSIC_MODE_ALIASES = {
    "t2m": "txt2music",
    "i2m": "instrumental",
    "lyr": "lyrics",
    "ext": "extend",
    "cov": "cover",
    "ai": "add_instrumental",
    "av": "add_vocals",
    "sep": "separate",
    "wav": "to_wav",
    "uext": "upload_extend",
}


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic 模型
# ─────────────────────────────────────────────────────────────────────────────
class MusicGenInterfaceCreate(BaseModel):
    id: str
    name: str
    type: str = "sdk"
    description: str = ""
    api_source_url: str = ""
    model_docs_url: str = ""
    config: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    builtin: bool = False


class MusicGenInterfaceUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None
    api_source_url: Optional[str] = None
    model_docs_url: Optional[str] = None
    enabled: Optional[bool] = None
    config: Optional[Dict[str, Any]] = None
    balance: Optional[Any] = None


class MusicGenModelAddRequest(BaseModel):
    model_name: str
    modes: List[str] = Field(default_factory=list)
    price: str = ""
    durations: List[int] = Field(default_factory=list)
    max_ref_audios: int = 0
    supports_lyrics: bool = True


class MusicGenTestRequest(BaseModel):
    interface_id: Optional[str] = None
    prompt: str = "宁静的夜晚，轻柔的钢琴曲，带一点弦乐铺底"
    negative_prompt: str = ""
    model: str = "V5_5"
    mode: str = "txt2music"
    duration: int = 60
    output_dir: Optional[str] = None
    extra_args: Optional[Dict[str, Any]] = None


class MusicGenSchemaRequest(BaseModel):
    config: Optional[Dict[str, Any]] = None
    interface_id: Optional[str] = None
    sdk_module: Optional[str] = None
    model: str = ""
    mode: str = "txt2music"


# ─────────────────────────────────────────────────────────────────────────────
# 接口 CRUD
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/")
async def list_musicgen_interfaces():
    mgr = get_musicgen_interface_manager()
    return {"interfaces": mask_deep(mgr.list_raw())}


@router.get("/enabled")
async def list_enabled_musicgen_interfaces():
    mgr = get_musicgen_interface_manager()
    return {"interfaces": mgr.get_enabled()}


@router.get("/{iface_id}")
async def get_musicgen_interface(iface_id: str):
    mgr = get_musicgen_interface_manager()
    iface = mgr.get_raw(iface_id)
    if not iface:
        raise HTTPException(status_code=404, detail="接口不存在")
    return mask_deep(iface)


@router.post("/reload")
async def reload_musicgen_interfaces():
    mgr = get_musicgen_interface_manager()
    ids = mgr.reload()
    return {"success": True, "interfaces": ids}


@router.post("/{iface_id}/refresh-balance")
async def refresh_musicgen_balance(iface_id: str):
    mgr = get_musicgen_interface_manager()
    if not mgr.get(iface_id):
        raise HTTPException(status_code=404, detail="接口不存在")
    return {"success": True, "balance": mgr.get(iface_id).get("balance")}


@router.post("/")
async def create_musicgen_interface(data: MusicGenInterfaceCreate):
    mgr = get_musicgen_interface_manager()
    try:
        iface = mgr.create(data.dict())
        return {"success": True, "interface": mask_deep(iface)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{iface_id}")
async def update_musicgen_interface(iface_id: str, data: MusicGenInterfaceUpdate):
    mgr = get_musicgen_interface_manager()
    try:
        iface = mgr.update(iface_id, data.dict(exclude_unset=True))
        return {"success": True, "interface": mask_deep(iface)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{iface_id}")
async def delete_musicgen_interface(iface_id: str):
    mgr = get_musicgen_interface_manager()
    try:
        mgr.delete(iface_id)
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{iface_id}/toggle")
async def toggle_musicgen_interface(iface_id: str, data: dict = Body(...)):
    mgr = get_musicgen_interface_manager()
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
async def get_musicgen_models(iface_id: str):
    mgr = get_musicgen_interface_manager()
    if not mgr.get(iface_id):
        raise HTTPException(status_code=404, detail="接口不存在")
    return {"models": mgr.get_models(iface_id)}


@router.get("/{iface_id}/models-for-node")
async def get_musicgen_models_for_node(
    iface_id: str,
    mode: str = Query("t2m", description="节点模式: t2m / i2m / lyr / ext / cov / ai / av / sep / wav / uext"),
):
    """供节点使用的模型列表与参数 schema（按模式过滤支持的模型）。"""
    mgr = get_musicgen_interface_manager()
    iface = mgr.get(iface_id)
    if not iface:
        raise HTTPException(status_code=404, detail="接口不存在")
    config = iface.get("config", {})
    metadata = config.get("model_metadata", {})
    target_mode = MUSIC_MODE_ALIASES.get(mode, mode)
    models = config.get("model_options", [])
    supported = [m for m in models if target_mode in (metadata.get(m, {}).get("modes", []))]
    sample_meta = metadata.get(supported[0], {}) if supported else {}
    param_schema = {
        "model": {
            "type": "string", "description": "模型版本", "source": "select",
            "options": supported, "default": supported[0] if supported else "",
        },
        "prompt": {"type": "string", "description": "提示词 / 歌词", "source": "text", "default": ""},
        "mode": {"type": "string", "description": "生成模式", "source": "select",
                 "options": list(MUSIC_MODE_ALIASES.keys()), "default": mode},
        "duration": {
            "type": "integer", "description": "时长(秒)", "source": "select",
            "options": sample_meta.get("durations", []), "default": (sample_meta.get("durations") or [60])[0],
        },
    }
    return {"models": supported, "param_schema": param_schema, "mode": target_mode}


@router.get("/{iface_id}/params/{model}")
async def get_musicgen_model_params(iface_id: str, model: str):
    """返回模型支持的模式 / 时长 / 参考音频限制 / 歌词支持等。"""
    mgr = get_musicgen_interface_manager()
    if not mgr.get(iface_id):
        raise HTTPException(status_code=404, detail="接口不存在")
    meta = mgr.get_model_metadata(iface_id).get(model, {})
    return {
        "model": model,
        "modes": meta.get("modes", []),
        "durations": meta.get("durations", []),
        "max_ref_audios": meta.get("max_ref_audios", 0),
        "supports_lyrics": meta.get("supports_lyrics", True),
    }


@router.post("/{iface_id}/models")
async def add_musicgen_model(iface_id: str, data: MusicGenModelAddRequest):
    mgr = get_musicgen_interface_manager()
    try:
        metadata = {
            "modes": data.modes,
            "price": data.price,
            "durations": data.durations,
            "max_ref_audios": data.max_ref_audios,
            "supports_lyrics": data.supports_lyrics,
        }
        models = mgr.add_model(iface_id, data.model_name, metadata=metadata)
        return {"success": True, "models": models}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{iface_id}/models/{model_name}")
async def remove_musicgen_model(iface_id: str, model_name: str):
    mgr = get_musicgen_interface_manager()
    try:
        models = mgr.remove_model(iface_id, model_name)
        return {"success": True, "models": models}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{iface_id}/fetch-models")
async def fetch_musicgen_models(iface_id: str):
    mgr = get_musicgen_interface_manager()
    if not mgr.get(iface_id):
        raise HTTPException(status_code=404, detail="接口不存在")
    return {"success": False, "message": "该接口暂不支持自动拉取模型"}


# ─────────────────────────────────────────────────────────────────────────────
# 测试生成
# ─────────────────────────────────────────────────────────────────────────────
def _run_generate_sync(iface_id: str, kwargs: dict):
    from backend.musicgen.musicgen_factory import get_musicgen_engine
    engine = get_musicgen_engine(iface_id)
    if engine is None:
        return []
    return engine.generate(**kwargs)


@router.post("/{iface_id}/test")
async def test_musicgen_interface(iface_id: str, req: MusicGenTestRequest):
    mgr = get_musicgen_interface_manager()
    if not mgr.get(iface_id):
        raise HTTPException(status_code=404, detail="接口不存在")

    output_dir = req.output_dir or os.path.join("static", "musicgen_test", str(uuid.uuid4()))
    os.makedirs(output_dir, exist_ok=True)

    kwargs = dict(
        prompt=req.prompt,
        output_dir=output_dir,
        model=req.model,
        mode=req.mode,
        api_key="",
    )
    if req.extra_args:
        kwargs.update(req.extra_args)

    try:
        loop = asyncio.get_event_loop()
        audios = await loop.run_in_executor(None, _run_generate_sync, iface_id, kwargs)
    except Exception as e:
        logger.error("Music interface test failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    return {"success": True, "audios": audios, "output_dir": output_dir, "count": len(audios)}


@router.post("/test/audio")
async def serve_test_audio(req: dict = Body(...)):
    """按绝对路径返回测试生成的音频文件。"""
    path = req.get("path", "")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="文件不存在")
    media_type = "audio/mpeg"
    ext = path.lower().rsplit(".", 1)[-1]
    if ext in ("wav",):
        media_type = "audio/wav"
    elif ext in ("ogg",):
        media_type = "audio/ogg"
    elif ext in ("flac",):
        media_type = "audio/flac"
    return FileResponse(path, media_type=media_type, filename=os.path.basename(path))


# ─────────────────────────────────────────────────────────────────────────────
# 节点设置 Schema
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_musicgen_config(mgr, iface_id=None, sdk_module=None, config=None):
    if config:
        return config
    if iface_id:
        iface = mgr.get(iface_id)
        if not iface:
            raise HTTPException(status_code=404, detail="接口不存在")
        return mask_deep(iface.get("config", {}))
    if sdk_module:
        for i in mgr.get_enabled():
            if (i.get("config", {}) or {}).get("sdk_module") == sdk_module:
                return i.get("config", {})
        for i in mgr.list_all():
            if (i.get("config", {}) or {}).get("sdk_module") == sdk_module:
                return i.get("config", {})
    raise HTTPException(status_code=400, detail="需提供 config / interface_id / sdk_module 之一")


def _build_musicgen_schema(config, model, mode):
    metadata = config.get("model_metadata", {})
    if not model and config.get("default_model"):
        model = config.get("default_model")
    meta = metadata.get(model, {}) if model else {}

    modes = list(meta.get("modes", []) or [])
    durations = list(meta.get("durations", []) or [])
    max_ref_audios = meta.get("max_ref_audios", 0)
    supports_lyrics = meta.get("supports_lyrics", True)

    settings = [
        {"key": "mode", "label": "生成模式", "type": "select",
         "options": [{"value": v, "label": v} for v in modes],
         "default": (modes[0] if modes else mode)},
        {"key": "prompt", "label": "提示词 / 歌词", "type": "textarea", "default": ""},
        {"key": "style", "label": "风格", "type": "text", "default": ""},
        {"key": "title", "label": "标题", "type": "text", "default": ""},
        {"key": "duration", "label": "时长(秒)", "type": "select",
         "options": [{"value": str(v), "label": str(v)} for v in durations],
         "default": str(durations[0]) if durations else "60"},
        {"key": "instrumental", "label": "纯音乐(无歌词)", "type": "switch", "default": False},
        {"key": "negative_tags", "label": "反向标签", "type": "text", "default": ""},
        {"key": "vocal_gender", "label": "人声性别", "type": "select",
         "options": [{"value": v, "label": v} for v in ["", "male", "female", "girl", "boy", "woman", "man", "children", "young boy", "young girl"]],
         "default": ""},
    ]
    return {
        "model": model,
        "mode": mode,
        "modes": modes,
        "durations": [str(d) for d in durations],
        "max_ref_audios": max_ref_audios,
        "supports_lyrics": supports_lyrics,
        "settings": settings,
    }


@router.post("/schema")
async def post_musicgen_schema(req: MusicGenSchemaRequest):
    mgr = get_musicgen_interface_manager()
    config = _resolve_musicgen_config(mgr, req.interface_id, req.sdk_module, req.config)
    return _build_musicgen_schema(config, req.model, req.mode)


@router.get("/{iface_id}/schema")
async def get_musicgen_schema_by_id(iface_id: str, model: str = "", mode: str = Query("txt2music")):
    mgr = get_musicgen_interface_manager()
    config = _resolve_musicgen_config(mgr, iface_id=iface_id)
    return _build_musicgen_schema(config, model, mode)


@router.get("/sdk/{sdk_module}/schema")
async def get_musicgen_schema_by_sdk(sdk_module: str, model: str = "", mode: str = Query("txt2music")):
    mgr = get_musicgen_interface_manager()
    config = _resolve_musicgen_config(mgr, sdk_module=sdk_module)
    return _build_musicgen_schema(config, model, mode)
