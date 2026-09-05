"""s_hyperframes_creative: HyperFrames 创意节点。

两步走工作流的第一步 —— 把原始输入（URL / 主题 / PR / 素材）收敛成一份可执行的
创意简报 ``BRIEF.md``：

- ``mode=create``：由小 Pi 会话按 HyperFrames 意图访谈写简报（默认）
- ``mode=load``  ：直接加载已有的 BRIEF.md，稳定复用既有工作流，不调用大模型

输出 BRIEF.md、项目目录与一句话摘要，供「HyperFrames 渲染」节点接续。
"""
from pathlib import Path
from typing import Callable, Optional

from backend.steps.s_hyperframes_base import (
    HyperFramesBase,
    _config,
    _inputs,
    _rel_or_abs,
)


class S_HyperFramesCreative(HyperFramesBase):
    step_id = "hyperframes_creative"
    step_name = "HyperFrames 创意"
    result_base = "hyperframes_brief"

    def validate_inputs(self, task_dir: str) -> bool:
        config, inputs = _config(self), _inputs(self)
        if str(config.get("mode") or "create").strip().lower() == "load":
            return True
        if str(config.get("subject") or "").strip():
            return True
        # 没有显式主题时，允许由连线输入提供
        return bool(inputs.get("source") or inputs.get("assets") or inputs.get("any"))

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        config, inputs = _config(self), _inputs(self)
        result = self.run_creative_phase(
            task_dir, config, inputs,
            callback=callback, cancel_callback=cancel_callback,
            progress_range=(5, 95),
        )

        brief = Path(result["brief"])
        project_dir = Path(result["project_dir"])
        payload = {
            **result,
            "mode": str(config.get("mode") or "create"),
        }
        result_path = self._write_result(task_dir, payload)

        if callback:
            callback(100, f"创意完成：{brief.name}")

        return {
            "artifacts": [
                _rel_or_abs(task_dir, result_path),
                _rel_or_abs(task_dir, brief),
            ],
            "outputs": {
                "brief": _rel_or_abs(task_dir, brief),
                "project_dir": _rel_or_abs(task_dir, project_dir),
                "summary": str(result.get("summary") or ""),
            },
        }


StepHyperFramesCreative = S_HyperFramesCreative
