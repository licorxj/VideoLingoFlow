"""s_kie_image_audio_to_video: KIE AI 图声生视频节点（图片 + 声音驱动视频）。

直接调用 backend/kieai_sdk（不经过视频生成接口），支持 KIE market 风格模型
（createTask 提交 + recordInfo 轮询）：

    kling-3.0/video          image_urls(最多 5 张) + 音频经 kling_elements 传入
                             必填: prompt/sound/duration/aspect_ratio/mode/
                                   multi_shots/multi_prompt
    kling/ai-avatar-standard image_url + audio_url + prompt
    kling/ai-avatar-pro      image_url + audio_url + prompt
    infinitalk/from-audio    image_url + audio_url + prompt (+resolution/seed)

输入：image1（主图，必填）+ image2~image5（可选参考图）+ audio（驱动音频，必填）
     + text（提示词，或由节点内「自定义提示词」提供）

API Key 由 KieClient 三级回退解析：项目密钥库 secret://KIEAI_API_KEY
（全局设置 → 密钥管理器）-> 环境变量 KIEAI_API_KEY。

产物落盘 <task_dir>/cache/videos，文件名格式：
    <主图名>_iav_<node_id>[_<序号>].<ext>
"""
import os
import re
import json
import shutil
import base64
import asyncio
import logging
import mimetypes
from typing import Callable, Optional

from backend.steps.base_step import BaseStep

logger = logging.getLogger(__name__)

SUPPORTED_MODELS = (
    "kling-3.0/video",
    "kling/ai-avatar-standard",
    "kling/ai-avatar-pro",
    "infinitalk/from-audio",
)
DEFAULT_MODEL = "infinitalk/from-audio"

# 参考图输入口（image1 为主图）
_IMAGE_PORTS = ("image1", "image2", "image3", "image4", "image5")

# Kling 3.0 引用元素名（音频通过该元素挂载，并在 prompt 中以 @name 引用）
_KLING_AUDIO_ELEMENT = "element_voice"


def _sanitize(name: str) -> str:
    n = re.sub(r'[\\/:*?"<>|\t]', "_", (name or "").strip())
    return n or "video"


