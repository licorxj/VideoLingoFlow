"""ASR Interface Manager: load, save, register custom ASR interfaces."""
import os
import json
import uuid
import threading
from typing import Optional, Dict, List, Any

INTERFACES_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "asr_interfaces.json"
)


class ASRInterfaceManager:
    """Manages ASR interface definitions loaded from JSON."""

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
        with open(INTERFACES_FILE, "w", encoding="utf-8-sig") as f:
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
                "config": data.get("config", self._default_config(data.get("type", "local")))
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

    def build_request_params(self, iface_id, audio_path, output_path,
                              language=None, model=None):
        iface = self.get(iface_id)
        if not iface:
            raise ValueError(f"Interface {iface_id} not found")
        cfg = iface.get("config", {})
        itype = iface.get("type", "local")

        if itype == "sdk":
            return self._build_sdk_params(cfg, audio_path, output_path, language, model)
        else:
            return self._build_local_params(cfg, audio_path, output_path, language, model)

    def _build_local_params(self, cfg, audio_path, output_path, language=None, model=None):
        base_url = cfg.get("api_url", "http://localhost:8800").rstrip("/")
        endpoint = cfg.get("endpoint", "/v1/audio/transcriptions")
        url = base_url + endpoint

        audio_param = cfg.get("audio_param", "file")
        lang_param = cfg.get("language_param", "language")

        body = {}
        if audio_param:
            body[audio_param] = audio_path
        if lang_param and language:
            body[lang_param] = language
        if model:
            body["model"] = model

        # Custom params with defaults
        for cp in cfg.get("custom_params", []):
            key = cp.get("key", "")
            default = cp.get("default", "")
            if key and key not in body:
                body[key] = default

        api_key = cfg.get("api_key", "")
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        body_type = cfg.get("body_type", "form")
        timeout = cfg.get("timeout", 300)

        return {
            "method": "POST",
            "url": url,
            "headers": headers,
            "body": body,
            "body_type": body_type,
            "audio_param": audio_param,
            "timeout": timeout,
        }

    def _build_sdk_params(self, cfg, audio_path, output_path, language=None, model=None):
        sdk_model = model or cfg.get("model", "")
        call_args = {
            "type": "sdk",
            "package": cfg.get("sdk_package", ""),
            "module": cfg.get("sdk_module", ""),
            "function": cfg.get("sdk_function", "transcribe"),
            "input_path": audio_path,
            "output_path": output_path,
            "model": sdk_model,
            "language": language,
            "extra_args": {**cfg.get("sdk_extra_args", {})},
        }
        if cfg.get("sdk_api_key"):
            call_args["extra_args"]["api_key"] = cfg["sdk_api_key"]
        return call_args

    @staticmethod
    def _default_config(itype):
        base = {
            "max_duration": 0,
            "word_timestamps": False,
            "diarize": False,
            "max_concurrent": 1,
            "timeout": 300,
            "custom_params": [],
            "model_options": [],
            "voice_options": [],
        }
        if itype == "sdk":
            return {
                **base,
                "sdk_package": "",
                "sdk_module": "",
                "sdk_function": "transcribe",
                "sdk_language_list_function": "",
                "sdk_api_key": "",
                "model": "",
                "text_param": "input_path",
                "model_list_url": "",
                "voice_list_url": "",
                "model_list_key": "",
                "voice_list_key": "",
                "sdk_extra_args": {},
            }
        else:
            return {
                **base,
                "api_url": "",
                "api_key": "",
                "audio_param": "file",
                "language_param": "language",
                "endpoint": "/v1/audio/transcriptions",
                "body_type": "form",
                "language_list_url": "",
                "language_list_key": "",
            }


_manager = None


def get_asr_interface_manager():
    global _manager
    if _manager is None:
        _manager = ASRInterfaceManager()
    return _manager
