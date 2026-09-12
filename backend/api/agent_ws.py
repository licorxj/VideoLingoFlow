# -*- coding: utf-8 -*-
"""创作 Agent 会话 WebSocket：/ws/tf-agent（单向推送，Agent 全部服务端执行）。

协议（JSON）：
    客户端 → {type: "chat", projectId: int, agent?: "production"|"script", text: str}
    服务端 → {type: "message"|"thinking"|"tool"|"tool_result"|"warn", ...}   过程事件
             {type: "done", content: str}                                   最终回复
             {type: "error", message: str}                                  异常

同一连接同时只处理一个请求（agent 运行中收到新 chat 会回 busy）。
"""
import asyncio
import traceback

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.toonflow.agents import production_agent, script_agent

router = APIRouter()


@router.websocket("/ws/tf-agent")
async def tf_agent_socket(ws: WebSocket):
    await ws.accept()
    loop = asyncio.get_running_loop()
    running = False

    def emit(kind: str, payload: dict):
        """线程安全推送（Agent 循环跑在工作线程）。"""
        data = {"type": kind, **(payload or {})}
        asyncio.run_coroutine_threadsafe(ws.send_json(data), loop)

    try:
        while True:
            data = await ws.receive_json()
            if data.get("type") != "chat":
                continue
            if running:
                await ws.send_json({"type": "error", "message": "Agent 正在执行中，请稍候"})
                continue

            project_id = int(data.get("projectId") or 0)
            text = str(data.get("text") or "").strip()
            agent_kind = str(data.get("agent") or "production")
            if not project_id or not text:
                await ws.send_json({"type": "error", "message": "缺少 projectId 或 text"})
                continue

            running = True

            def _run():
                try:
                    if agent_kind == "script":
                        return script_agent.run_script_agent(project_id, text, emit)
                    return production_agent.run_decision_agent(project_id, text, emit)
                except Exception as exc:  # noqa: BLE001
                    traceback.print_exc()
                    emit("error", {"message": f"{type(exc).__name__}: {str(exc)[:300]}"})
                    return None

            try:
                result = await asyncio.to_thread(_run)
                await ws.send_json({"type": "done", "content": result or ""})
            finally:
                running = False
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        try:
            await ws.send_json({"type": "error", "message": str(exc)[:300]})
        except Exception:  # noqa: BLE001
            pass
