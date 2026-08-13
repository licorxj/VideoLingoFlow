"""TTS Interface Manager: load, save, register custom TTS interfaces."""
import os
import json
import uuid
import subprocess
import threading
from typing import Optional, Dict, List, Any

INTERFACES_FILE = os.path.join(
    os.path.dirname(__file__), "..", "config", "tts_interfaces.json"
)
INTERFACES_FILE = os.path.normpath(INTERFACES_FILE)


def _speed_ref_audio(ref_audio: str, speed: float) -> str:
    """对参考音频进行变速处理，返回变速后的文件路径。

    原位保存为 <原文件名>_speed_<speed>.<ext>。
    使用 ffmpeg atempo 滤镜，atempo 范围 0.5~2.0，超出范围自动级联。
    """
    if not ref_audio or not os.path.exists(ref_audio) or abs(speed - 1.0) < 0.01:
        return ref_audio

    base, ext = os.path.splitext(ref_audio)
    out_path = f"{base}_speed_{speed:.2f}{ext}"
    if os.path.exists(out_path):
        return out_path

    # atempo 只支持 0.5~2.0，超出范围需级联多个 atempo
    factors = []
    remaining = speed
    if speed >= 1.0:
        while remaining > 2.0:
            factors.append(2.0)
            remaining /= 2.0
        factors.append(remaining)
    else:
        while remaining < 0.5:
            factors.append(0.5)
            remaining /= 0.5
        factors.append(remaining)

    filter_str = ",".join(f"atempo={f:.4f}" for f in factors)
    cmd = [
        "ffmpeg", "-y", "-i", ref_audio,
        "-filter:a", filter_str,
        "-vn", out_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            # ffmpeg 版本头过滤
            stderr = result.stderr or ""
            lines = stderr.strip().split("\n")
            err_lines = [l.strip() for l in lines if l.strip() and not l.startswith("ffmpeg version") and not l.startswith("  ")]
            raise Exception("; ".join(err_lines[-3:]) if err_lines else stderr[-200:])
        return out_path
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"ref audio speed change failed: {e}, using original")
        return ref_audio


