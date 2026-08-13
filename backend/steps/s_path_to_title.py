"""s_path_to_title: Extract path components and assemble a title.

Logic:
  1. Get input text: either from step input or read from file path
  2. Parse path components: filename, parent dir, grandparent dir
  3. Apply user's template to assemble the title
  4. Optionally update task_name in task.json
  5. Output the assembled title as text
"""
import os
import json
from typing import Callable, Optional, Dict

from backend.steps.base_step import BaseStep


class S_PathToTitle(BaseStep):
    step_id = "path_to_title"
    step_name = "路径转标题"
    dependencies = []
    artifacts = []

    def check_artifact(self, task_dir: str) -> bool:
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def _parse_path_components(self, path: str) -> Dict[str, str]:
        """Parse a file path into components: filename, parent, grandparent."""
        result = {"filename": "", "parent": "", "grandparent": ""}
        
        if not path:
            return result
        
        # Normalize path separators
        path = path.replace("\\", "/")
        
        # Split into parts
        parts = path.split("/")
        
        # Filter out empty parts
        parts = [p for p in parts if p]
        
        if not parts:
            return result
        
        # Get filename (last part, without extension)
        last_part = parts[-1]
        if "." in last_part:
            filename = last_part.rsplit(".", 1)[0]
        else:
            filename = last_part
        result["filename"] = filename
        
        # Get parent directory (second to last)
        if len(parts) >= 2:
            result["parent"] = parts[-2]
        
        # Get grandparent directory (third to last)
        if len(parts) >= 3:
            result["grandparent"] = parts[-3]
        
        return result

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        
        print(f"[PathToTitle] node_config: {node_config}")
        print(f"[PathToTitle] step_inputs: {step_inputs}")

        if callback:
            callback(10, "解析输入路径...")

        # 1. Get input path
        input_path = ""
        
        # Check if should read from input node
        read_from_input = node_config.get("read_from_input", False)
        
        if read_from_input:
            # Read from task.json's input field
            task_json_path = os.path.join(task_dir, "task.json")
            if os.path.exists(task_json_path):
                try:
                    with open(task_json_path, "r", encoding="utf-8") as f:
                        task_data = json.load(f)
                    input_config = task_data.get("input", {})
                    input_path = (input_config.get("videoPath") or 
                                  input_config.get("audioPath") or 
                                  input_config.get("subtitlePath") or "")
                    if not input_path:
                        raise ValueError("输入节点中未找到文件路径")
                except Exception as e:
                    print(f"[PathToTitle] 读取输入节点路径失败: {e}")
                    raise ValueError(f"无法读取输入节点路径: {e}")
            else:
                raise ValueError("task.json 不存在")
        else:
            # Get from step input
            input_path = step_inputs.get("text", "") or step_inputs.get("any", "")
            
            # If it looks like a file path, try to read the file content
            if input_path and os.path.isfile(input_path):
                try:
                    with open(input_path, "r", encoding="utf-8") as f:
                        input_path = f.read().strip()
                except Exception as e:
                    print(f"[PathToTitle] 读取文件失败: {e}")

        if not input_path:
            input_path = ""

        if callback:
            callback(30, f"解析路径: {input_path[:50]}...")

        # 2. Parse path components
        components = self._parse_path_components(input_path)
        print(f"[PathToTitle] 路径组件: {components}")

        # 3. Apply template
        template = node_config.get("template", "{filename}")
        
        # Replace placeholders
        title = template
        title = title.replace("{filename}", components.get("filename", ""))
        title = title.replace("{parent}", components.get("parent", ""))
        title = title.replace("{grandparent}", components.get("grandparent", ""))
        
        # Clean up multiple spaces and leading/trailing spaces
        title = " ".join(title.split())
        title = title.strip()

        if callback:
            callback(60, f"生成标题: {title}")

        # 4. Optionally update task_name
        update_task_name = node_config.get("update_task_name", False)
        print(f"[PathToTitle] update_task_name={update_task_name!r} (type={type(update_task_name).__name__}), title={title!r}")
        
        # Handle string "true"/"false" from frontend
        if isinstance(update_task_name, str):
            update_task_name = update_task_name.lower() in ("true", "1", "yes")
        
        if update_task_name and title:
            task_json_path = os.path.join(task_dir, "task.json")
            if os.path.exists(task_json_path):
                try:
                    with open(task_json_path, "r", encoding="utf-8") as f:
                        task_data = json.load(f)
                    old_name = task_data.get("task_name", "")
                    task_data["task_name"] = title
                    with open(task_json_path, "w", encoding="utf-8") as f:
                        json.dump(task_data, f, ensure_ascii=False, indent=2)
                    print(f"[PathToTitle] 更新 task_name: {old_name} -> {title}")
                except Exception as e:
                    print(f"[PathToTitle] 更新 task_name 失败: {e}")

        # 5. Save title to cache file for downstream nodes
        cache_dir = os.path.join(task_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        out_path = os.path.join(cache_dir, "path_to_title.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(title)

        if callback:
            callback(100, f"完成: {title}")

        return {
            "artifacts": [out_path],
            "outputs": {"text": out_path},
        }


StepPathToTitle = S_PathToTitle
