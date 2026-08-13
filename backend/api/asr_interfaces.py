"""ASR Interfaces API: CRUD for custom ASR interface definitions."""
import os
import uuid
import asyncio
import importlib
import requests
import json
import inspect
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Any

from backend.asr.asr_interface_manager import get_asr_interface_manager

router = APIRouter()

ASR_TEST_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tasks", "_asr_test",
)
ASR_UPLOAD_DIR = os.path.join(ASR_TEST_DIR, "uploads")

_executor = ThreadPoolExecutor(max_workers=2)


class ASRInterfaceCreate(BaseModel):
    id: Optional[str] = None
    name: str
    type: str = "local"
    builtin: Optional[bool] = None
    enabled: bool = True
    description: str = ""
    config: dict = Field(default_factory=dict)


class ASRInterfaceUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    enabled: Optional[bool] = None
    description: Optional[str] = None
    config: Optional[dict] = None


class ASRTestRequest(BaseModel):
    audio_path: str
    language: Optional[str] = None
    model: Optional[str] = None


@router.get("")
async def list_interfaces():
    mgr = get_asr_interface_manager()
    return {"interfaces": mgr.list_all()}


@router.get("/enabled")
async def list_enabled():
    mgr = get_asr_interface_manager()
    return {"interfaces": mgr.get_enabled()}


@router.get("/models")
async def list_model_options():
    """Return model options grouped by engine for frontend dropdowns."""
    mgr = get_asr_interface_manager()
    result = {}
    for iface in mgr.list_all():
        cfg = iface.get("config", {})
        model_opts = cfg.get("model_options", [])
        if model_opts:
            result[iface["id"]] = model_opts
    return {"models": result}


@router.get("/config-fields")
async def get_asr_config_fields():
    """Return dynamically generated config fields for the ASR node based on configured interfaces."""
    mgr = get_asr_interface_manager()
    interfaces = mgr.list_all()

    engine_options = [{"value": "", "label": "跟随全局配置"}]
    models_by_engine = {}
    compute_types_by_engine = {}

    for iface in interfaces:
        cfg = iface.get("config", {})
        engine_options.append({"value": iface["id"], "label": iface["name"]})
        models_by_engine[iface["id"]] = cfg.get("model_options", [])
        compute_types_by_engine[iface["id"]] = cfg.get("compute_type_options", cfg.get("dtype_options", []))

    return {
        "engine_options": engine_options,
        "models_by_engine": models_by_engine,
        "compute_types_by_engine": compute_types_by_engine,
    }


@router.get("/{iface_id}")
async def get_interface(iface_id: str):
    mgr = get_asr_interface_manager()
    iface = mgr.get(iface_id)
    if not iface:
        raise HTTPException(404, "Interface not found")
    return {"interface": iface}


@router.post("")
async def create_interface(req: ASRInterfaceCreate):
    mgr = get_asr_interface_manager()
    iface = mgr.create(req.model_dump())
    return {"success": True, "interface": iface}


@router.put("/{iface_id}")
async def update_interface(iface_id: str, req: ASRInterfaceUpdate):
    mgr = get_asr_interface_manager()
    iface = mgr.update(iface_id, req.model_dump(exclude_none=True))
    if not iface:
        raise HTTPException(404, "Interface not found")
    return {"success": True, "interface": iface}


@router.delete("/{iface_id}")
async def delete_interface(iface_id: str):
    mgr = get_asr_interface_manager()
    if not mgr.delete(iface_id):
        raise HTTPException(400, "Cannot delete builtin interface or not found")
    return {"success": True}


@router.post("/{iface_id}/toggle")
async def toggle_interface(iface_id: str, enabled: bool = True):
    mgr = get_asr_interface_manager()
    iface = mgr.toggle(iface_id, enabled)
    if not iface:
        raise HTTPException(404, "Interface not found")
    return {"success": True, "interface": iface}


@router.post("/reload")
async def reload_interfaces():
    mgr = get_asr_interface_manager()
    mgr.reload()
    return {"success": True, "count": len(mgr.list_all())}


