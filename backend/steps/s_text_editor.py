"""s_text_editor: 可视化编辑文本的透传节点。

默认不修改输入文本，直接按原名透传为输出；
用户在节点卡片点击「打开文本编辑页」编辑后，结果存于节点配置 edited_text，
节点运行时据此输出：开启「另存副本」则生成带随机后缀的副本文件，否则覆盖原文本文件。
"""
import os
import uuid
from typing import Callable, Optional

from backend.steps.base_step import BaseStep


class S_TextEditor(BaseStep):
    step_id = "s_text_editor"
    step_name = "文本编辑"
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
        edited = str(node_config.get("edited_text", "") or "")

        text_input = step_inputs.get("text", "")
        if not text_input:
            raise ValueError("未连接文本输入")

        # --- 解析输入：文件路径或直接文本 ---
        source_path = None
        content = ""
        if isinstance(text_input, str):
            raw = text_input
            p = raw if os.path.isabs(raw) else os.path.join(task_dir, raw)
            if os.path.isfile(p):
                source_path = p
                with open(p, "r", encoding="utf-8") as f:
                    content = f.read()
            else:
                content = raw
        else:
            content = str(text_input)

        # --- 未编辑：直接透传原文件（按原名） ---
        if not edited:
            if callback:
                callback(100, "未进行编辑，透传原文本")
            if source_path:
                return {"artifacts": [], "outputs": {"text": source_path}}
            output_dir = os.path.join(task_dir, "output")
            os.makedirs(output_dir, exist_ok=True)
            out_path = os.path.join(output_dir, f"text_edit_{node_id}.txt")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(content)
            rel = f"output/text_edit_{node_id}.txt"
            return {"artifacts": [rel], "outputs": {"text": rel}}

        # --- 已编辑：保存结果 ---
        if callback:
            callback(60, "正在保存编辑后的文本")

        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        if source_path and not enable_copy:
            # 不建副本：直接覆盖原文件
            save_path = source_path
        elif source_path:
            # 建副本：随机后缀名
            base = os.path.splitext(os.path.basename(source_path))[0]
            save_path = os.path.join(output_dir, f"{base}_{uuid.uuid4().hex[:8]}.txt")
        else:
            save_path = os.path.join(output_dir, f"text_edit_{node_id}.txt")

        with open(save_path, "w", encoding="utf-8") as f:
            f.write(edited)

        # 覆盖原文件时返回原路径（与透传行为一致），否则返回相对产物路径
        rel_path = source_path if save_path == source_path else os.path.relpath(save_path, task_dir).replace("\\", "/")
        if callback:
            callback(100, f"已保存编辑结果到 {os.path.basename(rel_path)}")
        return {"artifacts": [rel_path], "outputs": {"text": rel_path}}
