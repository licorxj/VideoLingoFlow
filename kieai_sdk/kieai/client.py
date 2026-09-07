#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Async kie.ai client.

All generation endpoints follow the same async pattern:

1. ``POST`` the task -> receive a ``taskId``
2. ``GET`` the status endpoint, polling until the task is ``SUCCESS``

The SDK never uses the ``callBackUrl`` mechanism; results are retrieved by
polling only.  File uploads are synchronous and return the URL directly.

Example
-------
    from kieai import KieClient

    async def main():
        async with KieClient(api_key="YOUR_KEY") as client:
            result = await client.generate(
                "bytedance/seedream-v4-text-to-image",
                prompt="a cat on a roof",
                image_size="square_hd",
                # save artifacts to disk; omit to use <cwd>/output/<category>/...
                output_path="out/cat.png",
            )
            print(result["local_paths"])  # list of saved file paths
            print(result["resultUrls"])   # remote URLs (when present)
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import aiohttp

from .exceptions import (
    KieRequestError,
    KieTaskFailed,
    KieTimeout,
)
from .models import Catalog, ModelEntry

# Keys that may hold the async task identifier in a submit response.
_TASK_ID_KEYS = ("taskId", "task_id", "id", "taskID")
# Numeric / string status values used across kie.ai families
# (0 GENERATING, 1 SUCCESS, 2/3 FAILED — see flux/runway/veo/suno docs).
_SUCCESS_VALUES = (1, "1", "SUCCESS", "success", "completed", "COMPLETED",
                   "SUCCEED", "succeed", "done", "DONE")
_FAILURE_VALUES = (2, 3, "2", "3", "FAILED", "FAIL", "failed", "fail",
                   "error", "ERROR", "rejected", "REJECTED")

# Keys that may hold a task status value in a poll response.
_STATUS_KEYS = ("status", "taskStatus", "progress", "state", "successFlag")
# Keys that may hold a final result URL inside a poll response.
_RESULT_KEYS = (
    "resultImageUrl", "imageUrl", "videoUrl", "audioUrl", "resultUrl",
    "downloadUrl", "audioDownloadUrl", "videoDownloadUrl", "fileUrl",
    "filePath", "url", "download_url", "resultUrlList", "imageUrls",
    "resultUrls", "fullResultUrls", "originUrls",
)

# Subset of the above that actually carry *downloadable* result media.
_DOWNLOAD_KEYS = (
    "resultUrls", "imageUrls", "fullResultUrls", "originUrls",
    "resultUrl", "imageUrl", "videoUrl", "audioUrl", "resultImageUrl",
    "downloadUrl", "audioDownloadUrl", "videoDownloadUrl", "fileUrl",
    "filePath", "url", "download_url",
)
# Extensions we are willing to trust when deriving a filename from a URL.
_MEDIA_EXTS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff",
    ".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v",
    ".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus",
    ".json", ".txt", ".srt", ".vtt", ".bin",
}
# Fallback extension when none can be inferred, keyed by category.
_CATEGORY_EXT = {"image": ".png", "video": ".mp4", "audio": ".mp3"}


def _collect_result_urls(result: Any) -> List[str]:
    """Collect every downloadable media URL found in a result payload."""
    urls: List[str] = []
    seen = set()

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if k in _DOWNLOAD_KEYS:
                    if isinstance(v, str) and v.startswith("http"):
                        if v not in seen:
                            seen.add(v)
                            urls.append(v)
                    elif isinstance(v, list):
                        for it in v:
                            if (isinstance(it, str) and it.startswith("http")
                                    and it not in seen):
                                seen.add(it)
                                urls.append(it)
                else:
                    walk(v)
        elif isinstance(o, list):
            for it in o:
                walk(it)

    walk(result)
    return urls


