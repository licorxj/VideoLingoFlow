import asyncio
import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.pi_rpc import get_pi_manager
from backend.pi_rpc.client import PiRpcError

router = APIRouter()


class CreateSessionRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    project_id: str = Field(default="default", max_length=100)
    cwd: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=200)
    system_prompt: str | None = Field(default=None, max_length=8000)
    tools: list[str] | None = None


class PromptRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    streaming_behavior: Literal["steer", "followUp"] | None = None
    attachments: list[str] | None = Field(default=None, max_length=20)


class SessionActionRequest(BaseModel):
    system_prompt: str | None = Field(default=None, max_length=8000)


class AgentSettingsRequest(BaseModel):
    values: dict[str, Any]


class AssistantSettingsRequest(BaseModel):
    values: dict[str, Any]


class IntegrationToggleRequest(BaseModel):
    enabled: bool


class InstallRequest(BaseModel):
    kind: str
    name: str
    level: str
    source_dir: str


class CacheClearRequest(BaseModel):
    category: str = Field(default="all", pattern=r"^(sessions|models|staging|all)$")


def _error(exc: Exception) -> HTTPException:
    message = str(exc)
    status = 503 if "runtime" in message.lower() or "process" in message.lower() else 400
    return HTTPException(status_code=status, detail={"code": "pi_rpc_error", "message": message[:500]})


@router.get("/health")
async def pi_health() -> dict[str, Any]:
    return get_pi_manager().status()


@router.get("/runtime")
async def pi_runtime() -> dict[str, Any]:
    return get_pi_manager().runtime()


@router.get("/diagnostics")
async def pi_diagnostics() -> dict[str, Any]:
    return get_pi_manager().diagnose()


@router.get("/settings")
async def get_agent_settings() -> dict[str, Any]:
    return get_pi_manager().settings()


@router.put("/settings")
async def update_agent_settings(request: AgentSettingsRequest) -> dict[str, Any]:
    return get_pi_manager().update_settings(request.values)


@router.put("/settings/assistants/{assistant_id}")
async def update_assistant_settings(assistant_id: str, request: AssistantSettingsRequest) -> dict[str, Any]:
    try:
        return get_pi_manager().update_assistant(assistant_id, request.values)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/settings/scan/{kind}")
async def scan_agent_resources(kind: str) -> list[dict[str, Any]]:
    try:
        return get_pi_manager().scan(kind)
    except Exception as exc:
        raise _error(exc) from exc


@router.put("/settings/{kind}/{item_id:path}")
async def toggle_agent_resource(kind: str, item_id: str, request: IntegrationToggleRequest) -> dict[str, bool]:
    try:
        get_pi_manager().set_integration(kind, item_id, request.enabled)
        return {"success": True}
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/settings/staging")
async def agent_install_staging() -> list[dict[str, str]]:
    return get_pi_manager().staging()


@router.get("/settings/models")
async def agent_model_catalog() -> list[dict[str, Any]]:
    return get_pi_manager().models()


@router.get("/settings/docs")
async def agent_docs_options() -> list[dict[str, Any]]:
    return get_pi_manager().scan("docs")


@router.post("/settings/install")
async def install_agent_resource(request: InstallRequest) -> dict[str, Any]:
    try:
        return get_pi_manager().install(request.kind, request.name, request.level, request.source_dir)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/cache/clear")
async def clear_agent_cache(request: CacheClearRequest) -> dict[str, Any]:
    try:
        return get_pi_manager().clear_cache(request.category)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/sessions")
async def create_session(request: CreateSessionRequest) -> dict[str, Any]:
    try:
        client = await get_pi_manager().create(**request.model_dump())
        return client.info.public()
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    try:
        return (await get_pi_manager().get(session_id)).info.public()
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/sessions/{session_id}/history")
async def session_history(session_id: str) -> list[dict[str, Any]]:
    try:
        client = await get_pi_manager().get(session_id)
        return get_pi_manager()._store.history(client.info.project_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/sessions/{session_id}/history/{history_id}/restore")
async def restore_history(session_id: str, history_id: int) -> dict[str, Any]:
    try:
        return (await get_pi_manager().restore_history(session_id, history_id)).info.public()
    except Exception as exc:
        raise _error(exc) from exc


@router.delete("/sessions/{session_id}/history/{history_id}")
async def delete_history(session_id: str, history_id: int) -> dict[str, bool]:
    try:
        manager = get_pi_manager()
        client = await manager.get(session_id)
        deleted = manager._store.delete_history(client.info.project_id, history_id)
        return {"success": deleted}
    except Exception as exc:
        raise _error(exc) from exc


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, bool]:
    try:
        await get_pi_manager().close(session_id)
        return {"success": True}
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/sessions/{session_id}/prompt")
async def prompt(session_id: str, request: PromptRequest) -> dict[str, Any]:
    try:
        return await get_pi_manager().prompt(
            session_id,
            request.message,
            request.attachments,
            request.streaming_behavior,
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/sessions/{session_id}/abort")
async def abort(session_id: str) -> dict[str, Any]:
    try:
        return await (await get_pi_manager().get(session_id)).abort()
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/sessions/{session_id}/clear")
async def clear_context(session_id: str) -> dict[str, Any]:
    try:
        return (await get_pi_manager().clear_context(session_id)).info.public()
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/sessions/{session_id}/new")
async def new_session(session_id: str, request: SessionActionRequest) -> dict[str, Any]:
    try:
        manager = get_pi_manager()
        current = await manager.get(session_id)
        project_id = current.info.project_id
        cwd = current.info.cwd
        model = current.info.model
        await manager.end(session_id)
        return (await manager.create(project_id=project_id, cwd=cwd, model=model, system_prompt=request.system_prompt)).info.public()
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/sessions/{session_id}/events")
async def events(session_id: str, after: int = -1) -> StreamingResponse:
    try:
        client = await get_pi_manager().get(session_id)
    except Exception as exc:
        raise _error(exc) from exc

    async def generate():
        baseline = client.info.seq
        for event in client.events:
            if event.get("seq", -1) > after:
                yield f"event: pi_event\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        while not client.info.closed:
            try:
                event = await client.next_event(timeout=20)
                if event.get("seq", -1) > baseline:
                    yield f"event: pi_event\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
            except asyncio.CancelledError:
                return

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
