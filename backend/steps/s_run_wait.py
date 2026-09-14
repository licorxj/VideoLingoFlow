"""s_run_wait: 运行等待节点。

开启：等待指定时长，超时后根据 timeout_action 决定行为：
  - error（默认）：抛出「等待超时」错误结束工作流
  - complete：标记为已完成并透传输入到输出，工作流继续执行
关闭：直接跳过（标记为已完成）并透传输入到输出。

进入等待状态时自动发送系统通知提醒用户。
"""
import time
from typing import Callable, Optional

from backend.control_plane.runtime import TaskCancelledError, TaskTimeoutError
from backend.steps.base_step import BaseStep
from backend.utils.runtime_notifications import push_notification


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

        timeout_action = str(node_config.get("timeout_action", "error") or "error")

        # 关闭：跳过等待，直接透传输入到输出
        if not enabled:
            if callback:
                callback(100, "已关闭，跳过等待并透传输入")
            return {"artifacts": [], "outputs": {"output": input_value}}

        if wait_seconds <= 0:
            raise ValueError("等待时长必须大于 0 秒")

        # ── 进入等待状态：发送系统通知 ──────────────────────
        try:
            push_notification(
                kind="info",
                title="任务进入等待状态",
                description=(
                    f"当前任务已进入运行等待节点，"
                    f"将等待 {int(wait_seconds)} 秒。"
                    f"请尽快完成过程检验或编辑工作。"
                ),
                dedup_key=f"run_wait:{task_dir}",
            )
        except Exception as e:
            print(f"[RunWait] 发送系统通知失败（不影响等待逻辑）: {e}")

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

        # ── 超时处理 ────────────────────────────────────────
        if timeout_action == "complete":
            if callback:
                callback(100, f"等待完成（{wait_seconds:g} 秒），继续执行下游节点")
            return {"artifacts": [], "outputs": {"output": input_value}}
        else:
            # 默认行为：抛出超时错误结束工作流
            if callback:
                callback(100, f"等待超时（{wait_seconds:g} 秒），结束工作流")
            raise TaskTimeoutError(f"运行等待超时（已等待 {wait_seconds:g} 秒）")
