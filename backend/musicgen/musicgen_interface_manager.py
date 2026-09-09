"""Music generation interface manager.

Mirrors backend.videogen.videogen_interface_manager but models the Suno/KieAI
music capabilities. The interface list is persisted to backend/config/musicgen_interfaces.json.

MODES (generation capabilities):
  txt2music        - text/lyrics -> full song (with vocals)
  instrumental     - text/style -> instrumental track (no vocals)
  lyrics           - text -> song lyrics only (no audio)
  extend           - extend an existing track (by audioId)
  cover            - style transfer / cover from a reference audio URL
  add_instrumental - add accompaniment to an uploaded track
  add_vocals       - add vocals to an uploaded track
  separate         - stem separation of an existing track
  to_wav           - transcode an existing track to WAV
  upload_extend    - upload a local audio and extend it
"""
import os
import json
import copy
import logging
import threading

from typing import Dict, Any

logger = logging.getLogger(__name__)

# Built-in list of generation modes (enabled flag overridden by config)
MUSIC_MODES = [
    "txt2music", "instrumental", "lyrics", "extend",
    "cover", "add_instrumental", "add_vocals", "separate", "to_wav", "upload_extend",
]

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")
CONFIG_PATH = os.path.join(CONFIG_DIR, "musicgen_interfaces.json")

# Default config (used as fallback if the JSON file is missing)
_default_config = {
    "interfaces": [
        {
            "id": "kieai_music",
            "name": "KieAI 音乐生成",
            "type": "sdk",
            "enabled": True,
            "config": {
                "sdk_module": "backend.musicgen.sdk.kieai_music_wrapper",
                "sdk_function": "generate",
                "api_key_env": "KIEAI_API_KEY",
                "base_url": "https://kieai.erweima.ai",
                "default_model": "V5_5",
                "model_options": ["V4", "V4_5", "V4_5PLUS", "V4_5ALL", "V5", "V5_5"],
                "model_metadata": {
                    "V5_5": {
                        "modes": MUSIC_MODES,
                        "price": "0.06",
                        "durations": [15, 30, 60, 120, 240],
                        "max_ref_audios": 1,
                        "supports_lyrics": True,
                    }
                },
                "modes": {m: {"enabled": True, "endpoint": ""} for m in MUSIC_MODES},
                "sdk_extra_args": {"poll_timeout": 600},
            },
        }
    ]
}


class MusicGenInterfaceManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._config = None
        self._config_path = CONFIG_PATH
        self._load_config()
        self._initialized = True

    def _load_config(self):
        try:
            if os.path.exists(self._config_path):
                with open(self._config_path, "r", encoding="utf-8") as f:
                    self._config = json.load(f)
            else:
                logger.warning(f"MusicGen interfaces config not found: {self._config_path}, using default")
                self._config = copy.deepcopy(_default_config)
        except Exception as e:
            logger.error(f"Failed to load musicgen interfaces config: {e}")
            self._config = copy.deepcopy(_default_config)

    def _save_config(self):
        try:
            os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save musicgen interfaces config: {e}")

    def get_all(self) -> list:
        return self._config.get("interfaces", [])

    def get(self, interface_id: str) -> dict:
        for iface in self._config.get("interfaces", []):
            if iface["id"] == interface_id:
                return iface
        return None

    def get_engine_ids(self) -> list:
        return [i["id"] for i in self._config.get("interfaces", []) if i.get("enabled", True)]

    # ----- Aliases / helpers used by the API router -----
    def list_raw(self) -> list:
        return self._config.get("interfaces", [])

    def get_raw(self, interface_id: str) -> dict:
        return self.get(interface_id)

    def get_enabled(self) -> list:
        return [i for i in self._config.get("interfaces", []) if i.get("enabled", True)]

    def list_all(self) -> list:
        return self._config.get("interfaces", [])

    def create(self, interface: dict) -> dict:
        if self.get(interface.get("id", "")):
            raise ValueError(f"接口 '{interface['id']}' 已存在")
        iface = {
            "type": "sdk",
            "enabled": True,
            "builtin": False,
            "balance": None,
            "description": "",
            "api_source_url": "",
            "model_docs_url": "",
        }
        iface.update(interface)
        self._config.setdefault("interfaces", []).append(iface)
        self._save_config()
        return iface

    def toggle(self, interface_id: str, enabled: bool) -> bool:
        iface = self.get(interface_id)
        if not iface:
            raise ValueError(f"接口 '{interface_id}' 不存在")
        iface["enabled"] = enabled
        self._save_config()
        return True

    def reload(self) -> list:
        self._load_config()
        return self.get_engine_ids()

    def get_models(self, interface_id: str) -> list:
        iface = self.get(interface_id)
        if not iface:
            return []
        cfg = iface.get("config", {})
        options = cfg.get("model_options", [])
        metadata = cfg.get("model_metadata", {})
        return [
            {"name": m, "modes": metadata.get(m, {}).get("modes", []),
             "price": metadata.get(m, {}).get("price", ""),
             "durations": metadata.get(m, {}).get("durations", [])}
            for m in options
        ]

    def add_model(self, interface_id: str, model_name: str, metadata: dict = None) -> list:
        iface = self.get(interface_id)
        if not iface:
            raise ValueError(f"接口 '{interface_id}' 不存在")
        cfg = iface.setdefault("config", {})
        options = cfg.setdefault("model_options", [])
        if model_name not in options:
            options.append(model_name)
        meta = cfg.setdefault("model_metadata", {})
        meta[model_name] = metadata or {}
        self._save_config()
        return options

    def remove_model(self, interface_id: str, model_name: str) -> list:
        iface = self.get(interface_id)
        if not iface:
            raise ValueError(f"接口 '{interface_id}' 不存在")
        cfg = iface.setdefault("config", {})
        options = cfg.get("model_options", [])
        if model_name in options:
            options.remove(model_name)
        cfg.get("model_metadata", {}).pop(model_name, None)
        self._save_config()
        return options

    def add(self, interface: dict) -> bool:
        for i, iface in enumerate(self._config.get("interfaces", [])):
            if iface["id"] == interface["id"]:
                self._config["interfaces"][i] = interface
                self._save_config()
                return True
        self._config.setdefault("interfaces", []).append(interface)
        self._save_config()
        return True

    def update(self, interface_id: str, updates: dict) -> bool:
        iface = self.get(interface_id)
        if not iface:
            return False
        iface.update(updates)
        self._save_config()
        return True

    def delete(self, interface_id: str) -> bool:
        before = len(self._config.get("interfaces", []))
        self._config["interfaces"] = [i for i in self._config.get("interfaces", []) if i["id"] != interface_id]
        saved = len(self._config.get("interfaces", [])) != before
        if saved:
            self._save_config()
        return saved

    def get_model_options(self, interface_id: str) -> list:
        iface = self.get(interface_id)
        if not iface:
            return []
        return iface["config"].get("model_options", [])

    def get_model_metadata(self, interface_id: str) -> dict:
        iface = self.get(interface_id)
        if not iface:
            return {}
        return iface["config"].get("model_metadata", {})

    def get_modes(self, interface_id: str) -> dict:
        iface = self.get(interface_id)
        if not iface:
            return {}
        return iface["config"].get("modes", {})

    def build_request_params(self, interface_id: str, prompt: str, output_dir: str,
                             model: str = "", mode: str = "txt2music",
                             api_key: str = "", **kwargs) -> dict:
        """Resolve the interface into concrete call arguments for the SDK wrapper.

        Returns a dict consumed by SDKMagicGen.generate:
            { module, function, model, mode, extra_args }
        """
        iface = self.get(interface_id)
        if not iface:
            raise ValueError(f"Interface '{interface_id}' not found")
        cfg = iface["config"]
        resolved_model = model or cfg.get("default_model", "")

        extra = dict(cfg.get("sdk_extra_args", {}))
        ak = (
            api_key
            or kwargs.pop("api_key", None)
            or extra.get("api_key")
            or os.getenv(cfg.get("api_key_env", "KIEAI_API_KEY"), "")
        )
        extra["api_key"] = ak
        if "poll_timeout" in extra:
            extra["poll_timeout"] = int(extra["poll_timeout"])

        return {
            "module": cfg.get("sdk_module", ""),
            "function": cfg.get("sdk_function", "generate"),
            "model": resolved_model,
            "mode": mode,
            "extra_args": extra,
        }


# Singleton accessor
_manager_instance = None


def get_musicgen_interface_manager() -> MusicGenInterfaceManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = MusicGenInterfaceManager()
    return _manager_instance


# ---- Self-test helpers used by the API router's test endpoint ----

def build_test_request(interface_id: str, prompt: str, model: str = "", mode: str = "txt2music",
                       api_key: str = "", **kwargs) -> dict:
    """Construct the actual call arguments used to test an interface.

    Mirrors videogen's build_test_request. For SDK interfaces this is None
    (the wrapper executes the call directly). For generic HTTP interfaces it
    returns the resolved body/headers so the router can show a preview.
    """
    mgr = get_musicgen_interface_manager()
    iface = mgr.get(interface_id)
    if not iface:
        return {"error": f"Interface '{interface_id}' not found"}
    if iface.get("type") == "sdk":
        params = mgr.build_request_params(interface_id, prompt, "", model=model, mode=mode, api_key=api_key, **kwargs)
        return {
            "interface_id": interface_id,
            "type": "sdk",
            "module": params["module"],
            "function": params["function"],
            "model": params["model"],
            "mode": params["mode"],
            "extra_args": params["extra_args"],
        }
    # Generic HTTP: build a preview body
    cfg = iface["config"]
    body = dict(cfg.get("body_template", {}))
    body.update(kwargs)
    if "prompt_field" in cfg:
        body[cfg["prompt_field"]] = prompt
    if model and "model_field" in cfg:
        body[cfg["model_field"]] = model
    return {
        "interface_id": interface_id,
        "type": "http",
        "url": cfg.get("url", ""),
        "method": cfg.get("method", "POST"),
        "headers": cfg.get("headers", {}),
        "body": body,
    }
