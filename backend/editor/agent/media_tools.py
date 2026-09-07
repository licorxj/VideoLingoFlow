"""剪辑 AI Agent 的媒体能力桥接层。

复用 VideoLingo 已配置的接口能力：
  - TTS   : backend.tts.tts_factory.get_tts_engine(..).synthesize(..)
  - ASR   : backend.asr.asr_factory.run_asr(..)
  - 生图  : 优先 ImageGenInterfaceManager 通用接口层（OpenAI 兼容走 HTTP / SDK 动态导入），
            失败回退 backend.imagegen.sdk.seedream_wrapper.generate(..)
  - 生视频: 优先 VideoGenInterfaceManager 通用接口层（动态导入配置的 SDK 模块），
            失败回退 backend.videogen.sdk.seedance_wrapper.generate(..)

所有产物落盘到任务的 editor/generated 目录，并注册为剪辑项目资产，
使 generate_* 之后可以直接用 add_video_to_timeline / add_audio_to_timeline
引用返回的 mediaId。
"""

from __future__ import annotations

import base64
import importlib
import inspect
import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

import requests

from backend.editor.repository import EditorProjectRepository

logger = logging.getLogger(__name__)

# 单次生成的兜底超时（秒）：生视频等长任务由调用方通过 timeout 控制
DEFAULT_PROBE_TIMEOUT = 30


def generated_dir(task_id: str) -> Path:
    """Agent 生成产物的落盘目录。"""
    repository = EditorProjectRepository()
    path = Path(repository.task_dir(task_id)) / "editor" / "generated"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _probe_media_info(path: Path) -> dict[str, Any]:
    """用 ffprobe 读取时长与尺寸；不可用时返回空字典（不阻塞主流程）。"""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-print_format", "json",
                "-show_entries", "format=duration:stream=width,height,codec_type",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=DEFAULT_PROBE_TIMEOUT,
        )
    except Exception:
        return {}
    if result.returncode != 0:
        return {}
    try:
        data = json.loads(result.stdout or "{}")
    except ValueError:
        return {}

    info: dict[str, Any] = {}
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
        if duration > 0:
            info["duration"] = duration
    except (TypeError, ValueError):
        pass
    for stream in data.get("streams") or []:
        if stream.get("width") and stream.get("height"):
            info["width"] = int(stream["width"])
            info["height"] = int(stream["height"])
            break
    return info


def asset_absolute_path(task_id: str, media_id: str) -> str:
    """把剪辑资产 ID 解析为本地绝对路径（供参考图/参考视频使用）。"""
    repository = EditorProjectRepository()
    root = Path(repository.task_dir(task_id))
    for asset in repository.snapshot(task_id)["assets"]:
        if asset.get("id") == media_id:
            return str(root / asset["relative_path"])
    return ""


def _register(
    task_id: str,
    path: Path,
    asset_type: str,
    source: str,
) -> dict[str, Any]:
    info = _probe_media_info(path)
    repository = EditorProjectRepository()
    asset = repository.register_asset(
        task_id,
        path,
        asset_type=asset_type,
        source=source,
        duration=info.get("duration"),
        width=info.get("width"),
        height=info.get("height"),
    )
    return asset.model_dump()


def _resolve_tts_mode(iface: dict[str, Any]) -> str:
    modes = (iface.get("config") or {}).get("modes") or {}
    for preferred in ("preset", "clone", "design", "controllable_clone"):
        if (modes.get(preferred) or {}).get("enabled"):
            return preferred
    for name, cfg in modes.items():
        if (cfg or {}).get("enabled"):
            return name
    return "preset"


def _call_synthesize(engine: Any, text: str, output_path: str, params: dict[str, Any]) -> None:
    """按引擎实际签名过滤参数后调用 TTS。

    ``TTSBase`` 只约定 ``synthesize(text, output_path)``，各引擎的扩展参数
    （mode / voice / speed / ref_audio …）并不一致，因此按签名筛选，
    而不是无脑全传或靠异常层层降级。
    """
    import inspect

    kwargs: dict[str, Any] = {}
    try:
        signature = inspect.signature(engine.synthesize)
    except (TypeError, ValueError):
        signature = None

    if signature is not None:
        accepts_var_keyword = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        for key, value in params.items():
            if value is None:
                continue
            if accepts_var_keyword or key in signature.parameters:
                kwargs[key] = value

    try:
        engine.synthesize(text, output_path, **kwargs)
    except TypeError:
        engine.synthesize(text, output_path)


