"""Image Generation Interface Manager: load, save, register custom image generation interfaces."""
import os
import json
import uuid
import threading
from typing import Optional, Dict, List, Any

INTERFACES_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "imagegen_interfaces.json"
)


class ImageGenInterfaceManager:
    """Manages image generation interface definitions loaded from JSON."""

    def __init__(self):
        self._lock = threading.Lock()
        self._interfaces: Dict[str, dict] = {}
        self._load()

    def _load(self):
        if not os.path.exists(INTERFACES_FILE):
            self._interfaces = {}
            return
        with open(INTERFACES_FILE, "r", encoding="utf-8-sig") as f:
            content = f.read().lstrip("\ufeff")
            data = json.loads(content)
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
                "type": data.get("type", "sdk"),
                "builtin": False,
                "enabled": data.get("enabled", True),
                "description": data.get("description", ""),
                "api_source_url": data.get("api_source_url", ""),
                "model_docs_url": data.get("model_docs_url", ""),
                "balance": data.get("balance", None),
                "config": data.get("config", self._default_config(data.get("type", "sdk")))
            }
            self._interfaces[iface_id] = iface
            self._save()
            return iface

    def update(self, iface_id, data):
        with self._lock:
            if iface_id not in self._interfaces:
                return None
            iface = self._interfaces[iface_id]
            for key in ["name", "type", "enabled", "description", "api_source_url", "model_docs_url", "balance"]:
                if key in data:
                    iface[key] = data[key]
            if "config" in data:
                iface["config"] = data["config"]
            self._interfaces[iface_id] = iface
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

    def get_models(self, iface_id):
        """Get model list for an interface."""
        iface = self.get(iface_id)
        if not iface:
            return []
        cfg = iface.get("config", {})
        return cfg.get("model_options", [])

    def get_model_metadata(self, iface_id):
        """Get model metadata dict for an interface."""
        iface = self.get(iface_id)
        if not iface:
            return {}
        cfg = iface.get("config", {})
        return cfg.get("model_metadata", {})

    def update_balance(self, iface_id, balance):
        """Update the cached balance for an interface."""
        with self._lock:
            iface = self._interfaces.get(iface_id)
            if not iface:
                return None
            iface["balance"] = balance
            self._save()
            return iface

    def add_model(self, iface_id, model_name, metadata=None):
        """Add a model to the interface's model list with optional metadata."""
        with self._lock:
            iface = self._interfaces.get(iface_id)
            if not iface:
                return False
            cfg = iface.get("config", {})
            models = cfg.get("model_options", [])
            if model_name and model_name not in models:
                models.append(model_name)
                cfg["model_options"] = models
                if metadata:
                    meta = cfg.get("model_metadata", {})
                    meta[model_name] = metadata
                    cfg["model_metadata"] = meta
                self._save()
            return True

    def remove_model(self, iface_id, model_name):
        """Remove a model from the interface's model list and its metadata."""
        with self._lock:
            iface = self._interfaces.get(iface_id)
            if not iface:
                return False
            cfg = iface.get("config", {})
            models = cfg.get("model_options", [])
            if model_name in models:
                models.remove(model_name)
                cfg["model_options"] = models
                # Also clean up metadata
                meta = cfg.get("model_metadata", {})
                if model_name in meta:
                    del meta[model_name]
                    cfg["model_metadata"] = meta
                self._save()
            return True

    def build_request_params(self, iface_id, prompt, output_dir, **kwargs):
        """Build request parameters based on interface type."""
        iface = self.get(iface_id)
        if not iface:
            raise ValueError(f"Interface {iface_id} not found")
        cfg = iface.get("config", {})
        itype = iface.get("type", "sdk")

        if itype == "openai_compatible":
            return self._build_openai_params(cfg, prompt, output_dir, **kwargs)
        else:
            return self._build_sdk_params(cfg, prompt, output_dir, **kwargs)

    def _build_openai_params(self, cfg, prompt, output_dir, **kwargs):
        """Build parameters for OpenAI-compatible image generation API.

        Mirrors the OpenAI SDK `client.images.generate(...)` contract:
        prompt / model / size / n / response_format / output_format, plus
        img2img via the `image` field. Endpoint-specific extras go through
        `custom_params` (equivalent to the SDK's `extra_body`).
        """
        body = {
            "prompt": prompt,
            "model": kwargs.get("model") or cfg.get("default_model", ""),
            "n": kwargs.get("num_images", 1),
        }

        # size: pass resolution verbatim ("1K"/"2K"/"4K" for most compatible
        # endpoints such as Doubao/Seedream; standard OpenAI uses pixel enums
        # like "1024x1024"). An explicit `size` in cfg/custom_params overrides.
        size = kwargs.get("size") or cfg.get("size") or kwargs.get("resolution", "1K")
        body["size"] = size

        # aspect_ratio: many compatible endpoints (e.g. Doubao) accept this as
        # a standalone field rather than baking it into size.
        aspect_ratio = kwargs.get("aspect_ratio")
        if aspect_ratio:
            body["aspect_ratio"] = aspect_ratio

        # Standard OpenAI fields: response_format (url | b64_json), output_format.
        body["response_format"] = (
            kwargs.get("response_format") or cfg.get("response_format", "url")
        )
        output_format = kwargs.get("output_format") or cfg.get("output_format")
        if output_format:
            body["output_format"] = output_format

        # Negative prompt if supported
        negative_prompt = kwargs.get("negative_prompt", "")
        if negative_prompt:
            body["negative_prompt"] = negative_prompt

        # img2img: standard OpenAI uses the `image` field (url or base64),
        # which the SDK would place under extra_body. Send the first ref as a
        # scalar, or the whole list when multiple are provided.
        ref_images = kwargs.get("ref_images") or []
        if ref_images:
            body["image"] = ref_images[0] if len(ref_images) == 1 else ref_images

        # API key and URL
        api_url = cfg.get("api_url", "")
        api_key = cfg.get("api_key", "")

        # Endpoint resolution
        modes = cfg.get("modes", {})
        mode = kwargs.get("mode", "txt2img")
        endpoint = ""
        if mode in modes and modes[mode].get("enabled"):
            endpoint = modes[mode].get("endpoint", "")

        url = (api_url.rstrip("/") + endpoint) if endpoint else api_url

        # Custom params: endpoint-specific extras (equivalent to the SDK's
        # extra_body). They may override optional fields like `size` to adapt to
        # endpoints that expect pixel enums (e.g. SiliconFlow/OpenAI). Core
        # fields prompt/model/n are protected from being overridden.
        _protected = {"prompt", "model", "n"}
        for cp in cfg.get("custom_params", []):
            key = cp.get("key", "")
            default = cp.get("default", "")
            if not key:
                continue
            # Tolerate SDK-style extra_body passed as a JSON string: expand it
            # into the body instead of sending a literal "extra_body" field.
            if key == "extra_body" and isinstance(default, str):
                try:
                    extra = json.loads(default)
                    if isinstance(extra, dict):
                        for ek, ev in extra.items():
                            if ek not in _protected:
                                body[ek] = ev
                        continue
                except Exception:
                    pass
            if key not in _protected:
                body[key] = default

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        timeout = cfg.get("timeout", 120)

        return {
            "method": "POST",
            "url": url,
            "headers": headers,
            "body": body,
            "body_type": "json",
            "timeout": timeout,
            "output_dir": output_dir,
        }

    def _build_sdk_params(self, cfg, prompt, output_dir, **kwargs):
        """Build parameters for SDK-based engines."""
        return {
            "type": "sdk",
            "package": cfg.get("sdk_package", ""),
            "module": cfg.get("sdk_module", ""),
            "function": cfg.get("sdk_function", "generate"),
            "prompt": prompt,
            "output_dir": output_dir,
            "model": kwargs.get("model") or cfg.get("default_model", ""),
            "negative_prompt": kwargs.get("negative_prompt", ""),
            "resolution": kwargs.get("resolution", "1K"),
            "aspect_ratio": kwargs.get("aspect_ratio", "1:1"),
            "num_images": kwargs.get("num_images", 1),
            "ref_images": kwargs.get("ref_images", []),
            "extra_args": {
                **cfg.get("sdk_extra_args", {}),
                **({"api_key": cfg["sdk_api_key"]} if cfg.get("sdk_api_key") else {}),
            },
            "timeout": cfg.get("timeout", 120),
        }

    @staticmethod
    def _resolve_size(resolution, aspect_ratio):
        """Map resolution + aspect_ratio to pixel size string."""
        base = {"1K": 1024, "2K": 2048, "4K": 4096}.get(resolution, 1024)
        ratio_map = {
            "1:1": (1, 1),
            "16:9": (16, 9),
            "9:16": (9, 16),
            "4:3": (4, 3),
            "3:4": (3, 4),
            "3:2": (3, 2),
            "2:3": (2, 3),
        }
        rw, rh = ratio_map.get(aspect_ratio, (1, 1))
        if rw >= rh:
            w = base
            h = int(base * rh / rw)
        else:
            h = base
            w = int(base * rw / rh)
        # Round to nearest 64
        w = max(256, (w // 64) * 64)
        h = max(256, (h // 64) * 64)
        return f"{w}x{h}"

    @staticmethod
    def _default_config(itype):
        """Return default config for a given interface type."""
        _modes = {
            "txt2img": {"enabled": True, "endpoint": ""},
            "img2img": {"enabled": True, "endpoint": ""},
            "fusion": {"enabled": True, "endpoint": ""},
            "grid": {"enabled": True, "endpoint": ""},
            "i2grid": {"enabled": True, "endpoint": ""},
            "refs2grid": {"enabled": True, "endpoint": ""},
            "websearch": {"enabled": True, "endpoint": ""},
        }
        if itype == "openai_compatible":
            return {
                "api_url": "",
                "api_key": "",
                "default_model": "",
                "model_options": [],
                "model_metadata": {},
                "model_list_url": "",
                "model_list_key": "",
                "balance_endpoint": "",
                "modes": {k: dict(v) for k, v in _modes.items()},
                "custom_params": [],
                "max_concurrent": 1,
                "timeout": 120,
            }
        else:  # sdk
            return {
                "sdk_package": "",
                "sdk_module": "",
                "sdk_function": "generate",
                "sdk_extra_args": {},
                "sdk_api_key": "",
                "default_model": "",
                "model_options": [],
                "model_metadata": {},
                "model_list_url": "",
                "model_list_key": "",
                "balance_endpoint": "",
                "modes": {k: dict(v) for k, v in _modes.items()},
                "custom_params": [],
                "max_concurrent": 1,
                "timeout": 120,
            }


_manager = None


def get_imagegen_interface_manager():
    global _manager
    if _manager is None:
        _manager = ImageGenInterfaceManager()
    return _manager
