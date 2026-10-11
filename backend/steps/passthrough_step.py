"""Preview node passthrough step.

预览类节点（视频预览器 / 图片预览器 / 图片对比 / 音频多轨预览）本身不做计算，
只把连入的输入原样透传到「同名输出端口」，便于下游节点直接从预览节点引用素材。
输出端口 id 与输入端口 id 一一对应（由节点定义的 outputs 决定）。
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
        # _step_inputs 的 key 即节点输入端口 id（等于对应的输出端口 id）：直接透传
        step_inputs = getattr(self, "_step_inputs", None) or {}
        outputs = {
            str(port_id): value
            for port_id, value in step_inputs.items()
            if value not in (None, "")
        }
        if callback:
            callback(100, f"透传 {len(outputs)} 路输入到输出端口")
        return {"artifacts": [], "outputs": outputs}
