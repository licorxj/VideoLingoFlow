"""TTS factory: creates TTS engine instances based on registered interfaces."""
import requests
import os
import importlib
import socket
import subprocess
import time
import urllib.parse
from typing import Optional
from backend.tts.tts_base import TTSBase
from backend.tts.tts_interface_manager import get_tts_interface_manager


def _speed_to_ssml_rate(speed: float) -> str:
    """将语速数值转换为 SSML prosody rate 百分比字符串。

    speed=1.0 → "0%", speed=0.9 → "-10%", speed=1.2 → "+20%"
    """
    pct = round((speed - 1.0) * 100)
    return f"{pct}%" if pct >= 0 else f"{pct}%"


def _wrap_ssml(text: str, speed: float = None) -> str:
    """用 SSML prosody 包装文本以控制语速。"""
    if speed is None or abs(speed - 1.0) < 0.01:
        return text
    rate = _speed_to_ssml_rate(speed)
    return (
        '<speak xmlns="http://www.w3.org/2001/10/synthesis"'
        ' xmlns:mstts="http://www.w3.org/2001/mstts">'
        f'<prosody rate="{rate}">{text}</prosody></speak>'
    )



def _check_port(host, port, timeout=1):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def _wait_for_port(host, port, interval=5, max_wait=120):
    elapsed = 0
    while elapsed < max_wait:
        if _check_port(host, port):
            return True
        time.sleep(interval)
        elapsed += interval
    return False


