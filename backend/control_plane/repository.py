from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from backend.control_plane.models import Task, TaskEvent
from backend.control_plane.runtime import transition
from backend.utils.observability import get_correlation_id


class ConcurrentUpdateError(RuntimeError):
    pass


def append_task_event(session: Session, task_id: str, event_type: str, payload: dict | None = None, correlation_id: str | None = None) -> TaskEvent:
    if session.execute(update(Task).where(Task.id == task_id).values(updated_at=func.now())).rowcount != 1:
        raise ConcurrentUpdateError(f"任务 {task_id} 不存在")
    sequence = session.scalar(select(func.max(TaskEvent.event_sequence)).where(TaskEvent.task_id == task_id)) or 0
    event = TaskEvent(task_id=task_id, event_sequence=sequence + 1, event_type=event_type, payload=payload or {}, correlation_id=get_correlation_id(correlation_id))
    session.add(event)
    session.flush()
    return event


def read_task_events(session: Session, task_id: str, after_sequence: int = 0, limit: int = 100) -> list[TaskEvent]:
    return list(session.scalars(select(TaskEvent).where(TaskEvent.task_id == task_id, TaskEvent.event_sequence > after_sequence).order_by(TaskEvent.event_sequence).limit(limit)).all())


def update_task_status(session: Session, task_id: str, expected_version: int, status: str) -> Task:
    current = session.get(Task, task_id)
    if current is None:
        raise ConcurrentUpdateError(f"任务 {task_id} 不存在")
    if current.version != expected_version:
        raise ConcurrentUpdateError(f"任务 {task_id} 已被并发修改或不存在")
    transition(current.status, status)
    result = session.execute(
        update(Task)
        .where(Task.id == task_id, Task.version == expected_version)
        .values(status=status, version=Task.version + 1)
    )
    if result.rowcount != 1:
        raise ConcurrentUpdateError(f"任务 {task_id} 已被并发修改或不存在")
    append_task_event(session, task_id, "status_changed", {"status": status})
    session.flush()
    return session.get(Task, task_id)
