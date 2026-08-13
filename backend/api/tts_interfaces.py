"""TTS Interfaces API: CRUD for custom TTS interface definitions."""
import os
import uuid
import shutil
import asyncio
import json
import threading
import importlib
import requests
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Any

from backend.tts.tts_interface_manager import get_tts_interface_manager

router = APIRouter()
voice_router = APIRouter()  # Separate router for /tts-voices endpoints

TTS_TEST_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tasks", "_tts_test"
)
TTS_UPLOAD_DIR = os.path.join(TTS_TEST_DIR, "uploads")

_executor = ThreadPoolExecutor(max_workers=2)

# Voice data file helper
VOICES_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "tts_voices.json")
_voices_lock = threading.Lock()


def _load_voices():
    if os.path.exists(VOICES_FILE):
        with open(VOICES_FILE, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    return {"version": 1, "voices": {}}


def _save_voices(data):
    with open(VOICES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


INTERFACES_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "tts_interfaces.json")


def _load():
    if os.path.exists(INTERFACES_FILE):
        with open(INTERFACES_FILE, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    return {"version": 1, "interfaces": []}


class TTSInterfaceCreate(BaseModel):
    id: Optional[str] = None
    name: str
    type: str = "local"
    builtin: Optional[bool] = None
    enabled: bool = True
    description: str = ""
    config: dict = Field(default_factory=dict)


class TTSInterfaceUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    enabled: Optional[bool] = None
    description: Optional[str] = None
    config: Optional[dict] = None


class TTSTestRequest(BaseModel):
    text: str = "这是一段测试语音，请听效果。This is a test voice."
    mode: Optional[str] = None
    speed: Optional[float] = None
    voice: Optional[str] = None
    model: Optional[str] = None
    ref_audio: Optional[str] = None
    voice_design: Optional[str] = None
    controllable_clone: Optional[str] = None


@router.get("")
async def list_interfaces():
    mgr = get_tts_interface_manager()
    return {"interfaces": mgr.list_all()}


@router.get("/enabled")
async def list_enabled():
    mgr = get_tts_interface_manager()
    return {"interfaces": mgr.get_enabled()}


@router.get("/by-mode/{mode}")
async def list_by_mode(mode: str):
    """获取支持指定TTS模式的已启用接口"""
    mgr = get_tts_interface_manager()
    enabled = mgr.get_enabled()
    filtered = []
    for iface in enabled:
        modes = iface.get("config", {}).get("modes", {})
        if mode in modes and modes[mode].get("enabled", False):
            filtered.append(iface)
    return {"interfaces": filtered, "mode": mode}


@router.get("/{iface_id}")
async def get_interface(iface_id: str):
    mgr = get_tts_interface_manager()
    iface = mgr.get(iface_id)
    if not iface:
        raise HTTPException(404, "Interface not found")
    return {"interface": iface}


@router.post("")
async def create_interface(req: TTSInterfaceCreate):
    mgr = get_tts_interface_manager()
    iface = mgr.create(req.model_dump())
    return {"success": True, "interface": iface}


@router.put("/{iface_id}")
async def update_interface(iface_id: str, req: TTSInterfaceUpdate):
    mgr = get_tts_interface_manager()
    iface = mgr.update(iface_id, req.model_dump(exclude_none=True))
    if not iface:
        raise HTTPException(404, "Interface not found")
    return {"success": True, "interface": iface}


@router.delete("/{iface_id}")
async def delete_interface(iface_id: str):
    mgr = get_tts_interface_manager()
    if not mgr.delete(iface_id):
        raise HTTPException(400, "Cannot delete builtin interface or not found")
    return {"success": True}


@router.post("/{iface_id}/toggle")
async def toggle_interface(iface_id: str, enabled: bool = True):
    mgr = get_tts_interface_manager()
    iface = mgr.toggle(iface_id, enabled)
    if not iface:
        raise HTTPException(404, "Interface not found")
    return {"success": True, "interface": iface}


@router.post("/reload")
async def reload_interfaces():
    mgr = get_tts_interface_manager()
    mgr.reload()
    return {"success": True, "count": len(mgr.list_all())}


@router.post("/upload-audio")
async def upload_audio(file: UploadFile = File(...)):
    os.makedirs(TTS_UPLOAD_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename or "audio.wav")[1] or ".wav"
    filename = f"upload_{uuid.uuid4().hex[:8]}{ext}"
    filepath = os.path.join(TTS_UPLOAD_DIR, filename)
    with open(filepath, "wb") as fp:
        shutil.copyfileobj(file.file, fp)
    return {
        "success": True,
        "path": filepath,
        "filename": file.filename,
        "saved_as": filename,
    }


def _run_tts_sync(engine, text, output_path, ref_audio, mode,
                   voice_design, controllable_clone, speed, model, voice):
    return engine.synthesize(
        text=text,
        output_path=output_path,
        ref_audio=ref_audio,
        mode=mode,
        voice_design=voice_design,
        controllable_clone=controllable_clone,
        speed=speed,
        model=model,
        voice=voice,
    )


@router.post("/{iface_id}/test")
async def test_interface(iface_id: str, req: TTSTestRequest):
    mgr = get_tts_interface_manager()
    iface = mgr.get(iface_id)
    if not iface:
        raise HTTPException(404, "Interface not found")

    os.makedirs(TTS_TEST_DIR, exist_ok=True)
    filename = f"test_{iface_id}_{uuid.uuid4().hex[:8]}.wav"
    output_path = os.path.join(TTS_TEST_DIR, filename)

    try:
        from backend.tts.tts_factory import get_tts_engine
        engine = get_tts_engine(iface_id)

        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(
            _executor,
            _run_tts_sync,
            engine, req.text, output_path, req.ref_audio, req.mode,
            req.voice_design, req.controllable_clone, req.speed,
            req.model, req.voice,
        )

        if success and os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            return {
                "success": True,
                "audio_url": f"/api/tts-interfaces/test/audio/{filename}",
                "filename": filename,
                "file_size": file_size,
            }
        else:
            iface_cfg = iface.get("config", {})
            msg = "TTS synthesis failed. "
            if iface.get("type") == "local" and req.mode == "clone":
                ref_key = iface_cfg.get("ref_audio_param", "")
                if ref_key and not req.ref_audio:
                    msg += f"This interface requires a reference audio file for clone mode (parameter: {ref_key})."
            if iface.get("type") == "local" and req.mode == "voice_design":
                msg += "Check that the voice design instruct text uses valid items."
            raise HTTPException(500, msg)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"TTS test error: {str(e)}")


@router.get("/test/audio/{filename}")
async def get_test_audio(filename: str):
    filepath = os.path.join(TTS_TEST_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(404, "Audio file not found")
    return FileResponse(filepath, media_type="audio/wav", filename=filename)


@router.get("/capabilities/{engine_id}")
async def get_engine_capabilities(engine_id: str):
    """获取指定TTS引擎支持的模式和能力"""
    mgr = get_tts_interface_manager()
    iface = mgr.get(engine_id)
    if not iface:
        raise HTTPException(404, f"TTS引擎 '{engine_id}' 不存在")

    modes = iface.get("config", {}).get("modes", {})
    supported_modes = [mode for mode, cfg in modes.items() if cfg.get("enabled")]

    return {
        "engine_id": engine_id,
        "name": iface.get("name"),
        "supported_modes": supported_modes,
        "voice_options": iface.get("config", {}).get("voice_options", []),
        "model_options": iface.get("config", {}).get("model_options", []),
    }


@router.get("/{engine_id}/voices")
async def get_engine_voices(engine_id: str):
    """Get voice options for an engine - now reads from tts_voices.json"""
    with _voices_lock:
        data = _load_voices()
    voices = data.get("voices", {}).get(engine_id, [])
    # Return voice_id list for backward compatibility with api-select
    voice_ids = [v["voice_id"] for v in voices] if voices else []
    return {"voices": voice_ids, "engine_id": engine_id}


@router.post("/{iface_id}/fetch-sdk-voices")
async def fetch_sdk_voices(iface_id: str):
    mgr = get_tts_interface_manager()
    iface = mgr.get(iface_id)
    if not iface:
        raise HTTPException(404, "Interface not found")
    cfg = iface.get("config", {})
    func_name = cfg.get("sdk_voice_list_function", "")
    if not func_name:
        raise HTTPException(400, "未配置获取音色列表的函数名")

    pkg_name = cfg.get("sdk_package", "")
    mod_path = cfg.get("sdk_module", "")

    try:
        import importlib
        if mod_path:
            mod = importlib.import_module(mod_path)
        elif pkg_name:
            mod_name = pkg_name.replace("-", "_")
            try:
                mod = importlib.import_module(mod_name)
            except ImportError:
                mod = importlib.import_module(pkg_name)
        else:
            raise HTTPException(400, "未配置 SDK 包名或模块路径")

        func = getattr(mod, func_name, None)
        if func is None:
            raise HTTPException(400, f"函数 {func_name} 在模块中未找到")

        import asyncio
        if asyncio.iscoroutinefunction(func):
            result = await func()
        else:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(_executor, func)

        if isinstance(result, list):
            voices = [str(v) for v in result]
        elif isinstance(result, dict):
            voices = [str(v) for v in result.values()] if result else []
        else:
            voices = []

        return {"success": True, "voices": voices}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"调用函数失败: {str(e)}")


@voice_router.get("/{interface_id}")
async def get_voices(interface_id: str):
    """Get voice list for an interface from tts_voices.json"""
    with _voices_lock:
        data = _load_voices()
    voices = data.get("voices", {}).get(interface_id, [])
    return {"voices": voices, "interface_id": interface_id}


@voice_router.post("/{interface_id}")
async def add_voice(interface_id: str, voice: dict):
    """Add a single voice to an interface"""
    with _voices_lock:
        data = _load_voices()
        voices = data.setdefault("voices", {}).setdefault(interface_id, [])
        # Check duplicate
        if any(v["voice_id"] == voice.get("voice_id") for v in voices):
            raise HTTPException(status_code=400, detail=f"Voice '{voice.get('voice_id')}' already exists")
        voices.append(voice)
        _save_voices(data)
    return {"success": True, "total": len(voices)}


@voice_router.post("/{interface_id}/batch")
async def add_voices_batch(interface_id: str, body: dict):
    """Batch add voices to an interface"""
    new_voices = body.get("voices", [])
    with _voices_lock:
        data = _load_voices()
        voices = data.setdefault("voices", {}).setdefault(interface_id, [])
        existing_ids = {v["voice_id"] for v in voices}
        added = 0
        for v in new_voices:
            if v.get("voice_id") and v["voice_id"] not in existing_ids:
                voices.append(v)
                existing_ids.add(v["voice_id"])
                added += 1
        _save_voices(data)
    return {"success": True, "added": added, "total": len(voices)}


@voice_router.delete("/{interface_id}/{voice_id}")
async def delete_voice(interface_id: str, voice_id: str):
    """Delete a voice from an interface"""
    with _voices_lock:
        data = _load_voices()
        voices = data.get("voices", {}).get(interface_id, [])
        data["voices"][interface_id] = [v for v in voices if v["voice_id"] != voice_id]
        _save_voices(data)
    return {"success": True}


@voice_router.post("/{interface_id}/fetch")
async def fetch_voices(interface_id: str):
    """Fetch supported voices from TTS interface (SDK, remote API, or built-in)"""
    # Find the interface
    iface = None
    for item in _load().get("interfaces", []):
        if item["id"] == interface_id:
            iface = item
            break
    if not iface:
        raise HTTPException(status_code=404, detail="Interface not found")

    cfg = iface.get("config", {})
    iface_type = iface.get("type", "")
    fetched_voices = []

    # 1. Try SDK voice list function (sdk or online type with sdk_voice_list_function)
    sdk_func_name = cfg.get("sdk_voice_list_function", "")
    if sdk_func_name:
        try:
            # Use sdk_voice_list_module if specified, otherwise fall back to sdk_module
            module_path = cfg.get("sdk_voice_list_module", "") or cfg.get("sdk_module", "")
            if module_path:
                mod = importlib.import_module(module_path)
                func = getattr(mod, sdk_func_name, None)
                if func:
                    api_key = cfg.get("sdk_api_key", "")
                    try:
                        raw_voices = func(api_key=api_key)
                    except TypeError:
                        raw_voices = func()
                    for v in raw_voices:
                        if isinstance(v, str):
                            fetched_voices.append({
                                "voice_id": v, "voice_name": "", "description": "",
                                "gender": "", "age": "", "language": ""
                            })
                        elif isinstance(v, dict):
                            fetched_voices.append({
                                "voice_id": v.get("id", v.get("voice_id", "")),
                                "voice_name": v.get("name", v.get("voice_name", "")),
                                "description": v.get("description", ""),
                                "gender": v.get("gender", ""),
                                "age": v.get("age", ""),
                                "language": v.get("language", v.get("locale", ""))
                            })
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"SDK voice fetch failed: {e}")

    # 2. Try remote API (online type with voice_list_url)
    elif cfg.get("voice_list_url"):
        try:
            resp = requests.get(cfg["voice_list_url"], timeout=10)
            resp.raise_for_status()
            raw = resp.json()
            key_path = cfg.get("voice_list_key", "")
            if key_path:
                for k in key_path.split("."):
                    raw = raw.get(k, []) if isinstance(raw, dict) else []
            if isinstance(raw, list):
                for v in raw:
                    if isinstance(v, str):
                        fetched_voices.append({
                            "voice_id": v, "voice_name": "", "description": "",
                            "gender": "", "age": "", "language": ""
                        })
                    elif isinstance(v, dict):
                        fetched_voices.append({
                            "voice_id": v.get("id", v.get("voice_id", "")),
                            "voice_name": v.get("name", v.get("voice_name", "")),
                            "description": v.get("description", ""),
                            "gender": v.get("gender", ""),
                            "age": v.get("age", ""),
                            "language": v.get("language", v.get("locale", ""))
                        })
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Remote voice fetch failed: {e}")

    # 3. Built-in voice lists for known online interfaces
    elif iface_type == "online":
        fetched_voices = _get_builtin_voices(interface_id, cfg)

    if not fetched_voices:
        raise HTTPException(status_code=400, detail="This interface does not support voice fetching (no sdk_voice_list_function or voice_list_url configured)")

    return {"voices": fetched_voices, "interface_id": interface_id}


