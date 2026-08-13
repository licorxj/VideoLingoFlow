import json
import os
import uuid
from datetime import datetime
from typing import Any, Optional

TASKS_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tasks")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class TaskRecorder:
    """Read/write task.json for a given task directory."""

    def __init__(self, task_dir: str):
        self.task_dir = task_dir
        self.path = os.path.join(task_dir, "task.json")

    def read(self) -> dict:
        if not os.path.exists(self.path):
            return {}
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def write(self, data: dict):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def update_step(self, step_id: str, updates: dict):
        data = self.read()
        if "steps" not in data:
            data["steps"] = {}
        if step_id not in data["steps"]:
            data["steps"][step_id] = {}
        data["steps"][step_id].update(updates)
        data["updated_at"] = _now()
        self.write(data)

    def update_status(self, status: str):
        data = self.read()
        data["status"] = status
        data["updated_at"] = _now()
        self.write(data)


def create_task_dir() -> str:
    task_id = uuid.uuid4().hex[:12]
    task_dir = os.path.join(TASKS_ROOT, task_id)
    os.makedirs(os.path.join(task_dir, "cache"), exist_ok=True)
    os.makedirs(os.path.join(task_dir, "output"), exist_ok=True)
    return task_dir


def list_tasks() -> list:
    if not os.path.exists(TASKS_ROOT):
        return []
    tasks = []
    for tid in os.listdir(TASKS_ROOT):
        td = os.path.join(TASKS_ROOT, tid)
        jp = os.path.join(td, "task.json")
        if os.path.isdir(td) and os.path.exists(jp):
            try:
                with open(jp, "r", encoding="utf-8") as f:
                    tasks.append(json.load(f))
            except Exception:
                pass
    tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    return tasks


def get_task(task_id: str) -> Optional[dict]:
    jp = os.path.join(TASKS_ROOT, task_id, "task.json")
    if not os.path.exists(jp):
        return None
    with open(jp, "r", encoding="utf-8") as f:
        return json.load(f)


def delete_task(task_id: str) -> bool:
    import shutil
    td = os.path.join(TASKS_ROOT, task_id)
    if os.path.exists(td):
        shutil.rmtree(td)
        return True
    return False
