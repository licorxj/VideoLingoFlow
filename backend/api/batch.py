"""Batch API: create, manage, and execute batch tasks."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List

from backend.engine.batch_executor import get_batch_executor
from backend.config.config_manager import config

router = APIRouter()


class BatchCreateRequest(BaseModel):
    workflow_id: str
    batch_name: str = ""
    tasks: List[dict] = Field(default_factory=list, description="List of per-task input dicts")
    common_config: dict = Field(default_factory=dict, description="Shared config applied to all tasks")


class BatchAddRequest(BaseModel):
    tasks: List[dict] = Field(default_factory=list)
    common_config: dict = Field(default_factory=dict)


class BatchDeleteTasksRequest(BaseModel):
    task_ids: List[str] = Field(default_factory=list)


class ConfigUpdateRequest(BaseModel):
    max_concurrent_tasks: int = Field(default=3, ge=1, le=20)
    task_start_interval: float = Field(default=0, ge=0, description="任务启动间隔(秒)")


@router.get("")
async def list_batches():
    """List all batches with summary info."""
    be = get_batch_executor()
    return {"batches": be.list_batches()}


@router.get("/summary")
async def list_batch_summaries(page: int = 1, page_size: int = 20):
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(status_code=422, detail="page 必须大于 0，page_size 必须在 1 到 100 之间")
    be = get_batch_executor()
    return be.get_batch_page(page, page_size)


@router.get("/config")
async def get_config():
    """Get batch configuration."""
    return {
        "max_concurrent_tasks": int(config.get("batch.max_concurrent_tasks", 3)),
        "task_start_interval": float(config.get("batch.task_start_interval", 0)),
    }


@router.put("/config")
async def update_config(req: ConfigUpdateRequest):
    """Update batch configuration."""
    be = get_batch_executor()
    be.set_max_workers(req.max_concurrent_tasks)
    be.set_task_start_interval(req.task_start_interval)
    return {"max_concurrent_tasks": req.max_concurrent_tasks, "task_start_interval": req.task_start_interval}


@router.post("/stop-all")
async def stop_all_batches():
    """Stop all running tasks across all batches."""
    try:
        be = get_batch_executor()
        return be.stop_all()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/resume-unfinished")
async def resume_all_unfinished():
    """Resume all unfinished tasks across all batches."""
    be = get_batch_executor()
    results = []
    for batch in be.list_batches():
        try:
            result = be.resume_unfinished(batch["id"])
            results.append({"batch_id": batch["id"], "status": result.get("status")})
        except Exception as e:
            results.append({"batch_id": batch["id"], "error": str(e)})
    return {"results": results}


@router.get("/{batch_id}")
async def get_batch_detail(batch_id: str):
    """Get full batch detail including all task statuses and node progress."""
    try:
        be = get_batch_executor()
        return be.get_batch_detail(batch_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


@router.post("/create")
async def create_batch(req: BatchCreateRequest):
    """Create a new batch of tasks from a workflow."""
    try:
        be = get_batch_executor()
        return be.create_batch(
            workflow_id=req.workflow_id,
            tasks_input=req.tasks,
            batch_name=req.batch_name,
            common_config=req.common_config,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{batch_id}/start")
async def start_batch(batch_id: str):
    """Start executing all tasks in a batch."""
    try:
        be = get_batch_executor()
        return be.start_batch(batch_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise


@router.post("/{batch_id}/stop")
async def stop_batch(batch_id: str):
    """Stop all tasks in a batch and cancel remaining queued tasks."""
    try:
        be = get_batch_executor()
        return be.stop_batch(batch_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{batch_id}/sync-workflow")
async def sync_workflow(batch_id: str, workflow_id: str = ""):
    """Sync batch workflow from the latest global workflow definition."""
    try:
        be = get_batch_executor()
        return be.sync_workflow(batch_id, workflow_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{batch_id}/resume")
async def resume_batch(batch_id: str):
    """Resume all unfinished tasks in a batch."""
    try:
        be = get_batch_executor()
        return be.resume_unfinished(batch_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{batch_id}/add")
async def add_tasks(batch_id: str, req: BatchAddRequest):
    """Add new tasks to an existing batch."""
    try:
        be = get_batch_executor()
        return be.append_tasks(batch_id, req.tasks, req.common_config)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{batch_id}/{task_id}/cancel")
async def cancel_task(batch_id: str, task_id: str):
    """Cancel a single running task in a batch."""
    try:
        be = get_batch_executor()
        return be.cancel_task(batch_id, task_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{batch_id}/{task_id}/retry")
async def retry_task(batch_id: str, task_id: str):
    """Retry a failed/cancelled task in a batch."""
    try:
        be = get_batch_executor()
        return be.retry_task(batch_id, task_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise


@router.post("/{batch_id}/{task_id}/resume")
async def resume_task(batch_id: str, task_id: str):
    """Resume a single task from its last checkpoint (keep completed nodes)."""
    try:
        be = get_batch_executor()
        return be.resume_single_task(batch_id, task_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise


@router.delete("/{batch_id}")
async def delete_batch(batch_id: str):
    """Delete an entire batch and all its tasks."""
    try:
        be = get_batch_executor()
        return be.delete_batch(batch_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{batch_id}/tasks")
async def delete_tasks(batch_id: str, req: BatchDeleteTasksRequest):
    """Batch delete selected tasks from a batch."""
    try:
        be = get_batch_executor()
        return be.delete_tasks(batch_id, req.task_ids)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/reset-pool")
async def reset_thread_pool():
    raise HTTPException(status_code=410, detail="本地线程池执行已移除，请检查 Celery worker 状态")


@router.get("/pool-status")
async def pool_status():
    from backend.control_plane.celery_runtime import celery_app
    if celery_app is None:
        return {"mode": "celery", "available": False, "workers": {}}
    try:
        return {"mode": "celery", "available": True, "workers": celery_app.control.inspect().stats() or {}}
    except Exception:
        return {"mode": "celery", "available": False, "workers": {}}