def synthesize_speech(
    task_id: str,
    text: str,
    voice: Optional[str] = None,
    engine_id: Optional[str] = None,
    speed: Optional[float] = None,
) -> dict[str, Any]:
    """调用 VideoLingo 的 TTS 接口合成语音，注册为音频资产。"""
    from backend.tts.tts_factory import get_tts_engine
    from backend.tts.tts_interface_manager import get_tts_interface_manager

    if not text.strip():
        raise ValueError("语音合成文本为空")

    manager = get_tts_interface_manager()
    iface = manager.get(engine_id) if engine_id else None
    if iface is None:
        enabled = manager.get_enabled()
        if not enabled:
            raise RuntimeError("未配置可用的 TTS 接口")
        iface = enabled[0]

    resolved_engine_id = iface["id"]
    mode = _resolve_tts_mode(iface)
    engine = get_tts_engine(resolved_engine_id)

    directory = generated_dir(task_id)
    output_path = directory / f"speech_{int(time.time() * 1000)}.wav"

    _call_synthesize(
        engine,
        text,
        str(output_path),
        {"mode": mode, "voice": voice, "speed": speed},
    )

    if not output_path.is_file():
        # 部分引擎会自行改写扩展名
        candidates = sorted(directory.glob(f"{output_path.stem}.*"))
        if not candidates:
            raise RuntimeError("TTS 未生成音频文件")
        output_path = candidates[0]

    asset = _register(task_id, output_path, "audio", "agent_tts")
    asset["engine"] = resolved_engine_id
    return asset


def transcribe_media(
    task_id: str,
    media_id: str,
    language: Optional[str] = None,
    engine_id: Optional[str] = None,
) -> dict[str, Any]:
    """调用 VideoLingo 的 ASR 接口转写媒体，返回识别文本与片段。"""
    from backend.asr.asr_factory import run_asr
    from backend.asr.asr_interface_manager import ASRInterfaceManager

    media_path = asset_absolute_path(task_id, media_id)
    if not media_path or not Path(media_path).is_file():
        raise ValueError(f"媒体资产不可用: {media_id}")

    manager = ASRInterfaceManager()
    if not engine_id:
        enabled = manager.get_enabled()
        if not enabled:
            raise RuntimeError("未配置可用的 ASR 接口")
        engine_id = enabled[0].get("id")

    directory = generated_dir(task_id)
    output_path = directory / f"asr_{int(time.time() * 1000)}.json"
    # run_asr 是 VideoLingo 的 ASR 服务层入口，内部负责：
    #   - GPU 服务 lane 调度（本地大模型不在本进程内抢显存）
    #   - 超长音频按静音边界切分、逐段推理并重组时间戳
    #   - _busy 标记，避免空闲清扫在加载途中误卸载引擎
    # 因此不要绕过它直接调用 engine.transcribe
    result = run_asr(
        media_path,
        str(output_path),
        callback=None,
        engine_name=engine_id,
        language=language,
    ) or {}

    segments = result.get("segments") or []
    text = " ".join(
        str(segment.get("text") or "").strip() for segment in segments
    ).strip()
    if not text:
        text = str(result.get("text") or "").strip()

    return {
        "engine": engine_id,
        "language": result.get("language") or language or "",
        "text": text,
        "segmentCount": len(segments),
        "segments": segments[:50],
        "outputPath": str(output_path),
    }


def _ref_paths(task_id: str, ref_media_id: Optional[str]) -> list[str]:
    """把剪辑资产 ID 解析为本地路径列表（供 Seedream/Seedance wrapper 引用）。"""
    if not ref_media_id:
        return []
    path = asset_absolute_path(task_id, ref_media_id)
    return [path] if path else []


def _to_data_uri(path: str) -> str:
    """本地图片转 data URI，供 OpenAI 兼容接口的 image 字段使用。"""
    ext = Path(path).suffix.lstrip(".").lower() or "png"
    mime = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
    }.get(ext, "image/png")
    raw = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:{mime};base64,{raw}"


def _save_openai_images(data: dict, output_dir: Path) -> list[str]:
    """解析 OpenAI images.generate 响应（url 或 b64_json），落盘为图片。"""
    items = data.get("data") or []
    paths: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        b64 = item.get("b64_json")
        if b64:
            output_path = output_dir / f"gen_{len(paths) + 1}.png"
            output_path.write_bytes(base64.b64decode(b64))
            paths.append(str(output_path))
        elif url:
            with requests.get(url, timeout=120) as resp:
                resp.raise_for_status()
                suffix = Path(str(url).split("?")[0]).suffix or ".png"
                output_path = output_dir / f"gen_{len(paths) + 1}{suffix}"
                output_path.write_bytes(resp.content)
                paths.append(str(output_path))
    return paths