class TTSInterfaceManager:
    """Manages TTS interface definitions loaded from JSON."""

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
                "type": data.get("type", "local"),
                "builtin": False,
                "enabled": data.get("enabled", True),
                "description": data.get("description", ""),
                "api_source_url": data.get("api_source_url", ""),
                "config": data.get("config", self._default_config(data.get("type", "local")))
            }
            self._interfaces[iface_id] = iface
            self._save()
            return iface

    def update(self, iface_id, data):
        with self._lock:
            if iface_id not in self._interfaces:
                return None
            iface = self._interfaces[iface_id]
            for key in ["name", "type", "enabled", "description", "api_source_url"]:
                if key in data:
                    iface[key] = data[key]
            if "config" in data:
                iface["config"] = data["config"]
            self._interfaces[iface_id] = iface
            self._save()
            return iface

    def delete(self, iface_id):
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

    def build_request_params(self, iface_id, text, output_path,
                             ref_audio=None, mode=None, voice_design=None,
                             controllable_clone=None, speed=None, model=None, voice=None,
                             ref_text=None):
        iface = self.get(iface_id)
        if not iface:
            raise ValueError(f"Interface {iface_id} not found")

        # 模式容差：controllable_clone 不可用时降级到 clone
        modes_cfg = iface.get("config", {}).get("modes", {})
        if mode == "controllable_clone" and not modes_cfg.get("controllable_clone", {}).get("enabled"):
            if modes_cfg.get("clone", {}).get("enabled"):
                mode = "clone"

        # Clone mode + 无原生 speed 支持 → 变速参考音频
        if (mode in ("clone", "controllable_clone")) and ref_audio and speed and abs(speed - 1.0) > 0.01:
            iface_cfg = iface.get("config", {})
            has_native_speed = iface_cfg.get("speed_param") or iface_cfg.get("ssml_speed") or iface_cfg.get("speed_hint")
            if not has_native_speed:
                ref_audio = _speed_ref_audio(ref_audio, speed)
                speed = None  # 已通过参考音频变速实现，不再传 speed
        cfg = iface.get("config", {})
        itype = iface.get("type", "local")
        if itype == "online":
            return self._build_online_params(cfg, text, output_path,
                                             ref_audio, mode, voice_design,
                                             controllable_clone, speed, model, voice,
                                             ref_text)
        elif itype == "sdk":
            return self._build_sdk_params(cfg, text, output_path,
                                          ref_audio, mode, voice_design,
                                          controllable_clone, speed, model, voice,
                                          ref_text)
        else:
            return self._build_local_params(cfg, text, output_path, ref_audio,
                                            mode, voice_design, controllable_clone, speed,
                                            ref_text)

    def _resolve_endpoint(self, cfg, mode=None):
        """Resolve the request endpoint from modes config."""
        modes_cfg = cfg.get("modes", {})
        if mode and mode in modes_cfg and modes_cfg[mode].get("enabled"):
            ep = modes_cfg[mode].get("endpoint", "")
            if ep:
                return ep
        # controllable_clone 不可用时降级到 clone
        if mode == "controllable_clone":
            clone_cfg = modes_cfg.get("clone", {})
            if clone_cfg.get("enabled"):
                ep = clone_cfg.get("endpoint", "")
                if ep:
                    return ep
        # Default: use first enabled mode's endpoint
        for m in ["clone", "voice_design", "controllable_clone", "preset_voice"]:
            if m in modes_cfg and modes_cfg[m].get("enabled"):
                ep = modes_cfg[m].get("endpoint", "")
                if ep:
                    return ep
        return ""

    def _build_online_params(self, cfg, text, output_path,
                             ref_audio=None, mode=None, voice_design=None,
                             controllable_clone=None, speed=None, model=None, voice=None,
                             ref_text=None):
        # SSML speed support (for Azure TTS etc.)
        if cfg.get("ssml_speed") and speed is not None and abs(speed - 1.0) > 0.01:
            from backend.tts.tts_factory import _wrap_ssml
            ssml_text = _wrap_ssml(text, speed)
            voice_val = voice or cfg.get("voice", "")
            # Azure: replace voice in SSML
            if voice_val:
                ssml_text = ssml_text.replace(
                    '<prosody',
                    f'<voice name="{voice_val}"><prosody',
                )
                ssml_text = ssml_text.replace('</prosody>', '</prosody></voice>')

            endpoint = self._resolve_endpoint(cfg, mode)
            base_url = cfg.get("api_url", "").rstrip("/")
            url = base_url + endpoint if endpoint else base_url

            headers = {"Content-Type": "application/ssml+xml"}
            api_key = cfg.get("api_key", "")
            if api_key:
                headers["Ocp-Apim-Subscription-Key"] = api_key
            return {"method": "POST", "url": url, "headers": headers, "body": ssml_text, "body_type": "data", "is_file_response": True}

        text_key = cfg.get("text_param", "input")
        body = {
            "model": model or cfg.get("model", "tts-1"),
            text_key: text,
            "voice": voice or cfg.get("voice", "alloy"),
            "response_format": cfg.get("response_format", "wav"),
        }
        spd = cfg.get("speed_param")
        if spd and speed is not None:
            body[spd] = speed

        # Mode-specific params for online APIs
        ref_param = cfg.get("ref_audio_param")
        if ref_param and ref_audio:
            body[ref_param] = ref_audio

        vd_param = cfg.get("voice_design_param")
        if vd_param and voice_design:
            body[vd_param] = voice_design

        cc_param = cfg.get("controllable_clone_param")
        if cc_param and controllable_clone:
            body[cc_param] = controllable_clone

        # 参考音频原文文本（克隆模式下用于辅助合成）
        ref_text_param = cfg.get("ref_text_param")
        if ref_text_param and ref_text:
            body[ref_text_param] = ref_text

        # Resolve endpoint from modes (pass mode to route correctly)
        endpoint = self._resolve_endpoint(cfg, mode)
        base_url = cfg.get("api_url", "").rstrip("/")
        url = base_url + endpoint if endpoint else base_url

        headers = {"Content-Type": "application/json"}
        api_key = cfg.get("api_key", "")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # Custom params
        for cp in cfg.get("custom_params", []):
            key = cp.get("key", "")
            default = cp.get("default", "")
            if key and key not in body:
                body[key] = default

        return {"method": "POST", "url": url, "headers": headers, "body": body, "body_type": "json", "is_file_response": True}

    def _build_sdk_params(self, cfg, text, output_path,
                          ref_audio=None, mode=None, voice_design=None,
                          controllable_clone=None, speed=None, model=None, voice=None,
                          ref_text=None):
        call_args = {
            "type": "sdk",
            "package": cfg.get("sdk_package", ""),
            "module": cfg.get("sdk_module", ""),
            "function": cfg.get("sdk_function", "synthesize"),
            "text": text,
            "output_path": output_path,
            "ref_audio": ref_audio,
            "ref_text": ref_text,
            "speed": speed,
            "model": model or cfg.get("model", ""),
            "voice": voice or cfg.get("voice", ""),
            "mode": mode,
            "voice_design": voice_design,
            "controllable_clone": controllable_clone,
            "timeout": cfg.get("timeout", 120),
            "extra_args": {**cfg.get("sdk_extra_args", {}), **({"api_key": cfg["sdk_api_key"]} if cfg.get("sdk_api_key") else {})},
        }
        return call_args

    def _build_local_params(self, cfg, text, output_path, ref_audio=None, mode=None, voice_design=None, controllable_clone=None, speed=None, ref_text=None):
        endpoint = self._resolve_endpoint(cfg, mode)
        base_url = cfg.get("api_url", "http://localhost:8080").rstrip("/")
        url = base_url + (endpoint if endpoint else "/")

        text_key = cfg.get("text_param", "text")
        body = {text_key: text}

        # Always send output_path for local APIs to save directly
        if output_path:
            output_param = cfg.get("output_path_param", "output_path")
            body[output_param] = output_path

        ref_param = cfg.get("ref_audio_param")
        if ref_param and ref_audio:
            body[ref_param] = ref_audio

        vd_param = cfg.get("voice_design_param")
        if vd_param and voice_design:
            body[vd_param] = voice_design

        cc_param = cfg.get("controllable_clone_param")
        if cc_param and controllable_clone:
            body[cc_param] = controllable_clone

        # 参考音频原文文本（克隆模式下用于辅助合成）
        ref_text_param = cfg.get("ref_text_param")
        if ref_text_param and ref_text:
            body[ref_text_param] = ref_text

        spd = cfg.get("speed_param")
        if spd and speed is not None:
            body[spd] = speed

        for cp in cfg.get("custom_params", []):
            key = cp.get("key", "")
            default = cp.get("default", "")
            if key and key not in body:
                body[key] = default

        body_type = cfg.get("body_type", "json")
        content_type = "multipart/form-data" if body_type == "form" else "application/json"
        timeout = cfg.get("timeout", 120)
        is_async = cfg.get("is_async", False)
        return {"method": "POST", "url": url, "headers": {"Content-Type": content_type}, "body": body, "body_type": body_type, "is_file_response": not is_async, "is_async": is_async, "timeout": timeout}

    @staticmethod
    def _default_config(itype):
        _modes = {
            "clone": {"enabled": False, "endpoint": ""},
            "voice_design": {"enabled": False, "endpoint": ""},
            "controllable_clone": {"enabled": False, "endpoint": ""},
            "preset_voice": {"enabled": False, "endpoint": ""},
        }
        if itype == "online":
            return {
                "api_url": "", "api_key": "", "model": "tts-1", "voice": "alloy",
                "response_format": "wav", "text_param": "input", "speed_param": "speed",
                "modes": {k: dict(v) for k, v in _modes.items()},
                "model_list_url": "", "voice_list_url": "",
                "model_list_key": "", "voice_list_key": "",
                "model_options": [], "voice_options": [],
                "max_concurrent": 1,
                "timeout": 120,
                "custom_params": [],
            }
        elif itype == "sdk":
            return {
                "sdk_package": "", "sdk_module": "", "sdk_function": "synthesize",
                "text_param": "text", "ref_audio_param": None, "speed_param": None,
                "modes": {k: dict(v) for k, v in _modes.items()},
                "model": "", "voice": "",
                "model_list_url": "", "voice_list_url": "",
                "model_list_key": "", "voice_list_key": "",
                "model_options": [], "voice_options": [],
                "sdk_extra_args": {},
                "max_concurrent": 1,
                "timeout": 120,
                "custom_params": [],
            }
        else:
            return {
                "api_url": "", "text_param": "text", "ref_audio_param": None,
                "modes": {k: dict(v) for k, v in _modes.items()},
                "voice_design_param": None, "controllable_clone_param": None,
                "speed_param": None,
                "model_options": [], "voice_options": [],
                "max_concurrent": 1,
                "timeout": 120,
                "startup_script": "",
                "custom_params": [],
            }


_manager = None

def get_tts_interface_manager():
    global _manager
    if _manager is None:
        _manager = TTSInterfaceManager()
    return _manager
