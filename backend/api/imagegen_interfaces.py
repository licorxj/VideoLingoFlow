"""Image Generation Interface API endpoints."""
import os
import uuid
import asyncio
import requests
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.imagegen.imagegen_interface_manager import get_imagegen_interface_manager
from backend.imagegen.imagegen_factory import get_imagegen_engine, clear_cache

router = APIRouter()
_executor = ThreadPoolExecutor(max_workers=2)

IMGGEN_TEST_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tasks", "_imggen_test"
)


# ─── Pydantic Models ───────────────────────────────────────────────
class ImageGenInterfaceCreate(BaseModel):
    id: Optional[str] = None
    name: str = ""
    type: str = "sdk"
    builtin: Optional[bool] = None
    enabled: bool = True
    description: str = ""
    api_source_url: str = ""
    model_docs_url: str = ""
    config: Optional[dict] = None


class ImageGenInterfaceUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    enabled: Optional[bool] = None
    description: Optional[str] = None
    api_source_url: Optional[str] = None
    model_docs_url: Optional[str] = None
    config: Optional[dict] = None


class ImageGenTestRequest(BaseModel):
    prompt: str = "a beautiful sunset over the ocean"
    negative_prompt: str = ""
    resolution: str = "1K"
    aspect_ratio: str = "1:1"
    num_images: int = 1
    ref_images: Optional[List[str]] = None
    model: str = ""
    mode: str = "txt2img"


class ModelAddRequest(BaseModel):
    model_name: str
    modes: list = ["t2i", "i2i"]
    price: str = ""
    resolutions: list = []
    aspect_ratios: list = []


# ─── Helper ─────────────────────────────────────────────────────────
def _run_generate_sync(engine, prompt, output_dir, **kwargs):
    """Synchronous wrapper for engine.generate."""
    return engine.generate(prompt, output_dir, **kwargs)


# ─── CRUD Endpoints ─────────────────────────────────────────────────
@router.get("/")
async def list_interfaces():
    mgr = get_imagegen_interface_manager()
    return {"interfaces": mgr.list_all()}


@router.get("/enabled")
async def list_enabled():
    mgr = get_imagegen_interface_manager()
    return mgr.get_enabled()


@router.get("/{iface_id}")
async def get_interface(iface_id: str):
    mgr = get_imagegen_interface_manager()
    iface = mgr.get(iface_id)
    if not iface:
        raise HTTPException(404, "Interface not found")
    return iface


@router.post("/")
async def create_interface(data: ImageGenInterfaceCreate):
    mgr = get_imagegen_interface_manager()
    iface = mgr.create(data.dict(exclude_none=True))
    clear_cache()
    return iface


@router.put("/{iface_id}")
async def update_interface(iface_id: str, data: ImageGenInterfaceUpdate):
    mgr = get_imagegen_interface_manager()
    iface = mgr.update(iface_id, data.dict(exclude_none=True))
    if not iface:
        raise HTTPException(404, "Interface not found")
    clear_cache()
    return iface


@router.delete("/{iface_id}")
async def delete_interface(iface_id: str):
    mgr = get_imagegen_interface_manager()
    if not mgr.delete(iface_id):
        raise HTTPException(400, "Cannot delete built-in or non-existent interface")
    clear_cache()
    return {"success": True}


@router.post("/{iface_id}/toggle")
async def toggle_interface(iface_id: str, body: dict = None):
    enabled = (body or {}).get("enabled", True)
    mgr = get_imagegen_interface_manager()
    iface = mgr.toggle(iface_id, enabled)
    if not iface:
        raise HTTPException(404, "Interface not found")
    clear_cache()
    return iface


@router.post("/reload")
async def reload_interfaces():
    mgr = get_imagegen_interface_manager()
    mgr.reload()
    clear_cache()
    return {"success": True}


# ─── Balance ───────────────────────────────────────────────────────
@router.post("/{iface_id}/refresh-balance")
async def refresh_balance(iface_id: str):
    """Fetch balance from the interface's balance endpoint."""
    mgr = get_imagegen_interface_manager()
    iface = mgr.get(iface_id)
    if not iface:
        raise HTTPException(404, "Interface not found")

    cfg = iface.get("config", {})
    balance_endpoint = cfg.get("balance_endpoint", "")
    if not balance_endpoint:
        raise HTTPException(400, "No balance endpoint configured")

    api_url = cfg.get("api_url", "")
    api_key = cfg.get("api_key", "")

    # Build full URL
    url = balance_endpoint
    if not balance_endpoint.startswith("http"):
        if api_url:
            url = api_url.rstrip("/") + "/" + balance_endpoint.lstrip("/")
        else:
            raise HTTPException(400, "No API URL configured for relative balance endpoint")

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            # Try common balance response formats
            balance = (
                data.get("balance")
                or data.get("data", {}).get("balance")
                or data.get("data", {}).get("available_balance")
                or data.get("available_balance")
                or data
            )
            mgr.update_balance(iface_id, balance)
            return {"success": True, "balance": balance}
        else:
            raise HTTPException(resp.status_code, f"Balance fetch failed: {resp.text[:200]}")
    except requests.exceptions.RequestException as e:
        raise HTTPException(502, f"Balance fetch error: {str(e)}")