def _call_wrapper_generate(func: Any, params: dict, prompt: str, output_dir: str) -> Any:
    """按 generate 函数实际签名过滤参数后调用。

    通用接口层（imagegen/videogen 的 sdk 类型）只保证 ``module``/``function``
    与一组约定的关键字，各 wrapper 的 ``generate`` 真实签名并不统一，
    因此用 inspect 过滤，而不是无脑全传。
    """
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        signature = None

    call: dict[str, Any] = {}
    if signature is not None:
        accepts_var_keyword = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        for key, value in params.items():
            if key in ("module", "function"):
                continue
            if key == "extra_args":
                for extra_key, extra_value in (value or {}).items():
                    if accepts_var_keyword or extra_key in signature.parameters:
                        call[extra_key] = extra_value
                continue
            if accepts_var_keyword or key in signature.parameters:
                call[key] = value

    call.setdefault("prompt", prompt)
    call.setdefault("output_dir", str(output_dir))
    try:
        return func(**call)
    except TypeError:
        return func(prompt=prompt, output_dir=str(output_dir))


def _run_imagegen_interface(
    iface_id: str,
    prompt: str,
    output_dir: Path,
    aspect_ratio: str,
    num_images: int,
    ref_images: list[str],
    model: Optional[str] = None,
) -> list[str]:
    """走 ImageGenInterfaceManager 通用接口层生成图片。

    覆盖用户在系统里配置的任何生图接口：openai_compatible 走 HTTP，
    sdk（如 Seedream）走动态导入其 generate 函数。``model`` 非 None 时
    覆盖接口配置的默认模型。
    """
    from backend.imagegen.imagegen_interface_manager import get_imagegen_interface_manager

    manager = get_imagegen_interface_manager()
    kwargs: dict[str, Any] = {
        "aspect_ratio": aspect_ratio,
        "num_images": num_images,
    }
    if model:
        kwargs["model"] = model
    if ref_images:
        kwargs["ref_images"] = [
            _to_data_uri(ref) if not str(ref).startswith(("http://", "https://", "data:")) else ref
            for ref in ref_images
        ]
        kwargs["mode"] = "img2img"

    params = manager.build_request_params(iface_id, prompt, str(output_dir), **kwargs)
    if params.get("method") == "POST":
        with requests.post(
            params["url"],
            headers=params.get("headers", {}),
            json=params.get("body", {}),
            timeout=params.get("timeout", 120),
        ) as resp:
            resp.raise_for_status()
            return _save_openai_images(resp.json(), Path(str(output_dir)))
    if params.get("type") == "sdk":
        module = importlib.import_module(params["module"])
        func = getattr(module, params.get("function") or "generate")
        result = _call_wrapper_generate(func, params, prompt, str(output_dir))
        if isinstance(result, str):
            return [result]
        return list(result or [])
    raise RuntimeError("未识别的生图接口类型")


def _run_videogen_interface(
    iface_id: str,
    prompt: str,
    output_dir: Path,
    duration: int,
    ratio: str,
    resolution: str,
    ref_images: list[str],
    model: Optional[str] = None,
) -> list[str]:
    """走 VideoGenInterfaceManager 通用接口层生成视频。

    其 build_request_params 只返回 SDK 路由信息，执行方式是动态导入
    配置的模块并调用其 generate（默认指向可灵 wrapper，用户也可配 Seedance）。
    ``model`` 非 None 时覆盖接口配置的默认模型。
    """
    from backend.videogen.videogen_interface_manager import get_videogen_interface_manager

    manager = get_videogen_interface_manager()
    params = manager.build_request_params(
        iface_id,
        "img2video" if ref_images else "txt2video",
        prompt,
        str(output_dir),
        ref_images=ref_images,
        num_videos=1,
        resolution=resolution,
        duration=duration,
        ratio=ratio,
    )
    if model:
        params["model"] = model
    module = params.get("module")
    if not module:
        raise RuntimeError("视频接口未配置 SDK 模块")
    func = getattr(importlib.import_module(module), params.get("function") or "generate")
    result = _call_wrapper_generate(func, params, prompt, str(output_dir))
    if isinstance(result, str):
        return [result]
    return list(result or [])


