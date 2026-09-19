"""s_file_downloader: 文件下载器节点。

按「下载地址」把文件下载到任务目录的 ``download/`` 文件夹：

- 文件名优先取「文件名称」连线输入；未提供时依次回退
  ``Content-Disposition`` 文件名 → URL 路径末段 → ``download_<时间戳>``；
- 无扩展名时按响应 ``Content-Type`` 补全常见扩展名；
- 同名文件默认覆盖；节点设置关闭「同名覆盖」后自动追加 ``-1`` / ``-2`` 序号；
- 下载过程按字节回报进度，支持协作取消（运行时可硬停止本节点）；
- 失败时清理半成品 ``.part_*`` 临时文件。

输出：``file``（相对任务目录的文件路径）、``filename``（最终文件名）。
另在 ``cache/downloader_<node_id>.json`` 落一份下载记录（大小 / 最终 URL / 内容类型）。
"""
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import unquote, urlparse

import requests

from backend.steps.base_step import BaseStep

DOWNLOAD_DIR = "download"
DEFAULT_TIMEOUT = 300
CHUNK_SIZE = 256 * 1024

# Content-Type -> 扩展名：文件名缺扩展名时补全
_CT_EXT = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp",
    "image/svg+xml": ".svg", "image/bmp": ".bmp", "image/tiff": ".tiff",
    "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
    "video/x-matroska": ".mkv", "video/x-msvideo": ".avi",
    "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/aac": ".aac",
    "audio/flac": ".flac", "audio/ogg": ".ogg", "audio/mp4": ".m4a",
    "application/pdf": ".pdf", "application/zip": ".zip", "application/x-7z-compressed": ".7z",
    "application/json": ".json", "application/xml": ".xml", "application/javascript": ".js",
    "text/plain": ".txt", "text/csv": ".csv", "text/html": ".html", "text/markdown": ".md",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls", "application/msword": ".doc",
}


def _pick(raw: Any) -> str:
    """取输入值：兼容多连线聚合成的列表与各类标量，统一转为去空白字符串。"""
    if isinstance(raw, (list, tuple)):
        raw = next((item for item in raw if item not in (None, "", [], {})), "")
    if raw is None:
        return ""
    return str(raw).strip()


def _safe_name(name: str) -> str:
    """清洗文件名：剥掉路径部分与非法字符，确保不会写出 download/ 之外。"""
    name = unquote(str(name or "")).strip().replace("\\", "/").split("/")[-1]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(". ")
    # Windows 保留名防护
    if name.split(".")[0].upper() in {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10)),
    }:
        name = f"_{name}"
    return name[:180]


