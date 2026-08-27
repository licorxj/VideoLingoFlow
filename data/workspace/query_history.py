#!/usr/bin/env python3
"""Query completed/failed tasks from the control plane database."""

import sqlite3
import json
import os
from datetime import datetime

# Database path
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control-plane.db")

# Terminal statuses from history.py
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "deleted"}

def query_history():
    """Query tasks from the database and return a list of dictionaries."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Enable column access by name
    cursor = conn.cursor()
    
    # Query all tasks, ordered by created_at descending
    cursor.execute("""
        SELECT id, status, payload, created_at, updated_at
        FROM cp_tasks
        WHERE status IN (?, ?, ?, ?)
        ORDER BY created_at DESC
    """, tuple(TERMINAL_STATUSES))
    
    tasks = []
    for row in cursor.fetchall():
        task_id = row["id"]
        status = row["status"]
        payload = json.loads(row["payload"]) if row["payload"] else {}
        created_at = row["created_at"]
        finished_at = row["updated_at"] if status in TERMINAL_STATUSES else None
        
        # Extract task name from payload or project
        batch = payload.get("batch") or {}
        workflow = payload.get("workflow") or {}
        task_name = batch.get("task_name") or payload.get("task_name")
        
        # Extract workflow info
        workflow_id = workflow.get("id") or payload.get("workflow_id") or batch.get("workflow_id") or ""
        workflow_name = batch.get("workflow_name") or workflow.get("name")
        
        # Determine task type
        batch_id = batch.get("batch_id") or payload.get("batch_id")
        if batch_id:
            task_type = "batch"
        elif payload.get("detached"):
            task_type = "normal"
        elif workflow_id:
            task_type = "workflow"
        else:
            task_type = "normal"
        
        task_info = {
            "id": task_id,
            "task_name": task_name,
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "status": "completed" if status == "succeeded" else status,
            "created_at": created_at,
            "finished_at": finished_at,
            "batch_id": batch_id,
            "task_type": task_type,
            "detached": bool(payload.get("detached")),
        }
        tasks.append(task_info)
    
    conn.close()
    return tasks

def format_task(task):
    """Format a task for display."""
    created = datetime.fromisoformat(task["created_at"]) if task["created_at"] else None
    finished = datetime.fromisoformat(task["finished_at"]) if task["finished_at"] else None
    
    status_emoji = {
        "completed": "✅",
        "failed": "❌",
        "cancelled": "⏹️",
        "deleted": "🗑️"
    }.get(task["status"], "❓")
    
    created_str = created.strftime("%Y-%m-%d %H:%M:%S") if created else "未知时间"
    finished_str = finished.strftime("%Y-%m-%d %H:%M:%S") if finished else "进行中"
    
    return (
        f"{status_emoji} {task['task_name'] or '未命名任务'}\n"
        f"   ID: {task['id']}\n"
        f"   类型: {task['task_type']}\n"
        f"   工作流: {task['workflow_name'] or task['workflow_id'] or '无'}\n"
        f"   创建时间: {created_str}\n"
        f"   完成时间: {finished_str}\n"
    )

if __name__ == "__main__":
    tasks = query_history()
    
    if not tasks:
        print("没有找到已完成的项目。")
    else:
        print(f"找到 {len(tasks)} 个已完成的项目：\n")
        for i, task in enumerate(tasks, 1):
            print(f"{i}. {format_task(task)}")
            print("-" * 50)