"""Cutia 深度融合桥接 API。

把第三方编辑器 Cutia（thirdparty/cutia）的 AI 能力接到 VideoLingo 已有的
接口层与 LLM 路由上，Cutia 侧不再需要单独配置任何 Key：

  - POST /api/cutia-bridge/chat/completions  OpenAI 兼容对话（tools / stream）
  - GET  /api/cutia-bridge/capabilities     可用生图 / 生视频 / TTS 接口清单
  - POST /api/cutia-bridge/upload           参考图上传（返回可访问 URL）
  - POST /api/cutia-bridge/image            生图
  - POST /api/cutia-bridge/video            提交生视频任务（异步）
  - GET  /api/cutia-bridge/video/{task_id}  查询生视频任务
  - POST /api/cutia-bridge/tts              语音合成

产物统一落在 data/cutia/generated 下，通过 /api/files/stream 回传可访问 URL。
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, quote, urlparse

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.creation.paths import DATA_ROOT
from backend.llm.llm_client import get_llm_client

logger = logging.getLogger(__name__)

router = APIRouter()

# Cutia 生成产物目录（公共可读，走 /api/files/stream 回传）
GENERATED_DIR = DATA_ROOT / "cutia" / "generated"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)

# 生视频任务表（进程内，桌面单实例足够；带 TTL 自动回收）
_VIDEO_TASKS: dict[str, dict[str, Any]] = {}
_VIDEO_LOCK = threading.Lock()
_VIDEO_TTL = 3600.0

# Cutia 侧代表「跟随主项目默认模型」的占位模型名
_HOST_PLACEHOLDER_MODELS = {"", "auto", "host", "videolingo", "videolingo-host", "default"}


def _public_url(path: Path) -> str:
    """把本地绝对路径包装成前端可访问的流式 URL。"""
    return f"/api/files/stream?path={quote(str(path), safe='')}"


def _prune_video_tasks() -> None:
    now = time.time()
    with _VIDEO_LOCK:
        for task_id in [
            key
            for key, value in _VIDEO_TASKS.items()
            if now - float(value.get("updatedAt") or now) > _VIDEO_TTL
        ]:
            _VIDEO_TASKS.pop(task_id, None)


# --------------------------------------------------------------------------- #
# LLM：OpenAI 兼容代理（Cutia Agent 直接调用）
# --------------------------------------------------------------------------- #


class ChatCompletionsRequest(BaseModel):
    model: Optional[str] = None
    messages: list = []
    tools: Optional[list] = None
    tool_choice: Optional[Any] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    stream: bool = False


def _llm_api_config() -> dict[str, Any]:
    """按 cutia_agent → editor_agent → default 顺序取第一个真正配了模型的连接配置。

    ``_get_api_config`` 在没有任何 step 覆盖时会把 step 名本身当模型名返回，
    这里逐个试，避免把 "cutia_agent" 这种占位值当真实模型发出去。
    """
    llm = get_llm_client()
    fallback: dict[str, Any] | None = None
    for step in ("cutia_agent", "editor_agent", "default"):
        cfg = llm._get_api_config(step)
        fallback = fallback or cfg
        model = str(cfg.get("model") or "")
        if model and model != step and model != "default":
            return cfg
    return fallback or {"base_url": "", "api_key": "", "model": ""}


def _resolve_model(requested: Optional[str], fallback: str) -> str:
    value = (requested or "").strip()
    if value and value.lower() not in _HOST_PLACEHOLDER_MODELS:
        return value
    return fallback


def _build_payload(req: ChatCompletionsRequest, default_model: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": _resolve_model(req.model, default_model),
        "messages": req.messages,
        "stream": bool(req.stream),
    }
    if req.tools:
        payload["tools"] = req.tools
        if req.tool_choice is not None:
            payload["tool_choice"] = req.tool_choice
    for key in ("temperature", "top_p", "max_tokens"):
        value = getattr(req, key)
        if value is not None:
            payload[key] = value
    return payload


def _stream_chunks(client: Any, payload: dict[str, Any]):
    """同步生成器：FastAPI 会放到线程池里迭代，不阻塞事件循环。"""
    try:
        for chunk in client.chat.completions.create(**payload):
            yield f"data: {chunk.model_dump_json(exclude_none=True)}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as exc:  # noqa: BLE001 - 需要把上游错误透给前端
        logger.exception("[cutia-bridge] 流式对话失败")
        yield f"data: {json.dumps({'error': {'message': str(exc)}}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"


@router.post("/chat/completions")
async def chat_completions(req: ChatCompletionsRequest):
    """OpenAI 兼容的 chat/completions，走主项目已配置的 LLM 连接。"""
    try:
        api_cfg = _llm_api_config()
        if not api_cfg.get("base_url") or not api_cfg.get("api_key"):
            raise HTTPException(status_code=503, detail="主项目 LLM 未配置")
        client = llm._make_client(api_cfg)
        payload = _build_payload(req, api_cfg["model"])
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("[cutia-bridge] 构建 LLM 请求失败")
        raise HTTPException(status_code=500, detail=str(exc))

    if req.stream:
        return StreamingResponse(
            _stream_chunks(client, payload),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        completion = client.chat.completions.create(**payload)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[cutia-bridge] 对话失败")
        raise HTTPException(status_code=502, detail=str(exc))
    return json.loads(completion.model_dump_json())


# --------------------------------------------------------------------------- #
# 能力清单
# --------------------------------------------------------------------------- #


def _iface_options(manager: Any) -> list[dict[str, Any]]:
    try:
        enabled = manager.get_enabled() or []
    except Exception:  # noqa: BLE001
        return []
    options = []
    for iface in enabled:
        if not isinstance(iface, dict):
            continue
        options.append(
            {
                "id": iface.get("id") or "",
                "name": iface.get("name") or iface.get("id") or "",
                "type": iface.get("type") or "",
                "models": _safe_models(manager, iface.get("id")),
            }
        )
    return [item for item in options if item["id"]]


def _safe_models(manager: Any, iface_id: Optional[str]) -> list[str]:
    if not iface_id or not hasattr(manager, "get_models"):
        return []
    try:
        models = manager.get_models(iface_id) or []
    except Exception:  # noqa: BLE001
        return []
    result = []
    for model in models:
        if isinstance(model, str):
            result.append(model)
        elif isinstance(model, dict):
            value = model.get("id") or model.get("name") or model.get("model")
            if value:
                result.append(str(value))
    return result


@router.get("/capabilities")
def capabilities():
    """返回主项目当前可用的 LLM / 生图 / 生视频 / TTS 能力，供 Cutia 展示。"""
    llm_info = {"connected": False, "model": ""}
    try:
        api_cfg = _llm_api_config()
        llm_info = {
            "connected": bool(api_cfg.get("base_url") and api_cfg.get("api_key")),
            "model": api_cfg.get("model") or "",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("[cutia-bridge] 读取 LLM 配置失败: %s", exc)

    result: dict[str, Any] = {"llm": llm_info}
    for key, module_path, attr in (
        ("image", "backend.imagegen.imagegen_interface_manager", "get_imagegen_interface_manager"),
        ("video", "backend.videogen.videogen_interface_manager", "get_videogen_interface_manager"),
        ("tts", "backend.tts.tts_interface_manager", "get_tts_interface_manager"),
    ):
        try:
            module = __import__(module_path, fromlist=[attr])
            manager = getattr(module, attr)()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[cutia-bridge] 读取 %s 接口层失败: %s", key, exc)
            result[key] = []
            continue
        result[key] = _iface_options(manager)
    return result


# --------------------------------------------------------------------------- #
# 参考图上传
# --------------------------------------------------------------------------- #


@router.post("/upload")
async def upload_reference(file: UploadFile = File(...)):
    """接收 Cutia 上传的参考图，返回 /api/files/stream 可访问 URL。"""
    directory = GENERATED_DIR / "refs"
    directory.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "").suffix or ".png"
    target = directory / f"ref_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}{suffix}"
    try:
        content = await file.read()
        target.write_bytes(content)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"上传失败: {exc}")
    return {"url": _public_url(target), "path": str(target)}


def _download_ref(url: str, directory: Path) -> Optional[str]:
    import requests

    suffix = Path(urlparse(url).path).suffix or ".png"
    target = directory / f"ref_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}{suffix}"
    try:
        with requests.get(url, timeout=120) as resp:
            resp.raise_for_status()
            target.write_bytes(resp.content)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[cutia-bridge] 下载参考图失败 %s: %s", url, exc)
        return None
    return str(target)


def _resolve_ref_images(urls: list[str], directory: Path) -> list[str]:
    """把各种形态的参考图 URL 归一化成本地路径 / data URI。

    Cutia 侧的素材 url 可能是 blob:（无法服务端获取，直接丢弃）、
    /api/files/stream?path=（主项目产物）、http(s) 或 data:。
    """
    resolved: list[str] = []
    for url in urls:
        if not url:
            continue
        if url.startswith("data:"):
            resolved.append(url)
            continue
        if url.startswith("blob:"):
            logger.warning("[cutia-bridge] 忽略无法服务端读取的 blob 参考图")
            continue
        if url.startswith("/api/files/stream"):
            query = parse_qs(urlparse(url).query)
            local = (query.get("path") or [""])[0]
            if local and Path(local).is_file():
                resolved.append(str(Path(local)))
            continue
        if url.startswith(("http://", "https://")):
            local = _download_ref(url, directory)
            if local:
                resolved.append(local)
            continue
        # 其它情况按本地路径尝试
        if Path(url).is_file():
            resolved.append(url)
    return resolved


def _media_result(path: Path, engine: str, prompt: str = "") -> dict[str, Any]:
    from backend.editor.agent.media_tools import _probe_media_info

    info = _probe_media_info(path)
    return {
        "url": _public_url(path),
        "path": str(path),
        "engine": engine,
        "prompt": prompt,
        **info,
    }


# --------------------------------------------------------------------------- #
# 生图
# --------------------------------------------------------------------------- #


class ImageRequest(BaseModel):
    prompt: str
    aspect_ratio: str = "16:9"
    num_images: int = 1
    ref_image_url: Optional[str] = None
    iface_id: Optional[str] = None
    model: Optional[str] = None


@router.post("/image")
def generate_image(req: ImageRequest):
    """走主项目生图接口层生成图片，返回可访问 URL。"""
    from backend.editor.agent.media_tools import _run_imagegen_interface
    from backend.imagegen.imagegen_interface_manager import get_imagegen_interface_manager
    from backend.imagegen.sdk import seedream_wrapper

    prompt = (req.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="生图提示词为空")

    out_dir = GENERATED_DIR / f"img_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    out_dir.mkdir(parents=True, exist_ok=True)
    ref_images = _resolve_ref_images([req.ref_image_url] if req.ref_image_url else [], out_dir)

    manager = get_imagegen_interface_manager()
    enabled = manager.get_enabled()
    specified = next((i for i in enabled if i.get("id") == req.iface_id), None) if req.iface_id else None
    candidates = [specified] if specified else []
    candidates.extend(i for i in enabled if i.get("id") != req.iface_id)

    for iface in candidates:
        try:
            paths = _run_imagegen_interface(
                iface["id"],
                prompt,
                out_dir,
                req.aspect_ratio or "16:9",
                max(1, int(req.num_images or 1)),
                ref_images,
                model=req.model,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[cutia-bridge] 生图接口 %s 失败: %s", iface.get("id"), exc)
            paths = []
        if paths:
            return _media_result(Path(paths[0]), iface.get("id") or "", prompt)

    try:
        paths = seedream_wrapper.generate(
            prompt=prompt,
            output_dir=str(out_dir),
            aspect_ratio=req.aspect_ratio or "16:9",
            num_images=max(1, int(req.num_images or 1)),
            ref_images=ref_images,
            mode="img2img" if ref_images else "txt2img",
            raise_on_error=True,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"生图失败: {exc}")
    if not paths:
        raise HTTPException(status_code=502, detail="生图未返回文件")
    return _media_result(Path(paths[0]), "seedream-fallback", prompt)


# --------------------------------------------------------------------------- #
# 生视频（异步任务 + 轮询）
# --------------------------------------------------------------------------- #


class VideoRequest(BaseModel):
    prompt: str
    duration: int = 5
    ratio: str = "16:9"
    resolution: str = "720P"
    ref_image_url: Optional[str] = None
    iface_id: Optional[str] = None
    model: Optional[str] = None


def _run_video_task(task_id: str, req: VideoRequest) -> None:
    from backend.editor.agent.media_tools import _run_videogen_interface, _probe_media_info
    from backend.videogen.sdk import seedance_wrapper
    from backend.videogen.videogen_interface_manager import get_videogen_interface_manager

    def update(**kwargs: Any) -> None:
        with _VIDEO_LOCK:
            _VIDEO_TASKS[task_id].update(kwargs, updatedAt=time.time())

    try:
        update(status="running", progress=5)
        out_dir = GENERATED_DIR / f"vid_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        out_dir.mkdir(parents=True, exist_ok=True)
        ref_images = _resolve_ref_images([req.ref_image_url] if req.ref_image_url else [], out_dir)

        manager = get_videogen_interface_manager()
        enabled = manager.get_enabled()
        specified = next((i for i in enabled if i.get("id") == req.iface_id), None) if req.iface_id else None
        candidates = [specified] if specified else []
        candidates.extend(i for i in enabled if i.get("id") != req.iface_id)

        paths: list[str] = []
        used = ""
        for iface in candidates:
            try:
                paths = _run_videogen_interface(
                    iface["id"],
                    req.prompt,
                    out_dir,
                    max(1, int(req.duration or 5)),
                    req.ratio or "16:9",
                    req.resolution or "720P",
                    ref_images,
                    model=req.model,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[cutia-bridge] 生视频接口 %s 失败: %s", iface.get("id"), exc)
                paths = []
            if paths:
                used = iface.get("id") or ""
                break

        if not paths:
            paths = seedance_wrapper.generate(
                prompt=req.prompt,
                output_dir=str(out_dir),
                ratio=req.ratio or "16:9",
                resolution=req.resolution or "720P",
                duration=max(1, int(req.duration or 5)),
                ref_images=ref_images,
                mode="img2video" if ref_images else "txt2video",
                raise_on_error=True,
            )
            used = used or "seedance-fallback"

        if not paths:
            update(status="failed", error="生视频未返回文件")
            return

        path = Path(paths[0])
        info = _probe_media_info(path)
        update(
            status="succeeded",
            progress=100,
            url=_public_url(path),
            path=str(path),
            engine=used,
            duration=info.get("duration") or float(req.duration or 5),
            width=info.get("width"),
            height=info.get("height"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("[cutia-bridge] 生视频任务失败")
        update(status="failed", error=str(exc))


@router.post("/video")
def submit_video(req: VideoRequest):
    """提交生视频任务，返回 task_id 供轮询。"""
    prompt = (req.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="生视频提示词为空")

    _prune_video_tasks()
    task_id = uuid.uuid4().hex
    with _VIDEO_LOCK:
        _VIDEO_TASKS[task_id] = {
            "taskId": task_id,
            "status": "pending",
            "progress": 0,
            "updatedAt": time.time(),
        }
    threading.Thread(target=_run_video_task, args=(task_id, req), daemon=True).start()
    return {"taskId": task_id, "status": "pending"}


@router.get("/video/{task_id}")
def get_video(task_id: str):
    with _VIDEO_LOCK:
        task = _VIDEO_TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return dict(task)


# --------------------------------------------------------------------------- #
# TTS
# --------------------------------------------------------------------------- #


class TtsRequest(BaseModel):
    text: str
    voice: Optional[str] = None
    engine_id: Optional[str] = None
    speed: Optional[float] = None


def _audio_mime(path: Path) -> str:
    return {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
    }.get(path.suffix.lower(), "audio/wav")


@router.post("/tts")
def synthesize(req: TtsRequest):
    """走主项目 TTS 接口层合成语音，返回 base64 音频（Cutia 侧直接解码入库）。"""
    from backend.editor.agent.media_tools import _call_synthesize, _probe_media_info, _resolve_tts_mode
    from backend.tts.tts_factory import get_tts_engine
    from backend.tts.tts_interface_manager import get_tts_interface_manager

    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="语音合成文本为空")

    manager = get_tts_interface_manager()
    iface = manager.get(req.engine_id) if req.engine_id else None
    if iface is None:
        enabled = manager.get_enabled()
        if not enabled:
            raise HTTPException(status_code=503, detail="未配置可用的 TTS 接口")
        iface = enabled[0]

    engine_id = iface.get("id") or ""
    mode = _resolve_tts_mode(iface)
    directory = GENERATED_DIR / "tts"
    directory.mkdir(parents=True, exist_ok=True)
    output_path = directory / f"speech_{int(time.time() * 1000)}.wav"

    try:
        engine = get_tts_engine(engine_id)
        _call_synthesize(
            engine,
            text,
            str(output_path),
            {"mode": mode, "voice": req.voice, "speed": req.speed},
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"语音合成失败: {exc}")

    if not output_path.is_file():
        candidates = sorted(directory.glob(f"{output_path.stem}.*"))
        if not candidates:
            raise HTTPException(status_code=502, detail="TTS 未生成音频文件")
        output_path = candidates[0]

    info = _probe_media_info(output_path)
    return {
        "audio": base64.b64encode(output_path.read_bytes()).decode("ascii"),
        "mime": _audio_mime(output_path),
        "url": _public_url(output_path),
        "engine": engine_id,
        "duration": info.get("duration") or 0,
    }
