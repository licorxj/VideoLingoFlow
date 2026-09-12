# -*- coding: utf-8 -*-
"""文本引擎适配：Toonflow `Ai.Text(...).invoke()/stream()` → 本项目 llm_client。

源契约（vendor textRequest）：返回 ai-sdk chat model，调用方走 generateText/streamText，
支持 think 开关与工具循环。本项目 llm_client 已具备 chat/stream/json/多模态，直接适配；
工具循环（Agent 用）见 agents/loop.py（P3），不在本模块。
"""
from typing import Generator

from backend.toonflow.engines.base import task_record


def invoke(prompt: str, *, system: str = "", json_mode: bool = False,
           images: list[str] | None = None, model: str = "", temperature: float | None = None,
           project_id: int | None = None) -> str:
    """一次性生成（阻塞）。json_mode=True 时返回解析后的对象（对齐源 response_json 语义）。"""
    from backend.llm.llm_client import get_llm_client

    with task_record("文本生成", "text", project_id):
        result = get_llm_client().chat(
            "toonflow",
            prompt,
            system_prompt=system or None,
            response_json=json_mode,
            stream=False,
            temperature=temperature,
            images=images or None,
            model_override=model or "",
        )
    return result


def stream(prompt: str, *, system: str = "", model: str = "",
           temperature: float | None = None,
           project_id: int | None = None) -> Generator[str, None, None]:
    """流式生成，逐段产出文本增量（供 socket 推送）。"""
    from backend.llm.llm_client import get_llm_client

    gen = get_llm_client().chat(
        "toonflow",
        prompt,
        system_prompt=system or None,
        response_json=False,
        stream=True,
        temperature=temperature,
        model_override=model or "",
    )
    # 台账不包裹生成器消费过程（流式生命周期由调用方控制）
    return gen
