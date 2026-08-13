"""s_run_wait: 运行等待节点。

开启：等待指定时长，时长耗尽后抛出“等待超时”错误结束工作流；
关闭：直接跳过（标记为已完成）并透传输入到输出。
"""
import time
from typing import Callable, Optional

from backend.control_plane.runtime import TaskCancelledError, TaskTimeoutError
from backend.steps.base_step import BaseStep


class S_RunWait(BaseStep):
    step_id = "s_run_wait"
    step_name = "运行等待"
    dependencies = []
    artifacts = []

    def check_artifact(self, task_dir: str) -> bool:
        return False  # 无文件产物，始终执行等待逻辑

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        input_value = step_inputs.get("input", "")

        enabled = node_config.get("enabled", False)
        if isinstance(enabled, str):
            enabled = enabled.lower() in ("true", "1", "yes")

        try:
            raw_wait = node_config.get("wait_seconds", 60)
            wait_seconds = float(raw_wait) if raw_wait not in (None, "") else 60.0
        except (ValueError, TypeError):
            wait_seconds = 60.0

        # 关闭：跳过等待，直接透传输入到输出
        if not enabled:
            if callback:
                callback(100, "已关闭，跳过等待并透传输入")
            return {"artifacts": [], "outputs": {"output": input_value}}

        if wait_seconds <= 0:
            raise ValueError("等待时长必须大于 0 秒")

        if callback:
            callback(10, f"开始等待 {wait_seconds:g} 秒")
        waited = 0.0
        while waited < wait_seconds:
            chunk = min(1.0, wait_seconds - waited)
            time.sleep(chunk)
            waited += chunk
            if cancel_callback is not None and cancel_callback():
                raise TaskCancelledError("运行等待被取消")
            if callback:
                percent = 10 + int(80 * waited / wait_seconds)
                callback(min(percent, 90), f"等待中 {waited:.1f}/{wait_seconds:g} 秒")

        if callback:
            callback(100, f"等待超时（{wait_seconds:g} 秒），结束工作流")
        raise TaskTimeoutError(f"运行等待超时（已等待 {wait_seconds:g} 秒）")
