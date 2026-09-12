"""s_kie_lip_sync: KIE AI 视频对口型节点。

直接调用 backend/kieai_sdk（不经过视频生成接口），支持 KIE market 风格模型
（createTask 提交 + recordInfo 轮询）：
    volcengine/video-to-video-lip-sync
        必填: mode(lite/basic), video_url, audio_url
        可选: separate_vocal, open_scenedet, align_audio, align_audio_reverse,
              templ_start_seconds

输入：video（待对口型视频）+ audio（目标音频）；本地文件自动上传取得 URL。

API Key 由 KieClient 三级回退解析：项目密钥库 secret://KIEAI_API_KEY
（全局设置 → 密钥管理器）-> 环境变量 KIEAI_API_KEY。

产物落盘 <task_dir>/cache/videos，文件名格式：
    <原文件名>_lipsync_<node_id>[_<序号>].<ext>
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

SUPPORTED_MODELS = ("volcengine/video-to-video-lip-sync",)
DEFAULT_MODEL = "volcengine/video-to-video-lip-sync"

# 布尔开关参数（模型声明时才下发）
_BOOL_PARAMS = (
    "separate_vocal", "open_scenedet", "align_audio", "align_audio_reverse",
)


def _sanitize(name: str) -> str:
    n = re.sub(r'[\\/:*?"<>|\t]', "_", (name or "").strip())
    return n or "video"


def _run_async(coro):
    """在同步上下文驱动协程；调用方已有运行中的事件循环时交由独立线程执行。

    不使用 asyncio.get_event_loop()：Python 3.12 在无当前事件循环的线程中会抛
    RuntimeError 且该用法已废弃，这里改用 get_running_loop() 判断。
    """
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
    """上传本地媒体到 KIE，返回公开可访问 URL。kind: videos / audios。"""
    default_mime = "video/mp4" if kind == "videos" else "audio/mpeg"
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


async def _do_lip_sync(video_in: str, audio_in: str, model: str, mode: str,
                       opts: dict, poll_timeout: int, temp_dir: str) -> list:
    """提交对口型任务并等待结果，返回 SDK 下载的本地文件路径列表。"""
    from backend.kieai_sdk.kieai import KieClient

    os.makedirs(temp_dir, exist_ok=True)
    async with KieClient() as client:
        entry = client.catalog.get(model)
        pnames = {p.name for p in entry.params}

        video_url = video_in
        if not video_url.startswith("http"):
            video_url = await _upload_media(client, video_in, "videos")
            if not video_url:
                raise RuntimeError("视频上传失败：未能取得可访问的 URL")

        audio_url = audio_in
        if not audio_url.startswith("http"):
            audio_url = await _upload_media(client, audio_in, "audios")
            if not audio_url:
                raise RuntimeError("音频上传失败：未能取得可访问的 URL")

        # 仅下发模型实际声明的参数
        params = {}
        if "video_url" in pnames:
            params["video_url"] = video_url
        if "audio_url" in pnames:
            params["audio_url"] = audio_url
        if "mode" in pnames:
            params["mode"] = mode
        for key in _BOOL_PARAMS:
            if key in pnames and key in opts:
                params[key] = bool(opts[key])
        if "templ_start_seconds" in pnames and opts.get("templ_start_seconds") is not None:
            try:
                params["templ_start_seconds"] = float(opts["templ_start_seconds"])
            except (TypeError, ValueError):
                pass
        if not params:
            raise RuntimeError(f"模型 {model} 未声明可用输入参数，无法提交对口型任务")

        client.max_poll = max(1, int(poll_timeout / max(client.poll_interval, 0.1)))
        result = await client.generate(model, output_path=temp_dir, **params)

    return result.get("local_paths") or []


class S_KieLipSync(BaseStep):
    """KIE AI 视频对口型：video + audio -> 口型匹配目标音频的视频。"""

    step_id = "kie_lip_sync"
    step_name = "视频对口型-kie"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        d = os.path.join(task_dir, "cache", "videos")
        if not os.path.isdir(d) or not node_id:
            return False
        return any(f"lipsync_{node_id}" in f for f in os.listdir(d))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        config = getattr(self, "_node_config", {}) or {}
        inputs = getattr(self, "_step_inputs", {}) or {}

        # 1. 输入视频与音频
        video_in = _resolve_media(inputs.get("video", ""), task_dir)
        if not video_in:
            raise ValueError("未获取到视频：请在 video 输入口连接待对口型的视频。")
        audio_in = _resolve_media(inputs.get("audio", ""), task_dir)
        if not audio_in:
            raise ValueError("未获取到音频：请在 audio 输入口连接目标音频（口型将匹配该音频）。")

        # 2. 模型与参数
        model = (config.get("model") or DEFAULT_MODEL).strip()
        if model not in SUPPORTED_MODELS:
            raise ValueError(
                f"不支持的对口型模型 '{model}'，支持: {', '.join(SUPPORTED_MODELS)}"
            )
        mode = (config.get("mode") or "basic").strip()
        try:
            poll_timeout = int(config.get("poll_timeout") or 900)
        except (TypeError, ValueError):
            poll_timeout = 900

        opts = {k: config.get(k) for k in _BOOL_PARAMS}
        opts["templ_start_seconds"] = config.get("templ_start_seconds", 0)

        cache_dir = os.path.join(task_dir, "cache", "videos")
        temp_dir = os.path.join(task_dir, "cache", "_kie_lipsync_temp", node_id)
        os.makedirs(cache_dir, exist_ok=True)

        if callback:
            callback(10, f"准备对口型（{model} / {mode}）...")
            callback(25, "提交对口型任务，处理较慢请耐心等待...")

        # 3. 执行
        try:
            paths = _run_async(
                _do_lip_sync(video_in, audio_in, model, mode, opts, poll_timeout, temp_dir)
            )
        except Exception as e:
            raise RuntimeError(f"KIE 视频对口型失败: {e}") from e

        if not paths:
            raise RuntimeError(
                "对口型未返回任何产物：请检查 KIE API Key"
                "（【全局设置 → 密钥管理器】中名称必须为 KIEAI_API_KEY）、"
                "视频与音频是否有效。"
            )

        # 4. 产物落盘（文件名带 node_id，避免同类型多实例互相覆盖）
        stem = _sanitize(os.path.splitext(os.path.basename(video_in.split("?")[0]))[0])[:24]
        saved = []
        for i, src in enumerate(paths):
            if not os.path.exists(src):
                continue
            ext = os.path.splitext(src)[1] or ".mp4"
            suffix = f"_{i + 1}" if len(paths) > 1 else ""
            name = f"{stem}_lipsync_{node_id}{suffix}{ext}"
            dest = os.path.join(cache_dir, name)
            shutil.copy2(src, dest)
            saved.append(os.path.join("cache", "videos", name))

        shutil.rmtree(temp_dir, ignore_errors=True)

        if not saved:
            raise RuntimeError("对口型产物保存失败。")

        # 5. 处理参数 JSON
        params_dir = os.path.join(task_dir, "cache", "kie_lipsync")
        os.makedirs(params_dir, exist_ok=True)
        params_rel = os.path.join("cache", "kie_lipsync", f"{node_id}_params.json")
        with open(os.path.join(task_dir, params_rel), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "node_id": node_id,
                    "model": model,
                    "mode": mode,
                    "video": video_in,
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
            callback(100, f"已保存 {len(saved)} 个对口型视频到 cache/videos")

        return {
            "artifacts": list(saved) + [params_rel],
            "outputs": {"video": saved[0], "videos": saved, "params": params_rel},
        }
