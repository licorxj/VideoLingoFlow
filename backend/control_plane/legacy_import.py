import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.control_plane.models import Project, Task, TaskNode, WorkflowVersion
from backend.control_plane.repository import append_task_event


@dataclass(frozen=True)
class LegacyTask:
    key: str
    task: dict
    workflow: dict


def scan_voiceforge_sqlite(database_path: Path) -> dict:
    if not database_path.exists():
        return {"present": False, "tables": {}, "error": "not_found"}
    uri = f"file:{database_path.resolve().as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
            return {
                "present": True,
                "tables": {table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables},
            }
    except sqlite3.Error as exc:
        return {"present": True, "tables": {}, "error": type(exc).__name__}


def scan_history(tasks_root: Path, workflows_root: Path) -> list[LegacyTask]:
    records: list[LegacyTask] = []
    if not tasks_root.exists():
        return records
    for task_path in sorted(tasks_root.glob("*/task.json"), key=lambda item: item.parent.name):
        try:
            task = json.loads(task_path.read_text(encoding="utf-8"))
            workflow_path = task_path.with_name("workflow.json")
            workflow = json.loads(workflow_path.read_text(encoding="utf-8")) if workflow_path.exists() else {}
            if not workflow and task.get("workflow_id"):
                configured = workflows_root / f"{task['workflow_id']}.json"
                if configured.exists():
                    workflow = json.loads(configured.read_text(encoding="utf-8"))
            records.append(LegacyTask(task_path.parent.name, task, workflow))
        except (OSError, json.JSONDecodeError):
            continue
    return records


def import_history(session: Session, records: list[LegacyTask], dry_run: bool = False) -> dict:
    report = {"scanned": len(records), "created": 0, "reused": 0, "nodes": 0}
    for record in records:
        if session.scalar(select(Task.id).where(Task.legacy_key == record.key)):
            report["reused"] += 1
            continue
        report["created"] += 1
        steps = record.task.get("steps") or {}
        # 旧 task.json 可能只有 steps 没有 nodes：归一为 nodes，确保导入后 nodes 完整
        if not record.task.get("nodes"):
            record.task["nodes"] = steps
        report["nodes"] += len(steps)
        if dry_run:
            continue
        project = Project(name=record.task.get("task_name") or record.key, description="由历史任务导入", legacy_key=f"task-project:{record.key}")
        workflow = WorkflowVersion(project=project, workflow_key=record.task.get("workflow_id") or record.key, revision=1, definition=record.workflow)
        session.add_all([project, workflow])
        session.flush()
        task = Task(project=project, workflow_version_id=workflow.id, legacy_key=record.key, status=record.task.get("status") or "created", payload=record.task)
        session.add(task)
        session.flush()
        append_task_event(session, task.id, "legacy_imported", {"legacy_key": record.key})
        for node_key, node_payload in steps.items():
            session.add(TaskNode(task_id=task.id, node_key=str(node_key), status=node_payload.get("status") or "pending", payload=node_payload))
    return report
