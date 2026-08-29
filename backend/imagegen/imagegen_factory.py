"""Image generation factory: creates engine instances based on registered interfaces."""
import os
import json
import importlib
import requests
from typing import Optional
from backend.imagegen.imagegen_base import ImageGenBase
from backend.imagegen.imagegen_interface_manager import get_imagegen_interface_manager


def _validate_generation_params(iface_id: str, **kwargs):
    """Validate mode, resolution, aspect_ratio against model metadata.
    Raises ValueError if validation fails."""
    mgr = get_imagegen_interface_manager()
    metadata = mgr.get_model_metadata(iface_id)
    model = kwargs.get("model", "")
    mode = kwargs.get("mode", "txt2img")
    resolution = kwargs.get("resolution", "1K")
    aspect_ratio = kwargs.get("aspect_ratio", "1:1")

    if not model or model not in metadata:
        return  # No metadata to validate against

    meta = metadata[model]
    errors = []

    # Validate mode
    supported_modes = meta.get("modes", [])
    if supported_modes:
        mode_map = {"txt2img": "t2i", "img2img": "i2i"}
        mapped_mode = mode_map.get(mode, mode)
        if mapped_mode not in supported_modes:
            errors.append(f"模型 '{model}' 不支持模式 '{mode}'（支持: {', '.join(supported_modes)}）")

    # Validate resolution
    supported_resolutions = meta.get("resolutions", [])
    if supported_resolutions and resolution not in supported_resolutions:
        errors.append(f"模型 '{model}' 不支持分辨率 '{resolution}'（支持: {', '.join(supported_resolutions)}）")

    # Validate aspect ratio
    supported_ratios = meta.get("aspect_ratios", [])
    if supported_ratios and aspect_ratio not in supported_ratios:
        errors.append(f"模型 '{model}' 不支持比例 '{aspect_ratio}'（支持: {', '.join(supported_ratios)}）")

    if errors:
        raise ValueError("; ".join(errors))


class GenericImageGen(ImageGenBase):
    """Generic HTTP-based image generation engine."""

    def __init__(self, iface_id: str):
        self.iface_id = iface_id

    def generate(self, prompt, output_dir, **kwargs):
        _validate_generation_params(self.iface_id, **kwargs)
        mgr = get_imagegen_interface_manager()
        params = mgr.build_request_params(self.iface_id, prompt, output_dir, **kwargs)
        timeout = params.get("timeout", 120)

        try:
            body = params.get("body", {})
            headers = dict(params.get("headers", {}))
            body_type = params.get("body_type", "json")

            # Debug: print request params (omit secret keys from headers)
            _safe_headers = {
                k: ("***" if k.lower() in ("authorization", "api-key", "x-api-key")
                    else v)
                for k, v in headers.items()
            }
            print("=== ImageGen Request ===")
            print(f"URL: {params.get('url')}")
            print(f"Method: {params.get('method', 'POST')}")
            print(f"Headers: {_safe_headers}")
            try:
                print(f"Body: {json.dumps(body, ensure_ascii=False)}")
            except Exception:
                print(f"Body: {body}")
            print("=======================")

            if body_type == "form":
                resp = requests.post(
                    url=params["url"],
                    data={k: str(v) for k, v in body.items() if v is not None},
                    timeout=timeout,
                )
            else:
                resp = requests.post(
                    url=params["url"],
                    headers=headers,
                    json=body,
                    timeout=timeout,
                )

            if resp.status_code != 200:
                print(f"ImageGen request failed: {resp.status_code} {resp.text[:300]}")
                return []

            os.makedirs(output_dir, exist_ok=True)
            saved_files = self._save_response(resp, output_dir)
            return saved_files

        except Exception as e:
            print(f"ImageGen request error: {e}")
            import traceback
            traceback.print_exc()
            return []

    _IMG_MAGIC = (
        (b"\x89PNG\r\n\x1a\n", "png"),
        (b"\xff\xd8\xff", "jpg"),
        (b"RIFF", "webp"),  # 需二次校验 WEBP，见下方
        (b"GIF87a", "gif"),
        (b"GIF89a", "gif"),
    )

    @classmethod
    def _guess_ext_from_bytes(cls, raw: bytes) -> str:
        for magic, ext in cls._IMG_MAGIC:
            if raw[: len(magic)] == magic:
                if ext == "webp" and raw[8:12] != b"WEBP":
                    continue
                return ext
        return "png"

    @staticmethod
    def _collect_items(data: dict):
        """Extract (kind, payload) pairs from a JSON response.

        kind is "url" or "b64"; payload is the url string or base64 string.
        Supports OpenAI style `data[].url|b64_json` and `images[]` nesting.
        """
        items = []
        for key in ("data", "images", "results"):
            arr = data.get(key)
            if not isinstance(arr, list):
                continue
            for item in arr:
                if isinstance(item, str):
                    items.append(("url", item))
                elif isinstance(item, dict):
                    if item.get("url"):
                        items.append(("url", item["url"]))
                    elif item.get("b64_json"):
                        items.append(("b64", item["b64_json"]))
            if items:
                break
        return items

    def _save_response(self, resp, output_dir):
        """Save response images. Supports direct binary, JSON with URLs, or base64."""
        saved = []
        content_type = resp.headers.get("content-type", "")

        # Direct image response
        if "image/" in content_type:
            ext = content_type.split("/")[-1].split(";")[0]
            if ext in ("png", "jpeg", "jpg", "webp", "gif"):
                filepath = os.path.join(output_dir, f"output_0.{ext}")
                with open(filepath, "wb") as f:
                    f.write(resp.content)
                return [filepath]

        # JSON response with URLs or base64
        try:
            data = resp.json()
            items = self._collect_items(data)

            for i, (kind, payload) in enumerate(items):
                try:
                    if kind == "url":
                        img_resp = requests.get(payload, timeout=60)
                        if img_resp.status_code != 200:
                            print(f"Download image {i} failed: HTTP {img_resp.status_code}")
                            continue
                        ext = "png"
                        ct = img_resp.headers.get("content-type", "")
                        if "jpeg" in ct or "jpg" in ct:
                            ext = "jpg"
                        elif "webp" in ct:
                            ext = "webp"
                        raw = img_resp.content
                    else:  # b64_json
                        import base64
                        raw = base64.b64decode(payload)
                        ext = self._guess_ext_from_bytes(raw)

                    filepath = os.path.join(output_dir, f"output_{i}.{ext}")
                    with open(filepath, "wb") as f:
                        f.write(raw)
                    saved.append(filepath)
                except Exception as dl_e:
                    print(f"Save image {i} failed: {dl_e}")

        except ValueError:
            pass

        return saved


