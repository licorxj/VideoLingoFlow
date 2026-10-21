"""OpenChatCut 桥接件：OpenAI 兼容端点（/api/openchatcut-bridge/v1）。

让 OpenChatCut（thirdparty/openchatcut，未改源码）的生图 / TTS / Agent 大模型
通过本项目已配置的接口层出图、出声、对话，密钥不流向第三方编辑器：

  - GET  /v1/models            密钥探测（OpenChatCut 的 image/openai、voice/openai 探活）
  - POST /v1/chat/completions  Agent 大模型（走主项目 LLM 连接）
  - POST /v1/images/generations  生图（JSON）
  - POST /v1/images/edits        生图（multipart，带参考图 / mask）
  - POST /v1/audio/speech        TTS 语音合成（返回原始音频字节）

接口与模型选择来自「AI剪辑台」设置（config.yaml 的 openchatcut.image / openchatcut.tts），
未指定接口时按主项目已启用接口顺序自动选择。
"""

from __future__ import annotations

import base64
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, quote, urlparse

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from backend.config.config_manager import config
from backend.creation.paths import DATA_ROOT
from backend.llm.llm_client import get_llm_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/openchatcut-bridge/v1", tags=["openchatcut-bridge"])

GENERATED_DIR = DATA_ROOT / "openchatcut" / "generated"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)

# 代表「跟随主项目默认模型」的占位模型名（OpenAI 兼容客户端常传 auto/default）
_HOST_PLACEHOLDER_MODELS = {"", "auto", "host", "videolingo", "videolingo-host", "default"}


def _public_url(path: Path) -> str:
    """把本地绝对路径包装成前端可访问的流式 URL。"""
    return f"/api/files/stream?path={quote(str(path), safe='')}"

# OpenAI 尺寸 → 本项目宽高比
_SIZE_TO_RATIO = {
    "1024x1024": "1:1",
    "1024x1792": "9:16",
    "1792x1024": "16:9",
    "1024x1536": "2:3",
    "1536x1024": "3:2",
    "1280x720": "16:9",
    "720x1280": "9:16",
    "1920x1080": "16:9",
    "1080x1920": "9:16",
}


def _ratio_from_size(size: Optional[str]) -> str:
    value = (size or "").strip().lower()
    if value in _SIZE_TO_RATIO:
        return _SIZE_TO_RATIO[value]
    if "x" in value:
        try:
            width, height = (float(part) for part in value.split("x", 1))
        except ValueError:
            return "1:1"
        if width <= 0 or height <= 0:
            return "1:1"
        ratio = width / height
        table = [(16 / 9, "16:9"), (9 / 16, "9:16"), (1.0, "1:1"), (4 / 3, "4:3"), (3 / 4, "3:4"), (3 / 2, "3:2"), (2 / 3, "2:3")]
        return min(table, key=lambda item: abs(item[0] - ratio))[1]
    return "1:1"


def _occ_setting(section: str) -> dict[str, Any]:
    stored = config.get("openchatcut", {}) or {}
    value = stored.get(section) if isinstance(stored, dict) else None
    return value if isinstance(value, dict) else {}


def _image_interface_id() -> str:
    return str(_occ_setting("image").get("interface_id") or "")


def _tts_interface_id() -> str:
    return str(_occ_setting("tts").get("interface_id") or "")


def _image_model_for(has_ref_images: bool) -> Optional[str]:
    """按请求形态解耦模型：无参考图 → 文生图模型；有参考图 → 图生图模型。

    模式专属模型未配置时回退旧的单模型字段，再回退接口默认（返回 None）。
    """
    image_cfg = _occ_setting("image")
    if has_ref_images:
        model = str(image_cfg.get("img2img_model") or "").strip()
    else:
        model = str(image_cfg.get("txt2img_model") or "").strip()
    if not model:
        model = str(image_cfg.get("model") or "").strip()
    return model or None


def _tts_model() -> Optional[str]:
    return str(_occ_setting("tts").get("model") or "").strip() or None


# --------------------------------------------------------------------------- #
# 密钥探测
# --------------------------------------------------------------------------- #


