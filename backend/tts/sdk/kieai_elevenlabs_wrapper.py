#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KIE AI（ElevenLabs）TTS SDK wrapper —— 供 TTS 工厂的 SDKTTS 引擎调用。

对应 catalog 模型 ``elevenlabs/text-to-speech-turbo-2-5``（market 风格：
``createTask`` 提交 + ``recordInfo`` 轮询，结果在 ``resultJson.resultUrls``）。

契约（见 ``backend/tts/tts_factory.SDKTTS``）：
    synthesize(text, output_path, voice=None, model=None, speed=None, **kwargs)
    -> 把音频写入 output_path；工厂以 os.path.exists(output_path) 判定成功。

``model`` 在此处即 catalog 模型 id（可在接口配置中切换为其它 elevenlabs TTS 模型），
``voice`` 为 ElevenLabs 音色 id（可选，留空则使用平台默认音色）。
"""
import os
import asyncio
import logging

from backend.kieai_sdk.kieai import KieClient

logger = logging.getLogger(__name__)

# 云端 API，不占本地 GPU（与 ASR 的 CLOUD 标记一致）
CLOUD = True

# 默认模型（接口默认 turbo-2-5；可在接口配置中覆盖）
DEFAULT_MODEL = "elevenlabs/text-to-speech-turbo-2-5"

# 可选高级参数：模型声明时才下发，留空则使用平台默认值
_OPTIONAL_PARAMS = (
    "stability", "similarity_boost", "style", "speed",
    "timestamps", "previous_text", "next_text", "language_code",
)


def _run_async(coro):
    """在同步上下文驱动协程；调用方已有运行中的事件循环时交由独立线程执行。

    不使用 asyncio.get_event_loop()：Python 3.12 在无当前事件循环的线程中会抛
    RuntimeError 且该用法已废弃，这里改用 get_running_loop() 判断。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def _synthesize_async(text, output_path, voice=None, model=None,
                            speed=None, **kwargs):
    api_key = kwargs.get("api_key") or None
    model_id = model or kwargs.get("model_id") or DEFAULT_MODEL
    poll_timeout = int(kwargs.get("poll_timeout") or kwargs.get("timeout") or 600)

    params = {"text": text}
    if voice:
        params["voice"] = voice
    if speed is not None:
        try:
            params["speed"] = float(speed)
        except (TypeError, ValueError):
            logger.warning("KIE TTS: 忽略非法 speed 值 %r", speed)

    for key in _OPTIONAL_PARAMS:
        if key in params:
            continue
        val = kwargs.get(key)
        if val is not None and val != "":
            params[key] = val

    # output_path 带扩展名，SDK 会按「文件路径」处理并精确写入该路径
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

    async with KieClient(api_key=api_key) as client:
        try:
            entry = client.catalog.get(model_id)
        except Exception as e:  # noqa: BLE001
            logger.error("KIE TTS: 模型未找到 %s (%s)", model_id, e)
            return False

        # 仅下发模型实际声明的参数，避免 unsupported field 类报错
        pnames = {p.name for p in entry.params}
        dropped = [k for k in params if k not in pnames]
        if dropped:
            logger.warning("KIE TTS: 模型 %s 不支持参数 %s，已忽略", model_id, dropped)
        params = {k: v for k, v in params.items() if k in pnames}

        client.max_poll = max(1, int(poll_timeout / max(client.poll_interval, 0.1)))

        try:
            result = await client.generate(model_id, output_path=output_path, **params)
        except Exception as e:  # noqa: BLE001
            logger.error("KIE TTS: 合成失败: %s", e)
            import traceback
            traceback.print_exc()
            return False

    paths = result.get("local_paths") or []
    if not paths:
        logger.error("KIE TTS: 接口未返回任何音频产物")
        return False

    logger.info("KIE TTS: 合成完成 -> %s", paths[0])
    return True


def synthesize(text, output_path, voice=None, model=None, speed=None, **kwargs):
    """合成语音并写入 output_path，成功返回 True。"""
    if not text:
        logger.error("KIE TTS: 待合成文本为空")
        return False
    return bool(_run_async(_synthesize_async(
        text, output_path, voice=voice, model=model, speed=speed, **kwargs
    )))


def list_voices(api_key=None):
    """返回该模型支持的音色列表。

    KIE 未提供音色名称查询接口，故 voice_name 直接使用音色 id。
    """
    try:
        client = KieClient(api_key=api_key or None)
        entry = client.catalog.get(DEFAULT_MODEL)
    except Exception as e:  # noqa: BLE001
        logger.warning("KIE TTS: 读取音色列表失败: %s", e)
        return []

    for p in entry.params:
        if p.name == "voice" and p.enum:
            return [
                {
                    "voice_id": v,
                    "voice_name": v,
                    "description": "",
                    "gender": "",
                    "age": "",
                    "language": "",
                }
                for v in p.enum
            ]
    return []
