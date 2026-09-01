"""
VideoGen Factory - 视频生成引擎工厂（结构镜像 imagegen/imagegen_factory.py）。
根据接口配置创建对应的引擎实例 (SDK / OpenAI 兼容)。
"""
import os
import logging
import importlib
import inspect
import requests
from typing import Optional

try:
    from backend.utils.observability import trace_function, trace_span
except ImportError:
    def trace_function(name=None):
        def decorator(func):
            return func
        return decorator
    def trace_span(name=None, **kwargs):
        class _C:
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return _C()

logger = logging.getLogger(__name__)


class GenericVideoGen:
    """通用视频生成引擎基类。"""

    def generate(self, **kwargs):
        raise NotImplementedError

    def upload_file(self, file_path_or_url, api_key=""):
        """上传文件到平台 OSS, 返回公开访问 URL。子类需实现。"""
        raise NotImplementedError


class SDKVideoGen(GenericVideoGen):
    """SDK 模式: 动态导入 Python 模块调用 generate / upload_file。"""

    def __init__(self, iface_id: str):
        self.iface_id = iface_id

    def upload_file(self, file_path_or_url, api_key=""):
        from backend.videogen.videogen_interface_manager import get_videogen_interface_manager
        mgr = get_videogen_interface_manager()
        iface = mgr.get(self.iface_id) or {}
        config = iface.get("config", {})
        base_url = config.get("api_url", "")
        resolved_key = api_key or config.get("api_key", "") or config.get("sdk_api_key", "")

        mod_path = config.get("sdk_module")
        if not mod_path:
            raise RuntimeError(f"Video SDK: 接口 {self.iface_id} 未配置 sdk_module")
        try:
            mod = importlib.import_module(mod_path)
        except ImportError as e:
            raise RuntimeError(f"Video SDK import failed: {e}")
        func = getattr(mod, "upload_file", None)
        if func is None:
            raise RuntimeError(f"模块 {mod_path} 未提供 upload_file")
        try:
            sig = inspect.signature(func)
        except (ValueError, TypeError):
            sig = None
        if sig is not None and "base_url" in sig.parameters:
            return func(file_path_or_url, api_key=resolved_key, base_url=base_url)
        return func(file_path_or_url, api_key=resolved_key)

    def generate(self, prompt, output_dir, **kwargs):
        from backend.videogen.videogen_interface_manager import get_videogen_interface_manager
        mgr = get_videogen_interface_manager()
        params = mgr.build_request_params(
            self.iface_id, kwargs.get("mode", "txt2video"), prompt, output_dir, **kwargs
        )
        mod_path = params.get("module")
        func_name = params.get("function", "generate")
        if not mod_path:
            logger.error("Video SDK: 接口 %s 未配置 sdk_module", self.iface_id)
            return []

        try:
            mod = importlib.import_module(mod_path)
        except ImportError as e:
            logger.error("Video SDK import failed: %s", e)
            return []

        func = getattr(mod, func_name, None)
        if func is None:
            logger.error("Video SDK function '%s' not found in %s", func_name, mod_path)
            return []

        call_args = {
            "prompt": prompt,
            "output_dir": output_dir,
            "model": params.get("model", ""),
            "negative_prompt": params.get("negative_prompt", ""),
            "resolution": params.get("resolution", "720P"),
            "ratio": params.get("ratio", "16:9"),
            "duration": params.get("duration", 5),
            "num_videos": params.get("num_videos", 1),
            "ref_images": params.get("ref_images", []),
            "ref_videos": params.get("ref_videos", []),
            "ref_audios": params.get("ref_audios", []),
            "audio": params.get("audio"),
            "mode": params.get("mode", "txt2video"),
        }
        call_args.update(params.get("extra_args", {}))

        try:
            result = func(**call_args)
        except Exception as e:
            logger.error("Video SDK generate error: %s", e)
            import traceback
            traceback.print_exc()
            return []

        if isinstance(result, list):
            return [str(p) for p in result]
        elif result and os.path.exists(str(result)):
            return [str(result)]
        return []


class OpenAIVideoGen(GenericVideoGen):
    """OpenAI 兼容视频生成 (如 Sora)。"""

    def __init__(self, iface_id: str):
        self.iface_id = iface_id

    def generate(self, prompt, output_dir, **kwargs):
        from backend.videogen.videogen_interface_manager import get_videogen_interface_manager
        mgr = get_videogen_interface_manager()
        iface = mgr.get(self.iface_id) or {}
        config = iface.get("config", {})
        api_key = kwargs.get("api_key") or config.get("api_key", "") or config.get("sdk_api_key", "")
        base_url = config.get("api_url", "https://api.openai.com/v1")
        if not api_key:
            logger.error("OpenAI 视频生成: 缺少 API Key")
            return []
        model = kwargs.get("model") or config.get("default_model", "sora")
        size_map = {"720P": "1280x720", "1080P": "1920x1080", "480P": "854x480", "768P": "1366x768"}
        size = size_map.get(kwargs.get("resolution", "720P"), "1280x720")
        payload = {
            "model": model,
            "prompt": prompt,
            "n": max(1, min(int(kwargs.get("num_videos", 1)), 4)),
            "size": size,
            "duration": kwargs.get("duration", 5),
        }
        if kwargs.get("negative_prompt"):
            payload["negative_prompt"] = kwargs["negative_prompt"]
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        os.makedirs(output_dir, exist_ok=True)
        saved = []
        try:
            resp = requests.post(f"{base_url.rstrip('/')}/videos", headers=headers, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            for i, item in enumerate(data.get("data", [])):
                url = item.get("url") or item.get("b64_json")
                if not url:
                    continue
                if url.startswith("data:"):
                    import base64
                    content = base64.b64decode(url.split(",", 1)[1])
                    path = os.path.join(output_dir, f"output_{i}.mp4")
                    with open(path, "wb") as f:
                        f.write(content)
                else:
                    r = requests.get(url, timeout=120, stream=True)
                    r.raise_for_status()
                    path = os.path.join(output_dir, f"output_{i}.mp4")
                    with open(path, "wb") as f:
                        for chunk in r.iter_content(8192):
                            f.write(chunk)
                saved.append(path)
        except Exception as e:
            logger.error("OpenAI 视频生成失败: %s", e)
        return saved


# 引擎实例缓存
_engines = {}


def get_videogen_engine(name: str) -> GenericVideoGen:
    """获取或创建视频生成引擎实例。"""
    global _engines
    if name in _engines:
        return _engines[name]

    from backend.videogen.videogen_interface_manager import get_videogen_interface_manager
    mgr = get_videogen_interface_manager()
    iface = mgr.get(name)

    if not iface:
        logger.error("VideoGen engine '%s' not found", name)
        return None

    if iface.get("type") == "sdk":
        engine = SDKVideoGen(name)
    else:
        engine = OpenAIVideoGen(name)

    _engines[name] = engine
    return engine


def list_videogen_engines() -> list:
    """列出所有启用的视频生成引擎 ID。"""
    from backend.videogen.videogen_interface_manager import get_videogen_interface_manager
    mgr = get_videogen_interface_manager()
    return mgr.get_engine_ids()


def clear_cache():
    """清空引擎缓存。"""
    global _engines
    _engines.clear()
