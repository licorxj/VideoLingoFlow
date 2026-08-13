"""Separation factory: creates separation engine instances by interface ID."""
import importlib
from typing import Optional

from backend.separation.sep_base import SeparationBase
from backend.separation.separation_interface_manager import get_separation_interface_manager

_engines = {}


def get_separation_engine(iface_id: str) -> SeparationBase:
    """Get or create a separation engine for the given interface ID."""
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


def list_separation_engines() -> list:
    """Return all enabled separation interface IDs."""
    mgr = get_separation_interface_manager()
    return mgr.get_engine_ids()


def clear_cache():
    """Clear cached engine instances."""
    _engines.clear()
