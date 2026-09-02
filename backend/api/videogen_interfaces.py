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


@router.get("/sdk/{sdk_module}/models-for-node")
async def get_videogen_models_for_node_by_sdk(
    sdk_module: str,
    mode: str = Query("", description="节点模式: t2v / i2v / flf / v2v 或原始模式名"),
):
    """按 sdk_module 定位视频生成接口并返回其模型列表（供专用 Seedance 节点动态下拉使用）。

    不依赖接口 id（生成型 UUID），通过配置中的 sdk_module 解析，便于配置升级模型。
    mode 可选 t2v/i2v/flf/v2v 或原始模式名 txt2video/img2video/flf2video/autovideo，按能力过滤模型。
    返回纯模型名数组，供前端 api-select 直接消费。
    """
    mgr = get_videogen_interface_manager()
    iface = None
    for i in mgr.get_enabled():
        if (i.get("config", {}) or {}).get("sdk_module") == sdk_module:
            iface = i
            break
    if iface is None:
        for i in mgr.list_all():
            if (i.get("config", {}) or {}).get("sdk_module") == sdk_module:
                iface = i
                break
    if iface is None:
        raise HTTPException(status_code=404, detail=f"未找到 sdk_module={sdk_module} 的视频生成接口")
    config = iface.get("config", {})
    metadata = config.get("model_metadata", {})
    models = config.get("model_options", [])
    if not mode:
        return models
    mode_map = {"t2v": "txt2video", "i2v": "img2video", "flf": "flf2video", "v2v": "autovideo"}
    target_mode = mode_map.get(mode, mode)
    return [m for m in models if target_mode in (metadata.get(m, {}).get("modes", []))]


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


# ─────────────────────────────────────────────────────────────────────────────
# 节点设置 Schema（按模型动态返回可选设置项与可选项）
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_videogen_config(mgr, iface_id=None, sdk_module=None, config=None):
    """按优先级解析接口配置：显式 config > interface_id > sdk_module。"""
    if config:
        return config
    if iface_id:
        iface = mgr.get(iface_id)
        if not iface:
            raise HTTPException(status_code=404, detail="接口不存在")
        return iface.get("config", {})
    if sdk_module:
        for i in mgr.get_enabled():
            if (i.get("config", {}) or {}).get("sdk_module") == sdk_module:
                return i.get("config", {})
        for i in mgr.list_all():
            if (i.get("config", {}) or {}).get("sdk_module") == sdk_module:
                return i.get("config", {})
    raise HTTPException(status_code=400, detail="需提供 config / interface_id / sdk_module 之一")


def _build_videogen_schema(config, model, mode):
    """根据模型 metadata / SDK 能力矩阵构造节点设置 schema（设置项及其可选项）。

    对 Seedance 类 SDK（sdk_module=backend.videogen.sdk.seedance_wrapper），直接按
    seedance_sdk._family 能力矩阵推导分辨率集合、时长区间与各专有参数支持情况，确保
    卡片展示的「可选时长 / 分辨率 / 开关项」与所选模型真实能力一致；其它接口沿用
    model_metadata。
    """
    sdk_module = config.get("sdk_module", "")
    is_seedance = sdk_module == "backend.videogen.sdk.seedance_wrapper"

    fam = None
    if is_seedance:
        try:
            from backend.videogen.sdk import seedance_sdk
            fam = seedance_sdk._family(model)
        except Exception:
            fam = None

    metadata = config.get("model_metadata", {})
    if not model and config.get("default_model"):
        model = config.get("default_model")
    meta = metadata.get(model, {}) if model else {}

    if fam:
        # 分辨率优先用 metadata（权威），缺失时回落能力矩阵档位排序
        _order = {"480p": 0, "720p": 1, "1080p": 2, "4k": 3}
        resolutions = list(meta.get("resolutions", [])) or sorted(fam["resolutions"], key=lambda r: _order.get(r, 9))
        # 时长优先用 metadata 中官方支持的离散取值；缺失时按家族区间展开（-1 表示智能时长）
        durs_meta = meta.get("durations", [])
        if durs_meta:
            durations = [int(d) for d in durs_meta]
            if fam.get("allow_neg1") and -1 not in durations:
                durations = [-1] + durations
        else:
            dmin, dmax = fam["duration"]
            durations = list(range(dmin, dmax + 1))
            if fam.get("allow_neg1"):
                durations = [-1] + durations
        supports_audio = meta.get("supports_audio", "generate_audio" in fam["supports"])
        default_audio = meta.get("default_audio", "on" if supports_audio else "model_default")
        sup = fam["supports"]
        ratio_default = meta.get("ratio_default") or fam.get("ratio_default", "16:9")
        modes = list(meta.get("modes", []) or [])
    else:
        resolutions = list(meta.get("resolutions", []))
        durations = list(meta.get("durations", []))
        supports_audio = meta.get("supports_audio", False)
        default_audio = meta.get("default_audio", "model_default")
        sup = set(meta.get("supports", []) or [])
        ratio_default = meta.get("ratio_default", "16:9")
        modes = list(meta.get("modes", []) or [])

    audio_options = ["on", "off", "keep_original", "model_default"] if supports_audio else []
    # 专有参数能力开关：供前端按模型显隐设置项（seedance 取能力矩阵，其它取 meta.supports）
    caps = {
        "seed": "seed" in sup,
        "camera_fixed": "camera_fixed" in sup,
        "return_last_frame": "return_last_frame" in sup,
        "draft": "draft" in sup,
        "tools_web_search": "tools_web_search" in sup,
        "service_tier_flex": "service_tier_flex" in sup,
        "priority": "priority" in sup,
        "output_format_mov": "output_format_mov" in sup,
    }
    settings = [
        {"key": "resolution", "label": "分辨率", "type": "select",
         "options": [{"value": v, "label": v} for v in resolutions],
         "default": resolutions[0] if resolutions else "720P"},
        {"key": "duration", "label": "时长(秒)", "type": "select",
         "options": [{"value": str(v), "label": ("智能" if v == -1 else str(v))} for v in durations],
         "default": str(durations[0]) if durations else "5"},
        {"key": "audio", "label": "声音", "type": "select",
         "options": [{"value": v, "label": v} for v in audio_options],
         "default": default_audio, "visible": supports_audio},
    ]
    return {
        "model": model,
        "mode": mode,
        "resolutions": resolutions,
        "durations": [str(d) for d in durations],
        "audio": audio_options,
        "modes": modes,
        "supports_audio": supports_audio,
        "default_audio": default_audio,
        "ratio_default": ratio_default,
        "max_ref_images": meta.get("max_ref_images", 0),
        "max_ref_videos": meta.get("max_ref_videos", 0),
        "max_ref_audios": meta.get("max_ref_audios", 0),
        "supports": caps,
        "settings": settings,
    }


