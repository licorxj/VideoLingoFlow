"""工作流步骤：将任意类型素材添加到剪辑工作台的素材库，不写入时间线轨道。

与「添加剪辑素材到轨道」(add_track_media) 行为一致地收集上游素材并恢复剪辑项目，
但只把素材注册到剪辑仓库（editor/assets.json），不构造时间线元素，供后续剪辑
操作（人工精修 / 剪辑AI Agent）按需取用。
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Callable, Optional

from backend.editor.repository import EditorProjectRepository
from backend.steps.base_step import BaseStep


# 与编辑器侧 ASSET_CATEGORY 推导规则保持一致：按文件扩展名 + ffprobe mime 粗判
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
_VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".m4v"}
_AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
_SUBTITLE_SUFFIXES = {".srt", ".vtt", ".ass", ".ssa"}

_CATEGORY_FROM_MIME = {
    "image": "image",
    "video": "video",
    "audio": "audio",
}


class S_AddMediaToLibrary(BaseStep):
    """添加素材到剪辑工作台素材库（不上轨道）。"""

    name = "添加素材到剪辑"
    description = "将任意类型素材注册到剪辑工作台的素材库（不写入时间线轨道），供后续剪辑操作调用"
    input_types: list[str] = ["json", "any"]
    output_types: list[str] = ["json"]

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    # ------------------------------------------------------------------ #
    # 工具方法
    # ------------------------------------------------------------------ #
    @staticmethod
    def _guess_media_type(media_path: Path) -> Optional[str]:
        """从扩展名粗判类别；探测失败/文本类直接返回 None（按 text 处理）。"""
        if not isinstance(media_path, Path):
            media_path = Path(media_path)
        suffix = media_path.suffix.lower()
        if suffix in _IMAGE_SUFFIXES:
            return "image"
        if suffix in _VIDEO_SUFFIXES:
            return "video"
        if suffix in _AUDIO_SUFFIXES:
            return "audio"
        if suffix in _SUBTITLE_SUFFIXES:
            return "subtitle"
        return None

    def _resolve_media_path(self, raw: object, task_dir: str) -> Optional[Path]:
        """从上游任意类型输入中提取首个有效文件路径。

        接受：单条字符串路径 / 字符串列表 / dict（含 path/file/url 等键）。
        """
        if raw is None:
            return None
        candidates: list[object] = []
        if isinstance(raw, str):
            candidates = [raw]
        elif isinstance(raw, dict):
            for key in ("path", "file", "file_path", "url"):
                value = raw.get(key)
                if isinstance(value, str):
                    candidates.append(value)
                    break
        elif isinstance(raw, (list, tuple)):
            for item in raw:
                if isinstance(item, str):
                    candidates.append(item)
                elif isinstance(item, dict):
                    for key in ("path", "file", "file_path", "url"):
                        value = item.get(key)
                        if isinstance(value, str):
                            candidates.append(value)
                            break
        for cand in candidates:
            if not cand:
                continue
            try:
                p = Path(cand)
                if p.is_file():
                    return p
            except OSError:
                continue
        return None

    # ------------------------------------------------------------------ #
    # 主入口
    # ------------------------------------------------------------------ #
    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        task_id = os.path.basename(os.path.normpath(task_dir))
        inputs = getattr(self, "_step_inputs", {}) or {}
        repository = EditorProjectRepository()

        # 1) 接力上游剪辑项目 JSON：恢复为当前项目（不上轨道，仅保素材库上下文一致）
        project_input = str(inputs.get("project") or "")
        if project_input and Path(project_input).is_file():
            if callback:
                callback(15, "正在加载上游剪辑项目")
            with open(project_input, "r", encoding="utf-8") as handle:
                repository.restore_snapshot(task_id, json.load(handle), updated_by="add_media_to_library")

        # 2) 解析素材端口
        media_path = self._resolve_media_path(inputs.get("media"), task_dir)
        if media_path is None:
            if callback:
                callback(100, "未收到素材：仅透传剪辑项目")
            snapshot = repository.snapshot(task_id)
            latest = snapshot["project"]
            project_path = Path(task_dir) / "output" / "editing_project.json"
            project_path.parent.mkdir(parents=True, exist_ok=True)
            with open(project_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "taskId": task_id,
                        "revision": snapshot.get("revision"),
                        "project": latest,
                        "assets": snapshot.get("assets"),
                        "lastWriter": str(getattr(self, "_node_id", "") or ""),
                    },
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
            return {"outputs": {"project": str(project_path)}}

        # 3) 任务目录外的素材先复制进 editor/media/，便于仓库以相对路径管理
        resolved = media_path.resolve()
        root = Path(task_dir).resolve()
        if root not in resolved.parents:
            media_dir = Path(task_dir) / "editor" / "media"
            media_dir.mkdir(parents=True, exist_ok=True)
            target = media_dir / f"{uuid.uuid4().hex[:8]}_{media_path.name}"
            shutil.copy2(resolved, target)
            media_path = target

        if callback:
            callback(35, "正在识别素材类型")

        # 4) 类别探测：扩展名 → ffprobe mime 兜底
        asset_type = self._guess_media_type(media_path)
        if asset_type is None:
            try:
                mime = repository._media_metadata(media_path.resolve(), "auto").get("mime")
                if isinstance(mime, str):
                    primary = mime.split("/", 1)[0]
                    asset_type = _CATEGORY_FROM_MIME.get(primary)
            except Exception:  # noqa: BLE001 - 探测失败按文本处理
                asset_type = None
        if asset_type not in {"image", "video", "audio", "subtitle"}:
            asset_type = "text"  # 兜底：作为文本资源注册（无文件也可入库）

        # 5) 探测元数据（文本素材无文件可探测，跳过）
        metadata: dict = {}
        if asset_type != "text":
            try:
                metadata = repository._media_metadata(media_path.resolve(), asset_type)
            except Exception:  # noqa: BLE001 - 元数据探测失败不影响入库
                metadata = {}

        if callback:
            callback(55, f"正在入库素材（{asset_type}）")

        # 6) 注册到仓库；source 标记为入库节点，便于追溯
        asset = repository.register_asset(
            task_id,
            media_path.resolve(),
            asset_type=asset_type,
            source="library_add",
            duration=metadata.get("duration"),
            width=metadata.get("width"),
            height=metadata.get("height"),
        )

        # 7) 触发一次 save_project 使 revision 递增（确保引擎按 outputs 判定本节点已完成），
        #    不构造任何时间线元素；剪辑项目内容保持不变，仅写入工程文件
        try:
            current = repository.snapshot(task_id)
            repository.save_project(
                task_id,
                current["project"],
                current.get("revision") or 1,
                updated_by="add_media_to_library",
            )
        except Exception:  # noqa: BLE001 - 即便落盘失败也返回已注册的素材信息
            pass

        if callback:
            callback(90, "正在输出剪辑项目 JSON")

        # 8) 导出共享剪辑项目 JSON（与剪辑链其他节点共用同一文件名）
        snapshot = repository.snapshot(task_id)
        project_path = Path(task_dir) / "output" / "editing_project.json"
        project_path.parent.mkdir(parents=True, exist_ok=True)
        with open(project_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "taskId": task_id,
                    "revision": snapshot.get("revision"),
                    "project": snapshot.get("project"),
                    "assets": snapshot.get("assets"),
                    "lastWriter": str(getattr(self, "_node_id", "") or ""),
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )

        return {
            "outputs": {
                "project": str(project_path),
                "asset_id": getattr(asset, "id", "") if asset else "",
                "asset_type": asset_type,
            }
        }

    def check_artifact(self, task_dir: str) -> bool:
        # 共享文件 editing_project.json 不能作为完成标记（其他剪辑链节点也会写它），
        # 完成判定完全交给引擎按 DB 中记录的本节点 outputs
        return False