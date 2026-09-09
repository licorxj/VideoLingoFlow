"""s_track_add_media: 将上游素材按卡片配置添加到剪辑项目轨道。

链路定位：接收上游剪辑项目 JSON 与任意类型素材文件，按用户选择的素材类型
（视频/音频/图片/文字）将素材写入指定轨道（可新建轨道、轨道尾部或自定义
插入点），输出更新后的剪辑项目 JSON，供下游继续接力。
"""
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from backend.editor.repository import EditorProjectRepository
from backend.steps.base_step import BaseStep

# 素材类型 → 承载轨道类型（图片与视频共用 video 轨道）
TRACK_TYPE_FOR = {"video": "video", "image": "video", "audio": "audio", "text": "text"}


class S_TrackAddMedia(BaseStep):
    step_id = "add_track_media"
    step_name = "添加剪辑素材到轨道"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        # 输出为剪辑链共享文件 output/editing_project.json：
        # 共享文件无法作为本节点完成标记（上游节点也会写它），统一返回 False，
        # 由引擎按 DB 中记录的本节点 outputs 判定是否已完成。
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    @staticmethod
    def _num(config: dict, key: str, default: float) -> float:
        try:
            value = float(config.get(key))
            return value
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _new_track(track_type: str, name: str) -> dict[str, Any]:
        track: dict[str, Any] = {
            "id": f"track_{uuid.uuid4().hex[:12]}",
            "type": track_type,
            "name": name,
            "elements": [],
        }
        if track_type == "video":
            track.update({"isMain": False, "muted": False, "hidden": False, "transitions": []})
        elif track_type == "audio":
            track.update({"isMain": False, "muted": False})
        else:
            track.update({"hidden": False})
        return track

    def _resolve_media_type(self, config: dict, media_path: Path | None) -> str:
        media_type = str(config.get("media_type") or "").strip().lower()
        if media_type in TRACK_TYPE_FOR:
            return media_type
        if media_path is not None:
            inferred = EditorProjectRepository()._media_type_for_path(media_path)
            if inferred:
                return inferred
        raise ValueError("无法确定素材类型，请在节点卡片上选择素材类型")

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        task_id = os.path.basename(os.path.normpath(task_dir))
        config = getattr(self, "_node_config", {}) or {}
        inputs = getattr(self, "_step_inputs", {}) or {}
        repository = EditorProjectRepository()

        if callback:
            callback(15, "正在加载剪辑项目")
        # 接力上游剪辑项目 JSON；无上游时使用仓库当前状态
        project_input = str(inputs.get("project") or "")
        if project_input and os.path.isfile(project_input):
            with open(project_input, "r", encoding="utf-8") as handle:
                snapshot = repository.restore_snapshot(task_id, json.load(handle), updated_by="add_track_media")
        else:
            try:
                snapshot = repository.snapshot(task_id)
            except Exception:
                snapshot = repository.import_assets(task_id, [])

        # 注册素材文件（文字素材不需要文件）
        media_value = str(inputs.get("media") or "")
        media_path = Path(media_value) if media_value else None
        if media_path is not None and not media_path.is_absolute():
            media_path = Path(task_dir) / media_path
        media_type = self._resolve_media_type(config, media_path if media_path else None)

        asset = None
        if media_type != "text":
            if media_path is None or not media_path.is_file():
                raise ValueError(f"素材类型为「{media_type}」，但未接收到有效的素材文件")
            if callback:
                callback(35, "正在注册素材资产")
            # 任务目录外的素材（如本地上传/外部路径）：先复制进 editor/media/，
            # 剪辑仓库资产以任务目录相对路径管理，外部路径无法直接注册
            resolved = media_path.resolve()
            root = Path(task_dir).resolve()
            if root not in resolved.parents:
                media_dir = Path(task_dir) / "editor" / "media"
                media_dir.mkdir(parents=True, exist_ok=True)
                target = media_dir / f"{uuid.uuid4().hex[:8]}_{media_path.name}"
                shutil.copy2(resolved, target)
                media_path = target
            metadata = repository._media_metadata(media_path.resolve(), media_type)
            asset = repository.register_asset(
                task_id,
                media_path.resolve(),
                asset_type=media_type,
                source="track_media",
                duration=metadata.get("duration"),
                width=metadata.get("width"),
                height=metadata.get("height"),
            )

        if callback:
            callback(55, "正在写入时间线轨道")
        project = snapshot.get("project") or {}
        scenes = project.get("scenes") or []
        scene = next((s for s in scenes if isinstance(s, dict) and s.get("id") == project.get("currentSceneId")), None)
        scene = scene if isinstance(scene, dict) else (scenes[0] if scenes else {})
        tracks = scene.setdefault("tracks", [])

        track_type = TRACK_TYPE_FOR[media_type]
        if config.get("new_track"):
            default_name = {"video": "视频轨道", "image": "图片轨道", "audio": "音频轨道", "text": "文字轨道"}[media_type]
            track = self._new_track(track_type, str(config.get("track_name") or "").strip() or default_name)
            tracks.append(track)
        else:
            track = next((t for t in tracks if isinstance(t, dict) and t.get("type") == track_type), None)
            if track is None:
                default_name = {"video": "视频轨道", "image": "图片轨道", "audio": "音频轨道", "text": "文字轨道"}[media_type]
                track = self._new_track(track_type, default_name)
                tracks.append(track)

        # 幂等重入（单节点重跑=替换语义）：先移除本节点上次添加的元素，避免重复叠加
        source_node = str(getattr(self, "_node_id", "") or "")
        for t in scene.get("tracks", []):
            if isinstance(t, dict) and isinstance(t.get("elements"), list):
                t["elements"] = [
                    e for e in t["elements"]
                    if not (isinstance(e, dict) and str(e.get("sourceNode") or "") == source_node)
                ]

        # 插入时间点：轨道尾部 or 自定义
        if str(config.get("insert_mode") or "end").strip().lower() == "custom":
            start = max(self._num(config, "insert_time", 0.0), 0.0)
        else:
            start = max(
                (
                    float(element.get("startTime", 0) or 0) + float(element.get("duration", 0) or 0)
                    for element in track.get("elements", [])
                    if isinstance(element, dict)
                ),
                default=0.0,
            )

        # 素材时长：视频/音频按真实时长，图片/文字用卡片设置的静态时长
        if media_type in ("video", "audio"):
            duration = float(asset.duration) if asset and asset.duration else 5.0
        else:
            duration = max(self._num(config, "static_duration", 3.0), 0.1)

        pos_x = self._num(config, "pos_x", 0.0)
        pos_y = self._num(config, "pos_y", 0.0)
        element_id = f"element_{uuid.uuid4().hex[:12]}"

        if media_type in ("video", "image"):
            element: dict[str, Any] = {
                "id": element_id,
                "type": media_type,
                "name": asset.name if asset else media_type,
                "mediaId": asset.id if asset else "",
                "startTime": start,
                "duration": duration,
                "trimStart": 0,
                "trimEnd": 0,
                "opacity": self._num(config, "opacity", 1.0),
                "sourceNode": source_node,
                "transform": {
                    "position": {"x": pos_x, "y": pos_y},
                    "scale": self._num(config, "scale", 1.0),
                    "rotate": self._num(config, "rotate", 0.0),
                },
            }
            if media_type == "video":
                element["hidden"] = False
        elif media_type == "audio":
            element = {
                "id": element_id,
                "type": "audio",
                "sourceType": "upload",
                "name": asset.name if asset else "audio",
                "mediaId": asset.id if asset else "",
                "startTime": start,
                "duration": duration,
                "trimStart": 0,
                "trimEnd": 0,
                "volume": self._num(config, "volume", 1.0),
                "muted": bool(config.get("muted", False)),
                "sourceNode": source_node,
            }
        else:  # text
            element = {
                "id": element_id,
                "type": "text",
                "name": "Text",
                "content": str(config.get("content") or ""),
                "startTime": start,
                "duration": duration,
                "trimStart": 0,
                "trimEnd": 0,
                "fontSize": self._num(config, "font_size", 5.0),
                "fontFamily": str(config.get("font_family") or "Arial"),
                "color": str(config.get("color") or "#ffffff"),
                "backgroundColor": str(config.get("background_color") or "rgba(0, 0, 0, 0.7)"),
                "textAlign": str(config.get("text_align") or "center"),
                "fontWeight": str(config.get("font_weight") or "normal"),
                "sourceNode": source_node,
                "transform": {"position": {"x": pos_x, "y": pos_y}, "scale": 1, "rotate": 0},
                "opacity": 1,
            }
        track.setdefault("elements", []).append(element)

        repository.save_project(
            task_id,
            project,
            expected_revision=int(snapshot.get("revision") or 1),
            updated_by="add_track_media",
        )

        if callback:
            callback(80, "正在导出剪辑项目 JSON")
        latest = repository.snapshot(task_id)
        output_dir = Path(task_dir) / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        # 写回剪辑链共享项目文件（与上游输入同一个文件，原位修改）
        path = output_dir / "editing_project.json"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "taskId": task_id,
                    "revision": latest.get("revision"),
                    "project": latest.get("project"),
                    "assets": latest.get("assets"),
                    "lastWriter": source_node,
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )
        if callback:
            callback(100, "素材已添加到轨道")
        return {
            "artifacts": [str(path)],
            "outputs": {"project": str(path)},
        }
