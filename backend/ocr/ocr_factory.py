"""OCR factory: creates OCR engine instances by interface ID.

OCR 服务层统一入口，调用方通过 get_ocr_engine(iface_id) 获取引擎实例。
当前仅支持 sdk 型（rapidocr 本地库），动态 import 配置中的 sdk_module/sdk_class。

引擎生命周期：空闲超过 5 秒无任务调用时自动卸载（归还内存/显存），
下次调用按需重建；配置变更时 clear_cache() 立即全部卸载。
"""
import importlib
import json
from typing import Optional

from backend.ocr.ocr_base import OCRBase
from backend.ocr.ocr_interface_manager import get_ocr_interface_manager
from backend.utils.engine_lifecycle import IdleEngineRegistry

_registry = IdleEngineRegistry(idle_timeout=5.0, name="OCR")


def _build_engine(iface_id: str, overrides: Optional[dict] = None) -> OCRBase:
    """构建真实引擎实例（不做缓存，由注册表统一管理）。

    overrides 为节点级模型覆盖参数（ocr_version/model_type/custom_model_name），
    用于按节点配置覆盖接口默认模型。
    """
    mgr = get_ocr_interface_manager()
    iface = mgr.get(iface_id)
    if not iface:
        raise ValueError(f"OCR interface '{iface_id}' not found")

    cfg = iface.get("config", {})
    itype = iface.get("type", "sdk")

    if itype == "sdk":
        mod_path = cfg.get("sdk_module", "")
        class_name = cfg.get("sdk_class", "")
        if not mod_path or not class_name:
            raise ValueError(f"Interface '{iface_id}' missing sdk_module or sdk_class config")
        mod = importlib.import_module(mod_path)
        cls = getattr(mod, class_name)
        return cls(iface_id, overrides)
    else:
        raise ValueError(f"OCR interface '{iface_id}' type '{itype}' not supported (仅支持 sdk 型本地引擎)")


def get_ocr_engine(iface_id: str = "rapidocr", overrides: Optional[dict] = None) -> OCRBase:
    """Get or create an OCR engine; idle engines are auto-unloaded after 5s.

    overrides 非空时按覆盖参数区分缓存实例，避免不同模型配置并发重建抖动。
    """
    if overrides:
        key = f"{iface_id}|{json.dumps(overrides, sort_keys=True)}"
        return _registry.acquire(key, lambda: _build_engine(iface_id, overrides))
    return _registry.acquire(iface_id, lambda: _build_engine(iface_id))


def list_ocr_engines() -> list:
    """Return all enabled OCR interface IDs."""
    mgr = get_ocr_interface_manager()
    return mgr.get_engine_ids()


def clear_cache():
    """Unload all cached engine instances (e.g. after config change)."""
    _registry.clear_all()
