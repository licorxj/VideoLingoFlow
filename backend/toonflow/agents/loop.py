# -*- coding: utf-8 -*-
"""自建轻量 tool-loop —— 对齐源系统基于 Vercel AI SDK 的工具循环语义
（generateText + tools + stopWhen: stepCountIs）。

- 出口：经本项目 llm_client 的 **DirectRouter**（进程内直连上游，多协议路由），
  与全项目 LLM 同一配置与日志；不再直连 localhost 网关；
- 工具：Python callable + JSON Schema，服务端执行（源"前端执行器回调"已服务端化）；
  tools 在 openai/custom 协议下原样透传；claude/gemini 协议为极简转换（不含工具），
  此时循环自然退化为单轮文本（emit warn 提示）；
- 步数上限：对齐源 `stepCountIs(工具数×50)`，默认 200。
"""
import json
from typing import Callable

MAX_STEPS_DEFAULT = 200


class Tool:
    """一个可被 LLM 调用的服务端工具。"""

    def __init__(self, name: str, description: str, parameters: dict,
                 execute: Callable[[dict], object]):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.execute = execute

    def schema(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": self.parameters or {"type": "object", "properties": {}},
        }}


def _temperature(agent_key: str, default: float = 1.0) -> float:
    """tf_agent_deploy 中的温度覆盖（源 o_agentDeploy 语义）。"""
    try:
        from sqlalchemy import select

        from backend.control_plane.database import session_scope
        from backend.toonflow.core.models import TfAgentDeploy

        with session_scope() as session:
            row = session.scalars(select(TfAgentDeploy).where(
                TfAgentDeploy.key == agent_key)).first()
            return float(row.temperature) if row and row.temperature else default
    except Exception:  # noqa: BLE001
        return default


def _chat(convo: list[dict], tools: list[dict], temperature: float) -> dict:
    """单次对话补全，返回 choices[0].message dict。

    与 llm_client 同路：use_router + 本地网关 → DirectRouter（strategy = 配置的默认模型名）；
    否则回退 OpenAI SDK 走网关/直连。tools 仅在 openai 兼容协议下有效（其余协议自然降级）。
    """
    from backend.llm.llm_client import get_llm_client

    body = {"messages": convo, "temperature": temperature}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"

    client = get_llm_client()
    api_cfg = client._get_api_config("toonflow")  # noqa: SLF001 —— 受控复用路由解析
    llm_cfg = client._get_llm_config_snapshot()  # noqa: SLF001
    use_direct = (
        llm_cfg.get("use_router")
        and llm_cfg.get("direct_router", True)
        and client._is_local_router(api_cfg["base_url"])
    )
    if use_direct:
        from backend.llm.direct_router import get_direct_router

        resp = get_direct_router().forward(api_cfg["model"], body,
                                           timeout=api_cfg.get("timeout", 120) or 120)
    else:
        from openai import OpenAI

        sdk = OpenAI(base_url=api_cfg["base_url"], api_key=api_cfg["api_key"])
        r = sdk.chat.completions.create(**{**body, "model": api_cfg["model"]})
        resp = r.model_dump() if hasattr(r, "model_dump") else r

    choices = resp.get("choices") or []
    if not choices:
        raise RuntimeError(f"LLM 返回缺少 choices: {str(resp)[:200]}")
    return choices[0].get("message") or {}


def run_tool_loop(messages: list[dict], tools: dict[str, Tool], *,
                  agent_key: str, max_steps: int = MAX_STEPS_DEFAULT,
                  emit: Callable[[str, dict], None] | None = None) -> str:
    """执行一轮工具循环，返回助手最终文本。

    emit(kind, payload)：kind ∈ message / thinking / tool / tool_result / warn，向 UI 单向推送。
    """
    emit = emit or (lambda kind, payload: None)
    temperature = _temperature(agent_key)
    tool_schemas = [t.schema() for t in tools.values()]
    convo = list(messages)
    max_steps = min(max_steps, len(tools) * 50) if tools else max_steps
    last_text = ""

    for _step in range(max(1, max_steps)):
        msg = _chat(convo, tool_schemas, temperature)
        content = msg.get("content") or ""
        tool_calls = list(msg.get("tool_calls") or [])

        if not tool_calls:
            if tool_schemas and _step == 0:
                emit("warn", {"message": "当前上游协议未返回工具调用，已按纯文本模式处理"})
            emit("message", {"content": content})
            return content
        if content:
            emit("thinking", {"text": content})

        convo.append({"role": "assistant", "content": content or None, "tool_calls": tool_calls})
        for tc in tool_calls:
            fn = tc.get("function") or {}
            name = fn.get("name") or ""
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            tool = tools.get(name)
            emit("tool", {"name": name, "args": args})
            if tool is None:
                result = {"error": f"未知工具: {name}"}
            else:
                try:
                    result = tool.execute(args if isinstance(args, dict) else {})
                except Exception as exc:  # noqa: BLE001
                    result = {"error": f"{type(exc).__name__}: {exc}"}
            text_result = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            emit("tool_result", {"name": name, "preview": text_result[:8000]})
            convo.append({"role": "tool", "tool_call_id": tc.get("id") or "",
                          "content": text_result[:24000]})
            last_text = text_result

    emit("warn", {"message": f"已达步数上限（{max_steps}），强制结束"})
    return last_text or "（已达步数上限）"
