"""Music generation factory: creates engine instances based on registered interfaces."""
import os
import importlib
import asyncio
from typing import List, Optional

from backend.musicgen.musicgen_base import MusicGenBase
from backend.musicgen.musicgen_interface_manager import get_musicgen_interface_manager


class GenericMusicGen(MusicGenBase):
    """Generic HTTP-based music generation engine."""

    def __init__(self, iface_id: str):
        self.iface_id = iface_id
        mgr = get_musicgen_interface_manager()
        cfg = mgr.get(iface_id) or {}
        super().__init__(cfg)

    def generate(self, prompt, output_dir, model="", mode="txt2music", api_key="", **kwargs):
        mgr = get_musicgen_interface_manager()
        params = mgr.build_request_params(self.iface_id, prompt, output_dir, model=model, mode=mode, api_key=api_key, **kwargs)
        try:
            import requests
            url = params.get("url")
            if not url:
                print(f"GenericMusicGen: no url for {self.iface_id}")
                return []
            body = params.get("body", {})
            headers = dict(params.get("headers", {}))
            timeout = params.get("timeout", 300)
            resp = requests.post(url, headers=headers, json=body, timeout=timeout)
            if resp.status_code != 200:
                print(f"GenericMusicGen request failed: {resp.status_code} {resp.text[:300]}")
                return []
            os.makedirs(output_dir, exist_ok=True)
            ct = resp.headers.get("content-type", "")
            if "audio/" in ct or resp.content[:4] in (b"ID3 ", b"RIFF", b"\xff\xfb", b"OggS"):
                ext = ct.split("/")[-1].split(";")[0] if "audio/" in ct else "mp3"
                fp = os.path.join(output_dir, f"output_0.{ext}")
                with open(fp, "wb") as f:
                    f.write(resp.content)
                return [fp]
            return []
        except Exception as e:
            print(f"GenericMusicGen error: {e}")
            import traceback
            traceback.print_exc()
            return []


class SDKMagicGen(MusicGenBase):
    """SDK-based music generation engine that dynamically imports a Python module."""

    def __init__(self, iface_id: str):
        self.iface_id = iface_id
        mgr = get_musicgen_interface_manager()
        cfg = mgr.get(iface_id) or {}
        super().__init__(cfg)

    def generate(self, prompt, output_dir, model="", mode="txt2music", api_key="", **kwargs):
        mgr = get_musicgen_interface_manager()
        params = mgr.build_request_params(self.iface_id, prompt, output_dir, model=model, mode=mode, api_key=api_key, **kwargs)
        try:
            mod_path = params.get("module", "")
            func_name = params.get("function", "generate")
            extra_args = params.get("extra_args", {})

            if not mod_path:
                print(f"SDKMagicGen: no module specified for {self.iface_id}")
                return []
            mod = importlib.import_module(mod_path)
            func = getattr(mod, func_name, None)
            if func is None:
                print(f"SDKMagicGen: function '{func_name}' not found in '{mod_path}'")
                return []

            call_args = {
                "prompt": prompt,
                "output_dir": output_dir,
                "model": model,
                "mode": mode,
                "api_key": api_key,
            }
            call_args.update(extra_args)
            # 调用方传入的模式参数（style / title / audio_path / audio_id ...）透传给 wrapper
            call_args.update(kwargs)

            if asyncio.iscoroutinefunction(func):
                result = asyncio.run(func(**call_args))
            else:
                result = func(**call_args)

            if isinstance(result, list):
                return result
            elif result and os.path.exists(str(result)):
                return [str(result)]
            return []
        except Exception as e:
            print(f"SDKMagicGen error: {e}")
            import traceback
            traceback.print_exc()
            return []


class OpenAIMusicGen(MusicGenBase):
    """Placeholder for OpenAI-style music generation (e.g. future Suno/ref models)."""

    def __init__(self, iface_id: str):
        self.iface_id = iface_id
        mgr = get_musicgen_interface_manager()
        cfg = mgr.get(iface_id) or {}
        super().__init__(cfg)

    def generate(self, prompt, output_dir, model="", mode="txt2music", api_key="", **kwargs):
        print(f"OpenAIMusicGen: engine '{self.iface_id}' is not implemented yet.")
        return []


# Cache of engine instances
_engines = {}


def get_musicgen_engine(name: str) -> Optional[MusicGenBase]:
    """Factory function to get or create a music generation engine."""
    global _engines
    if name in _engines:
        return _engines[name]

    mgr = get_musicgen_interface_manager()
    iface = mgr.get(name)

    if not iface:
        print(f"MusicGen engine '{name}' not found")
        return None

    itype = iface.get("type", "generic")
    if itype == "sdk":
        engine = SDKMagicGen(name)
    elif itype == "openai":
        engine = OpenAIMusicGen(name)
    else:
        engine = GenericMusicGen(name)

    _engines[name] = engine
    return engine


def list_musicgen_engines() -> List[str]:
    """List all enabled music generation engine IDs."""
    mgr = get_musicgen_interface_manager()
    return mgr.get_engine_ids()


def clear_cache():
    """Clear engine cache."""
    global _engines
    _engines = {}
