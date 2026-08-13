"""Separation Interfaces API: CRUD for separation interface definitions."""
import os
import uuid
import asyncio
import shutil
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional

from backend.separation.separation_interface_manager import get_separation_interface_manager

router = APIRouter()

SEP_TEST_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tasks", "_sep_test",
)
SEP_UPLOAD_DIR = os.path.join(SEP_TEST_DIR, "uploads")

_executor = ThreadPoolExecutor(max_workers=2)


class SeparationInterfaceCreate(BaseModel):
    id: Optional[str] = None
    name: str
    type: str = "local"
    builtin: Optional[bool] = None
    enabled: bool = True
    description: str = ""
    config: dict = Field(default_factory=dict)


class SeparationInterfaceUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    enabled: Optional[bool] = None
    description: Optional[str] = None
    config: Optional[dict] = None


class SeparationTestRequest(BaseModel):
    audio_path: str
    model: Optional[str] = None
    format: Optional[str] = None


@router.get("")
async def list_interfaces():
    mgr = get_separation_interface_manager()
    return {"interfaces": mgr.list_all()}


@router.get("/enabled")
async def list_enabled():
    mgr = get_separation_interface_manager()
    return {"interfaces": mgr.get_enabled()}


@router.get("/models")
async def list_model_options():
    """Return model options grouped by engine for frontend dropdowns."""
    mgr = get_separation_interface_manager()
    result = {}
    for iface in mgr.list_all():
        cfg = iface.get("config", {})
        opts = cfg.get("model_options", [])
        if opts:
            result[iface["id"]] = opts
    return {"models": result}


@router.get("/config-fields")
async def get_sep_config_fields():
    """Return dynamically generated config fields for the separation node."""
    mgr = get_separation_interface_manager()
    interfaces = mgr.list_all()

    engine_options = [{"value": "", "label": "跟随全局配置"}]
    models_by_engine = {}
    model_details_by_engine = {}

    for iface in interfaces:
        cfg = iface.get("config", {})
        engine_options.append({"value": iface["id"], "label": iface["name"]})
        model_options = cfg.get("model_options", [])
        models_by_engine[iface["id"]] = model_options
        
        # Build model details with descriptions
        model_details = cfg.get("model_details", {})
        details_list = []
        for model_id in model_options:
            detail = model_details.get(model_id, {})
            details_list.append({
                "value": model_id,
                "label": model_id,
                "description": detail.get("description", "")
            })
        model_details_by_engine[iface["id"]] = details_list

    return {
        "engine_options": engine_options,
        "models_by_engine": models_by_engine,
        "model_details_by_engine": model_details_by_engine,
    }


@router.get("/{iface_id}")
async def get_interface(iface_id: str):
    mgr = get_separation_interface_manager()
    iface = mgr.get(iface_id)
    if not iface:
        raise HTTPException(404, "Interface not found")
    return {"interface": iface}


@router.post("")
async def create_interface(req: SeparationInterfaceCreate):
    mgr = get_separation_interface_manager()
    iface = mgr.create(req.model_dump())
    return {"success": True, "interface": iface}


@router.put("/{iface_id}")
async def update_interface(iface_id: str, req: SeparationInterfaceUpdate):
    mgr = get_separation_interface_manager()
    iface = mgr.update(iface_id, req.model_dump(exclude_none=True))
    if not iface:
        raise HTTPException(404, "Interface not found")
    return {"success": True, "interface": iface}


@router.delete("/{iface_id}")
async def delete_interface(iface_id: str):
    mgr = get_separation_interface_manager()
    if not mgr.delete(iface_id):
        raise HTTPException(400, "Cannot delete builtin interface or not found")
    return {"success": True}


@router.post("/{iface_id}/toggle")
async def toggle_interface(iface_id: str, enabled: bool = True):
    mgr = get_separation_interface_manager()
    iface = mgr.toggle(iface_id, enabled)
    if not iface:
        raise HTTPException(404, "Interface not found")
    return {"success": True, "interface": iface}


@router.post("/reload")
async def reload_interfaces():
    mgr = get_separation_interface_manager()
    mgr.reload()
    return {"success": True, "count": len(mgr.list_all())}


