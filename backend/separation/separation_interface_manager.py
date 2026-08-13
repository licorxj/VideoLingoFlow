"""Separation Interface Manager: load, save, manage separation interface definitions."""
import os
import json
import uuid
import threading
from typing import Dict, Any

INTERFACES_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "separation_interfaces.json"
)


class SeparationInterfaceManager:
    """Manages separation interface definitions loaded from JSON."""

    def __init__(self):
        self._lock = threading.Lock()
        self._interfaces: Dict[str, dict] = {}
        self._load()

    def _load(self):
        if not os.path.exists(INTERFACES_FILE):
            self._interfaces = {}
            return
        with open(INTERFACES_FILE, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        for iface in data.get("interfaces", []):
            self._interfaces[iface["id"]] = iface

    def _save(self):
        data = {"version": 1, "interfaces": list(self._interfaces.values())}
        os.makedirs(os.path.dirname(INTERFACES_FILE), exist_ok=True)
        with open(INTERFACES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def reload(self):
        with self._lock:
            self._interfaces = {}
            self._load()

    def list_all(self):
        with self._lock:
            return list(self._interfaces.values())

    def get(self, iface_id):
        with self._lock:
            return self._interfaces.get(iface_id)

    def create(self, data):
        with self._lock:
            iface_id = data.get("id") or uuid.uuid4().hex[:8]
            iface = {
                "id": iface_id,
                "name": data.get("name", ""),
                "type": data.get("type", "local"),
                "builtin": False,
                "enabled": data.get("enabled", True),
                "description": data.get("description", ""),
                "config": data.get("config") or self._default_config(data.get("type", "local")),
            }
            self._interfaces[iface_id] = iface
            self._save()
            return iface

    def update(self, iface_id, data):
        with self._lock:
            if iface_id not in self._interfaces:
                return None
            iface = self._interfaces[iface_id]
            if iface.get("builtin"):
                for key in ["description", "config"]:
                    if key in data:
                        iface[key] = data[key]
            else:
                for key in ["name", "type", "enabled", "description"]:
                    if key in data:
                        iface[key] = data[key]
                if "config" in data:
                    iface["config"] = data["config"]
            self._save()
            return iface

    def delete(self, iface_id):
        with self._lock:
            iface = self._interfaces.get(iface_id)
            if not iface or iface.get("builtin"):
                return False
            del self._interfaces[iface_id]
            self._save()
            return True

    def toggle(self, iface_id, enabled):
        with self._lock:
            iface = self._interfaces.get(iface_id)
            if not iface:
                return None
            iface["enabled"] = enabled
            self._save()
            return iface

    def get_enabled(self):
        with self._lock:
            return [i for i in self._interfaces.values() if i.get("enabled")]

    def get_engine_ids(self):
        with self._lock:
            return [i["id"] for i in self._interfaces.values() if i.get("enabled")]

    def build_request_params(self, iface_id, input_path, output_dir, model=None, format=None):
        """Build HTTP request params for online/local interfaces."""
        iface = self.get(iface_id)
        if not iface:
            raise ValueError(f"Interface {iface_id} not found")
        cfg = iface.get("config", {})
        itype = iface.get("type", "local")

        if itype == "sdk":
            return self._build_sdk_params(cfg, input_path, output_dir, model, format)
        else:
            return self._build_http_params(cfg, input_path, output_dir, model, format)

    def _build_sdk_params(self, cfg, input_path, output_dir, model, format):
        return {
            "type": "sdk",
            "sdk_module": cfg.get("sdk_module", ""),
            "sdk_class": cfg.get("sdk_class", ""),
            "input_path": input_path,
            "output_dir": output_dir,
            "model": model or cfg.get("model", ""),
            "format": format or cfg.get("format", "wav"),
            "extra_args": dict(cfg.get("sdk_extra_args", {})),
        }

    def _build_http_params(self, cfg, input_path, output_dir, model, format):
        base_url = cfg.get("api_url", "http://localhost:8800").rstrip("/")
        endpoint = cfg.get("endpoint", "/v1/separate")
        url = base_url + endpoint
        audio_param = cfg.get("audio_param", "file")
        api_key = cfg.get("api_key", "")
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        body = {}
        if model:
            body["model"] = model
        if format:
            body["format"] = format
        for cp in cfg.get("custom_params", []):
            key = cp.get("key", "")
            default = cp.get("default", "")
            if key and key not in body:
                body[key] = default

        return {
            "method": "POST",
            "url": url,
            "headers": headers,
            "body": body,
            "body_type": cfg.get("body_type", "form"),
            "audio_param": audio_param,
            "timeout": cfg.get("timeout", 600),
        }

    def _default_config(itype):
        base = {
            "model": "",
            "model_options": [],
            "model_details": {},
            "format": "wav",
            "format_options": ["wav", "mp3"],
            "timeout": 600,
            "max_concurrent": 1,
            "custom_params": [],
        }
        if itype == "sdk":
            return {
                **base,
                "sdk_module": "",
                "sdk_class": "",
                "segment": 1200,
                "two_stems": "vocals",
            }
        else:
            return {
                **base,
                "api_url": "",
                "api_key": "",
                "endpoint": "/v1/separate",
                "body_type": "form",
                "audio_param": "file",
                "startup_script": "",
            }


_manager = None


def get_separation_interface_manager():
    global _manager
    if _manager is None:
        _manager = SeparationInterfaceManager()
    return _manager
