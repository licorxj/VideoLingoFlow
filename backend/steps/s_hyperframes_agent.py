"""s_hyperframes_agent: HyperFrames 智能体复合节点。

一个节点跑完「创意 → 渲染」整条链路，或直接调用本项目的 piagent（小 Pi）框架
执行一段 HyperFrames 任务。与拆分节点的区别在于编排粒度：

- ``span=full``    ：同一节点内依次跑创意与渲染，共享同一个项目目录
- ``span=creative``：只跑创意（等价于 HyperFrames 创意节点）
- ``span=render``  ：只跑渲染（等价于 HyperFrames 渲染节点）

创意阶段会自动识别已存在的 BRIEF.md（连线输入或节点设置），命中即按加载模式
复用既有工作流，不重复做意图访谈。
"""
from pathlib import Path
from typing import Callable, Optional

from backend.steps.s_hyperframes_base import (
    HyperFramesBase,
    _config,
    _inputs,
    _rel_or_abs,
)
from backend.utils import hyperframes as hf


class S_HyperFramesAgent(HyperFramesBase):
    step_id = "hyperframes_agent"
    step_name = "HyperFrames 智能体"
    result_base = "hyperframes_agent"

    def validate_inputs(self, task_dir: str) -> bool:
        config, inputs = _config(self), _inputs(self)
        span = str(config.get("span") or "full")
        if span == "render":
            return True
        if inputs.get("brief") or str(config.get("brief_path") or "").strip():
            return True
        if str(config.get("subject") or "").strip():
            return True
        return bool(inputs.get("source") or inputs.get("assets") or inputs.get("any"))

    def _has_existing_brief(self, task_dir: str, config: dict, inputs: dict) -> bool:
        if inputs.get("brief"):
            return True
        if str(config.get("brief_path") or "").strip():
            return True
        project_dir = self._project_dir(task_dir, config, inputs, create=False)
        return hf.find_brief(project_dir) is not None

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        config, inputs = _config(self), _inputs(self)
        span = str(config.get("span") or "full")
        if span not in ("full", "creative", "render"):
            raise ValueError(f"未知的执行跨度：{span}")

        result: dict = {"span": span}
        creative: Optional[dict] = None

        if span in ("full", "creative"):
            creative_config = dict(config)
            if self._has_existing_brief(task_dir, config, inputs):
                # 已有简报时按加载模式复用既有工作流
                creative_config["mode"] = "load"
                if callback:
                    callback(4, "检测到已有 BRIEF.md，按加载模式复用")
            result.update(self.run_creative_phase(
                task_dir, creative_config, inputs,
                callback=callback, cancel_callback=cancel_callback,
                progress_range=(5, 45),
            ))
            creative = result

        if span in ("full", "render"):
            result.update(self.run_render_phase(
                task_dir, config, inputs, creative=creative,
                callback=callback, cancel_callback=cancel_callback,
                progress_range=(50 if span == "full" else 5, 95),
            ))

        project_dir = Path(result.get("project_dir") or self._project_dir(task_dir, config, inputs))
        brief = result.get("brief") or ""
        video = result.get("video") or ""
        if callback and not video and span != "creative":
            callback(96, "未产出成片：请检查渲染阶段日志")

        summary = str(result.get("summary") or result.get("message") or "")
        if video:
            summary = f"{summary}｜成片：{Path(video).name}".lstrip("｜")

        artifacts = [_rel_or_abs(task_dir, self._write_result(task_dir, result))]
        outputs: dict[str, str] = {
            "project_dir": _rel_or_abs(task_dir, project_dir),
            "brief": _rel_or_abs(task_dir, Path(brief)) if brief and Path(brief).is_file() else "",
            "text": summary,
        }
        if video and Path(video).is_file():
            artifacts.append(_rel_or_abs(task_dir, Path(video)))
            outputs["video"] = _rel_or_abs(task_dir, Path(video))

        if callback:
            callback(100, "HyperFrames 智能体完成")

        return {"artifacts": artifacts, "outputs": outputs}


StepHyperFramesAgent = S_HyperFramesAgent
