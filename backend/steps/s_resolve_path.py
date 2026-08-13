"""s_resolve_path: Resolve a relative path against the task directory."""
import os
from typing import Callable, Optional

from backend.steps.base_step import BaseStep


class S_ResolvePath(BaseStep):
    step_id = "s_resolve_path"
    step_name = "取文件路径"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return True

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        relative_path = node_config.get("relative_path", "").strip()
        # Allow upstream input to override or provide the relative path
        if not relative_path:
            relative_path = step_inputs.get("input", "")
            if isinstance(relative_path, str):
                relative_path = relative_path.strip()

        if not relative_path:
            raise ValueError("未设置相对路径。请在节点配置中填写相对路径。")

        # Normalize path separators
        relative_path = relative_path.replace("\\", "/").lstrip("/")

        resolved = os.path.normpath(os.path.join(task_dir, relative_path))

        if callback:
            callback(100, f"路径: {resolved}")

        return {
            "artifacts": [],
            "outputs": {
                "output": resolved,
            },
        }