@router.post("/upload-audio")
async def upload_audio(file: UploadFile = File(...)):
    os.makedirs(SEP_UPLOAD_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename or "audio.wav")[1] or ".wav"
    filename = f"upload_{uuid.uuid4().hex[:8]}{ext}"
    filepath = os.path.join(SEP_UPLOAD_DIR, filename)
    with open(filepath, "wb") as fp:
        shutil.copyfileobj(file.file, fp)
    return {
        "success": True,
        "path": filepath,
        "filename": file.filename,
        "saved_as": filename,
    }


def _run_sep_test(iface_id, audio_path, output_dir, model, fmt):
    """Run separation test for a given interface."""
    from backend.separation.separation_factory import get_separation_engine
    engine = get_separation_engine(iface_id)
    result = engine.separate(audio_path, output_dir, model=model, format=fmt)
    return result


@router.post("/{iface_id}/test")
async def test_interface(iface_id: str, req: SeparationTestRequest):
    mgr = get_separation_interface_manager()
    iface = mgr.get(iface_id)
    if not iface:
        raise HTTPException(404, "Interface not found")

    if not req.audio_path or not os.path.exists(req.audio_path):
        raise HTTPException(400, "Audio file not found")

    os.makedirs(SEP_TEST_DIR, exist_ok=True)
    test_id = uuid.uuid4().hex[:8]
    output_dir = os.path.join(SEP_TEST_DIR, f"test_{iface_id}_{test_id}")
    os.makedirs(output_dir, exist_ok=True)

    fmt = req.format or iface.get("config", {}).get("format", "wav")

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            _executor,
            _run_sep_test,
            iface_id, req.audio_path, output_dir, req.model, fmt,
        )

        vocals_path = result.get("vocals", "")
        bg_path = result.get("background", "")

        return {
            "success": True,
            "vocals_url": f"/api/separation-interfaces/test/audio/{os.path.basename(vocals_path)}" if vocals_path else None,
            "background_url": f"/api/separation-interfaces/test/audio/{os.path.basename(bg_path)}" if bg_path else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Separation test error: {str(e)}")


@router.get("/test/audio/{filename}")
async def get_test_audio(filename: str):
    """Download test audio file."""
    # Search in all test subdirectories
    for root, dirs, files in os.walk(SEP_TEST_DIR):
        filepath = os.path.join(root, filename)
        if os.path.exists(filepath):
            return FileResponse(filepath, media_type="audio/wav", filename=filename)
    raise HTTPException(404, "Test audio not found")


@router.delete("/test/cleanup")
async def cleanup_test_results():
    if os.path.exists(SEP_TEST_DIR):
        shutil.rmtree(SEP_TEST_DIR)
    return {"success": True}


# --- Model details management ---

class ModelDetailCreate(BaseModel):
    name: str
    description: str


@router.post("/{iface_id}/models/{model_name}")
async def set_model_detail(iface_id: str, model_name: str, req: ModelDetailCreate):
    """Set or update model name and description for an interface."""
    mgr = get_separation_interface_manager()
    iface = mgr.get(iface_id)
    if not iface:
        raise HTTPException(404, "Interface not found")
    cfg = iface.setdefault("config", {})
    model_details = cfg.setdefault("model_details", {})
    model_details[model_name] = {"name": req.name, "description": req.description}
    mgr._save()
    return {"success": True}


@router.delete("/{iface_id}/models/{model_name}")
async def delete_model_detail(iface_id: str, model_name: str):
    """Remove a model detail entry."""
    mgr = get_separation_interface_manager()
    iface = mgr.get(iface_id)
    if not iface:
        raise HTTPException(404, "Interface not found")
    cfg = iface.get("config", {})
    model_details = cfg.get("model_details", {})
    if model_name in model_details:
        del model_details[model_name]
        mgr._save()
    return {"success": True}


@router.put("/{iface_id}/models/{model_name}/set-default")
async def set_model_as_default(iface_id: str, model_name: str):
    """Set a model as the default for this interface."""
    mgr = get_separation_interface_manager()
    iface = mgr.get(iface_id)
    if not iface:
        raise HTTPException(404, "Interface not found")
    cfg = iface.get("config", {})
    model_options = cfg.get("model_options", [])
    if model_name not in model_options:
        model_options.append(model_name)
    cfg["model"] = model_name
    mgr._save()
    return {"success": True}