class SDKImageGen(ImageGenBase):
    """SDK-based image generation engine that dynamically imports Python modules."""

    def __init__(self, iface_id: str):
        self.iface_id = iface_id

    def generate(self, prompt, output_dir, **kwargs):
        _validate_generation_params(self.iface_id, **kwargs)
        mgr = get_imagegen_interface_manager()
        params = mgr.build_request_params(self.iface_id, prompt, output_dir, **kwargs)

        try:
            pkg_name = params.get("package", "")
            mod_path = params.get("module", "")
            func_name = params.get("function", "generate")
            extra_args = params.get("extra_args", {})

            if mod_path:
                mod = importlib.import_module(mod_path)
            elif pkg_name:
                mod_name = pkg_name.replace("-", "_")
                try:
                    mod = importlib.import_module(mod_name)
                except ImportError:
                    mod = importlib.import_module(pkg_name)
            else:
                print(f"SDK ImageGen: no package/module specified for {self.iface_id}")
                return []

            func = getattr(mod, func_name, None)
            if func is None:
                print(f"SDK ImageGen: function '{func_name}' not found in module '{mod_path or pkg_name}'")
                return []

            call_args = {
                "prompt": prompt,
                "output_dir": output_dir,
                "model": params.get("model", ""),
                "negative_prompt": params.get("negative_prompt", ""),
                "resolution": params.get("resolution", "1K"),
                "aspect_ratio": params.get("aspect_ratio", "1:1"),
                "num_images": params.get("num_images", 1),
                "ref_images": params.get("ref_images", []),
            }
            call_args.update(extra_args)

            import asyncio
            if asyncio.iscoroutinefunction(func):
                result = asyncio.run(func(**call_args))
            else:
                result = func(**call_args)

            # Expect result to be a list of file paths
            if isinstance(result, list):
                return result
            elif result and os.path.exists(str(result)):
                return [str(result)]
            return []

        except Exception as e:
            print(f"SDK ImageGen error: {e}")
            import traceback
            traceback.print_exc()
            return []


# Cache of engine instances
_engines = {}


def get_imagegen_engine(name: str) -> ImageGenBase:
    """Factory function to get or create an image generation engine."""
    global _engines
    if name in _engines:
        return _engines[name]

    mgr = get_imagegen_interface_manager()
    iface = mgr.get(name)

    if not iface:
        print(f"ImageGen engine '{name}' not found")
        return None

    if iface.get("type") == "sdk":
        engine = SDKImageGen(name)
    else:
        engine = GenericImageGen(name)

    _engines[name] = engine
    return engine


def list_imagegen_engines() -> list:
    """List all enabled image generation engine IDs."""
    mgr = get_imagegen_interface_manager()
    return mgr.get_engine_ids()


def clear_cache():
    """Clear engine cache."""
    global _engines
    _engines = {}
