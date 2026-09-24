# -*- coding: utf-8 -*-
"""
文件中转站取自节点（Step）

作用：从「文件中转站」取一件素材，把它的文件路径输出给下游。

两种取法（节点卡片上配置）：

- 手动：点「选择文件」按钮在弹窗里指定一条记录（记录 id/路径存入节点配置）；
- 自动：按「文件类型 + 排序规则」取——最新入库 / 最旧入库 / 排序序号(第 N 个) / 文件名称。

输出：
    path —— 素材文件路径（filepath）
    info —— 该条记录详情 JSON（名称/类型/所属任务/入库时间）
"""
import os
from typing import Callable

from backend.steps.base_step import BaseStep
from backend.utils.file_transit import pick_file


class S_FileTransitOut(BaseStep):
    step_id = "s_file_transit_out"
    step_name = "文件中转站取自"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        # 取件结果依赖中转站当时的内容，不做产物缓存
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir, callback=None, cancel_callback=None):
        config = getattr(self, "_node_config", {}) or {}
        report: Callable = callback or (lambda *a, **k: None)

        pick_mode = str(config.get("pick_mode") or "auto").strip().lower()
        selected_path = str(config.get("selected_path") or "").strip()
        file_type = str(config.get("file_type") or "all").strip() or "all"
        order = str(config.get("order") or "latest").strip() or "latest"
        keyword = str(config.get("keyword") or "").strip()
        try:
            index = int(float(config.get("index") or 1))
        except (TypeError, ValueError):
            index = 1

        try:
            report(30, "正在从文件中转站取件...")
        except Exception:
            pass

        item = None
        if pick_mode == "manual" and selected_path:
            item = pick_file(path=selected_path)
            if item is None:
                # 手动指定的记录已不在库中：退回按规则自动取，避免节点直接失败
                item = pick_file(file_type=file_type, keyword=keyword, order=order, index=index)
        else:
            item = pick_file(file_type=file_type, keyword=keyword, order=order, index=index)

        if item is None:
            try:
                report(100, "中转站内没有匹配的素材")
            except Exception:
                pass
            return {"artifacts": [], "outputs": {"path": "", "info": {}}}

        try:
            report(100, f"已取件：{item.get('name')}")
        except Exception:
            pass
        return {
            "artifacts": [],
            "outputs": {
                "path": str(item.get("path") or ""),
                "info": item,
            },
        }
