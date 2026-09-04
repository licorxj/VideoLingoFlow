"""Confucius4-TTS 本地 API 封装（sdk 型 TTS 接口）。

调用网易有道开源 Confucius4-TTS 的本地 API 服务（默认端口 8857）。
流程：POST /api/v1/voice/clone 提交克隆任务 → 轮询 GET /api/v1/tasks/{task_id}
→ GET /api/v1/voice/download/{task_id} 下载 WAV 写入 output_path。

仅支持声音克隆（clone / controllable_clone 均走克隆端点），无预置音色与声音设计。
无原生语速参数，变速由 Manager 对参考音频预先变速实现（speed_param 留空）。

参数取值优先级（由高到低）：
    1. 调用 synthesize 时显式传入的参数
    2. 配置文件 backend/config/tts_interfaces.json 中 confucius4_tts 接口的设置
       （优先 sdk_extra_args，其次 custom_params 的 default）
    3. 本文件中的硬编码兜底默认值 _HARDCODED_DEFAULTS
"""
import json
import logging
import os
import time

import requests
from backend.tts.tts_interface_manager import finalize_tts_output

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "http://localhost:8857"

# 各采样/接口参数的代码内硬编码兜底默认值。
# 配置文件 tts_interfaces.json 中 confucius4_tts 接口的设置值会覆盖这些默认值。
_HARDCODED_DEFAULTS = {
    "api_url": DEFAULT_API_URL,
    "lang": "zh",
    "temperature": 0.8,
    "top_p": 0.8,
    "top_k": 30,
    "num_beams": 3,
    "repetition_penalty": 10.0,
    "max_length": 1520,
    "n_timesteps": 25,
    "inference_cfg_rate": 0.7,
    "poll_interval": 1.0,
}

# 按接口 id 缓存从配置文件解析出的覆盖值，避免每次调用重复读取磁盘。
_CONFIG_CACHE = {}

# 可被配置文件覆盖的参数名（与配置中 sdk_extra_args / custom_params 的 key 一致）。
_CONFIGURABLE_KEYS = tuple(_HARDCODED_DEFAULTS.keys())


def _coerce(value):
    """将配置文件中的字符串默认值尽量转换为数值类型，失败则原样返回。"""
    if isinstance(value, (int, float, bool)):
        return value
    if not isinstance(value, str) or value == "":
        return value
    try:
        if "." in value or "e" in value.lower():
            return float(value)
        return int(value)
    except (ValueError, TypeError):
        return value


