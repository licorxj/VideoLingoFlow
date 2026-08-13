import os
import threading
from typing import Any, Optional
from ruamel.yaml import YAML

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "config.yaml")
_config_lock = threading.Lock()

_yaml = YAML()
_yaml.preserve_quotes = True


class ConfigManager:
    """Thread-safe YAML config manager. Reads on every get() call for live updates."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or CONFIG_PATH

    def _load(self) -> dict:
        with open(self.path, "r", encoding="utf-8") as f:
            data = _yaml.load(f)
        return data or {}

    def _save(self, data: dict):
        with open(self.path, "w", encoding="utf-8") as f:
            _yaml.dump(data, f)

    @staticmethod
    def _traverse(data: dict, keys: list) -> Any:
        for k in keys:
            if isinstance(data, dict) and k in data:
                data = data[k]
            else:
                return None
        return data

    @staticmethod
    def _set_nested(data: dict, keys: list, value: Any):
        for k in keys[:-1]:
            if k not in data or not isinstance(data[k], dict):
                data[k] = {}
            data = data[k]
        data[keys[-1]] = value

    def get(self, key: str, default: Any = None) -> Any:
        with _config_lock:
            data = self._load()
        value = self._traverse(data, key.split("."))
        return default if value is None else value

    def set(self, key: str, value: Any) -> bool:
        with _config_lock:
            data = self._load()
            self._set_nested(data, key.split("."), value)
            self._save(data)
        return True

    def get_snapshot(self) -> dict:
        with _config_lock:
            return self._load()

    def get_all(self) -> dict:
        return self.get_snapshot()


# Singleton
config = ConfigManager()