def _name_from_disposition(header: str) -> str:
    """从 Content-Disposition 解析文件名（优先 RFC 5987 的 filename*）。"""
    if not header:
        return ""
    match = re.search(r"filename\*=(?:UTF-8''|utf-8'')?([^;]+)", header, re.IGNORECASE)
    if match:
        return unquote(match.group(1).strip().strip('"'))
    match = re.search(r'filename="?([^";]+)"?', header, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _name_from_url(url: str) -> str:
    """从 URL 路径末段取文件名（忽略 query 与 fragment）。"""
    path = urlparse(url or "").path or ""
    return unquote(path.rstrip("/").split("/")[-1]) if path else ""


def _parse_headers(raw: Any) -> dict:
    """解析附加请求头（JSON 对象文本），留空返回空字典。"""
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"附加请求头必须是 JSON 对象：{exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("附加请求头必须是 JSON 对象")
    return {str(key): str(value) for key, value in parsed.items()}


def _human(size: float) -> str:
    """字节数转可读文本。"""
    value = float(size or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


class S_FileDownloader(BaseStep):
    step_id = "file_downloader"
    step_name = "文件下载器"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        meta = self._meta_path(task_dir)
        if not meta.is_file():
            return False
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        rel = str((data or {}).get("file") or "")
        return bool(rel) and (Path(task_dir) / rel).is_file()

    def validate_inputs(self, task_dir: str) -> bool:
        return bool(_pick((getattr(self, "_step_inputs", {}) or {}).get("url")))

    def _meta_path(self, task_dir: str) -> Path:
        node_id = getattr(self, "_node_id", "") or "node"
        return Path(task_dir) / "cache" / f"downloader_{node_id}.json"

    @staticmethod
    def _unique_path(directory: Path, name: str, overwrite: bool) -> Path:
        """按「是否覆盖同名」决定最终落盘路径。"""
        candidate = directory / name
        if overwrite or not candidate.exists():
            return candidate
        stem, ext = os.path.splitext(name)
        for index in range(1, 1000):
            alt = directory / f"{stem}-{index}{ext}"
            if not alt.exists():
                return alt
        return directory / f"{stem}-{int(time.time())}{ext}"

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        inputs = getattr(self, "_step_inputs", {}) or {}
        config = getattr(self, "_node_config", {}) or {}
        node_id = getattr(self, "_node_id", "") or "node"

        url = _pick(inputs.get("url"))
        if not url:
            raise ValueError("文件下载器需要「下载地址」输入")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError(f"下载地址必须是有效的 http/https 地址：{url}")

        want_name = _pick(inputs.get("filename"))
        timeout = max(1.0, float(config.get("timeout") or DEFAULT_TIMEOUT))
        overwrite = bool(config.get("overwrite", True))
        headers = _parse_headers(config.get("headers"))

        task_dir_path = Path(task_dir).resolve()
        dl_dir = task_dir_path / DOWNLOAD_DIR
        dl_dir.mkdir(parents=True, exist_ok=True)
        (task_dir_path / "cache").mkdir(exist_ok=True)

        def progress(percent: int, message: str) -> None:
            if callback:
                try:
                    callback(percent, message)
                except Exception:
                    pass

        progress(5, f"开始下载：{url}")
        tmp_path = dl_dir / f".part_{node_id}"
        name = ""
        content_type = ""
        final_url = url
        done = 0

        try:
            with requests.get(url, stream=True, timeout=timeout,
                              headers=headers or None) as response:
                final_url = str(response.url or url)
                if response.status_code >= 400:
                    raise RuntimeError(f"下载失败：HTTP {response.status_code}（{final_url}）")

                name = (
                    _safe_name(want_name)
                    or _safe_name(_name_from_disposition(response.headers.get("Content-Disposition", "")))
                    or _safe_name(_name_from_url(final_url))
                    or f"download_{time.strftime('%Y%m%d_%H%M%S')}"
                )
                content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if not os.path.splitext(name)[1] and content_type in _CT_EXT:
                    name += _CT_EXT[content_type]

                try:
                    total = int(response.headers.get("Content-Length") or 0)
                except (TypeError, ValueError):
                    total = 0

                last_report = 0.0
                with open(tmp_path, "wb") as handle:
                    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                        if cancel_callback and cancel_callback():
                            raise RuntimeError("任务已取消")
                        if not chunk:
                            continue
                        handle.write(chunk)
                        done += len(chunk)
                        now = time.monotonic()
                        if now - last_report < 0.5:
                            continue
                        last_report = now
                        if total > 0:
                            progress(min(95, 10 + int(done / total * 85)),
                                     f"已下载 {_human(done)} / {_human(total)}")
                        else:
                            progress(50, f"已下载 {_human(done)}")

                # 声明了长度却收不满（且未经压缩传输）视为中断，避免把残片当成成功
                encoding = (response.headers.get("Content-Encoding") or "identity").lower()
                if total > 0 and done < total and encoding in ("", "identity"):
                    raise RuntimeError(
                        f"下载中断：仅收到 {_human(done)} / {_human(total)}（{final_url}）"
                    )

            target = self._unique_path(dl_dir, name, overwrite)
            os.replace(tmp_path, target)
        except Exception:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            raise

        rel_path = f"{DOWNLOAD_DIR}/{target.name}"
        size = target.stat().st_size
        meta = {
            "file": rel_path,
            "filename": target.name,
            "url": final_url,
            "requested_url": url,
            "requested_filename": want_name,
            "size": size,
            "content_type": content_type,
        }
        meta_path = self._meta_path(task_dir)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        progress(100, f"下载完成：{target.name}（{_human(size)}）")
        return {
            "artifacts": [rel_path, f"cache/{meta_path.name}"],
            "outputs": {
                "file": rel_path,
                "filename": target.name,
            },
        }


StepFileDownloader = S_FileDownloader