def generate_image(
    task_id: str,
    prompt: str,
    aspect_ratio: str = "16:9",
    num_images: int = 1,
    ref_media_id: Optional[str] = None,
    iface_id: Optional[str] = None,
    model: Optional[str] = None,
) -> dict[str, Any]:
    """通过 VideoLingo 配置的生图接口生成图片，注册为图片资产。

    接口选择策略（优先级从高到低）：
      1. 前端指定的 iface_id（仅当它仍处于启用状态）；
      2. 其余已启用接口逐个尝试，直到某接口调用成功；
      3. 回退到 Seedream wrapper（读 ARK_API_KEY，无需接口配置）。
    """
    from backend.imagegen.imagegen_interface_manager import get_imagegen_interface_manager
    from backend.imagegen.sdk import seedream_wrapper

    if not prompt.strip():
        raise ValueError("生图提示词为空")

    directory = generated_dir(task_id)
    ref_local = _ref_paths(task_id, ref_media_id)

    manager = get_imagegen_interface_manager()
    enabled = manager.get_enabled()
    specified = next((iface for iface in enabled if iface["id"] == iface_id), None) if iface_id else None
    if iface_id and not specified:
        logger.warning("指定的生图接口 %s 不在启用列表，转为自动选择", iface_id)
    candidates = [specified] if specified else []
    candidates.extend(iface for iface in enabled if iface["id"] != iface_id)

    for iface in candidates:
        try:
            paths = _run_imagegen_interface(
                iface["id"], prompt, directory, aspect_ratio, num_images, ref_local, model=model,
            )
        except Exception as exc:
            logger.warning("生图接口 %s 调用失败，尝试下一个: %s", iface["id"], exc)
            paths = []
        if paths:
            asset = _register(task_id, Path(paths[0]), "image", "agent_imagegen")
            asset["prompt"] = prompt
            asset["engine"] = iface["id"]
            asset["engineSpecified"] = bool(specified and iface["id"] == iface_id)
            return asset

    paths = seedream_wrapper.generate(
        prompt=prompt,
        output_dir=str(directory),
        aspect_ratio=aspect_ratio or "16:9",
        num_images=max(1, int(num_images or 1)),
        ref_images=ref_local,
        mode="img2img" if ref_local else "txt2img",
        raise_on_error=True,
    )
    if not paths:
        raise RuntimeError("生图未返回文件")

    asset = _register(task_id, Path(paths[0]), "image", "agent_imagegen")
    asset["prompt"] = prompt
    return asset


def generate_video(
    task_id: str,
    prompt: str,
    duration: int = 5,
    ratio: str = "16:9",
    resolution: str = "720P",
    ref_media_id: Optional[str] = None,
    iface_id: Optional[str] = None,
    model: Optional[str] = None,
) -> dict[str, Any]:
    """通过 VideoLingo 配置的视频生成接口生成视频，注册为视频资产。

    接口选择策略（优先级从高到低）：
      1. 前端指定的 iface_id（仅当它仍处于启用状态）；
      2. 其余已启用接口逐个尝试，直到某接口调用成功；
      3. 回退到 Seedance wrapper（读 ARK_API_KEY，无需接口配置）。
    """
    from backend.videogen.sdk import seedance_wrapper
    from backend.videogen.videogen_interface_manager import get_videogen_interface_manager

    if not prompt.strip():
        raise ValueError("生视频提示词为空")

    directory = generated_dir(task_id)
    ref_local = _ref_paths(task_id, ref_media_id)

    manager = get_videogen_interface_manager()
    enabled = manager.get_enabled()
    specified = next((iface for iface in enabled if iface["id"] == iface_id), None) if iface_id else None
    if iface_id and not specified:
        logger.warning("指定的生视频接口 %s 不在启用列表，转为自动选择", iface_id)
    candidates = [specified] if specified else []
    candidates.extend(iface for iface in enabled if iface["id"] != iface_id)

    for iface in candidates:
        try:
            paths = _run_videogen_interface(
                iface["id"], prompt, directory, duration, ratio, resolution, ref_local, model=model,
            )
        except Exception as exc:
            logger.warning("生视频接口 %s 调用失败，尝试下一个: %s", iface["id"], exc)
            paths = []
        if paths:
            path = Path(paths[0])
            asset = _register(task_id, path, "video", "agent_videogen")
            asset["prompt"] = prompt
            asset["engine"] = iface["id"]
            asset["engineSpecified"] = bool(specified and iface["id"] == iface_id)
            if not asset.get("duration"):
                asset["duration"] = float(duration)
            return asset

    paths = seedance_wrapper.generate(
        prompt=prompt,
        output_dir=str(directory),
        ratio=ratio or "16:9",
        resolution=resolution or "720P",
        duration=max(1, int(duration or 5)),
        ref_images=ref_local,
        mode="img2video" if ref_local else "txt2video",
        raise_on_error=True,
    )
    if not paths:
        raise RuntimeError("生视频未返回文件")

    path = Path(paths[0])
    asset = _register(task_id, path, "video", "agent_videogen")
    asset["prompt"] = prompt
    if not asset.get("duration"):
        asset["duration"] = float(duration)
    return asset