@router.post("/upload-audio")
async def upload_audio(file: UploadFile = File(...)):
    os.makedirs(ASR_UPLOAD_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename or "audio.wav")[1] or ".wav"
    filename = f"upload_{uuid.uuid4().hex[:8]}{ext}"
    filepath = os.path.join(ASR_UPLOAD_DIR, filename)
    with open(filepath, "wb") as fp:
        import shutil
        shutil.copyfileobj(file.file, fp)
    return {
        "success": True,
        "path": filepath,
        "filename": file.filename,
        "saved_as": filename,
    }


def _run_asr_sdk(cfg, audio_path, output_path, language, model):
    """Run ASR via SDK module.

    Dynamically imports the SDK module and calls the target function,
    forwarding all relevant parameters including sdk_extra_args from config.
    """
    pkg_name = cfg.get("sdk_package", "")
    mod_path = cfg.get("sdk_module", "")
    func_name = cfg.get("sdk_function", "transcribe")

    if mod_path:
        mod = importlib.import_module(mod_path)
    elif pkg_name:
        mod_name = pkg_name.replace("-", "_")
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            mod = importlib.import_module(pkg_name)
    else:
        raise ValueError("No SDK package or module configured")

    func = getattr(mod, func_name, None)
    if func is None:
        raise ValueError(f"Function '{func_name}' not found in module")

    # Build kwargs from function signature + config extras
    sig = inspect.signature(func)
    kwargs = {}

    # Core positional/keyword params
    for param_name in sig.parameters:
        if param_name in ("input_path", "input"):
            kwargs["input_path"] = audio_path
        elif param_name in ("output_path", "output"):
            kwargs["output_path"] = output_path
        elif param_name == "callback":
            continue
        elif param_name == "language" and language:
            kwargs["language"] = language
        elif param_name == "model" and model:
            kwargs["model"] = model

    # Forward sdk_extra_args (e.g. compute_type, word_timestamps, vad_onset, etc.)
    sdk_extra = cfg.get("sdk_extra_args", {})
    for k, v in sdk_extra.items():
        # Special handling: flatten vad_onset/vad_offset into vad_options dict
        if k in ("vad_onset", "vad_offset"):
            if "vad_options" not in kwargs:
                kwargs["vad_options"] = {}
            kwargs["vad_options"][k] = v
        elif k in sig.parameters or k in (
            "compute_type", "word_timestamps", "batch_size",
            "align_model_name", "vad_options", "asr_options",
        ):
            kwargs[k] = v

    # Also forward word_timestamps from top-level config
    wt = cfg.get("word_timestamps")
    if wt is not None and "word_timestamps" not in kwargs:
        kwargs["word_timestamps"] = wt

    # Forward diarization params from top-level config
    for key in ("diarize", "diarize_model", "hf_token", "num_speakers", "min_speakers", "max_speakers", "hotwords"):
        val = cfg.get(key)
        if val is not None and key in sig.parameters:
            kwargs[key] = val

    if asyncio.iscoroutinefunction(func):
        return asyncio.run(func(**kwargs))
    else:
        return func(**kwargs)


def _run_asr_local(cfg, audio_path, output_path, language, model):
    """Run ASR via local HTTP API."""
    mgr = get_asr_interface_manager()
    local_id = None
    for iface in mgr.list_all():
        if iface.get("type") == "local":
            local_id = iface["id"]
            break
    if not local_id:
        raise ValueError("No local ASR interface found")
    params = mgr.build_request_params(local_id, audio_path, output_path, language, model)

    timeout = params.get("timeout", 300)

    if params.get("body_type") == "form":
        files = {}
        audio_param = params.get("audio_param", "file")
        body = dict(params.get("body", {}))
        if audio_path and os.path.exists(audio_path):
            files[audio_param] = open(audio_path, "rb")
            body.pop(audio_param, None)

        resp = requests.post(
            params["url"],
            headers=params.get("headers"),
            data=body,
            files=files or None,
            timeout=timeout,
        )
        for f in files.values():
            f.close()
    else:
        resp = requests.post(
            params["url"],
            headers=params.get("headers"),
            json=params.get("body"),
            timeout=timeout,
        )

    if resp.status_code != 200:
        raise Exception(f"ASR request failed: {resp.status_code} {resp.text[:300]}")

    try:
        result = resp.json()
    except Exception:
        result = {"text": resp.text}

    return result


