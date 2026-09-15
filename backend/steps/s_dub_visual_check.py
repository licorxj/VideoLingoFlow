# -*- coding: utf-8 -*-
"""配音审听及微调节点。

输入配音任务 JSON（s09_tts 输出的 dub_task.json），并把上游输入 JSON 透传到输出（json）。
节点本身不做配音处理：真正的「逐句试听 / 微调 / 重生」在节点卡片的
「打开检查页面」弹窗（DubCheckDialog）中完成，数据读写走 /api/dub-check/*。

可选等待审听：节点配置勾选「是否等待审听」后，执行时进入等待（默认 600 秒），
期间用户在检查页完成试听微调；等待时长到期后自动透传输入 JSON 到输出并继续下游。
"""

import json
import os
import time
from pathlib import Path
from typing import Callable, Optional

from backend.control_plane.runtime import TaskCancelledError
from backend.steps.base_step import BaseStep
from backend.utils.runtime_notifications import push_notification


class S_DubVisualCheck(BaseStep):
    step_id = "dub_visual_check"
    step_name = "配音审听及微调"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        # 检查页是交互式工具，每次运行都应重新读取最新配音任务
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    @staticmethod
    def _resolve(task_dir: str, raw: object) -> Optional[Path]:
        """从上游输入中解析出配音任务 JSON 的绝对路径。"""
        if isinstance(raw, dict):
            for key in ("path", "file", "file_path", "json"):
                value = raw.get(key)
                if isinstance(value, str) and value.strip():
                    raw = value.strip()
                    break
            else:
                return None
        if not isinstance(raw, str) or not raw.strip():
            return None
        value = raw.strip()
        if os.path.isabs(value):
            return Path(value) if os.path.isfile(value) else None
        candidate = Path(task_dir) / value
        return candidate if candidate.is_file() else None

    @staticmethod
    def _wait_audition(node_config: dict) -> tuple[bool, float]:
        """读取「是否等待审听 / 等待时间（秒）」配置。"""
        enabled = node_config.get("wait_audition", False)
        if isinstance(enabled, str):
            enabled = enabled.lower() in ("true", "1", "yes")
        try:
            raw_wait = node_config.get("wait_seconds", 600)
            wait_seconds = float(raw_wait) if raw_wait not in (None, "") else 600.0
        except (TypeError, ValueError):
            wait_seconds = 600.0
        return bool(enabled), wait_seconds

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback=None) -> dict:
        step_inputs = getattr(self, "_step_inputs", {}) or {}
        node_config = getattr(self, "_node_config", {}) or {}
        report = callback or (lambda *a, **k: None)

        report(10, "解析配音任务…")
        dub_path = self._resolve(task_dir, step_inputs.get("json"))
        if dub_path is None:
            raise ValueError(
                "未收到配音任务 JSON：请将「语音合成(TTS)」等上游节点的配音任务输出连接到本节点的 json 输入端口"
            )

        report(30, "读取配音片段…")
        try:
            with open(dub_path, "r", encoding="utf-8") as handle:
                dub_data = json.load(handle)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"读取配音任务 JSON 失败: {dub_path}（{exc}）") from None

        segments = dub_data.get("segments", []) if isinstance(dub_data, dict) else []
        if not isinstance(segments, list):
            segments = []

        # 统计已生成的音频片段数，便于执行日志快速判断配音完整性
        ready = 0
        for seg in segments:
            audio_rel = str(seg.get("audio_file") or "").strip()
            if not audio_rel:
                continue
            audio_abs = audio_rel if os.path.isabs(audio_rel) else os.path.join(task_dir, audio_rel)
            if os.path.isfile(audio_abs) and os.path.getsize(audio_abs) > 0:
                ready += 1

        # 透传上游输入 JSON 到输出（相对 task_dir，供下游按路径读取）
        output_rel = os.path.relpath(str(dub_path), task_dir).replace("\\", "/")

        # ── 可选：等待审听（到期后透传输入 JSON 到输出并继续下游）──────────
        wait_enabled, wait_seconds = self._wait_audition(node_config)
        if wait_enabled:
            if wait_seconds <= 0:
                raise ValueError("等待审听时间必须大于 0 秒")

            try:
                push_notification(
                    kind="info",
                    title="任务等待审听",
                    description=(
                        f"配音审听及微调节点已进入等待：共 {len(segments)} 句，"
                        f"将等待 {int(wait_seconds)} 秒供试听微调，到期自动继续下游。"
                    ),
                    dedup_key=f"dub_visual_check:{task_dir}",
                )
            except Exception as e:  # noqa: BLE001 - 通知失败不影响等待
                print(f"[DubVisualCheck] 发送系统通知失败（不影响等待逻辑）: {e}")

            report(60, f"等待审听中，最长 {wait_seconds:g} 秒…")
            waited = 0.0
            while waited < wait_seconds:
                chunk = min(1.0, wait_seconds - waited)
                time.sleep(chunk)
                waited += chunk
                if cancel_callback is not None and cancel_callback():
                    raise TaskCancelledError("等待审听被取消")
                percent = 60 + int(35 * waited / wait_seconds)
                report(min(percent, 95), f"等待审听中 {waited:.0f}/{wait_seconds:g} 秒")

            report(100, f"等待审听结束（{wait_seconds:g} 秒），透传输入到输出：共 {len(segments)} 句，已生成音频 {ready} 句")
        else:
            report(100, f"配音审听及微调就绪：共 {len(segments)} 句，已生成音频 {ready} 句")

        return {
            "artifacts": [str(dub_path)],
            "outputs": {
                "json": output_rel,
            },
        }
