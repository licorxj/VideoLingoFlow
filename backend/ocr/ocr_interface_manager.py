"""OCR Interface Manager: load, save, manage OCR interface definitions."""
import os
import json
import uuid
import threading
from typing import Dict, Any

INTERFACES_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "ocr_interfaces.json"
)


class OCRInterfaceManager:
    """Manages OCR interface definitions loaded from JSON."""

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
                "type": data.get("type", "sdk"),
                "builtin": False,
                "enabled": data.get("enabled", True),
                "description": data.get("description", ""),
                "config": data.get("config") or self._default_config(data.get("type", "sdk")),
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

    @staticmethod
    def _default_config(itype):
        """Return default config for a given interface type (OCR 仅支持 sdk 型本地引擎)。"""
        return {
            "sdk_module": "backend.ocr.ocr_rapidocr",
            "sdk_class": "RapidOCREngine",
            "engine_type": "onnxruntime",
            "ocr_version": "PP-OCRv6",
            "model_type": "small",
            "custom_model_name": "",
            "lang_type": "ch",
            "use_cuda": False,
            "device_id": 0,
            "use_det": True,
            "use_cls": True,
            "use_rec": True,
            "text_score": 0.5,
            "box_thresh": 0.5,
            "unclip_ratio": 1.6,
            "limit_side_len": 736,
            "threads": -1,
            "return_word_box": False,
            "max_workers": 4,
            "timeout": 120,
        }


_manager = None


def get_ocr_interface_manager():
    global _manager
    if _manager is None:
        _manager = OCRInterfaceManager()
    return _manager
