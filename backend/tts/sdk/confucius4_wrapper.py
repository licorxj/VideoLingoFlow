"""Confucius4-TTS 本地 API 封装（sdk 型 TTS 接口）。

调用网易有道开源 Confucius4-TTS 的本地 API 服务（默认端口 8857）。
流程：POST /api/v1/voice/clone 提交克隆任务 → 轮询 GET /api/v1/tasks/{task_id}
→ GET /api/v1/voice/download/{task_id} 下载 WAV 写入 output_path。

仅支持声音克隆（clone / controllable_clone 均走克隆端点），无预置音色与声音设计。
无原生语速参数，变速由 Manager 对参考音频预先变速实现（speed_param 留空）。
"""
import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "http://localhost:8857"


def synthesize(
    text,
    output_path,
    ref_audio=None,
    mode=None,
    speed=None,
    timeout=600,
    api_url=DEFAULT_API_URL,
    lang="zh",
    temperature=0.8,
    top_p=0.8,
    top_k=30,
    num_beams=3,
    repetition_penalty=10.0,
    max_length=1520,
    n_timesteps=25,
    inference_cfg_rate=0.7,
    poll_interval=1.0,
    **kwargs,
):
    """调用 Confucius4-TTS 本地 API 合成语音并写入 output_path。"""
    if not ref_audio or not os.path.exists(ref_audio):
        logger.error(f"Confucius4-TTS clone requires ref_audio, got: {ref_audio}")
        return False

    base_url = (api_url or DEFAULT_API_URL).rstrip("/")
    timeout = float(timeout or 600)

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

        # 3. 下载音频写入 output_path
        audio_resp = requests.get(
            f"{base_url}/api/v1/voice/download/{task_id}", timeout=60
        )
        audio_resp.raise_for_status()
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(audio_resp.content)

        logger.info(
            f"Confucius4-TTS synthesized {len(audio_resp.content)} bytes, "
            f"rtf={status_data.get('rtf')}"
        )
        return os.path.isfile(output_path) and os.path.getsize(output_path) > 0
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Confucius4-TTS service unreachable at {base_url}: {e}")
        return False
    except Exception:
        logger.exception("Confucius4-TTS synthesis failed")
        return False


def list_voices():
    """Confucius4-TTS 仅支持声音克隆，无预置音色。"""
    return []