class VideoGenSchemaRequest(BaseModel):
    config: Optional[Dict[str, Any]] = None
    interface_id: Optional[str] = None
    sdk_module: Optional[str] = None
    model: str = ""
    mode: str = "txt2video"


@router.post("/schema")
async def post_videogen_schema(req: VideoGenSchemaRequest):
    """接收完整接口配置 JSON（或 interface_id / sdk_module），返回所选模型的设置 schema。

    前端在用户选择接口与模型后调用，自动匹配卡片上的可选设置项及各设置项的可选项，
    避免用户记忆模型参数差异。AI生视频 节点亦使用此接口（传递整个接口配置）。
    """
    mgr = get_videogen_interface_manager()
    config = _resolve_videogen_config(mgr, req.interface_id, req.sdk_module, req.config)
    return _build_videogen_schema(config, req.model, req.mode)


@router.get("/{iface_id}/schema")
async def get_videogen_schema_by_id(iface_id: str, model: str = "", mode: str = Query("txt2video")):
    mgr = get_videogen_interface_manager()
    config = _resolve_videogen_config(mgr, iface_id=iface_id)
    return _build_videogen_schema(config, model, mode)


@router.get("/sdk/{sdk_module}/schema")
async def get_videogen_schema_by_sdk(sdk_module: str, model: str = "", mode: str = Query("txt2video")):
    mgr = get_videogen_interface_manager()
    config = _resolve_videogen_config(mgr, sdk_module=sdk_module)
    return _build_videogen_schema(config, model, mode)


# ─────────────────────────────────────────────────────────────────────────────
# Seedance 任务进度查询（前端节点「查询生成进度」按钮调用）
# ─────────────────────────────────────────────────────────────────────────────
class SeedanceQueryRequest(BaseModel):
    task_id: str
    api_key: Optional[str] = ""


def _seedance_api_key(api_key: str = "") -> str:
    """API Key 解析：显式参数 > 环境变量 ARK_API_KEY > seedance_video 接口配置。"""
    if api_key:
        return api_key
    from backend.videogen.sdk import seedance_sdk
    k = seedance_sdk._get_api_key("")
    if k:
        return k
    try:
        mgr = get_videogen_interface_manager()
        iface = mgr.get("seedance_video")
        if iface:
            cfg = iface.get("config", {}) or {}
            k = cfg.get("sdk_api_key") or cfg.get("api_key") or ""
            if k:
                return k
    except Exception:
        pass
    return k


@router.post("/seedance/query")
async def query_seedance_task(req: SeedanceQueryRequest):
    """按 task_id 查询 Seedance 视频生成任务状态与产物，返回精简结果供前端展示。"""
    if not req.task_id:
        raise HTTPException(status_code=400, detail="task_id 不能为空")
    from backend.videogen.sdk import seedance_sdk
    api_key = _seedance_api_key(req.api_key)
    try:
        task = seedance_sdk.query_task(req.task_id, api_key=api_key)
    except Exception as e:
        logger.error("Seedance 查询任务失败: %s", e)
        raise HTTPException(status_code=502, detail=f"查询失败: {e}")
    content = task.get("content") or {}
    return {
        "task_id": req.task_id,
        "status": task.get("status"),
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
        "error": task.get("error"),
        "usage": task.get("usage"),
        "content": {
            "video_url": content.get("video_url"),
            "last_frame_url": content.get("last_frame_url"),
        },
        "raw": task,
    }
