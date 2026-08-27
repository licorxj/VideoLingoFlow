"""
视频生成接口管理 - 负责前端设置页面的接口配置 CRUD / 模型管理 / 生成参数构建。
结构镜像 backend/imagegen/imagegen_interface_manager.py（仅改名为 VideoGen）。
"""
import os
import json
import logging
import threading
import importlib
import requests

logger = logging.getLogger(__name__)


class VideoGenInterfaceManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, config_path=None):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self, config_path=None):
        if self._initialized:
            return
        self._initialized = True
        self.config_path = config_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "videogen_interfaces.json"
        )
        self.interfaces = {}
        self._lock = threading.RLock()
        self._load()

    def _load(self):
        with self._lock:
            self.interfaces = {}
            try:
                if not os.path.exists(self.config_path):
                    logger.warning("VideoGen interfaces config not found: %s", self.config_path)
                    return
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for iface in data.get("interfaces", []):
                    self.interfaces[iface["id"]] = iface
                logger.info("Loaded %d video interfaces from %s", len(self.interfaces), self.config_path)
            except Exception as e:
                logger.error("Failed to load video interfaces config: %s", e)

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            data = {"interfaces": list(self.interfaces.values())}
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("Failed to save video interfaces config: %s", e)

    def reload(self):
        with self._lock:
            self._load()
        return list(self.interfaces.keys())

    def list_all(self):
        return list(self.interfaces.values())

    def get(self, iface_id):
        return self.interfaces.get(iface_id)

    def create(self, data):
        with self._lock:
            iface_id = data.get("id")
            if not iface_id:
                raise ValueError("接口 ID 不能为空")
            if iface_id in self.interfaces:
                raise ValueError(f"接口已存在: {iface_id}")
            self.interfaces[iface_id] = data
            self._save()
            return data

    def update(self, iface_id, data):
        with self._lock:
            if iface_id not in self.interfaces:
                raise ValueError(f"接口不存在: {iface_id}")
            iface = self.interfaces[iface_id]
            iface.update({k: v for k, v in data.items() if k != "id"})
            self._save()
            return iface

    def delete(self, iface_id):
        with self._lock:
            if iface_id not in self.interfaces:
                raise ValueError(f"接口不存在: {iface_id}")
            if iface.get("builtin"):
                raise ValueError("内置接口不可删除")
            del self.interfaces[iface_id]
            self._save()
            return True

    def toggle(self, iface_id, enabled):
        with self._lock:
            if iface_id not in self.interfaces:
                raise ValueError(f"接口不存在: {iface_id}")
            self.interfaces[iface_id]["enabled"] = enabled
            self._save()
            return enabled

    def get_enabled(self):
        return [i for i in self.interfaces.values() if i.get("enabled", True)]

    def get_engine_ids(self):
        return [i["id"] for i in self.interfaces.values() if i.get("enabled", True)]

    def get_models(self, iface_id):
        iface = self.interfaces.get(iface_id)
        if not iface:
            return []
        return iface.get("config", {}).get("model_options", [])

    def get_model_metadata(self, iface_id):
        iface = self.interfaces.get(iface_id)
        if not iface:
            return {}
        return iface.get("config", {}).get("model_metadata", {})

    def update_balance(self, iface_id, balance):
        with self._lock:
            if iface_id not in self.interfaces:
                raise ValueError(f"接口不存在: {iface_id}")
            self.interfaces[iface_id]["balance"] = balance
            self._save()
            return balance

    def add_model(self, iface_id, model_name, metadata=None):
        with self._lock:
            if iface_id not in self.interfaces:
                raise ValueError(f"接口不存在: {iface_id}")
            config = self.interfaces[iface_id].setdefault("config", {})
            models = config.setdefault("model_options", [])
            meta = config.setdefault("model_metadata", {})
            if model_name not in models:
                models.append(model_name)
            meta[model_name] = metadata or {}
            self._save()
            return models

    def remove_model(self, iface_id, model_name):
        with self._lock:
            if iface_id not in self.interfaces:
                raise ValueError(f"接口不存在: {iface_id}")
            config = self.interfaces[iface_id].setdefault("config", {})
            models = config.setdefault("model_options", [])
            meta = config.setdefault("model_metadata", {})
            if model_name in models:
                models.remove(model_name)
            meta.pop(model_name, None)
            self._save()
            return models

    def build_request_params(self, iface_id, mode, prompt, output_dir, ref_images=None,
                             num_videos=1, resolution="720P", duration=5, ref_videos=None,
                             audio=None, negative_prompt="", model="", endpoint=None,
                             api_key="", extra_args=None):
        """构建视频生成请求参数（供 SDK 引擎动态导入并调用 generate）。

        返回字典包含：module / function / extra_args（路由信息）+ 视频生成调用参数。
        """
        iface = self.interfaces.get(iface_id, {})
        config = iface.get("config", {})
        extra = dict(config.get("sdk_extra_args", {}) or {})
        extra["api_key"] = api_key or config.get("api_key", "") or config.get("sdk_api_key", "")
        params = {
            "module": config.get("sdk_module"),
            "function": config.get("sdk_function", "generate"),
            "extra_args": extra,
            "model": model or config.get("default_model", ""),
            "negative_prompt": negative_prompt,
            "resolution": resolution,
            "duration": duration,
            "num_videos": num_videos,
            "ref_images": ref_images or [],
            "ref_videos": ref_videos or [],
            "audio": audio,
            "mode": mode,
        }
        if extra_args:
            params.update(extra_args)
        return params

    def _default_config(self, api_url, api_key):
        return {
            "default_model": "可灵 3.0",
            "model_options": [],
            "model_metadata": {},
            "modes": {
                "txt2video": {"enabled": True, "endpoint": ""},
                "img2video": {"enabled": True, "endpoint": ""},
                "flf2video": {"enabled": True, "endpoint": ""},
                "autovideo": {"enabled": True, "endpoint": ""},
            },
            "api_url": api_url,
            "api_key": api_key,
            "sdk_module": "backend.videogen.sdk.wuli_video_wrapper",
            "sdk_function": "generate",
            "max_concurrent": 1,
            "timeout": 1200,
        }


_manager_instance = None
_manager_lock = threading.Lock()


def get_videogen_interface_manager(config_path=None):
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = VideoGenInterfaceManager(config_path)
    return _manager_instance
