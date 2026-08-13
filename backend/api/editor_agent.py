from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.editor.agent.service import EditorAgentService
from backend.editor.models import AgentApprovalRequest, AgentRunRequest


router = APIRouter()
service = EditorAgentService()


@router.post("/tasks/{task_id}/agent/runs")
async def start_agent_run(task_id: str, request: AgentRunRequest):
    run = service.execute(task_id, request.content, request.expert_role, request.expected_revision, request.manual_config)
    return run


@router.post("/tasks/{task_id}/agent/execute")
async def execute_agent(task_id: str, request: AgentRunRequest):
    return service.execute(task_id, request.content, request.expert_role, request.expected_revision, request.manual_config)


@router.get("/tasks/{task_id}/agent/runs/{run_id}")
async def get_agent_run(task_id: str, run_id: str):
    try:
        return service.get_run(task_id, run_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/tasks/{task_id}/agent/runs/{run_id}/events")
async def agent_events(task_id: str, run_id: str):
    try:
        run = service.get_run(task_id, run_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc

    def stream():
        for event in run.get("events", []):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'run.completed', 'status': run.get('status'), 'revision': run.get('output_revision')}, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/tasks/{task_id}/agent/runs/{run_id}/approvals")
async def approve_agent_run(task_id: str, run_id: str, request: AgentApprovalRequest):
    try:
        run = service.get_run(task_id, run_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"id": run_id, "status": run.get("status"), "approved": request.approved, "tool_call_ids": request.tool_call_ids}


@router.post("/tasks/{task_id}/agent/runs/{run_id}/cancel")
async def cancel_agent_run(task_id: str, run_id: str):
    try:
        run = service.get_run(task_id, run_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    if run.get("status") == "running":
        run["status"] = "cancelled"
    return {"id": run_id, "status": run.get("status")}
