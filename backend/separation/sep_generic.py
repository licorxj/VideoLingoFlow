"""Generic separation engine for online/local HTTP-based separation services."""
import os
import requests
from typing import Callable, Optional

from backend.separation.sep_base import SeparationBase
from backend.separation.separation_interface_manager import get_separation_interface_manager


class GenericSeparation(SeparationBase):
    """Separation via HTTP API (online cloud service or local service)."""

    def __init__(self, iface_id: str):
        mgr = get_separation_interface_manager()
        iface = mgr.get(iface_id)
        self._config = (iface or {}).get("config", {})
        self._iface_id = iface_id

    def separate(
        self,
        input_path: str,
        output_dir: str,
        callback: Optional[Callable] = None,
        *,
        model: str = "",
        format: str = "",
        **kwargs,
    ) -> dict:
        if callback:
            callback(20, f"Calling separation API ({self._iface_id})...")

        mgr = get_separation_interface_manager()
        params = mgr.build_request_params(self._iface_id, input_path, output_dir, model, format)

        url = params["url"]
        headers = params.get("headers", {})
        body = params.get("body", {})
        body_type = params.get("body_type", "form")
        timeout = params.get("timeout", 600)

        fmt = format or self._config.get("format", "wav")
        vocals_dst = os.path.join(output_dir, f"vocals.{fmt}")
        bg_dst = os.path.join(output_dir, f"background.{fmt}")

        if body_type == "form":
            audio_param = params.get("audio_param", "file")
            files = {}
            data = dict(body)
            if os.path.exists(input_path):
                files[audio_param] = open(input_path, "rb")
                data.pop(audio_param, None)
            resp = requests.post(url, headers=headers, data=data, files=files or None, timeout=timeout)
            for f in files.values():
                f.close()
        else:
            resp = requests.post(url, headers=headers, json=body, timeout=timeout)

        if resp.status_code != 200:
            raise Exception(f"Separation API failed: {resp.status_code} {resp.text[:300]}")

        # Handle response: could be file download or JSON with URLs
        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type:
            result = resp.json()
            vocals_url = result.get("vocals_url") or result.get("vocals")
            bg_url = result.get("background_url") or result.get("background") or result.get("accompaniment_url")
            if vocals_url:
                self._download(vocals_url, vocals_dst, headers)
            if bg_url:
                self._download(bg_url, bg_dst, headers)
        else:
            # Direct file response
            with open(vocals_dst, "wb") as f:
                f.write(resp.content)

        return {"vocals": vocals_dst, "background": bg_dst}

    def _download(self, url, dst, headers=None):
        resp = requests.get(url, headers=headers, timeout=300, stream=True)
        if resp.status_code == 200:
            with open(dst, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)