def _run_async(coro):
    """在同步上下文驱动协程；调用方已有运行中的事件循环时交由独立线程执行。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _resolve_media(value, task_dir: str) -> str:
    """解析媒体输入：支持单路径 / 列表 / HTTP URL，返回本地绝对路径或 URL。"""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    if not value or not isinstance(value, str):
        return ""
    raw = value.strip()
    if not raw:
        return ""
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    if os.path.isabs(raw):
        return raw if os.path.exists(raw) else ""
    joined = os.path.join(task_dir, raw)
    return joined if os.path.exists(joined) else ""


async def _upload_media(client, path: str, kind: str) -> str:
    """上传本地媒体到 KIE，返回公开可访问 URL。kind: images / audios。"""
    default_mime = "audio/mpeg" if kind == "audios" else "image/png"
    mime = mimetypes.guess_type(path)[0] or default_mime
    with open(path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode()
    up = await client.upload(
        method="base64",
        base64Data=f"data:{mime};base64,{b64}",
        uploadPath=kind,
        fileName=os.path.basename(path),
    )
    return up.get("downloadUrl") or up.get("url") or up.get("fileUrl") or ""


def _read_input_as_text(value, task_dir: str = "") -> str:
    """解析文本输入：若是 .txt 文件路径则读内容，否则原样返回。"""
    if not value or not isinstance(value, str):
        return str(value) if value else ""
    candidate = value.strip()
    if os.path.isfile(candidate):
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return candidate
    if task_dir:
        rel = os.path.join(task_dir, candidate)
        if os.path.isfile(rel):
            try:
                with open(rel, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception:
                return candidate
    return value.strip()


async def _generate(image_urls: list, audio_url: str, prompt: str, model: str,
                    opts: dict, poll_timeout: int, temp_dir: str) -> list:
    """提交图声生视频任务并等待结果，返回 SDK 下载的本地文件路径列表。"""
    from backend.kieai_sdk.kieai import KieClient

    os.makedirs(temp_dir, exist_ok=True)
    async with KieClient() as client:
        entry = client.catalog.get(model)
        pnames = {p.name for p in entry.params}

        params: dict = {"prompt": prompt}

        if model == "kling-3.0/video":
            if "image_urls" in pnames and image_urls:
                params["image_urls"] = image_urls
            if "sound" in pnames:
                params["sound"] = bool(opts.get("sound", False))
            if "duration" in pnames:
                params["duration"] = str(opts.get("duration") or 5)
            if "aspect_ratio" in pnames:
                params["aspect_ratio"] = opts.get("aspect_ratio") or "16:9"
            if "mode" in pnames:
                params["mode"] = opts.get("mode") or "pro"
            if "multi_shots" in pnames:
                params["multi_shots"] = False
            if "multi_prompt" in pnames:
                params["multi_prompt"] = []
            # 音频：Kling 3.0 需经 kling_elements 挂载，并在 prompt 中 @引用
            if audio_url and "kling_elements" in pnames:
                elem_urls = image_urls[:4] if len(image_urls) >= 2 else image_urls
                if len(elem_urls) < 2:
                    logger.warning(
                        "Kling 3.0: 元素引用建议 2-4 张图片，当前仅 %d 张", len(elem_urls)
                    )
                params["kling_elements"] = [{
                    "name": _KLING_AUDIO_ELEMENT,
                    "description": "voice reference",
                    "element_input_urls": elem_urls,
                    "element_input_audio_urls": [audio_url],
                }]
                if f"@{_KLING_AUDIO_ELEMENT}" not in params["prompt"]:
                    params["prompt"] = f"{params['prompt']} @{_KLING_AUDIO_ELEMENT}"
        else:
            # kling/ai-avatar-standard|pro、infinitalk/from-audio
            if "image_url" in pnames and image_urls:
                params["image_url"] = image_urls[0]
            if "audio_url" in pnames and audio_url:
                params["audio_url"] = audio_url
            if "resolution" in pnames and opts.get("resolution"):
                params["resolution"] = opts["resolution"]
            if "seed" in pnames and opts.get("seed") not in (None, ""):
                try:
                    params["seed"] = int(opts["seed"])
                except (TypeError, ValueError):
                    pass

        params = {k: v for k, v in params.items() if k in pnames}
        client.max_poll = max(1, int(poll_timeout / max(client.poll_interval, 0.1)))
        result = await client.generate(model, output_path=temp_dir, **params)

    return result.get("local_paths") or []


class S_KieImageAudioToVideo(BaseStep):
    """KIE AI 图声生视频：图片 + 音频 -> 视频。"""

    step_id = "kie_image_audio_to_video"
    step_name = "图声生视频-kie"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        d = os.path.join(task_dir, "cache", "videos")
        if not os.path.isdir(d) or not node_id:
            return False
        return any(f"_iav_{node_id}" in f for f in os.listdir(d))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        config = getattr(self, "_node_config", {}) or {}
        inputs = getattr(self, "_step_inputs", {}) or {}

        # 1. 模型
        model = (config.get("model") or DEFAULT_MODEL).strip()
        if model not in SUPPORTED_MODELS:
            raise ValueError(
                f"不支持的模型 '{model}'，支持: {', '.join(SUPPORTED_MODELS)}"
            )

        # 2. 提示词（节点内优先，其次连线文本；所有模型均必填）
        prompt = ""
        if config.get("custom_prompt_enabled"):
            prompt = (config.get("custom_prompt", "") or "").strip()
        if not prompt:
            prompt = _read_input_as_text(inputs.get("text", ""), task_dir)
        if not prompt:
            raise ValueError(
                "提示词为空：请连接文本输入，或在节点面板开启「使用节点内提示词」并填写。"
            )

        # 3. 图片与音频（连线输入）
        raw_images = []
        for port in _IMAGE_PORTS:
            v = _resolve_media(inputs.get(port, ""), task_dir)
            if v:
                raw_images.append(v)
        if not raw_images:
            raise ValueError("未获取到图片：请在 image1 输入口连接主图片。")

        audio_in = _resolve_media(inputs.get("audio", ""), task_dir)
        if not audio_in:
            raise ValueError("未获取到音频：请在 audio 输入口连接驱动音频。")

        try:
            poll_timeout = int(config.get("poll_timeout") or 900)
        except (TypeError, ValueError):
            poll_timeout = 900

        opts = {
            "sound": config.get("sound", False),
            "duration": config.get("duration", 5),
            "aspect_ratio": config.get("aspect_ratio", "16:9"),
            "mode": config.get("mode", "pro"),
            "resolution": config.get("resolution", "480p"),
            "seed": config.get("seed", ""),
        }

        cache_dir = os.path.join(task_dir, "cache", "videos")
        temp_dir = os.path.join(task_dir, "cache", "_kie_iav_temp", node_id)
        os.makedirs(cache_dir, exist_ok=True)

        if callback:
            callback(10, f"准备生成（{model}）...")
            callback(20, "上传图片与音频...")

        # 4. 执行（上传在协程内完成）
        try:
            paths = _run_async(
                _prepare_and_generate(
                    raw_images, audio_in, prompt, model, opts, poll_timeout, temp_dir
                )
            )
        except Exception as e:
            raise RuntimeError(f"KIE 图声生视频失败: {e}") from e

        if not paths:
            raise RuntimeError(
                "图声生视频未返回任何产物：请检查 KIE API Key"
                "（【全局设置 → 密钥管理器】中名称必须为 KIEAI_API_KEY）、"
                "图片与音频是否有效。"
            )

        # 5. 产物落盘（文件名带 node_id）
        stem = _sanitize(os.path.splitext(os.path.basename(raw_images[0].split("?")[0]))[0])[:24]
        saved = []
        for i, src in enumerate(paths):
            if not os.path.exists(src):
                continue
            ext = os.path.splitext(src)[1] or ".mp4"
            suffix = f"_{i + 1}" if len(paths) > 1 else ""
            name = f"{stem}_iav_{node_id}{suffix}{ext}"
            dest = os.path.join(cache_dir, name)
            shutil.copy2(src, dest)
            saved.append(os.path.join("cache", "videos", name))

        shutil.rmtree(temp_dir, ignore_errors=True)

        if not saved:
            raise RuntimeError("生成产物保存失败。")

        # 6. 参数 JSON
        params_dir = os.path.join(task_dir, "cache", "kie_iav")
        os.makedirs(params_dir, exist_ok=True)
        params_rel = os.path.join("cache", "kie_iav", f"{node_id}_params.json")
        with open(os.path.join(task_dir, params_rel), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "node_id": node_id,
                    "model": model,
                    "prompt": prompt,
                    "images": raw_images,
                    "audio": audio_in,
                    "options": opts,
                    "outputs": saved,
                    "created_at": __import__("datetime").datetime.now().isoformat(),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

        if callback:
            callback(100, f"已保存 {len(saved)} 个视频到 cache/videos")

        return {
            "artifacts": list(saved) + [params_rel],
            "outputs": {"video": saved[0], "videos": saved, "params": params_rel},
        }


async def _prepare_and_generate(raw_images, audio_in, prompt, model, opts,
                                poll_timeout, temp_dir):
    """上传本地素材（HTTP URL 直接透传）后提交生成任务。"""
    from backend.kieai_sdk.kieai import KieClient

    os.makedirs(temp_dir, exist_ok=True)
    async with KieClient() as client:
        image_urls = []
        for p in raw_images:
            if p.startswith("http"):
                image_urls.append(p)
                continue
            url = await _upload_media(client, p, "images")
            if url:
                image_urls.append(url)
            else:
                logger.warning("KIE 图声生视频: 图片上传失败，已跳过: %s", p)
        if not image_urls:
            raise RuntimeError("图片上传失败：未能取得任何可访问的 URL")

        audio_url = audio_in
        if not audio_url.startswith("http"):
            audio_url = await _upload_media(client, audio_in, "audios")
            if not audio_url:
                raise RuntimeError("音频上传失败：未能取得可访问的 URL")

    return await _generate(image_urls, audio_url, prompt, model, opts,
                           poll_timeout, temp_dir)
