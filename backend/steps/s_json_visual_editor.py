"""s_json_visual_editor: 可视化编辑 JSON 的透传节点。

默认不修改输入 JSON，直接按原名透传为输出；
用户在节点卡片点击「打开 JSON 编辑页」可视化编辑后，编辑结果存于节点配置
edited_json，节点运行时据此输出：开启「另存副本」则生成带随机后缀的副本文件，
否则覆盖原 JSON 文件。
"""
import json
import os
import uuid
from typing import Callable, Optional

from backend.steps.base_step import BaseStep


class S_JsonVisualEditor(BaseStep):
    step_id = "s_json_visual_editor"
    step_name = "JSON可视化编辑"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return False  # 透传或覆盖原文件，无独立产物标记，始终执行

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        enable_copy = node_config.get("enable_copy", True)
        if isinstance(enable_copy, str):
            enable_copy = enable_copy.lower() in ("true", "1", "yes")
        edited = node_config.get("edited_json", "")
        edited = str(edited or "").strip()

        json_input = step_inputs.get("json", "")
        if not json_input:
            raise ValueError("未连接 JSON 输入")

        # --- 解析输入：文件路径或 JSON 字符串/对象 ---
        source_path = None
        data = None
        if isinstance(json_input, (dict, list)):
            data = json_input
        else:
            raw = str(json_input)
            p = raw if os.path.isabs(raw) else os.path.join(task_dir, raw)
            if os.path.isfile(p):
                source_path = p
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    raise ValueError("输入既不是有效文件路径，也不是合法 JSON 字符串")

        # --- 未编辑：直接透传原文件（按原名） ---
        if not edited:
            if callback:
                callback(100, "未进行编辑，透传原 JSON")
            if source_path:
                return {"artifacts": [], "outputs": {"json": source_path}}
            output_dir = os.path.join(task_dir, "output")
            os.makedirs(output_dir, exist_ok=True)
            out_path = os.path.join(output_dir, f"json_visual_edit_{node_id}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            rel = f"output/json_visual_edit_{node_id}.json"
            return {"artifacts": [rel], "outputs": {"json": rel}}

        # --- 已编辑：解析编辑结果 ---
        try:
            edited_data = json.loads(edited)
        except json.JSONDecodeError as exc:
            raise ValueError("编辑后的 JSON 内容无效") from exc

        if callback:
            callback(60, "正在保存编辑后的 JSON")

        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        if source_path and not enable_copy:
            # 不建副本：直接覆盖原文件
            save_path = source_path
        elif source_path:
            # 建副本：随机后缀名
            base = os.path.splitext(os.path.basename(source_path))[0]
            save_path = os.path.join(output_dir, f"{base}_{uuid.uuid4().hex[:8]}.json")
        else:
            save_path = os.path.join(output_dir, f"json_visual_edit_{node_id}.json")

        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(edited_data, f, ensure_ascii=False, indent=2)

        # 覆盖原文件时返回原路径（与透传行为一致），否则返回相对产物路径
        rel_path = source_path if save_path == source_path else os.path.relpath(save_path, task_dir).replace("\\", "/")
        if callback:
            callback(100, f"已保存编辑结果到 {os.path.basename(rel_path)}")
        return {"artifacts": [rel_path], "outputs": {"json": rel_path}}
