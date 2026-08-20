"""Separation factory: creates separation engine instances by interface ID.

启用 GPU 服务层时返回服务代理：人声分离任务提交到常驻服务执行；
服务不可用时代理自动回退到进程内引擎。
"""
import importlib
from typing import Optional

from backend.separation.sep_base import SeparationBase
from backend.separation.separation_interface_manager import get_separation_interface_manager

_engines = {}


def _build_engine(iface_id: str) -> SeparationBase:
    """构建真实引擎实例（带缓存）。"""
    if iface_id in _engines:
        return _engines[iface_id]

    mgr = get_separation_interface_manager()
    iface = mgr.get(iface_id)
    if not iface:
        # Fallback to spleeter
        iface = mgr.get("spleeter")
        if not iface:
            raise ValueError(f"Separation interface '{iface_id}' not found and no fallback available")
        iface_id = "spleeter"

    cfg = iface.get("config", {})
    itype = iface.get("type", "sdk")

    if itype == "sdk":
        mod_path = cfg.get("sdk_module", "")
        class_name = cfg.get("sdk_class", "")
        if not mod_path or not class_name:
            raise ValueError(f"Interface '{iface_id}' missing sdk_module or sdk_class config")

        mod = importlib.import_module(mod_path)
        cls = getattr(mod, class_name)
        engine = cls(iface_id)
    else:
        # online/local: use generic HTTP-based separation
        from backend.separation.sep_generic import GenericSeparation
        engine = GenericSeparation(iface_id)

    _engines[iface_id] = engine
    return engine


class _ServiceSeparationProxy(SeparationBase):
    """GPU 服务代理：separate() 走服务层，服务不可用时回退进程内引擎。"""

    def __init__(self, iface_id: str):
        self._iface_id = iface_id
        self._real: Optional[SeparationBase] = None

    def _ensure_real(self) -> SeparationBase:
        if self._real is None:
            self._real = _build_engine(self._iface_id)
        return self._real

    def separate(
        self,
        input_path: str,
        output_dir: str,
        callback=None,
        *,
        model: str = "",
        format: str = "",
        **kwargs,
    ) -> dict:
        try:
            from backend.gpu_service import client as gpu_client
            if gpu_client.gpu_service_enabled():
                return gpu_client.run_separation(
                    self._iface_id, input_path, output_dir,
                    model=model, format=format, callback=callback,
                )
        except Exception as exc:
            from backend.gpu_service.jobs import GpuServiceUnavailableError
            if not isinstance(exc, GpuServiceUnavailableError):
                print(f"[Separation] GPU 服务调用失败，回退进程内执行: {exc}")
        return self._ensure_real().separate(input_path, output_dir, callback, model=model, format=format, **kwargs)


def get_separation_engine(iface_id: str) -> SeparationBase:
    """Get or create a separation engine for the given interface ID."""
    try:
        from backend.gpu_service import client as gpu_client
        if gpu_client.gpu_service_enabled():
            return _ServiceSeparationProxy(iface_id)
    except Exception:
        pass
    return _build_engine(iface_id)


def list_separation_engines() -> list:
    """Return all enabled separation interface IDs."""
    mgr = get_separation_interface_manager()
    return mgr.get_engine_ids()


def clear_cache():
    """Clear cached engine instances."""
    _engines.clear()
