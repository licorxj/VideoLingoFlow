#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kieai — async Python SDK for the kie.ai API (image / video / music / upload).

All generation calls are asynchronous: submit a task, then poll for the result.
No callback URLs are used.

Quick start
-----------
    from kieai import KieClient, Catalog

    async def main():
        # api_key is optional; falls back to secret://KIEAI_API_KEY then $KIEAI_API_KEY
        async with KieClient() as client:
            # image (Market unified endpoint)
            img = await client.generate(
                "bytedance/seedream-v4-text-to-image",
                prompt="a calm lake at dawn", image_size="landscape_16_9")
            # video (Veo 3.1)
            vid = await client.generate(
                "generate-veo-3-video", model="veo3_fast", prompt="a dog playing")
            # music (Suno) — prefer the dedicated SunoMusicClient for chaining
            from .suno import SunoMusicClient
            async with SunoMusicClient() as music:
                task = await music.generate(custom_mode=False,
                                            instrumental=False, model="V6",
                                            prompt="lofi beat")
                print("music taskId:", task["taskId"])
            # file upload
            up = await client.upload(method="url", fileUrl="https://x/y.jpg")

        # inspect the catalog
        cat = Catalog.load()
        for m in cat.search(category="video", family="veo3"):
            print(m.id, m.endpoint)
"""

from .client import KieClient, Task
from .exceptions import (
    KieError,
    KieModelNotFound,
    KieRequestError,
    KieTaskFailed,
    KieTimeout,
)
from .models import Catalog, ModelEntry, Param
from .pricing import KiePricing, PriceRecord, fetch_prices, find_records
from .suno import (
    CREATE_TASK_URL,
    RECORD_INFO_URL,
    SUNO_OPERATIONS,
    SunoMusicClient,
    validate_params,
)

__all__ = [
    "KieClient",
    "Task",
    "Catalog",
    "ModelEntry",
    "Param",
    "KiePricing",
    "PriceRecord",
    "fetch_prices",
    "find_records",
    "SunoMusicClient",
    "SUNO_OPERATIONS",
    "validate_params",
    "CREATE_TASK_URL",
    "RECORD_INFO_URL",
    "KieError",
    "KieModelNotFound",
    "KieRequestError",
    "KieTaskFailed",
    "KieTimeout",
]

__version__ = "0.1.0"