def _run_asr_test(iface_id, audio_path, output_path, language, model):
    """Run ASR test for a given interface."""
    mgr = get_asr_interface_manager()
    iface = mgr.get(iface_id)
    if not iface:
        raise ValueError(f"Interface {iface_id} not found")

    cfg = iface.get("config", {})
    itype = iface.get("type", "local")

    if itype == "sdk":
        return _run_asr_sdk(cfg, audio_path, output_path, language, model)
    else:
        return _run_asr_local(cfg, audio_path, output_path, language, model)


@router.post("/{iface_id}/test")
async def test_interface(iface_id: str, req: ASRTestRequest):
    mgr = get_asr_interface_manager()
    iface = mgr.get(iface_id)
    if not iface:
        raise HTTPException(404, "Interface not found")

    if not req.audio_path or not os.path.exists(req.audio_path):
        raise HTTPException(400, "Audio file not found")

    os.makedirs(ASR_TEST_DIR, exist_ok=True)
    filename = f"test_{iface_id}_{uuid.uuid4().hex[:8]}.json"
    output_path = os.path.join(ASR_TEST_DIR, filename)

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            _executor,
            _run_asr_test,
            iface_id, req.audio_path, output_path, req.language, req.model,
        )

        if os.path.exists(output_path):
            with open(output_path, "r", encoding="utf-8") as f:
                result_data = json.load(f)
        elif isinstance(result, dict):
            result_data = result
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result_data, f, ensure_ascii=False, indent=2)
        else:
            result_data = {"raw": str(result)}

        segment_count = len(result_data.get("segments", []))
        return {
            "success": True,
            "result": result_data,
            "segment_count": segment_count,
            "result_url": f"/api/asr-interfaces/test/result/{filename}",
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"ASR test error: {str(e)}")


@router.get("/test/result/{filename}")
async def get_test_result(filename: str):
    filepath = os.path.join(ASR_TEST_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(404, "Result file not found")
    return FileResponse(filepath, media_type="application/json", filename=filename)


@router.delete("/test/cleanup")
async def cleanup_test_results():
    if os.path.exists(ASR_TEST_DIR):
        import shutil
        shutil.rmtree(ASR_TEST_DIR)
    return {"success": True}


@router.post("/{iface_id}/fetch-sdk-languages")
async def fetch_sdk_languages(iface_id: str):
    """Fetch available languages from SDK function for a given ASR interface."""
    mgr = get_asr_interface_manager()
    iface = mgr.get(iface_id)
    if not iface:
        raise HTTPException(404, "Interface not found")

    cfg = iface.get("config", {})
    func_name = cfg.get("sdk_language_list_function", "")
    if not func_name:
        raise HTTPException(400, "No SDK language list function configured")

    pkg_name = cfg.get("sdk_package", "")
    mod_path = cfg.get("sdk_module", "")

    try:
        if mod_path:
            mod = importlib.import_module(mod_path)
        elif pkg_name:
            mod_name = pkg_name.replace("-", "_")
            try:
                mod = importlib.import_module(mod_name)
            except ImportError:
                mod = importlib.import_module(pkg_name)
        else:
            raise HTTPException(400, "No SDK package or module configured")

        func = getattr(mod, func_name, None)
        if func is None:
            raise HTTPException(400, f"Function '{func_name}' not found in module")

        if asyncio.iscoroutinefunction(func):
            result = await func()
        else:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(_executor, func)

        if isinstance(result, list):
            languages = [str(v) for v in result]
        elif isinstance(result, dict):
            languages = [str(v) for v in result.values()] if result else []
        else:
            languages = []

        return {"success": True, "languages": languages}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Failed to call function: {str(e)}")