# ─── Model Management ──────────────────────────────────────────────
@router.get("/{iface_id}/models")
async def get_models(iface_id: str):
    mgr = get_imagegen_interface_manager()
    models = mgr.get_models(iface_id)
    metadata = mgr.get_model_metadata(iface_id)
    return {"models": models, "model_metadata": metadata}


@router.get("/{iface_id}/models-for-node")
async def get_models_for_node(iface_id: str, mode: str = "txt2img"):
    """Return model names filtered by mode for workflow node usage."""
    mgr = get_imagegen_interface_manager()
    metadata = mgr.get_model_metadata(iface_id)
    if not metadata:
        # Fallback: return all model_options without filtering
        return mgr.get_models(iface_id)
    mode_key = {
        "txt2img": "t2i",
        "img2img": "i2i",
        "fusion": "i2i",
        "grid": "t2i",
        "i2grid": "i2i",
        "refs2grid": "i2i",
        "websearch": "t2i",
    }.get(mode, mode)
    filtered = [name for name, meta in metadata.items() if mode_key in meta.get("modes", [])]
    return filtered


@router.get("/sdk/{sdk_module}/models-for-node")
async def get_models_for_node_by_sdk(sdk_module: str, mode: str = ""):
    """按 sdk_module 定位生图接口并返回其模型列表（供专用 Seedream 节点动态下拉使用）。

    不依赖接口 id（其为生成型 UUID），通过配置中的 sdk_module 解析，便于配置升级模型。
    mode 可选 txt2img/img2img/fusion/grid/websearch/layer，用于按能力过滤；留空返回全部 model_options。
    """
    mgr = get_imagegen_interface_manager()
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
        raise HTTPException(status_code=404, detail=f"未找到 sdk_module={sdk_module} 的生图接口")
    iface_id = iface["id"]
    if mode:
        metadata = mgr.get_model_metadata(iface_id)
        if not metadata:
            return mgr.get_models(iface_id)
        mode_key = {
            "txt2img": "t2i", "img2img": "i2i", "fusion": "i2i",
            "grid": "t2i", "i2grid": "i2i", "refs2grid": "i2i", "websearch": "t2i",
        }.get(mode, mode)
        return [name for name, meta in metadata.items() if mode_key in meta.get("modes", [])]
    return mgr.get_models(iface_id)


@router.get("/{iface_id}/params/{model}")
async def get_model_params(iface_id: str, model: str):
    """Return resolution and aspect_ratio options for a specific model."""
    mgr = get_imagegen_interface_manager()
    metadata = mgr.get_model_metadata(iface_id)
    if not metadata or model not in metadata:
        return {"resolutions": ["1K", "2K"], "aspect_ratios": ["1:1", "16:9", "9:16"]}
    meta = metadata[model]
    return {
        "resolutions": meta.get("resolutions", ["1K", "2K"]),
        "aspect_ratios": meta.get("aspect_ratios", ["1:1", "16:9", "9:16"]),
    }


@router.post("/{iface_id}/models")
async def add_model(iface_id: str, data: ModelAddRequest):
    mgr = get_imagegen_interface_manager()
    meta = {"modes": data.modes, "price": data.price, "resolutions": data.resolutions, "aspect_ratios": data.aspect_ratios}
    if not mgr.add_model(iface_id, data.model_name, metadata=meta):
        raise HTTPException(404, "Interface not found")
    return {"success": True, "models": mgr.get_models(iface_id), "model_metadata": mgr.get_model_metadata(iface_id)}


@router.delete("/{iface_id}/models/{model_name}")
async def remove_model(iface_id: str, model_name: str):
    mgr = get_imagegen_interface_manager()
    if not mgr.remove_model(iface_id, model_name):
        raise HTTPException(404, "Interface not found")
    return {"success": True, "models": mgr.get_models(iface_id), "model_metadata": mgr.get_model_metadata(iface_id)}


@router.post("/{iface_id}/fetch-models")
async def fetch_models_from_sdk(iface_id: str):
    """Fetch model list from SDK module (if available)."""
    mgr = get_imagegen_interface_manager()
    iface = mgr.get(iface_id)
    if not iface:
        raise HTTPException(404, "Interface not found")

    cfg = iface.get("config", {})
    mod_path = cfg.get("sdk_module", "")
    func_name = cfg.get("sdk_model_list_function", "list_models")

    if not mod_path:
        raise HTTPException(400, "No SDK module configured")

    try:
        import importlib
        mod = importlib.import_module(mod_path)
        func = getattr(mod, func_name, None)
        if func is None:
            raise HTTPException(400, f"Function '{func_name}' not found in module")

        import asyncio
        if asyncio.iscoroutinefunction(func):
            models = await func()
        else:
            models = func()

        if isinstance(models, list):
            for m in models:
                mgr.add_model(iface_id, m)
            return {"success": True, "models": mgr.get_models(iface_id)}

        raise HTTPException(500, "Unexpected return type from model list function")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to fetch models: {str(e)}")


