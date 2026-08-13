"""s_timed_delay: Wait for a specified time, then pass through upstream output.

Logic:
  1. Get input (any file path from upstream)
  2. Calculate wait duration based on mode (time_point / countdown)
  3. Optionally add random tail seconds
  4. Sleep for the calculated duration
  5. Pass through the input as output unchanged
"""
import os
import time
import random
import json
from datetime import datetime, timedelta
from typing import Callable, Optional

from backend.steps.base_step import BaseStep


class S_TimedDelay(BaseStep):
    step_id = "timed_delay"
    step_name = "定时执行"
    dependencies = []
    artifacts = []

    def check_artifact(self, task_dir: str) -> bool:
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def _resolve_input_path(self, step_inputs: dict) -> str:
        """Resolve input path from any port."""
        for key in ("any", "video", "audio", "subtitle", "text", "json"):
            val = step_inputs.get(key, "")
            if val and isinstance(val, str):
                return val
        return ""

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        if callback:
            callback(5, "解析定时配置...")

        # 1. Get input path (pass-through)
        input_path = self._resolve_input_path(step_inputs)

        # 2. Read config
        delay_mode = node_config.get("delay_mode", "countdown")
        # Handle string booleans from frontend
        random_tail_enabled = node_config.get("random_tail_enabled", False)
        if isinstance(random_tail_enabled, str):
            random_tail_enabled = random_tail_enabled.lower() in ("true", "1", "yes")

        # 3. Calculate wait seconds
        wait_seconds = 0

        if delay_mode == "time_point":
            # Time point mode: wait until the specified time
            # Combine separate date and time fields
            target_date = node_config.get("target_date", "")
            target_time_str = node_config.get("target_time", "")
            if not target_date and not target_time_str:
                raise ValueError("时间点模式下未设置目标日期和时间")
            # Build ISO datetime string from date + time
            if target_date and target_time_str:
                datetime_str = f"{target_date}T{target_time_str}"
            elif target_date:
                datetime_str = f"{target_date}T00:00"
            else:
                # Only time provided, use today's date
                datetime_str = f"{datetime.now().strftime('%Y-%m-%d')}T{target_time_str}"
            try:
                target_dt = datetime.fromisoformat(datetime_str)
                now = datetime.now()
                diff = (target_dt - now).total_seconds()
                if diff <= 0:
                    print(f"[TimedDelay] 目标时间 {datetime_str} 已过，不等待")
                    wait_seconds = 0
                else:
                    wait_seconds = diff
                    print(f"[TimedDelay] 等待到 {datetime_str}，需等待 {wait_seconds:.1f} 秒")
            except ValueError as e:
                raise ValueError(f"无法解析目标时间 '{datetime_str}': {e}")

        elif delay_mode == "countdown":
            # Countdown mode: wait for the specified duration
            hours = int(node_config.get("countdown_hours", 0) or 0)
            minutes = int(node_config.get("countdown_minutes", 0) or 0)
            seconds = int(node_config.get("countdown_seconds", 0) or 0)
            wait_seconds = hours * 3600 + minutes * 60 + seconds
            if wait_seconds <= 0:
                print("[TimedDelay] 倒计时为0，不等待")
            else:
                print(f"[TimedDelay] 倒计时 {hours}时{minutes}分{seconds}秒 = {wait_seconds} 秒")
        else:
            raise ValueError(f"未知的延迟模式: {delay_mode}")

        # 4. Add random tail if enabled
        if random_tail_enabled:
            random_min = float(node_config.get("random_min", 0) or 0)
            random_max = float(node_config.get("random_max", 0) or 0)
            if random_max > 0:
                random_tail = random.uniform(
                    max(0, random_min), random_max
                )
                wait_seconds += random_tail
                print(f"[TimedDelay] 随机追加 {random_tail:.1f} 秒 (范围 {random_min}~{random_max})")

        # 5. Sleep
        if wait_seconds > 0:
            if callback:
                callback(10, f"等待 {wait_seconds:.0f} 秒...")

            start_time = time.time()
            remaining = wait_seconds
            while remaining > 0:
                # Sleep in small chunks to allow cancellation checks
                chunk = min(remaining, 5)
                time.sleep(chunk)
                elapsed = time.time() - start_time
                remaining = wait_seconds - elapsed
                if callback:
                    pct = int(10 + 80 * elapsed / wait_seconds)
                    callback(min(pct, 90), f"等待中... 剩余 {max(0, remaining):.0f} 秒")
        else:
            if callback:
                callback(90, "无需等待")

        # 6. Pass through input as output
        if callback:
            callback(100, f"完成，等待 {wait_seconds:.1f} 秒后继续")

        outputs = {}
        if input_path:
            outputs["any"] = input_path
        elif input_path == "":
            # No input, just output empty
            print("[TimedDelay] 无输入文件，仅等待")

        return {
            "artifacts": [],
            "outputs": outputs,
        }


StepTimedDelay = S_TimedDelay