@router.get("/models")
def list_models():
    """OpenAI 兼容模型清单（供 OpenChatCut 保存 Key 时探活）。"""
    return {
        "object": "list",
        "data": [
            {"id": "videolingo-host", "object": "model", "created": int(time.time()), "owned_by": "videolingo"},
            {"id": "videolingo-image", "object": "model", "created": int(time.time()), "owned_by": "videolingo"},
            {"id": "videolingo-tts", "object": "model", "created": int(time.time()), "owned_by": "videolingo"},
        ],
    }


# --------------------------------------------------------------------------- #
# Agent 大模型：OpenAI 兼容 chat/completions（走主项目已配置的 LLM 连接）
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
    """按 editor_agent → default 顺序取第一个真正配了模型的连接配置。

    ``_get_api_config`` 在没有任何 step 覆盖时会把 step 名本身当模型名返回，
    这里逐个试，避免把占位值当真实模型发出去。
    """
    llm = get_llm_client()
    fallback: dict[str, Any] | None = None
    for step in ("editor_agent", "default"):
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
        logger.exception("[openchatcut-bridge] 流式对话失败")
        yield f"data: {json.dumps({'error': {'message': str(exc)}}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"


@router.post("/chat/completions")
async def chat_completions(payload: dict[str, Any]):
    req = ChatCompletionsRequest(**{
        key: payload.get(key)
        for key in ("model", "messages", "tools", "tool_choice", "temperature", "top_p", "max_tokens")
        if payload.get(key) is not None
    } | {"stream": bool(payload.get("stream"))})
    try:
        api_cfg = _llm_api_config()
        if not api_cfg.get("base_url") or not api_cfg.get("api_key"):
            raise HTTPException(status_code=503, detail="主项目 LLM 未配置")
        client = get_llm_client()._make_client(api_cfg)
        payload_out = _build_payload(req, api_cfg["model"])
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("[openchatcut-bridge] 构建 LLM 请求失败")
        raise HTTPException(status_code=500, detail=str(exc))

    if req.stream:
        return StreamingResponse(
            _stream_chunks(client, payload_out),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        completion = client.chat.completions.create(**payload_out)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[openchatcut-bridge] 对话失败")
        raise HTTPException(status_code=502, detail=str(exc))
    return json.loads(completion.model_dump_json())


# --------------------------------------------------------------------------- #
# 生图
# --------------------------------------------------------------------------- #


class ImageGenerationsRequest(BaseModel):
    model: Optional[str] = None
    prompt: str = ""
    size: Optional[str] = None
    n: int = 1
    quality: Optional[str] = None
    response_format: Optional[str] = None


def _download_ref(url: str, directory: Path) -> Optional[str]:
    import requests

    suffix = Path(urlparse(url).path).suffix or ".png"
    target = directory / f"ref_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}{suffix}"
    try:
        with requests.get(url, timeout=120) as resp:
            resp.raise_for_status()
            target.write_bytes(resp.content)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[openchatcut-bridge] 下载参考图失败 %s: %s", url, exc)
        return None
    return str(target)


def _resolve_ref_images(urls: list[str], directory: Path) -> list[str]:
    """把各种形态的参考图 URL 归一化成本地路径 / data URI。"""
    resolved: list[str] = []
    for url in urls:
        if not url:
            continue
        if url.startswith("data:"):
            resolved.append(url)
            continue
        if url.startswith("blob:"):
            logger.warning("[openchatcut-bridge] 忽略无法服务端读取的 blob 参考图")
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
        if Path(url).is_file():
            resolved.append(url)
    return resolved


class ImageRequest(BaseModel):
    prompt: str
    aspect_ratio: str = "16:9"
    num_images: int = 1
    ref_image_url: Optional[str] = None
    iface_id: Optional[str] = None
    model: Optional[str] = None


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
            logger.warning("[openchatcut-bridge] 生图接口 %s 失败: %s", iface.get("id"), exc)
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


def _run_imagegen(prompt: str, size: str, n: int, model: Optional[str], ref_images: list[str]) -> list[Path]:
    """走主项目生图接口层，返回本地文件路径列表。"""
    req = ImageRequest(
        prompt=prompt,
        aspect_ratio=_ratio_from_size(size),
        num_images=max(1, min(int(n or 1), 4)),
        ref_image_url=ref_images[0] if ref_images else None,
        iface_id=_image_interface_id() or None,
        # 请求侧显式模型优先（OpenChatCut 生成设置里选的模型），
        # 否则按有无参考图取设置里的 文生图/图生图 专属模型
        model=(model or "").strip() or _image_model_for(bool(ref_images)),
    )
    result = generate_image(req)
    path = result.get("path")
    return [Path(path)] if path else []


def _image_payload(paths: list[Path]) -> dict[str, Any]:
    data = []
    for path in paths:
        data.append({
            "b64_json": base64.b64encode(path.read_bytes()).decode("ascii"),
            "revised_prompt": None,
        })
    return {"created": int(time.time()), "data": data}


@router.post("/images/generations")
def images_generations(req: ImageGenerationsRequest):
    prompt = (req.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt 为空")
    try:
        paths = _run_imagegen(prompt, req.size or "1024x1024", req.n, req.model, [])
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"生图失败: {exc}")
    if not paths:
        raise HTTPException(status_code=502, detail="生图未返回文件")
    return _image_payload(paths)


@router.post("/images/edits")
async def images_edits(
    image: list[UploadFile] = File(default=[]),
    mask: UploadFile | None = File(default=None),
    prompt: str = Form(default=""),
    model: Optional[str] = Form(default=None),
    size: Optional[str] = Form(default=None),
    n: int = Form(default=1),
):
    """multipart 参考图编辑生图（OpenChatCut gpt-image 参考图 / mask 走此端点）。"""
    text = (prompt or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="prompt 为空")

    directory = GENERATED_DIR / f"edit_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    directory.mkdir(parents=True, exist_ok=True)
    ref_paths: list[str] = []
    for index, upload in enumerate(image or []):
        if not upload or not upload.filename:
            continue
        target = directory / f"ref_{index}_{Path(upload.filename).suffix or '.png'}"
        target.write_bytes(await upload.read())
        ref_paths.append(str(target))
    if mask is not None and mask.filename:
        target = directory / f"mask_{Path(mask.filename).suffix or '.png'}"
        target.write_bytes(await mask.read())
        ref_paths.append(str(target))

    try:
        paths = _run_imagegen(text, size or "1024x1024", n, model, ref_paths)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"生图失败: {exc}")
    if not paths:
        raise HTTPException(status_code=502, detail="生图未返回文件")
    return _image_payload(paths)


