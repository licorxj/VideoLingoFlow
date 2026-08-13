"""s_file_rename: Rename an input file in-place with custom name, prefix, or suffix.

Logic:
  1. Get input file path from upstream node
  2. Compute new filename based on rename mode (custom/prefix/suffix)
  3. Rename the file in-place (same directory)
  4. Update upstream node outputs in task.json to reference the new path
  5. Output the renamed file path
"""
import os
import json
from pathlib import Path
from typing import Callable, Optional

from backend.steps.base_step import BaseStep


class S_FileRename(BaseStep):
    step_id = "file_rename"
    step_name = "文件改名"
    dependencies = []
    artifacts = []

    def check_artifact(self, task_dir: str) -> bool:
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        if callback:
            callback(10, "获取输入文件路径...")

        # 1. Get input file path（可能是相对工作区的路径，需解析为绝对路径）
        input_path = step_inputs.get("any", "") or step_inputs.get("video", "") or step_inputs.get("audio", "") or step_inputs.get("text", "") or step_inputs.get("subtitle", "") or step_inputs.get("json", "") or ""
        
        if not input_path or not isinstance(input_path, str):
            raise ValueError("未收到有效的输入文件路径")

        if not os.path.isabs(input_path):
            input_path = os.path.join(task_dir, input_path)

        # If input is a text file, read its content as the actual path
        if os.path.isfile(input_path) and input_path.endswith(".txt"):
            try:
                with open(input_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content and os.path.exists(content):
                    input_path = content
            except Exception:
                pass

        if not os.path.exists(input_path):
            raise ValueError(f"输入文件不存在: {input_path}")

        # 2. Compute new filename
        rename_mode = node_config.get("rename_mode", "suffix")
        custom_name = node_config.get("custom_name", "").strip()
        prefix = node_config.get("prefix", "").strip()
        suffix = node_config.get("suffix", "").strip()

        input_dir = os.path.dirname(input_path)
        input_basename = os.path.basename(input_path)
        name_part, ext = os.path.splitext(input_basename)

        if rename_mode == "custom":
            if not custom_name:
                raise ValueError("自定义文件名不能为空")
            new_name = custom_name + ext
        elif rename_mode == "prefix":
            if not prefix:
                raise ValueError("前缀不能为空")
            new_name = prefix + name_part + ext
        elif rename_mode == "suffix":
            if not suffix:
                raise ValueError("后缀不能为空")
            new_name = name_part + suffix + ext
        else:
            raise ValueError(f"未知的改名模式: {rename_mode}")

        new_path = os.path.join(input_dir, new_name)

        if callback:
            callback(40, f"改名: {input_basename} -> {new_name}")

        # 3. Rename the file
        if input_path == new_path:
            print(f"[FileRename] 文件名未变化: {input_path}")
        else:
            if os.path.exists(new_path):
                raise ValueError(f"目标文件已存在: {new_path}")
            os.rename(input_path, new_path)
            print(f"[FileRename] 已改名: {input_path} -> {new_path}")

        if callback:
            callback(70, "更新上游节点输出引用...")

        # 4. Update upstream node outputs in task.json
        task_json_path = os.path.join(task_dir, "task.json")
        updated_count = 0
        if os.path.exists(task_json_path) and input_path != new_path:
            try:
                with open(task_json_path, "r", encoding="utf-8") as f:
                    task_data = json.load(f)
                
                nodes = task_data.get("nodes", {})
                for nid, node_info in nodes.items():
                    node_outputs = node_info.get("outputs", {})
                    changed = False
                    for key, value in node_outputs.items():
                        if isinstance(value, str) and value == input_path:
                            node_outputs[key] = new_path
                            changed = True
                            updated_count += 1
                            print(f"[FileRename] 更新节点 {nid} 的输出 {key}: {input_path} -> {new_path}")
                        elif isinstance(value, list):
                            for i, item in enumerate(value):
                                if isinstance(item, str) and item == input_path:
                                    value[i] = new_path
                                    changed = True
                                    updated_count += 1
                                    print(f"[FileRename] 更新节点 {nid} 的输出 {key}[{i}]: {input_path} -> {new_path}")
                    if changed:
                        node_info["outputs"] = node_outputs
                
                # Also update input config if the file was an input file
                input_config = task_data.get("input", {})
                for key in ("videoPath", "audioPath", "subtitlePath"):
                    if input_config.get(key) == input_path:
                        input_config[key] = new_path
                        updated_count += 1
                        print(f"[FileRename] 更新输入配置 {key}: {input_path} -> {new_path}")

                with open(task_json_path, "w", encoding="utf-8") as f:
                    json.dump(task_data, f, ensure_ascii=False, indent=2)
                
                print(f"[FileRename] 共更新 {updated_count} 处引用")
            except Exception as e:
                print(f"[FileRename] Warning: 更新 task.json 失败: {e}")

        # 4.5 同步改名到控制平面数据库（TaskNode.payload.result.outputs 与 task.payload.input）
        # 新架构运行态事实来源是 DB，task.json 只是兼容产物；不改 DB 会导致下游节点经
        # _resolve_step_inputs 注入的仍是旧路径。
        if input_path != new_path:
            try:
                from backend.control_plane.database import session_scope
                from backend.control_plane.models import Task
                from backend.control_plane.workflow_runtime import _write_legacy_task

                task_id = os.path.basename(os.path.normpath(task_dir))
                with session_scope() as session:
                    task = session.get(Task, task_id)
                    if task is None:
                        print(f"[FileRename] Warning: 控制平面任务不存在: {task_id}，跳过 DB 同步")
                    else:
                        # 更新 input 配置中的文件路径
                        input_cfg = dict((task.payload or {}).get("input", {}) or {})
                        for key in ("videoPath", "audioPath", "subtitlePath"):
                            if input_cfg.get(key) == input_path:
                                input_cfg[key] = new_path
                        task.payload = {**task.payload, "input": input_cfg}
                        # 更新所有节点 outputs 中的旧路径引用
                        for node in task.nodes:
                            result = (node.payload or {}).get("result", {}) or {}
                            outputs = result.get("outputs", {}) or {}
                            changed = False
                            for key, value in outputs.items():
                                if isinstance(value, str) and value == input_path:
                                    outputs[key] = new_path
                                    changed = True
                            if changed:
                                node.payload = {**node.payload, "result": {**result, "outputs": outputs}}
                        session.flush()
                        # 同步写出兼容 task.json
                        try:
                            _write_legacy_task(task, Path(task_dir))
                        except Exception as e:
                            print(f"[FileRename] Warning: 重写 task.json 失败: {e}")
                        print(f"[FileRename] DB 同步完成: {input_path} -> {new_path}")
            except Exception as e:
                print(f"[FileRename] Warning: 同步控制平面 DB 失败: {e}")

        if callback:
            callback(100, f"完成: {new_name}")

        return {
            "artifacts": [new_path],
            "outputs": {"any": new_path},
        }


StepFileRename = S_FileRename
