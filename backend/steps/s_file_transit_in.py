# -*- coding: utf-8 -*-
"""
文件中转站入库节点（Step）

作用：把接入的单个文件 / 文件列表登记到「文件中转站」数据库表。
**只记录元信息（名称、类型、所属任务名称、文件路径、入库时间），不移动也不复制文件**，
文件仍停在它原来的位置。

输入：
    file  —— 单文件（filepath）
    files —— 文件列表（list）
输出：
    path   —— 首个入库文件的路径（便于下游直接接单文件端口）
    paths  —— 全部入库文件路径（list）
    count  —— 本次入库条数（text）
"""
import json
import os
from typing import Callable

from backend.steps.base_step import BaseStep
from backend.utils.file_transit import ingest_paths


def _task_meta(task_dir: str):
    """从任务工作区的 task.json 读任务名与任务 id（相对路径预览需要 task_id）。"""
    task_id = os.path.basename(os.path.normpath(task_dir or ""))
    task_name = ""
    try:
        with open(os.path.join(task_dir, "task.json"), "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        task_name = str(data.get("task_name") or "").strip()
        task_id = str(data.get("id") or task_id).strip() or task_id
    except Exception:
        pass
    if not task_name:
        task_name = task_id
    return task_id, task_name


class S_FileTransitIn(BaseStep):
    step_id = "s_file_transit_in"
    step_name = "文件中转站入库"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        # 入库是纯登记动作，产物位置不在任务目录内，始终执行以便刷新记录
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir, callback=None, cancel_callback=None):
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        report: Callable = callback or (lambda *a, **k: None)

        raw = step_inputs.get("file")
        if raw in (None, "", []):
            raw = step_inputs.get("files")
        # 两个端口都接了时合并处理
        if step_inputs.get("file") and step_inputs.get("files"):
            raw = [step_inputs.get("file"), step_inputs.get("files")]

        task_id, task_name = _task_meta(task_dir)
        try:
            report(30, "正在登记到文件中转站...")
        except Exception:
            pass

        items = ingest_paths(raw, task_id=task_id, task_name=task_name)
        paths = [str(item.get("path") or "") for item in items]
        try:
            report(100, f"已入库 {len(items)} 个文件")
        except Exception:
            pass

        return {
            "artifacts": [],
            "outputs": {
                "path": paths[0] if paths else "",
                "paths": paths,
                "count": str(len(items)),
            },
        }
