#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Basic usage examples for the kie.ai async SDK.

Run with:  python examples/basic_usage.py

The API key is resolved automatically (caller -> secret://KIEAI_API_KEY ->
KIEAI_API_KEY env var). You can also pass it explicitly:
    api_key = os.environ.get("KIEAI_API_KEY")
    KieClient(api_key=api_key)
"""

import asyncio

from kieai import KieClient


async def main():
    # api_key is optional; falls back to secret://KIEAI_API_KEY then $KIEAI_API_KEY
    async with KieClient() as client:

        # ---- 1. Image generation (Market unified endpoint) ---------------
        image = await client.generate(
            "bytedance/seedream-v4-text-to-image",
            prompt="a calm lake at dawn, photorealistic",
            image_size="landscape_16_9",
        )
        print("IMAGE result:", image)

        # ---- 2. Video generation (Veo 3.1) --------------------------------
        video = await client.generate(
            "generate-veo3-1-video",          # family "veo3"
            model="veo3_fast",                # veo3 / veo3_fast / veo3_lite
            prompt="a golden retriever running on a beach",
        )
        print("VIDEO result:", video)

        # ---- 3. Music generation (Suno) -----------------------------------
        music = await client.generate(
            "generate-music",                 # family "suno"
            model="V4_5",
            prompt="a relaxing lo-fi beat",
            customMode=False,
            instrumental=False,
        )
        print("MUSIC result:", music)

        # ---- 4. File upload (synchronous, returns URL) -------------------
        upload = await client.upload(
            method="url",                     # url / stream / base64
            fileUrl="https://example.com/sample.jpg",
            uploadPath="images",
            fileName="sample.jpg",
        )
        print("UPLOAD result:", upload)

        # ---- 5. Submit + poll manually (for long tasks) ------------------
        task = await client.submit(
            "generate-veo3-1-video", model="veo3_fast", prompt="city timelapse"
        )
        print("submitted task:", task.task_id)
        result = await task.wait(poll_interval=5, max_poll=60)
        print("polled result:", result)


if __name__ == "__main__":
    asyncio.run(main())
