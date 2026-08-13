"""
Passthrough step for workflow nodes that exist only in the editor UI.
These nodes have no backend execution behavior and should succeed immediately.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from backend.steps.base_step import BaseStep


class PassthroughStep(BaseStep):
    step_id = "passthrough"
    step_name = "直通节点"
    dependencies: list[str] = []
    artifacts: list[str] = []

    def check_artifact(self, task_dir: str) -> bool:
        return True

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> Dict[str, Any]:
        if callback:
            callback(100, "跳过无执行逻辑的节点")
        return {"skipped": True}
