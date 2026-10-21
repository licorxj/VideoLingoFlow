#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Suno 音乐 API 串联示例（与 kie.ai/suno-api 官网标签页一一对应）。

Run with:  python examples/music_chains.py

每个提交类端点完成后都返回 ``taskId``，下游节点用该 ID（或音轨 audio_id /
persona_id）继续串联。API key 自动解析：实参 -> secret://KIEAI_API_KEY ->
KIEAI_API_KEY 环境变量。
"""

import asyncio

from kieai import SunoMusicClient


async def chain_generate_extend():
    """生成 → 轮询取音轨 → 续写扩展 → 转 WAV。"""
    async with SunoMusicClient() as music:
        # 1. Generate：提交后立即拿到 taskId
        sub = await music.generate(
            custom_mode=False, instrumental=False, model="V6",
            prompt="An upbeat acoustic song about a summer road trip",
        )
        task_id = sub["taskId"]
        print("[generate] taskId =", task_id)

        # 2. 轮询直到完成，取第一条音轨的 audio_id（供所有下游节点串联）
        done = await music.wait(task_id, poll_interval=5, max_poll=100)
        track = done["tracks"][0]
        audio_id = track["id"]
        print("[generate] audio_id =", audio_id, "url =", track["audio_url"])

        # 3. Extend：从第 60 秒续写（同样返回新 taskId）
        ext = await music.extend(audio_id=audio_id, model="V6",
                                 continue_at=60, style=track.get("tags", ""))
        print("[extend] taskId =", ext["taskId"])
        ext_done = await music.wait(ext["taskId"])

        # 4. Convert To Wav Format：把原音轨转 WAV
        wav = await music.convert_to_wav(task_id=task_id, audio_id=audio_id)
        wav_done = await music.wait(wav["taskId"])
        print("[convert-to-wav]", wav_done["resultUrls"])


async def chain_persona():
    """生成 → Persona（同步返回 persona_id）→ 用 persona 再生成。"""
    async with SunoMusicClient() as music:
        sub = await music.generate(custom_mode=False, instrumental=False,
                                   model="V6", prompt="electronic pop")
        done = await music.wait(sub["taskId"])
        audio_id = done["tracks"][0]["id"]

        # Generate Persona 是同步端点：直接返回 persona_id（无 taskId 轮询）
        persona = await music.generate_persona(
            task_id=sub["taskId"], audio_id=audio_id,
            name="Electronic Pop Singer",
            description="A modern electronic music style pop singer",
        )
        print("[persona] persona_id =", persona["persona_id"])

        # persona_id 串回 generate
        again = await music.generate(
            custom_mode=False, instrumental=False, model="V6",
            prompt="another electronic pop song",
            persona_id=persona["persona_id"], persona_model="style_persona",
        )
        print("[generate w/ persona] taskId =", again["taskId"])


async def chain_voice():
    """自建音色三步链：验证短语 → 上传验证录音 → 检查可用。"""
    async with SunoMusicClient() as music:
        v = await music.voice_validate(
            voice_url="https://example.com/user_voice.mp3",
            vocal_start_s=0, vocal_end_s=10, language="zh",
        )
        validate_task_id = v["taskId"]           # 该 ID 同时就是将来的 voice_id
        print("[voice-validate] taskId =", validate_task_id)

        await music.await_voice_ready(validate_task_id)   # 等验证短语就绪

        created = await music.voice_create(
            task_id=validate_task_id,
            verify_url="https://example.com/user_verify.mp3",
            voice_name="My Voice", singer_skill_level="professional",
        )
        print("[voice-create] taskId =", created["taskId"])

        check = await music.voice_check(task_id=validate_task_id)  # 同步
        print("[voice-check] isAvailable =", check["isAvailable"])


async def chain_stems_midi():
    """生成 → 分轨分离 → 从 stems 生成 MIDI。"""
    async with SunoMusicClient() as music:
        sub = await music.generate(custom_mode=False, instrumental=False,
                                   model="V6", prompt="piano ballad")
        done = await music.wait(sub["taskId"])
        audio_id = done["tracks"][0]["id"]

        sep = await music.separate_vocals(task_id=sub["taskId"],
                                          audio_id=audio_id,
                                          type="split_stem")
        sep_done = await music.wait(sep["taskId"])
        print("[separate] stems =", sep_done["resultUrls"])

        stem_id = (sep_done["raw"].get("resultObject", {})
                   .get("origin_data", [{}])[0].get("id"))
        midi = await music.generate_midi(task_id=sep["taskId"],
                                         audio_id=stem_id)
        midi_done = await music.wait_midi(midi["taskId"])
        print("[midi] instruments =", midi_done["midi"])


async def main():
    await chain_generate_extend()
    # await chain_persona()
    # await chain_voice()
    # await chain_stems_midi()


if __name__ == "__main__":
    asyncio.run(main())