def _start_service(script_path):
    if not script_path or not os.path.exists(script_path):
        return False
    script_dir = os.path.dirname(os.path.abspath(script_path))
    try:
        subprocess.Popen(
            ["python", script_path],
            cwd=script_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        return True
    except Exception as e:
        print(f"Failed to start TTS service: {e}")
        return False


class GenericTTS(TTSBase):
    """Generic TTS engine that uses registered interface config to make HTTP requests."""

    def __init__(self, iface_id: str):
        self.iface_id = iface_id

    def synthesize(self, text: str, output_path: str,
                   ref_audio: str = None, mode: str = None,
                   voice_design: str = None, controllable_clone: str = None,
                   speed: float = None, model: str = None, voice: str = None,
                   ref_text: str = None) -> bool:
        mgr = get_tts_interface_manager()
        iface = mgr.get(self.iface_id)
        if not iface or not iface.get("enabled"):
            return False

        params = mgr.build_request_params(
            self.iface_id, text, output_path,
            ref_audio=ref_audio, mode=mode,
            voice_design=voice_design,
            controllable_clone=controllable_clone,
            speed=speed, model=model, voice=voice,
            ref_text=ref_text,
        )

        timeout = params.get("timeout", 120)

        # Auto-start local service if port is not listening
        api_url = params.get("url", "")
        import re as _re
        m = _re.match(r'(https?)://([^:/]+):(\d+)', api_url)
        if m:
            host, port = m.group(2), int(m.group(3))
            if not _check_port(host, port):
                cfg = iface.get("config", {})
                startup = cfg.get("startup_script", "")
                if startup:
                    print(f"Auto-starting TTS service for {self.iface_id} via {startup}")
                    _start_service(startup)
                    if not _wait_for_port(host, port, max_wait=cfg.get("timeout", 120)):
                        print(f"Failed to start TTS service: port {port} not listening after wait")
                        return False
                else:
                    print(f"TTS service not running on {host}:{port} and no startup_script configured")
                    return False

        try:
            body = params.get("body", {})
            headers = dict(params.get("headers", {}))

            if params.get("body_type") == "form":
                form_fields = {k: str(v) for k, v in body.items() if v is not None}
                resp = requests.post(
                    url=params["url"],
                    data=form_fields,
                    timeout=timeout,
                )
            else:
                resp = requests.request(
                    method=params["method"],
                    url=params["url"],
                    headers=headers,
                    json=params.get("body") if params.get("body_type") == "json" else None,
                    data=params.get("body") if params.get("body_type") != "json" else None,
                    timeout=timeout,
                )

            if resp.status_code != 200:
                print(f"TTS request failed: {resp.status_code} {resp.text[:300]}")
                return False

            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # Handle async task-based APIs (OmniVoice, VoxCPM, etc.)
            if params.get("is_async"):
                return self._poll_async_task(resp, params, output_path, timeout)

            # Direct file response
            if params.get("is_file_response", True):
                with open(output_path, "wb") as fp:
                    fp.write(resp.content)
                return True

            # JSON response with audio_url
            resp_json = resp.json()
            if "audio_url" in resp_json:
                audio_resp = requests.get(resp_json["audio_url"], timeout=timeout)
                if audio_resp.status_code == 200:
                    with open(output_path, "wb") as fp:
                        fp.write(audio_resp.content)
                    return True
                print(f"Download audio failed: {audio_resp.status_code}")
                return False

            with open(output_path, "wb") as fp:
                fp.write(resp.content)
            return True

        except Exception as e:
            print(f"TTS request error: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _poll_async_task(self, init_resp, params, output_path, timeout):
        """For async TTS APIs (e.g. OmniVoice): poll task status then use local output_path."""
        import shutil
        try:
            resp_json = init_resp.json()
            task_id = resp_json.get("task_id")
            if not task_id:
                print(f"Async TTS: no task_id in response: {resp_json}")
                return False

            api_url = params.get("url", "")
            import re
            base_match = re.match(r'(https?://[^/]+)', api_url)
            base = base_match.group(1) if base_match else api_url

            status_url = f"{base}/api/v1/tasks/{task_id}"
            download_url = f"{base}/api/v1/voice/download/{task_id}"

            print(f"Async TTS: task {task_id} created, polling {status_url}")
            poll_interval = 2
            elapsed = 0
            while elapsed < timeout:
                time.sleep(poll_interval)
                elapsed += poll_interval
                try:
                    status_resp = requests.get(status_url, timeout=10)
                    if status_resp.status_code != 200:
                        continue
                    status_data = status_resp.json()
                    status = status_data.get("status", "")
                    if status == "completed":
                        # Priority 1: File was saved directly to output_path by the local API
                        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                            print(f"Async TTS: task completed, audio saved directly at {output_path}")
                            return True
                        # Priority 2: API returned an output_path in status response
                        remote_path = status_data.get("output_path")
                        if remote_path and os.path.exists(remote_path):
                            print(f"Async TTS: task completed, copying from {remote_path}")
                            shutil.copy2(remote_path, output_path)
                            return True
                        # Priority 3: Download via HTTP (fallback)
                        print(f"Async TTS: task completed, downloading from {download_url}")
                        dl_resp = requests.get(download_url, timeout=timeout)
                        if dl_resp.status_code == 200:
                            os.makedirs(os.path.dirname(output_path), exist_ok=True)
                            with open(output_path, "wb") as fp:
                                fp.write(dl_resp.content)
                            return True
                        print(f"Download failed: {dl_resp.status_code} {dl_resp.text[:200]}")
                        return False
                    elif status == "failed":
                        print(f"Async TTS: task failed: {status_data.get('message', '')}")
                        return False
                except Exception as pe:
                    print(f"Poll error: {pe}")
                    continue

            print(f"Async TTS: timeout after {timeout}s waiting for task {task_id}")
            return False
        except Exception as e:
            print(f"Async TTS poll error: {e}")
            return False


class EdgeTTSDirect(TTSBase):
    """Direct Edge TTS without HTTP request (for backward compatibility)."""

    def synthesize(self, text: str, output_path: str, **kwargs) -> bool:
        from backend.config.config_manager import config
        voice = kwargs.get("voice") or config.get("tts.edge_tts.voice") or "zh-CN-YunjianNeural"
        try:
            import asyncio
            import edge_tts
            communicate = edge_tts.Communicate(text, voice)
            asyncio.run(communicate.save(output_path))
            return True
        except ImportError:
            from pydub import AudioSegment
            silence = AudioSegment.silent(duration=max(100, len(text) * 50))
            silence.export(output_path, format="wav")
            return True
        except Exception as e:
            print(f"EdgeTTS error: {e}")
            return False


class SDKTTS(TTSBase):
    """SDK-based TTS engine that dynamically imports and calls a Python package function."""

    def __init__(self, iface_id: str):
        self.iface_id = iface_id

    def synthesize(self, text: str, output_path: str,
                   ref_audio: str = None, mode: str = None,
                   voice_design: str = None, controllable_clone: str = None,
                   speed: float = None, model: str = None, voice: str = None,
                   ref_text: str = None) -> bool:
        mgr = get_tts_interface_manager()
        iface = mgr.get(self.iface_id)
        if not iface or not iface.get("enabled"):
            return False

        params = mgr.build_request_params(
            self.iface_id, text, output_path,
            ref_audio=ref_audio, mode=mode,
            voice_design=voice_design,
            controllable_clone=controllable_clone,
            speed=speed, model=model, voice=voice,
            ref_text=ref_text,
        )

        try:
            pkg_name = params.get("package", "")
            mod_path = params.get("module", "")
            func_name = params.get("function", "synthesize")
            extra_args = params.get("extra_args", {})
            sdk_voice = params.get("voice", "")
            sdk_model = params.get("model", "")

            if mod_path:
                mod = importlib.import_module(mod_path)
            elif pkg_name:
                mod_name = pkg_name.replace("-", "_")
                try:
                    mod = importlib.import_module(mod_name)
                except ImportError:
                    mod = importlib.import_module(pkg_name)
            else:
                print(f"SDK TTS: no package/module specified for {self.iface_id}")
                return False

            func = getattr(mod, func_name, None)
            if func is None:
                print(f"SDK TTS: function '{func_name}' not found in module '{mod_path or pkg_name}'")
                return False

            # Special handling for edge-tts
            if pkg_name == "edge-tts":
                return self._call_edge_tts(mod, text, output_path, sdk_voice or extra_args.get("voice", "zh-CN-YunjianNeural"), speed)

            # Generic SDK call
            call_args = {"text": text, "output_path": output_path}
            if sdk_voice:
                call_args["voice"] = sdk_voice
            if sdk_model:
                call_args["model"] = sdk_model
            if ref_audio:
                call_args["ref_audio"] = ref_audio
            if ref_text:
                call_args["ref_text"] = ref_text
            if speed is not None:
                call_args["speed"] = speed
            if mode:
                call_args["mode"] = mode
            if voice_design:
                call_args["voice_design"] = voice_design
            if controllable_clone:
                call_args["controllable_clone"] = controllable_clone
            if params.get("timeout"):
                call_args["timeout"] = params["timeout"]
            call_args.update(extra_args)

            import asyncio
            if asyncio.iscoroutinefunction(func):
                asyncio.run(func(**call_args))
            else:
                func(**call_args)
            return os.path.exists(output_path)

        except Exception as e:
            print(f"SDK TTS error: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _call_edge_tts(self, mod, text, output_path, voice, speed=None):
        import asyncio
        ssml_text = _wrap_ssml(text, speed)
        communicate = mod.Communicate(ssml_text, voice)
        asyncio.run(communicate.save(output_path))
        return os.path.exists(output_path)


# Cache of engine instances
_engines = {}


def get_tts_engine(name: str) -> TTSBase:
    global _engines
    if name in _engines:
        return _engines[name]

    mgr = get_tts_interface_manager()
    iface = mgr.get(name)

    if not iface:
        engine = EdgeTTSDirect()
    elif name == "edge_tts":
        engine = EdgeTTSDirect()
    elif iface.get("type") == "sdk":
        engine = SDKTTS(name)
    else:
        engine = GenericTTS(name)

    _engines[name] = engine
    return engine


def list_tts_engines() -> list:
    mgr = get_tts_interface_manager()
    return mgr.get_engine_ids()


def clear_cache():
    global _engines
    _engines = {}