def _get_builtin_voices(interface_id: str, cfg: dict) -> list:
    """Return built-in voice lists for known online TTS interfaces."""
    voices = []

    # OpenAI TTS: fixed voice set
    if interface_id == "openai_tts":
        openai_voices = [
            ("alloy", "Alloy", "Balanced, neutral tone"),
            ("ash", "Ash", "Clear and expressive"),
            ("ballad", "Ballad", "Warm and melodic"),
            ("coral", "Coral", "Friendly and natural"),
            ("echo", "Echo", "Smooth and resonant"),
            ("fable", "Fable", "Expressive storytelling voice"),
            ("nova", "Nova", "Bright and energetic"),
            ("onyx", "Onyx", "Deep and authoritative"),
            ("sage", "Sage", "Calm and thoughtful"),
            ("shimmer", "Shimmer", "Soft and gentle"),
        ]
        for vid, vname, desc in openai_voices:
            voices.append({
                "voice_id": vid, "voice_name": vname, "description": desc,
                "gender": "", "age": "adult", "language": "en"
            })

    # Azure TTS: common Chinese + English voices
    elif interface_id == "azure_tts":
        azure_voices = [
            ("zh-CN-YunjianNeural", "云健", "成熟男声，适合新闻播报", "male", "zh-CN"),
            ("zh-CN-YunxiNeural", "云希", "年轻男声，活泼自然", "male", "zh-CN"),
            ("zh-CN-XiaoxiaoNeural", "晓晓", "成熟女声，温柔亲切", "female", "zh-CN"),
            ("zh-CN-XiaoyiNeural", "晓伊", "年轻女声，甜美清新", "female", "zh-CN"),
            ("zh-CN-YunjhNeural", "云杰", "沉稳男声", "male", "zh-CN"),
            ("zh-CN-YanxiNeural", "云溪", "温柔女声", "female", "zh-CN"),
            ("en-US-AriaNeural", "Aria", "Natural female voice", "female", "en-US"),
            ("en-US-GuyNeural", "Guy", "Natural male voice", "male", "en-US"),
            ("en-US-JennyNeural", "Jenny", "Professional female voice", "female", "en-US"),
            ("en-US-DavisNeural", "Davis", "Calm male voice", "male", "en-US"),
            ("ja-JP-NanamiNeural", "Nanami", "Japanese female voice", "female", "ja-JP"),
            ("ko-KR-SunHiNeural", "SunHi", "Korean female voice", "female", "ko-KR"),
        ]
        for vid, vname, desc, gender, lang in azure_voices:
            voices.append({
                "voice_id": vid, "voice_name": vname, "description": desc,
                "gender": gender, "age": "adult", "language": lang
            })

    return voices


@router.delete("/test/cleanup")
async def cleanup_test_audio():
    if os.path.exists(TTS_TEST_DIR):
        shutil.rmtree(TTS_TEST_DIR)
    return {"success": True}