def _timestamp() -> str:
    """Local timestamp used in default output filenames."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _ext_from_url(url: str) -> str:
    """Return a trusted lower-cased extension (with dot) for ``url``."""
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    ext = ext.lower()
    if ext and ext in _MEDIA_EXTS:
        return ext
    return ""


def _extract_result(payload: Any, fallback: Any) -> Any:
    """Return a result object if the payload already carries result URLs.

    Market models wrap results in ``resultJson`` — a JSON *string* — so we
    also try to parse that and search inside it.
    """
    if isinstance(payload, dict):
        if _find(payload, _RESULT_KEYS) is not None:
            return payload
        rj = payload.get("resultJson")
        if isinstance(rj, str) and rj.strip():
            try:
                obj = json.loads(rj)
            except (ValueError, TypeError):
                obj = None
            if isinstance(obj, dict) and _find(obj, _RESULT_KEYS) is not None:
                return obj
    return None


def _find(data: Any, keys) -> Optional[Any]:
    """Depth-first search for the first matching key in a nested dict/list."""
    if isinstance(data, dict):
        for k in keys:
            if k in data and data[k] not in (None, "", []):
                return data[k]
        for v in data.values():
            r = _find(v, keys)
            if r is not None:
                return r
    elif isinstance(data, list):
        for item in data:
            r = _find(item, keys)
            if r is not None:
                return r
    return None


class Task:
    """A submitted (but not yet finished) async task."""

    def __init__(self, entry: ModelEntry, task_id: str, client: "KieClient"):
        self.entry = entry
        self.task_id = task_id
        self.client = client

    async def wait(self, **kwargs) -> Dict[str, Any]:
        return await self.client.wait(self, **kwargs)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Task {self.task_id} model={self.entry.id}>"


class KieClient:
    def __init__(
        self,
        api_key: str,
        *,
        catalog: Optional[Catalog] = None,
        catalog_path: Optional[str] = None,
        timeout: float = 60.0,
        poll_interval: float = 3.0,
        max_poll: int = 120,
        session: Optional[aiohttp.ClientSession] = None,
        output_base: Optional[str] = None,
    ):
        self.api_key = api_key
        self.catalog = catalog or Catalog.load(catalog_path)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.max_poll = max_poll
        # Root directory for default output when ``output_path`` is omitted.
        # Defaults to ``<cwd>/output`` (i.e. the current project's output dir).
        self.output_base = output_base or os.path.join(os.getcwd(), "output")
        self._owns_session = session is None
        self._session = session
        self._headers = {"Authorization": f"Bearer {api_key}"}

    # ------------------------------------------------------------------ #
    # session management
    # ------------------------------------------------------------------ #
    async def __aenter__(self) -> "KieClient":
        if self._session is None:
            self._session = aiohttp.ClientSession(headers=self._headers)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession(headers=self._headers)
        return self._session

    # ------------------------------------------------------------------ #
    # catalog helpers
    # ------------------------------------------------------------------ #
    def model(self, key: str) -> ModelEntry:
        return self.catalog.get(key)

    def search(self, **kwargs):
        return self.catalog.search(**kwargs)

    # ------------------------------------------------------------------ #
    # core request primitives
    # ------------------------------------------------------------------ #
    async def _post_json(self, url: str, body: Dict[str, Any]) -> Dict[str, Any]:
        async with self.session.post(url, json=body) as resp:
            try:
                data = await resp.json()
            except Exception:
                text = await resp.text()
                raise KieRequestError(
                    f"Non-JSON response ({resp.status}): {text[:200]}",
                    status=resp.status,
                )
            if resp.status >= 400 or (isinstance(data, dict) and data.get("code") not in (None, 200)):
                raise KieRequestError(
                    f"Request failed ({resp.status}): {data.get('msg', data)}",
                    status=resp.status,
                    body=data,
                )
            return data

    async def _get_json(self, url: str) -> Dict[str, Any]:
        async with self.session.get(url) as resp:
            try:
                data = await resp.json()
            except Exception:
                text = await resp.text()
                raise KieRequestError(
                    f"Non-JSON response ({resp.status}): {text[:200]}",
                    status=resp.status,
                )
            if resp.status >= 400:
                raise KieRequestError(
                    f"Poll failed ({resp.status}): {data.get('msg', data)}",
                    status=resp.status,
                    body=data,
                )
            return data

    # ------------------------------------------------------------------ #
    # result download / local persistence
    # ------------------------------------------------------------------ #
    def _resolve_output_paths(
        self,
        urls: List[str],
        category: str,
        task_id: str,
        output_path: Optional[str],
    ) -> List[str]:
        """Compute one local file path per result URL.

        * ``output_path`` given as a file (has an extension) -> used as the
          base name; multiple URLs get a ``_1``, ``_2`` … suffix.
        * ``output_path`` given as a directory (no extension) -> files are
          written there using a ``<task_id>_<timestamp>`` base name.
        * ``output_path`` omitted -> ``<output_base>/<category>/<task_id>_<timestamp>``.
        """
        n = len(urls)
        stamp = _timestamp()
        if output_path:
            op = os.path.expanduser(output_path)
            _, ext = os.path.splitext(op)
            if ext:  # looks like a file path
                directory = os.path.dirname(op) or "."
                base = os.path.basename(op)[: -len(ext)]
                forced_ext: Optional[str] = ext
            else:  # looks like a directory
                directory = op
                base = f"{task_id}_{stamp}"
                forced_ext = None
        else:
            directory = os.path.join(self.output_base, category)
            base = f"{task_id}_{stamp}"
            forced_ext = None

        os.makedirs(directory, exist_ok=True)
        fallback_ext = _CATEGORY_EXT.get(category, ".bin")

        paths: List[str] = []
        for i, url in enumerate(urls):
            ext = forced_ext or _ext_from_url(url) or fallback_ext
            suffix = f"_{i + 1}" if n > 1 else ""
            fname = f"{base}{suffix}{ext}"
            paths.append(os.path.join(directory, fname))
        return paths

    async def _download_file(self, url: str, path: str) -> None:
        """Stream ``url`` to ``path`` using the shared session."""
        try:
            async with self.session.get(url) as resp:
                if resp.status >= 400:
                    raise KieRequestError(
                        f"Download failed ({resp.status}): {url}",
                        status=resp.status,
                    )
                with open(path, "wb") as fh:
                    async for chunk in resp.content.iter_chunked(65536):
                        fh.write(chunk)
        except KieRequestError:
            raise
        except Exception as e:  # noqa: BLE001
            raise KieRequestError(f"Download failed: {e} ({url})") from e

    async def _save_results(
        self,
        result: Dict[str, Any],
        entry: ModelEntry,
        task_id: str,
        output_path: Optional[str],
    ) -> List[str]:
        """Download every media URL in ``result`` to local disk.

        Returns the list of saved file paths (empty when there is nothing to
        download).  The returned ``result`` dict is augmented with a
        ``local_paths`` key holding those paths.
        """
        urls = _collect_result_urls(result)
        if not urls:
            return []
        category = (entry.category or "file").lower()
        if category not in ("image", "video", "audio"):
            category = "file"
        paths = self._resolve_output_paths(urls, category, task_id, output_path)
        saved: List[str] = []
        for url, path in zip(urls, paths):
            await self._download_file(url, path)
            saved.append(path)
        if isinstance(result, dict):
            result["local_paths"] = saved
        return saved

    # ------------------------------------------------------------------ #
    # submit / wait / generate
    # ------------------------------------------------------------------ #
    async def submit(self, key: str, **params: Any) -> Task:
        """Submit a generation task and return a :class:`Task` (not yet done)."""
        entry = self.catalog.get(key)
        body = entry.build_body(params)
        data = await self._post_json(entry.endpoint, body)
        task_id = _find(data, _TASK_ID_KEYS)
        if not task_id:
            raise KieRequestError(
                "Could not extract task id from submit response", body=data
            )
        return Task(entry, str(task_id), self)

    async def wait(
        self,
        task: Task,
        *,
        poll_interval: Optional[float] = None,
        max_poll: Optional[int] = None,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Poll the task status endpoint until it succeeds or fails.

        When the task finishes, every downloadable result URL is persisted to
        local disk (see ``output_path`` / ``local_paths`` below) and a
        ``local_paths`` key listing the saved files is added to the returned
        dict.
        """
        if task.entry.poll_endpoint is None:
            raise KieRequestError(
                f"Model {task.entry.id!r} has no poll endpoint (synchronous?)"
            )
        interval = poll_interval or self.poll_interval
        attempts = max_poll or self.max_poll
        param = task.entry.poll_id_param or "taskId"
        url = f"{task.entry.poll_endpoint}?{param}={task.task_id}"

        last = None
        for _ in range(attempts):
            last = await self._get_json(url)
            payload = last.get("data", last) if isinstance(last, dict) else last

            status = _find(payload, _STATUS_KEYS)
            if status in _FAILURE_VALUES:
                raise KieTaskFailed(
                    f"Task {task.task_id} failed (status={status})",
                    task_id=task.task_id,
                    body=last,
                )
            if status in _SUCCESS_VALUES:
                result = _extract_result(payload, last) or (
                    payload if isinstance(payload, dict) else last
                )
            else:
                # lenient: a result URL present usually means completion
                result = _extract_result(payload, last)
            if result is not None:
                if isinstance(result, dict):
                    await self._save_results(
                        result, task.entry, task.task_id, output_path
                    )
                return result
            await asyncio.sleep(interval)

        raise KieTimeout(
            f"Task {task.task_id} did not finish after {attempts} polls",
            task_id=task.task_id,
        )

    async def generate(
        self,
        key: str,
        *,
        output_path: Optional[str] = None,
        **params: Any,
    ) -> Dict[str, Any]:
        """Submit a task and block (poll) until the result is ready.

        ``output_path`` controls where result artifacts are saved:
        * a file path -> used as the base name (``_1``, ``_2`` … for multiples);
        * a directory  -> files written there with a ``<task_id>_<timestamp>``
          base name;
        * omitted       -> ``<output_base>/<category>/<task_id>_<timestamp>``
          (the SDK's ``output_base`` defaults to ``<cwd>/output``).

        The returned dict always carries the remote URLs and, once downloaded,
        a ``local_paths`` list of the saved files.
        """
        task = await self.submit(key, **params)
        return await self.wait(task, output_path=output_path)

    # ------------------------------------------------------------------ #
    # file upload (synchronous)
    # ------------------------------------------------------------------ #
    async def upload(self, method: str = "url", **params: Any) -> Dict[str, Any]:
        """Upload a file via the File Upload API.

        ``method`` is one of ``url`` / ``stream`` / ``base64`` and selects the
        matching catalog entry (``upload-file-url`` / ``upload-file-stream`` /
        ``upload-file-base-64``).
        suffix = {"url": "upload-file-url", "stream": "upload-file-stream",
                  "base64": "upload-file-base-64"}[method]
        """
        suffix = {
            "url": "upload-file-url",
            "stream": "upload-file-stream",
            "base64": "upload-file-base-64",
        }[method]
        entry = self.catalog.get(suffix)
        data = await self._post_json(entry.endpoint, dict(params))
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data

    # ------------------------------------------------------------------ #
    # convenience shortcuts (resolve a sensible default per category)
    # ------------------------------------------------------------------ #
    async def generate_image(
        self, key: str, *, output_path: Optional[str] = None, **params: Any
    ) -> Dict[str, Any]:
        return await self.generate(key, output_path=output_path, **params)

    async def generate_video(
        self, key: str, *, output_path: Optional[str] = None, **params: Any
    ) -> Dict[str, Any]:
        return await self.generate(key, output_path=output_path, **params)

    async def generate_music(
        self,
        key: str = "generate-music",
        *,
        output_path: Optional[str] = None,
        **params: Any,
    ) -> Dict[str, Any]:
        return await self.generate(key, output_path=output_path, **params)
