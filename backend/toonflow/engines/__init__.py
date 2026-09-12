# -*- coding: utf-8 -*-
"""AI 能力适配层 —— 对齐 Toonflow `Ai` 门面（utils/ai.ts），但直连本项目引擎工厂。

    from backend.toonflow.engines import Ai
    Ai.image({"prompt": "...", "referenceList": [...], "size": "2K", "aspectRatio": "16:9"})
    Ai.video({"prompt": "...", "referenceList": [first, last], "duration": 5, "audio": True})
    Ai.audio({"text": "...", "mode": "voice_design", "voiceDesign": "..."})
    Ai.music({"prompt": "轻快古风 BGM"})
    Ai.text.invoke(prompt, system=..., json_mode=...) / Ai.text.stream(...)
    Ai.imaging.zip_image(...) / Ai.imaging.merge_images(...)

源 vendor 契约的 base64 返回经 EngineOutput.to_base64() 兼容；本项目侧一律以落盘路径为主。
"""
from backend.toonflow.engines import audio, image, imaging, music, text, video  # noqa: F401


class _Ai:
    text = text
    image = image
    video = video
    audio = audio
    music = music
    imaging = imaging


Ai = _Ai()