# --------------------------------------------------------------------------- #
# TTS（OpenChatCut voice/openai 走 AI SDK，POST {base}/audio/speech）
# --------------------------------------------------------------------------- #


class TtsRequest(BaseModel):
    text: str
    voice: Optional[str] = None
    engine_id: Optional[str] = None
    speed: Optional[float] = None
    # 显式模型（引擎签名不支持时由 _call_synthesize 自动过滤）
    model: Optional[str] = None


def _audio_mime(path: Path) -> str:
    return {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
    }.get(path.suffix.lower(), "audio/wav")


def _synthesize(req: TtsRequest):
    """走主项目 TTS 接口层合成语音，返回 base64 音频。"""
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
            {"mode": mode, "voice": req.voice, "speed": req.speed, "model": req.model},
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


class AudioSpeechRequest(BaseModel):
    model: Optional[str] = None
    voice: Optional[str] = None
    input: str = ""
    instructions: Optional[str] = None


@router.post("/audio/speech")
def audio_speech(req: AudioSpeechRequest):
    text = (req.input or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="input 为空")

    result = _synthesize(TtsRequest(
        text=text,
        voice=(req.voice or "").strip() or None,
        engine_id=_tts_interface_id() or None,
        # 请求侧显式模型优先，否则用设置里选择的 TTS 合成模型
        model=(req.model or "").strip() or _tts_model(),
    ))
    audio_b64 = result.get("audio") or ""
    if not audio_b64:
        raise HTTPException(status_code=502, detail="TTS 未返回音频")
    mime = result.get("mime") or "audio/wav"
    return Response(content=base64.b64decode(audio_b64), media_type=mime)
