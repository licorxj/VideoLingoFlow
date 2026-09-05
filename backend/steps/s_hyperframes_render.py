"""s_hyperframes_render: HyperFrames 渲染节点。

两步走工作流的第二步 —— 读取 ``BRIEF.md``，由小 Pi 会话按其中的工作流路由
构建 HyperFrames 合成并渲染成片：

- ``build_and_render``：构建 + 渲染（默认）
- ``build``    ：只构建合成，不渲染
- ``render``   ：对已有合成直接渲染
- ``validate`` ：只做 lint / check / validate

可勾选渲染后 publish，成片会被复制到任务缓存作为节点产物。
"""
from pathlib import Path
from typing import Callable, Optional

from backend.steps.s_hyperframes_base import (
    HyperFramesBase,
    _config,
    _inputs,
    _rel_or_abs,
)


class S_HyperFramesRender(HyperFramesBase):
    step_id = "hyperframes_render"
    step_name = "HyperFrames 渲染"
    result_base = "hyperframes_render"

    def validate_inputs(self, task_dir: str) -> bool:
        config, inputs = _config(self), _inputs(self)
        if inputs.get("brief") or inputs.get("project_dir"):
            return True
        if str(config.get("brief_path") or "").strip():
            return True
        # 上游创意节点把项目目录落在任务缓存下时，BRIEF.md 可被自动发现
        project_dir = self._project_dir(task_dir, config, inputs, create=False)
        return (project_dir / "BRIEF.md").is_file()

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        config, inputs = _config(self), _inputs(self)
        result = self.run_render_phase(
            task_dir, config, inputs,
            callback=callback, cancel_callback=cancel_callback,
            progress_range=(5, 95),
        )

        project_dir = Path(result["project_dir"])
        brief = Path(result["brief"])
        artifacts = []
        outputs: dict[str, str] = {
            "project_dir": _rel_or_abs(task_dir, project_dir),
            "brief": _rel_or_abs(task_dir, brief),
            "url": str(result.get("url") or ""),
        }

        video = str(result.get("video") or "")
        if video and Path(video).is_file():
            artifacts.append(_rel_or_abs(task_dir, Path(video)))
            outputs["video"] = _rel_or_abs(task_dir, Path(video))

        result_path = self._write_result(task_dir, result)
        artifacts.append(_rel_or_abs(task_dir, result_path))

        if callback:
            callback(100, "渲染完成" if video else "渲染阶段结束（未产出成片）")

        return {"artifacts": artifacts, "outputs": outputs}


StepHyperFramesRender = S_HyperFramesRender
