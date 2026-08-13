from __future__ import annotations

import json
import mimetypes
import os
import re
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from backend.editor.models import AssetRecord, ImportCandidate
TASKS_ROOT = Path(__file__).resolve().parents[2] / "tasks"


TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{4,128}$")
MEDIA_EXTENSIONS = {
    "video": {".mp4", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".flv"},
    "audio": {".mp3", ".wav", ".aac", ".m4a", ".ogg", ".flac", ".opus"},
    "image": {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"},
    "subtitle": {".srt", ".ass", ".ssa", ".vtt", ".sub", ".txt"},
}


class RevisionConflictError(Exception):
    def __init__(self, revision: int):
        self.revision = revision
        super().__init__("revision_conflict")


class EditorProjectRepository:
    _locks: dict[str, threading.RLock] = {}
    _locks_guard = threading.Lock()

    def _lock_for(self, task_id: str) -> threading.RLock:
        with self._locks_guard:
            return self._locks.setdefault(task_id, threading.RLock())

    def _resolve_task_root(self, task_id: str) -> Path | None:
        """解析任务根目录：优先控制平面工作区（CONTROL_PLANE_WORKSPACE_ROOT），其次旧 backend/tasks；均不存在返回 None。"""
        if not TASK_ID_PATTERN.fullmatch(task_id):
            raise HTTPException(400, "Invalid task id")
        control_root = Path(os.getenv("CONTROL_PLANE_WORKSPACE_ROOT", Path.cwd() / "control_plane_workspaces"))
        for root in (control_root, Path(TASKS_ROOT)):
            candidate = root / task_id
            if candidate.is_dir():
                return candidate
        return None

    def validate_task_id(self, task_id: str) -> None:
        if self._resolve_task_root(task_id) is None:
            raise HTTPException(404, "Task not found")

    def task_dir(self, task_id: str) -> Path:
        root = self._resolve_task_root(task_id)
        if root is None:
            raise HTTPException(404, "Task not found")
        return root

    def editor_dir(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "editor"

    def project_path(self, task_id: str) -> Path:
        return self.editor_dir(task_id) / "project.json"

    def assets_path(self, task_id: str) -> Path:
        return self.editor_dir(task_id) / "assets.json"

    def characters_path(self, task_id: str) -> Path:
        return self.editor_dir(task_id) / "characters.json"

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(500, f"Invalid editor metadata: {path.name}") from exc

    def _write_json(self, path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    def _media_type_for_path(self, path: Path) -> str | None:
        suffix = path.suffix.lower()
        for media_type, extensions in MEDIA_EXTENSIONS.items():
            if suffix in extensions:
                return media_type
        return None

    def _category_for(self, media_type: str, path: Path) -> str:
        name = path.name.lower()
        if media_type == "image" and any(token in name for token in ("cover", "thumbnail", "key_frame", "封面")):
            return "cover"
        return media_type if media_type in {"video", "audio", "subtitle"} else "other"

    def _source_priority(self, path: Path, media_type: str) -> tuple[int, int, str]:
        name = path.name.lower()
        output_score = 0 if "output" in path.parts else 1
        semantic_score = 2
        if media_type == "video" and any(token in name for token in ("dub", "merged", "output", "final", "字幕", "配音")):
            semantic_score = 0
        elif media_type == "audio" and any(token in name for token in ("dub", "tts", "voice", "配音")):
            semantic_score = 0
        elif media_type == "subtitle" and any(token in name for token in ("dub", "bilingual", "subtitle", "字幕")):
            semantic_score = 0
        elif media_type == "image" and any(token in name for token in ("cover", "thumbnail", "封面")):
            semantic_score = 0
        return output_score, semantic_score, name

    def _selection_priority(self, candidate: ImportCandidate) -> tuple[int, int, int, str]:
        name = candidate.name.lower()
        if candidate.category == "video":
            priority = 0 if "_dub" in name else 1 if "_subs" in name else 2 if "input" in name else 3
        elif candidate.category == "cover":
            priority = 0 if "cover" in name else 1 if "key_frame" in name else 2
        else:
            priority = 0
        source_priority = self._source_priority(Path(candidate.relative_path), candidate.type)
        return priority, source_priority[0], source_priority[1], source_priority[2]

    def _audio_element(self, candidate: ImportCandidate, start: float, duration: float) -> dict[str, Any]:
        return {
            "id": self._new_id("element"), "type": "audio", "sourceType": "upload", "name": candidate.name,
            "mediaId": candidate.id, "startTime": start, "duration": duration,
            "trimStart": 0, "trimEnd": 0, "volume": 1, "muted": False,
        }

    def _title_element(self, content: str, *, hook: bool = False) -> dict[str, Any]:
        return {
            "id": self._new_id("element"), "type": "text", "name": "Hook title" if hook else "Main title", "content": content,
            "startTime": 0, "duration": 1.5, "trimStart": 0, "trimEnd": 0,
            "fontSize": 6 if hook else 10, "fontFamily": "Open Sans", "color": "#ffff00" if hook else "#000000",
            "backgroundColor": "transparent" if hook else "#ffffff", "textAlign": "center",
            "fontWeight": "bold", "fontStyle": "normal", "textDecoration": "none",
            "transform": {"scale": 1, "position": {"x": 0, "y": 130 if hook else 0}, "rotate": 0}, "opacity": 1,
            **({"stroke": {"color": "#000000", "width": 3}} if hook else {}),
        }

    def _media_metadata(self, path: Path, media_type: str) -> dict[str, float | int]:
        if media_type not in {"video", "audio", "image"}:
            return {}
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-print_format", "json",
                    "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if result.returncode != 0:
                return {}
            info = json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            return {}
        metadata: dict[str, float | int] = {}
        try:
            duration = float(info.get("format", {}).get("duration"))
            if duration >= 0:
                metadata["duration"] = duration
        except (TypeError, ValueError):
            pass
        stream = next((item for item in info.get("streams", []) if item.get("codec_type") == "video"), None)
        if stream:
            for key in ("width", "height"):
                if isinstance(stream.get(key), int) and stream[key] > 0:
                    metadata[key] = stream[key]
            frame_rate = str(stream.get("r_frame_rate") or "")
            if "/" in frame_rate:
                numerator, denominator = frame_rate.split("/", 1)
                try:
                    fps = float(numerator) / float(denominator)
                    if fps > 0:
                        metadata["fps"] = fps
                except (ValueError, ZeroDivisionError):
                    pass
        return metadata

    def _parse_subtitle_timestamp(self, value: str) -> float | None:
        value = value.strip().replace(",", ".")
        parts = value.split(":")
        if len(parts) != 3:
            return None
        try:
            hours, minutes, seconds = parts
            result = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
            return result if result >= 0 else None
        except ValueError:
            return None

    def _subtitle_entries(self, path: Path) -> list[tuple[float, float, str]]:
        try:
            content = path.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")
        except OSError:
            return []
        entries: list[tuple[float, float, str]] = []
        if path.suffix.lower() in {".srt", ".vtt"}:
            for block in re.split(r"\n\s*\n", content.strip()):
                lines = [line.strip() for line in block.split("\n") if line.strip()]
                timing_index = next((index for index, line in enumerate(lines) if "-->" in line), None)
                if timing_index is None:
                    continue
                start_text, end_text = lines[timing_index].split("-->", 1)
                start = self._parse_subtitle_timestamp(start_text)
                end = self._parse_subtitle_timestamp(end_text.split()[0])
                text = "\n".join(lines[timing_index + 1:]).strip()
                if start is not None and end is not None and end > start and text:
                    entries.append((start, end, text))
        elif path.suffix.lower() in {".ass", ".ssa"}:
            for line in content.split("\n"):
                if not line.startswith("Dialogue:"):
                    continue
                fields = line.split(":", 1)[1].split(",", 9)
                if len(fields) != 10:
                    continue
                start = self._parse_subtitle_timestamp(fields[1])
                end = self._parse_subtitle_timestamp(fields[2])
                text = re.sub(r"\{[^}]*\}", "", fields[9]).replace("\\N", "\n").strip()
                if start is not None and end is not None and end > start and text:
                    entries.append((start, end, text))
        return entries

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    def _text_element(self, start: float, end: float, content: str) -> dict[str, Any]:
        return {
            "id": self._new_id("element"), "type": "text", "name": "Subtitle", "content": content,
            "startTime": start, "duration": end - start, "trimStart": 0, "trimEnd": 0,
            "fontSize": 5, "fontFamily": "Arial", "color": "#ffffff",
            "backgroundColor": "rgba(0, 0, 0, 0.7)", "textAlign": "center",
            "fontWeight": "normal", "fontStyle": "normal", "textDecoration": "none",
            "transform": {"scale": 1, "position": {"x": 0, "y": 300}, "rotate": 0}, "opacity": 1,
        }

    def _task_outputs(self, task_id: str) -> dict[str, str]:
        task_json = self.task_dir(task_id) / "task.json"
        data = self._read_json(task_json, {})
        paths: dict[str, str] = {}
        for node in data.get("nodes", {}).values():
            for output_id, output_path in node.get("outputs", {}).items():
                if isinstance(output_path, str) and output_path:
                    paths[output_path] = output_id
        return paths

    def import_candidates(self, task_id: str) -> list[ImportCandidate]:
        self.validate_task_id(task_id)
        root = self.task_dir(task_id)
        outputs = self._task_outputs(task_id)
        paths: dict[Path, str] = {}
        for raw_path, output_id in outputs.items():
            path = Path(raw_path)
            resolved_path = path.resolve()
            if path.is_file() and root in resolved_path.parents and "dub_temp" not in resolved_path.relative_to(root).parts:
                paths[resolved_path] = output_id
        for directory_name in ("cache", "output"):
            directory = root / directory_name
            if directory.is_dir():
                for path in directory.rglob("*"):
                    if path.is_file() and "dub_temp" not in path.relative_to(root).parts:
                        paths.setdefault(path.resolve(), directory_name)
        candidates: list[ImportCandidate] = []
        for path, source in paths.items():
            media_type = self._media_type_for_path(path)
            if not media_type:
                continue
            relative_path = path.relative_to(root).as_posix()
            category = self._category_for(media_type, path)
            asset_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{task_id}:{relative_path}").hex
            metadata = self._media_metadata(path, media_type)
            candidates.append(ImportCandidate(
                id=asset_id,
                name=path.name,
                type=media_type,
                relative_path=relative_path,
                source=source,
                size=path.stat().st_size,
                mime_type=mimetypes.guess_type(path.name)[0],
                category=category,
                **metadata,
            ))
        grouped: dict[str, list[ImportCandidate]] = {}
        for candidate in candidates:
            grouped.setdefault(candidate.category, []).append(candidate)
        for category, items in grouped.items():
            priority = self._selection_priority if category in {"video", "cover"} else lambda item: self._source_priority(root / item.relative_path, item.type)
            items.sort(key=priority)
            if items:
                items[0].recommended = True
                items[0].selected = True
        return sorted(candidates, key=lambda item: (item.category, self._selection_priority(item) if item.category in {"video", "cover"} else self._source_priority(root / item.relative_path, item.type)))

    def _default_project(self, task_id: str, name: str) -> dict[str, Any]:
        now = self._utc_now()
        scene_id = f"scene_{uuid.uuid4().hex[:12]}"
        video_track_id = f"track_{uuid.uuid4().hex[:12]}"
        return {
            "metadata": {"id": task_id, "name": name, "duration": 0, "createdAt": now, "updatedAt": now},
            "scenes": [{"id": scene_id, "name": "Main scene", "isMain": True, "tracks": [{"id": video_track_id, "type": "video", "name": "Main", "isMain": True, "elements": [], "transitions": []}], "bookmarks": [], "createdAt": now, "updatedAt": now}],
            "currentSceneId": scene_id,
            "settings": {"fps": 30, "canvasSize": {"width": 1920, "height": 1080}, "originalCanvasSize": None, "background": {"type": "color", "color": "#000000"}},
            "version": 3,
            "timelineViewState": {"zoomLevel": 1, "scrollLeft": 0, "playheadTime": 0},
            "taskId": task_id,
            "revision": 1,
            "updatedBy": "import",
            "updatedAt": now,
        }

    def _load_assets(self, task_id: str) -> list[dict[str, Any]]:
        return self._read_json(self.assets_path(task_id), {"assets": []}).get("assets", [])

    def _number(self, value: Any) -> float | None:
        try:
            number = float(value)
            return number if number >= 0 else None
        except (TypeError, ValueError):
            return None

    def _dub_segment_candidates(self, task_id: str) -> list[tuple[ImportCandidate, float, float]]:
        root = self.task_dir(task_id).resolve()
        path = root / "cache" / "dub_task.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        segments = data.get("segments") if isinstance(data, dict) else None
        if not isinstance(segments, list):
            return []
        result: list[tuple[ImportCandidate, float, float]] = []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            adjusted_path = segment.get("audio_file_adjusted")
            audio_path = adjusted_path if isinstance(adjusted_path, str) else segment.get("audio_file")
            if not isinstance(audio_path, str) or not audio_path.strip():
                continue
            candidate_path = (root / audio_path).resolve()
            if root not in candidate_path.parents or not candidate_path.is_file() or candidate_path.stat().st_size == 0:
                if audio_path == adjusted_path:
                    audio_path = segment.get("audio_file")
                    if not isinstance(audio_path, str) or not audio_path.strip():
                        continue
                    candidate_path = (root / audio_path).resolve()
                if root not in candidate_path.parents or not candidate_path.is_file() or candidate_path.stat().st_size == 0:
                    continue
            if self._media_type_for_path(candidate_path) != "audio":
                continue
            adjusted = audio_path == adjusted_path
            duration = self._media_metadata(candidate_path, "audio").get("duration")
            if not isinstance(duration, (int, float)) or duration <= 0:
                duration = self._number(segment.get("adjusted_duration") if adjusted else segment.get("real_duration")) or self._number(segment.get("duration"))
            start = self._number(segment.get("new_start"))
            start = start if start is not None else self._number(segment.get("target_start"))
            start = start if start is not None else self._number(segment.get("start"))
            if start is None or not isinstance(duration, (int, float)) or duration <= 0:
                continue
            relative_path = candidate_path.relative_to(root).as_posix()
            result.append((ImportCandidate(
                id=uuid.uuid5(uuid.NAMESPACE_URL, f"{task_id}:{relative_path}").hex,
                name=candidate_path.name,
                type="audio",
                relative_path=relative_path,
                source="dub_segment",
                size=candidate_path.stat().st_size,
                mime_type=mimetypes.guess_type(candidate_path.name)[0],
                category="audio",
                duration=float(duration),
            ), start, float(duration)))
        return sorted(result, key=lambda item: item[1])

    def _title_metadata(self, task_id: str) -> tuple[str, str]:
        cache_dir = self.task_dir(task_id) / "cache"
        if not cache_dir.is_dir():
            return "", ""
        title_files = sorted(
            (path for path in cache_dir.glob("*.json") if "title" in path.name.lower()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in title_files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            main_title = data.get("tittle") or data.get("title") or ""
            hook = data.get("hook") or ""
            return str(main_title).strip(), str(hook).strip()
        return "", ""

    def _normalize_project(self, task_id: str, project: dict[str, Any]) -> dict[str, Any]:
        now = self._utc_now()
        normalized = dict(project) if isinstance(project, dict) else {}
        metadata = normalized.setdefault("metadata", {})
        metadata["id"] = task_id
        metadata.setdefault("name", f"剪辑项目 {task_id}")
        metadata.setdefault("duration", 0)
        metadata.setdefault("createdAt", now)
        metadata.setdefault("updatedAt", now)
        settings = normalized.setdefault("settings", {})
        settings.setdefault("fps", 30)
        settings.setdefault("canvasSize", {"width": 1920, "height": 1080})
        settings.setdefault("originalCanvasSize", None)
        settings.setdefault("background", {"type": "color", "color": "#000000"})
        normalized.setdefault("version", 3)
        normalized.setdefault("timelineViewState", {"zoomLevel": 1, "scrollLeft": 0, "playheadTime": 0})
        normalized["taskId"] = task_id
        normalized.setdefault("revision", 1)
        normalized.setdefault("updatedBy", "import")
        normalized.setdefault("updatedAt", now)
        scenes = normalized.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            scene_id = self._new_id("scene")
            scenes = [{"id": scene_id, "name": "Main scene", "isMain": True, "tracks": [], "bookmarks": [], "createdAt": now, "updatedAt": now}]
            normalized["scenes"] = scenes
        for scene_index, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                scene = {}
                scenes[scene_index] = scene
            scene.setdefault("id", self._new_id("scene"))
            scene.setdefault("name", "Main scene")
            scene.setdefault("isMain", scene_index == 0)
            scene.setdefault("bookmarks", [])
            scene.setdefault("createdAt", now)
            scene.setdefault("updatedAt", now)
            tracks = scene.get("tracks")
            if not isinstance(tracks, list):
                tracks = []
                scene["tracks"] = tracks
            if not tracks:
                tracks.append({"id": self._new_id("track"), "type": "video", "name": "Main", "isMain": True, "muted": False, "hidden": False, "elements": [], "transitions": []})
            for track_index, track in enumerate(tracks):
                if not isinstance(track, dict):
                    track = {}
                    tracks[track_index] = track
                track_type = track.get("type") if track.get("type") in {"video", "audio", "text", "sticker"} else "video"
                track["type"] = track_type
                track.setdefault("id", self._new_id("track"))
                track.setdefault("name", track_type.title())
                track.setdefault("elements", [])
                if track_type == "video":
                    track.setdefault("isMain", track_index == 0)
                    track.setdefault("muted", False)
                    track.setdefault("hidden", False)
                    track.setdefault("transitions", [])
                elif track_type == "audio":
                    track.setdefault("muted", False)
                else:
                    track.setdefault("hidden", False)
                for element_index, element in enumerate(track["elements"]):
                    if not isinstance(element, dict):
                        element = {}
                        track["elements"][element_index] = element
                    element_type = element.get("type")
                    if element_type == "subtitle":
                        replacement = self._text_element(
                            float(element.get("startTime", 0) or 0),
                            float(element.get("startTime", 0) or 0) + max(float(element.get("duration", 3) or 3), 0.01),
                            str(element.get("content") or element.get("text") or ""),
                        )
                        replacement["id"] = element.get("id") or replacement["id"]
                        track["elements"][element_index] = element = replacement
                        element_type = "text"
                    element.setdefault("id", self._new_id("element"))
                    element.setdefault("name", element_type.title() if isinstance(element_type, str) else "Element")
                    element.setdefault("startTime", 0)
                    element.setdefault("duration", 3)
                    element.setdefault("trimStart", 0)
                    element.setdefault("trimEnd", 0)
                    if element_type in {"video", "image", "text", "sticker"}:
                        element.setdefault("hidden", False)
                        element.setdefault("transform", {"scale": 1, "position": {"x": 0, "y": 0}, "rotate": 0})
                        element.setdefault("opacity", 1)
                    if element_type == "audio":
                        element.setdefault("sourceType", "upload")
                        element.setdefault("volume", 1)
                        element.setdefault("muted", False)
                    if element_type == "text":
                        element.setdefault("content", "")
                        element.setdefault("fontSize", 5)
                        element.setdefault("fontFamily", "Arial")
                        element.setdefault("color", "#ffffff")
                        element.setdefault("backgroundColor", "transparent")
                        element.setdefault("textAlign", "center")
                        element.setdefault("fontWeight", "normal")
                        element.setdefault("fontStyle", "normal")
                        element.setdefault("textDecoration", "none")
        normalized.setdefault("currentSceneId", scenes[0]["id"])
        metadata["duration"] = max(
            float(metadata.get("duration") or 0),
            max((float(element.get("startTime", 0) or 0) + float(element.get("duration", 0) or 0) for scene in scenes for track in scene["tracks"] for element in track["elements"]), default=0),
        )
        return normalized

    def import_assets(
        self,
        task_id: str,
        candidate_ids: list[str],
        use_dub_segments: bool = False,
    ) -> dict[str, Any]:
        self.validate_task_id(task_id)
        with self._lock_for(task_id):
            candidates = {candidate.id: candidate for candidate in self.import_candidates(task_id)}
            selected_ids = candidate_ids or [candidate.id for candidate in candidates.values() if candidate.selected]
            selected_ids = list(dict.fromkeys(selected_ids))
            unknown_ids = set(selected_ids) - set(candidates)
            if unknown_ids:
                raise HTTPException(400, "Unknown import candidates")
            existing_assets = {asset["id"]: asset for asset in self._load_assets(task_id)}
            for candidate_id in selected_ids:
                candidate = candidates[candidate_id]
                existing_assets[candidate.id] = candidate.model_dump()
            project = self._read_json(self.project_path(task_id), None)
            if not project:
                task = self._read_json(self.task_dir(task_id) / "task.json", {})
                project = self._default_project(task_id, task.get("task_name") or f"剪辑项目 {task_id}")
                scene = project["scenes"][0]
                main_track = scene["tracks"][0]
                selected = [candidates[candidate_id] for candidate_id in selected_ids]
                main_video = next((candidate for candidate in selected if candidate.category == "video"), None)
                cover = next((candidate for candidate in selected if candidate.category == "cover"), None)
                if main_video:
                    main_track["elements"].append({
                        "id": self._new_id("element"), "type": "video", "mediaId": main_video.id, "startTime": 0,
                        "duration": main_video.duration or 5.0, "trimStart": 0, "trimEnd": 0, "opacity": 1,
                        "transform": {"position": {"x": 0, "y": 0}, "scale": 1, "rotate": 0},
                    })
                if cover:
                    scene["tracks"].append({
                        "id": self._new_id("track"), "type": "video", "name": "Cover", "isMain": False, "muted": False, "hidden": False, "transitions": [],
                        "elements": [{"id": self._new_id("element"), "type": "image", "mediaId": cover.id, "startTime": 0, "duration": 1.5, "trimStart": 0, "trimEnd": 0, "opacity": 1, "transform": {"position": {"x": 0, "y": 0}, "scale": 1, "rotate": 0}}],
                    })
                selected_audio = [candidate for candidate in selected if candidate.type == "audio"]
                if selected_audio:
                    audio_track = {"id": self._new_id("track"), "type": "audio", "name": "Audio", "isMain": False, "muted": False, "elements": []}
                    audio_track["elements"] = [self._audio_element(candidate, 0, candidate.duration or 5.0) for candidate in selected_audio]
                    scene["tracks"].append(audio_track)
                dub_segments = self._dub_segment_candidates(task_id) if use_dub_segments else []
                if use_dub_segments and not dub_segments:
                    fallback = next((candidate for candidate in candidates.values() if candidate.type == "audio" and "dub" in candidate.name.lower()), None)
                    if fallback:
                        dub_segments = [(fallback, 0.0, fallback.duration or 5.0)]
                primary_track = None
                secondary_track = None
                primary_end = 0.0
                for candidate, start, duration in dub_segments:
                    existing_assets[candidate.id] = candidate.model_dump()
                    if primary_track is None or start >= primary_end:
                        if primary_track is None:
                            primary_track = {"id": self._new_id("track"), "type": "audio", "name": "Dub audio", "isMain": False, "muted": False, "elements": []}
                            scene["tracks"].append(primary_track)
                        primary_track["elements"].append(self._audio_element(candidate, start, duration))
                        primary_end = start + duration
                    else:
                        if secondary_track is None:
                            secondary_track = {"id": self._new_id("track"), "type": "audio", "name": "Dub audio 2", "isMain": False, "muted": False, "elements": []}
                            scene["tracks"].append(secondary_track)
                        secondary_track["elements"].append(self._audio_element(candidate, start, duration))
                subtitle_entries = [(candidate, self._subtitle_entries(self.task_dir(task_id) / candidate.relative_path)) for candidate in selected if candidate.type == "subtitle"]
                if any(entries for _, entries in subtitle_entries):
                    subtitle_track = {"id": self._new_id("track"), "type": "text", "name": "Captions", "hidden": False, "elements": []}
                    for _, entries in subtitle_entries:
                        subtitle_track["elements"].extend(self._text_element(start, end, content) for start, end, content in entries)
                    scene["tracks"].append(subtitle_track)
                main_title, hook = self._title_metadata(task_id)
                if main_title:
                    scene["tracks"].append({"id": self._new_id("track"), "type": "text", "name": "Main title", "hidden": False, "elements": [self._title_element(main_title)]})
                if hook:
                    scene["tracks"].append({"id": self._new_id("track"), "type": "text", "name": "Hook title", "hidden": False, "elements": [self._title_element(hook, hook=True)]})
                project = self._normalize_project(task_id, project)
                self._write_json(self.project_path(task_id), project)
                self._write_json(self.characters_path(task_id), {"revision": 1, "characters": []})
            self._write_json(self.assets_path(task_id), {"assets": list(existing_assets.values()), "updatedAt": self._utc_now()})
            return self.snapshot(task_id)

    def snapshot(self, task_id: str) -> dict[str, Any]:
        self.validate_task_id(task_id)
        project = self._read_json(self.project_path(task_id), None)
        if project is None:
            raise HTTPException(404, "Editor project not found")
        project = self._normalize_project(task_id, project)
        self._write_json(self.project_path(task_id), project)
        characters = self._read_json(self.characters_path(task_id), {"revision": 1, "characters": []})
        return {"project": project, "assets": self._load_assets(task_id), "characters": characters.get("characters", []), "revision": project.get("revision", 1)}

    def save_project(self, task_id: str, project: dict[str, Any], expected_revision: int, updated_by: str) -> dict[str, Any]:
        self.validate_task_id(task_id)
        with self._lock_for(task_id):
            current = self._read_json(self.project_path(task_id), None)
            if current is None:
                raise HTTPException(404, "Editor project not found")
            current_revision = int(current.get("revision", 1))
            if current_revision != expected_revision:
                raise RevisionConflictError(current_revision)
            project = self._normalize_project(task_id, project)
            project["taskId"] = task_id
            project["revision"] = current_revision + 1
            project["updatedBy"] = updated_by
            project["updatedAt"] = self._utc_now()
            metadata = project.setdefault("metadata", {})
            metadata["id"] = task_id
            metadata["updatedAt"] = project["updatedAt"]
            self._write_json(self.project_path(task_id), project)
            return self.snapshot(task_id)

    def save_characters(self, task_id: str, characters: list[dict[str, Any]], expected_revision: int) -> dict[str, Any]:
        self.validate_task_id(task_id)
        with self._lock_for(task_id):
            current = self._read_json(self.characters_path(task_id), {"revision": 1, "characters": []})
            if int(current.get("revision", 1)) != expected_revision:
                raise RevisionConflictError(int(current.get("revision", 1)))
            value = {"revision": expected_revision + 1, "characters": characters, "updatedAt": self._utc_now()}
            self._write_json(self.characters_path(task_id), value)
            return value

    def asset_path(self, task_id: str, asset_id: str) -> Path:
        self.validate_task_id(task_id)
        asset = next((asset for asset in self._load_assets(task_id) if asset.get("id") == asset_id), None)
        if not asset:
            raise HTTPException(404, "Asset not found")
        root = self.task_dir(task_id).resolve()
        path = (root / asset["relative_path"]).resolve()
        if root not in path.parents or not path.is_file():
            raise HTTPException(404, "Asset file not found")
        return path

    def export_path(self, task_id: str, suffix: str) -> Path:
        self.validate_task_id(task_id)
        safe_suffix = suffix.lower() if suffix.lower() in {".mp4", ".webm"} else ".mp4"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_dir = self.task_dir(task_id) / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir / f"edited-{timestamp}{safe_suffix}"

    def register_export(self, task_id: str, path: Path) -> AssetRecord:
        root = self.task_dir(task_id)
        asset = AssetRecord(
            id=uuid.uuid4().hex,
            name=path.name,
            type="video",
            relative_path=path.relative_to(root).as_posix(),
            source="editor_export",
            size=path.stat().st_size,
            mime_type=mimetypes.guess_type(path.name)[0] or "video/mp4",
            recommended=True,
        )
        with self._lock_for(task_id):
            assets = self._load_assets(task_id)
            assets.append(asset.model_dump())
            self._write_json(self.assets_path(task_id), {"assets": assets, "updatedAt": self._utc_now()})
        return asset
