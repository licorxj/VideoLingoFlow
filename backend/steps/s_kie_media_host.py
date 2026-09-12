"""s_kie_media_host: KIE AI 图床网存节点（免费媒体暂存，返回外链）。

直接调用 backend/kieai_sdk 的上传接口（catalog 的 file-upload 家族）：
    upload-file-base64   base64Data + uploadPath + fileName
    upload-file-url      fileUrl    + uploadPath + fileName
返回 data.downloadUrl，可直接作为其它 KIE 生成接口的输入 URL。

支持 image / video / audio / file 四个输入口，可同时上传多个文件：
已连接的口都会上传，本地文件走 base64 上传，已是 HTTP(S) 链接的走 url 上传。

本节点仅做文件暂存，不消耗生成额度。

产物：<task_dir>/cache/kie_media_host/<node_id>_urls.json（上传明细）
"""
import os
import json
import base64
import asyncio
import logging
import mimetypes
from typing import Callable, Optional

from backend.steps.base_step import BaseStep

logger = logging.getLogger(__name__)

# 输入口顺序（决定 urls 输出顺序）
_MEDIA_PORTS = ("image", "video", "audio", "file")

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v", ".flv", ".wmv"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}


def _run_async(coro):
    """在同步上下文驱动协程；调用方已有运行中的事件循环时交由独立线程执行。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _iter_values(value):
    """把端口值展开为字符串列表（支持单值 / 列表 / 逗号分隔 / JSON 数组）。"""
    if not value:
        return []
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        if s.startswith("[") or "," in s:
            try:
                arr = json.loads(s)
                if isinstance(arr, list):
                    return [str(x).strip() for x in arr if str(x).strip()]
            except Exception:
                return [x.strip() for x in s.split(",") if x.strip()]
        return [s]
    if isinstance(value, (list, tuple)):
        out = []
        for v in value:
            out.extend(_iter_values(v))
        return out
    return [str(value)]


def _auto_upload_path(path: str) -> str:
    """按扩展名推断 uploadPath 目录。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in _IMAGE_EXTS:
        return "images"
    if ext in _VIDEO_EXTS:
        return "videos"
    if ext in _AUDIO_EXTS:
        return "audios"
    return "files"


def _resolve_local(value: str, task_dir: str) -> str:
    """解析本地文件路径（绝对路径或相对 task_dir）。"""
    raw = (value or "").strip()
    if not raw:
        return ""
    if os.path.isabs(raw):
        return raw if os.path.exists(raw) else ""
    joined = os.path.join(task_dir, raw)
    return joined if os.path.exists(joined) else ""


async def _upload_one(client, item: str, upload_path: str, timeout: int) -> dict:
    """上传单个条目（本地路径或 URL），返回明细 dict。"""
    if item.startswith("http://") or item.startswith("https://"):
        path = upload_path if upload_path != "auto" else "files"
        up = await client.upload(
            method="url", fileUrl=item, uploadPath=path,
            fileName=os.path.basename(item.split("?")[0]) or "file",
        )
        return {
            "source": item, "method": "url", "uploadPath": path,
            "url": up.get("downloadUrl") or up.get("url") or up.get("fileUrl") or "",
        }

    if not os.path.exists(item):
        return {"source": item, "method": "base64", "uploadPath": "", "url": "",
                "error": "file not found"}

    path = upload_path if upload_path != "auto" else _auto_upload_path(item)
    mime = mimetypes.guess_type(item)[0] or "application/octet-stream"
    try:
        with open(item, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode()
    except Exception as e:  # noqa: BLE001
        return {"source": item, "method": "base64", "uploadPath": path, "url": "",
                "error": f"read failed: {e}"}

    try:
        up = await client.upload(
            method="base64",
            base64Data=f"data:{mime};base64,{b64}",
            uploadPath=path,
            fileName=os.path.basename(item),
        )
    except Exception as e:  # noqa: BLE001
        return {"source": item, "method": "base64", "uploadPath": path, "url": "",
                "error": f"upload failed: {e}"}

    return {
        "source": item, "method": "base64", "uploadPath": path,
        "url": up.get("downloadUrl") or up.get("url") or up.get("fileUrl") or "",
    }


async def _upload_all(items: list, upload_path: str, timeout: int) -> list:
    from backend.kieai_sdk.kieai import KieClient

    results = []
    async with KieClient() as client:
        if timeout:
            client.timeout = float(timeout)
        for item in items:
            results.append(await _upload_one(client, item, upload_path, timeout))
    return results


class S_KieMediaHost(BaseStep):
    """KIE AI 图床网存-kie：本地媒体 -> 外链 URL。"""

    step_id = "kie_media_host"
    step_name = "图床网存-kie"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        if not node_id:
            return False
        p = os.path.join(task_dir, "cache", "kie_media_host", f"{node_id}_urls.json")
        return os.path.isfile(p) and os.path.getsize(p) > 0

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        config = getattr(self, "_node_config", {}) or {}
        inputs = getattr(self, "_step_inputs", {}) or {}

        upload_path = (config.get("upload_path") or "auto").strip() or "auto"
        try:
            timeout = int(config.get("timeout") or 120)
        except (TypeError, ValueError):
            timeout = 120

        # 1. 收集待上传条目（保持端口顺序去重）
        pending = []
        for port in _MEDIA_PORTS:
            for raw in _iter_values(inputs.get(port, "")):
                if raw in pending:
                    continue
                if raw.startswith("http"):
                    pending.append(raw)
                    continue
                local = _resolve_local(raw, task_dir)
                if local:
                    pending.append(local)
                else:
                    logger.warning("KIE 图床: 跳过无效文件 %s（端口 %s）", raw, port)

        if not pending:
            raise ValueError(
                "没有可上传的文件：请在 image / video / audio / file 任一输入口连接文件。"
            )

        if callback:
            callback(15, f"准备上传 {len(pending)} 个文件...")

        # 2. 执行上传
        try:
            details = _run_async(_upload_all(pending, upload_path, timeout))
        except Exception as e:
            raise RuntimeError(f"KIE 图床上传失败: {e}") from e

        urls = [d.get("url", "") for d in details if d.get("url")]
        if not urls:
            errs = "; ".join(
                f"{d.get('source', '')}: {d.get('error', '未返回 URL')}" for d in details
            )
            raise RuntimeError(
                "上传未返回任何链接：请检查 KIE API Key"
                "（【全局设置 → 密钥管理器】中名称必须为 KIEAI_API_KEY）。"
                + (f" 明细：{errs}" if errs else "")
            )

        # 3. 写入明细
        out_dir = os.path.join(task_dir, "cache", "kie_media_host")
        os.makedirs(out_dir, exist_ok=True)
        rel = os.path.join("cache", "kie_media_host", f"{node_id}_urls.json")
        with open(os.path.join(task_dir, rel), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "node_id": node_id,
                    "upload_path": upload_path,
                    "items": details,
                    "urls": urls,
                    "created_at": __import__("datetime").datetime.now().isoformat(),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

        if callback:
            callback(100, f"已上传 {len(urls)}/{len(pending)} 个文件")

        return {
            "artifacts": [rel],
            "outputs": {"url": urls[0], "urls": urls, "json": rel},
        }