def _load_confucius4_config():
    """读取 tts_interfaces.json 中 confucius4_tts 接口的配置。

    返回一个 dict：key 为参数名，value 为配置文件中的设置值（已尽量转为正确类型）。
    优先使用 sdk_extra_args（JSON 中已为正确类型），custom_params 的字符串 default 作为补充。
    """
    cached = _CONFIG_CACHE.get("confucius4_tts")
    if cached is not None:
        return cached

    values = {}
    cfg_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "config", "tts_interfaces.json")
    )
    try:
        with open(cfg_path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        for iface in data.get("interfaces", []):
            if iface.get("id") == "confucius4_tts":
                cfg = iface.get("config", {})
                # 1) sdk_extra_args 中的值优先使用
                values.update(cfg.get("sdk_extra_args", {}))
                # 2) custom_params 的字符串 default 作为补充（不覆盖 sdk_extra_args）
                for cp in cfg.get("custom_params", []):
                    key = cp.get("key")
                    if not key or key in values:
                        continue
                    dv = cp.get("default", "")
                    if dv in (None, ""):
                        continue
                    values[key] = _coerce(dv)
                break
    except Exception as e:
        logger.warning(f"Confucius4-TTS: failed to load config overrides: {e}")

    _CONFIG_CACHE["confucius4_tts"] = values
    return values


def _resolve(key, arg):
    """解析单个参数的最终取值：显式传入 > 配置文件设置 > 硬编码默认值。"""
    if arg is not None:
        return arg
    cfg = _load_confucius4_config()
    cfg_val = cfg.get(key)
    if cfg_val not in (None, ""):
        return cfg_val
    return _HARDCODED_DEFAULTS.get(key)


def synthesize(
    text,
    output_path,
    ref_audio=None,
    mode=None,
    speed=None,
    timeout=600,
    api_url=None,
    lang=None,
    temperature=None,
    top_p=None,
    top_k=None,
    num_beams=None,
    repetition_penalty=None,
    max_length=None,
    n_timesteps=None,
    inference_cfg_rate=None,
    poll_interval=None,
    **kwargs,
):
    """调用 Confucius4-TTS 本地 API 合成语音并写入 output_path。

    参数取值优先级：调用时显式传入 > 配置文件 tts_interfaces.json 中
    confucius4_tts 接口的设置（sdk_extra_args / custom_params）> 代码内硬编码默认值。
    """
    if not ref_audio or not os.path.exists(ref_audio):
        logger.error(f"Confucius4-TTS clone requires ref_audio, got: {ref_audio}")
        return False

    # 配置文件设置值覆盖硬编码默认值（显式传入的参数优先级最高）
    api_url = _resolve("api_url", api_url) or DEFAULT_API_URL
    lang = _resolve("lang", lang)
    temperature = _resolve("temperature", temperature)
    top_p = _resolve("top_p", top_p)
    top_k = _resolve("top_k", top_k)
    num_beams = _resolve("num_beams", num_beams)
    repetition_penalty = _resolve("repetition_penalty", repetition_penalty)
    max_length = _resolve("max_length", max_length)
    n_timesteps = _resolve("n_timesteps", n_timesteps)
    inference_cfg_rate = _resolve("inference_cfg_rate", inference_cfg_rate)
    poll_interval = _resolve("poll_interval", poll_interval)
    timeout = float(timeout or 600)

    base_url = api_url.rstrip("/")

    try:
        # 1. 提交声音克隆任务（Form 表单，本地路径模式）
        form = {
            "text": text,
            "ref_audio_path": ref_audio,
            "lang": lang or "zh",
            "temperature": float(temperature),
            "top_p": float(top_p),
            "top_k": int(top_k),
            "num_beams": int(num_beams),
            "repetition_penalty": float(repetition_penalty),
            "max_length": int(max_length),
            "n_timesteps": int(n_timesteps),
            "inference_cfg_rate": float(inference_cfg_rate),
        }
        resp = requests.post(f"{base_url}/api/v1/voice/clone", data=form, timeout=30)
        resp.raise_for_status()
        task_id = resp.json().get("task_id")
        if not task_id:
            logger.error(f"Confucius4-TTS: no task_id in response: {resp.text[:200]}")
            return False

        # 2. 轮询任务状态直到完成/失败
        deadline = time.monotonic() + timeout
        status_data = {}
        while time.monotonic() < deadline:
            status_resp = requests.get(f"{base_url}/api/v1/tasks/{task_id}", timeout=15)
            status_resp.raise_for_status()
            status_data = status_resp.json()
            status = status_data.get("status")
            if status == "completed":
                break
            if status == "failed":
                logger.error(f"Confucius4-TTS task failed: {status_data.get('message', '')}")
                return False
            time.sleep(max(0.2, float(poll_interval)))
        else:
            logger.error(f"Confucius4-TTS: timeout after {timeout}s waiting for task {task_id}")
            return False

        # 3. 下载音频写入 output_path（统一落盘助手：HTTP 下载兜底）
        download_url = f"{base_url}/api/v1/voice/download/{task_id}"
        ok = finalize_tts_output(output_path, download_url=download_url, timeout=timeout)
        if ok:
            logger.info(
                f"Confucius4-TTS synthesized to {output_path}, "
                f"rtf={status_data.get('rtf')}"
            )
        return ok
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Confucius4-TTS service unreachable at {base_url}: {e}")
        return False
    except Exception:
        logger.exception("Confucius4-TTS synthesis failed")
        return False


def list_voices():
    """Confucius4-TTS 仅支持声音克隆，无预置音色。"""
    return []
