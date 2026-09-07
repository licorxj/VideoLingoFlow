#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kieai — async Python SDK for the kie.ai API (image / video / music / upload).

All generation calls are asynchronous: submit a task, then poll for the result.
No callback URLs are used.

Quick start
-----------
    from kieai import KieClient, Catalog

    async def main():
        async with KieClient(api_key="YOUR_KEY") as client:
            # image (Market unified endpoint)
            img = await client.generate(
                "bytedance/seedream-v4-text-to-image",
                prompt="a calm lake at dawn", image_size="landscape_16_9")
            # video (Veo 3.1)
            vid = await client.generate(
                "generate-veo-3-video", model="veo3_fast", prompt="a dog playing")
            # music (Suno)
            song = await client.generate(
                "generate-music", model="V4_5", prompt="lofi beat", customMode=False)
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
    "KieError",
    "KieModelNotFound",
    "KieRequestError",
    "KieTaskFailed",
    "KieTimeout",
]

__version__ = "0.1.0"
