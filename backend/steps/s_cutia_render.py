"""s_cutia_render: 无头渲染剪辑项目并导出成片。

接收上游「剪辑AI Agent」或「Cutia 交互剪辑」产出的剪辑项目，驱动无头浏览器
加载 Cutia 渲染内核完成导出，实现无需人工介入的剪辑闭环。
"""
import json
import os
from pathlib import Path
from typing import Callable, Optional

from backend.editor.headless_renderer import HeadlessRenderError, ensure_chromium_installed, render_project
from backend.editor.repository import EditorProjectRepository
from backend.steps.base_step import BaseStep

EXPORT_FORMATS = {"mp4", "webm"}
EXPORT_QUALITIES = {"low", "medium", "high", "very_high"}


class S_CutiaRender(BaseStep):
    step_id = "cutia_render"
    step_name = "剪辑渲染"
    dependencies = []

    @staticmethod
    def _task_id(task_dir: str) -> str:
        return os.path.basename(os.path.normpath(task_dir))

    def _latest_export(self, task_dir: str) -> str:
        """返回任务下最新一次剪辑导出成片的绝对路径。"""
        repository = EditorProjectRepository()
        try:
            assets = repository.snapshot(self._task_id(task_dir))["assets"]
        except Exception:
            return ""
        exports = [
            asset for asset in assets
            if asset.get("source") == "editor_export" and asset.get("type") == "video"
        ]
        for asset in reversed(exports):
            path = Path(task_dir) / str(asset.get("relative_path") or "")
            if path.is_file():
                return str(path)
        return ""

    def check_artifact(self, task_dir: str) -> bool:
        return bool(self._latest_export(task_dir))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        task_id = self._task_id(task_dir)
        config = getattr(self, "_node_config", {}) or {}
        repository = EditorProjectRepository()

        # 接力上游「剪辑AI Agent / Cutia 交互剪辑」输出的剪辑项目 JSON：优先渲染该快照
        project_input = str((getattr(self, "_step_inputs", {}) or {}).get("project") or "")
        if project_input and os.path.isfile(project_input):
            with open(project_input, "r", encoding="utf-8") as handle:
                snapshot = repository.restore_snapshot(task_id, json.load(handle), updated_by="cutia_render")
        else:
            try:
                snapshot = repository.snapshot(task_id)
            except Exception:
                snapshot = repository.import_assets(task_id, [])

        project = snapshot.get("project") or {}
        assets = snapshot.get("assets") or []
        revision = int(snapshot.get("revision") or 1)

        if not project.get("scenes"):
            raise ValueError("剪辑项目为空，请先由「剪辑AI Agent」或「Cutia 交互剪辑」生成时间线")

        export_format = str(config.get("export_format") or "mp4").strip().lower()
        if export_format not in EXPORT_FORMATS:
            export_format = "mp4"
        quality = str(config.get("quality") or "high").strip().lower()
        if quality not in EXPORT_QUALITIES:
            quality = "high"

        try:
            fps = int(config.get("fps") or 0) or None
        except (TypeError, ValueError):
            fps = None

        include_audio = bool(config.get("include_audio", True))
        browser_channel = str(config.get("browser_channel") or "").strip() or None
        try:
            timeout_minutes = float(config.get("timeout_minutes") or 60)
        except (TypeError, ValueError):
            timeout_minutes = 60.0

        def progress(percent: int, message: str) -> None:
            if callback:
                callback(max(0, min(100, int(percent))), message)

        # 渲染前自检 Playwright Chromium 内核：缺失或版本不匹配时自动下载
        # （用户显式指定 browser_channel 时使用系统浏览器，无需下载内核）
        if not browser_channel:
            if callback:
                callback(2, "正在检查 Playwright Chromium 内核")
            ensure_chromium_installed(callback)

        try:
            render_project(
                task_id=task_id,
                project=project,
                assets=assets,
                revision=revision,
                export_format=export_format,
                quality=quality,
                fps=fps,
                include_audio=include_audio,
                browser_channel=browser_channel,
                timeout=max(60.0, timeout_minutes * 60.0),
                progress=progress,
            )
        except HeadlessRenderError as exc:
            raise RuntimeError(str(exc)) from exc

        export_path = self._latest_export(task_dir)
        if not export_path:
            raise RuntimeError("剪辑渲染已结束，但未找到导出的成片文件")

        return {
            "artifacts": [export_path],
            "outputs": {"video": export_path},
        }