# ─── Test Endpoint ──────────────────────────────────────────────────
@router.post("/{iface_id}/test")
async def test_interface(iface_id: str, req: ImageGenTestRequest):
    mgr = get_imagegen_interface_manager()
    iface = mgr.get(iface_id)
    if not iface:
        raise HTTPException(404, "Interface not found")

    os.makedirs(IMGGEN_TEST_DIR, exist_ok=True)
    output_dir = os.path.join(IMGGEN_TEST_DIR, f"test_{iface_id}_{uuid.uuid4().hex[:8]}")
    os.makedirs(output_dir, exist_ok=True)

    try:
        engine = get_imagegen_engine(iface_id)
        if not engine:
            raise HTTPException(500, "Failed to create engine instance")

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            _executor,
            _run_generate_sync,
            engine, req.prompt, output_dir,
            req.negative_prompt, req.resolution, req.aspect_ratio,
            req.num_images, req.ref_images, req.model,
        )

        # Also pass mode as kwargs
        kwargs = {
            "negative_prompt": req.negative_prompt,
            "resolution": req.resolution,
            "aspect_ratio": req.aspect_ratio,
            "num_images": req.num_images,
            "ref_images": req.ref_images,
            "model": req.model,
            "mode": req.mode,
        }
        result = await loop.run_in_executor(
            _executor,
            lambda: engine.generate(req.prompt, output_dir, **kwargs),
        )

        if result and len(result) > 0:
            return {
                "success": True,
                "images": [os.path.basename(f) for f in result],
                "output_dir": output_dir,
                "count": len(result),
            }
        else:
            raise HTTPException(500, "Image generation failed. Check engine configuration and logs.")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Image generation error: {str(e)}")


@router.get("/test/image/{subdir}/{filename}")
async def get_test_image(subdir: str, filename: str):
    """Serve test-generated images."""
    filepath = os.path.join(IMGGEN_TEST_DIR, subdir, filename)
    if not os.path.exists(filepath):
        raise HTTPException(404, "Image not found")
    from fastapi.responses import FileResponse
    return FileResponse(filepath)


# ─── 节点设置 Schema（按模型动态返回可选设置项与可选项）─────────────────
def _resolve_imagegen_config(mgr, iface_id=None, sdk_module=None, config=None):
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


def _build_imagegen_schema(config, model, mode):
    """根据模型 metadata 构造节点设置 schema（设置项及其可选项）。"""
    metadata = config.get("model_metadata", {})
    if not model and config.get("default_model"):
        model = config.get("default_model")
    meta = metadata.get(model, {}) if model else {}
    resolutions = list(meta.get("resolutions", []))
    aspect_ratios = list(meta.get("aspect_ratios", []))
    # 保留「自动」作为首选项（wrapper 在未指定分辨率时自行推算）
    res_options = (["auto"] if "auto" not in resolutions else []) + resolutions
    settings = [
        {"key": "resolution", "label": "分辨率", "type": "select",
         "options": [{"value": v, "label": v} for v in res_options],
         "default": "auto" if "auto" in res_options else (res_options[0] if res_options else "")},
        {"key": "aspect_ratio", "label": "图片比例", "type": "select",
         "options": [{"value": v, "label": v} for v in aspect_ratios],
         "default": aspect_ratios[0] if aspect_ratios else "1:1"},
    ]
    return {
        "model": model,
        "mode": mode,
        "resolutions": res_options,
        "aspect_ratios": aspect_ratios,
        "settings": settings,
    }


class ImageGenSchemaRequest(BaseModel):
    config: Optional[dict] = None
    interface_id: Optional[str] = None
    sdk_module: Optional[str] = None
    model: str = ""
    mode: str = "txt2img"


@router.post("/schema")
async def post_imagegen_schema(req: ImageGenSchemaRequest):
    """接收完整接口配置 JSON（或 interface_id / sdk_module），返回所选模型的设置 schema。

    前端在用户选择接口与模型后调用，自动匹配卡片上的可选设置项及各设置项的可选项，
    避免用户记忆模型参数差异。
    """
    mgr = get_imagegen_interface_manager()
    config = _resolve_imagegen_config(mgr, req.interface_id, req.sdk_module, req.config)
    return _build_imagegen_schema(config, req.model, req.mode)


@router.get("/{iface_id}/schema")
async def get_imagegen_schema_by_id(iface_id: str, model: str = "", mode: str = "txt2img"):
    mgr = get_imagegen_interface_manager()
    config = _resolve_imagegen_config(mgr, iface_id=iface_id)
    return _build_imagegen_schema(config, model, mode)


@router.get("/sdk/{sdk_module}/schema")
async def get_imagegen_schema_by_sdk(sdk_module: str, model: str = "", mode: str = "txt2img"):
    mgr = get_imagegen_interface_manager()
    config = _resolve_imagegen_config(mgr, sdk_module=sdk_module)
    return _build_imagegen_schema(config, model, mode)
