from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

import httpx

from backend.editor.repository import EditorProjectRepository, RevisionConflictError
from backend.llm.llm_client import get_llm_client


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_project_info",
            "description": "Read the current editing project, assets, tracks, and revision.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_video_to_timeline",
            "description": "Add a video or image asset to the main timeline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mediaId": {"type": "string"},
                    "startTime": {"type": "number", "minimum": 0},
                    "duration": {"type": "number", "minimum": 0.1},
                },
                "required": ["mediaId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_audio_to_timeline",
            "description": "Add an audio asset to an audio track.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mediaId": {"type": "string"},
                    "startTime": {"type": "number", "minimum": 0},
                    "duration": {"type": "number", "minimum": 0.1},
                },
                "required": ["mediaId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_text_to_timeline",
            "description": "Add a styled text element to the timeline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "startTime": {"type": "number", "minimum": 0},
                    "duration": {"type": "number", "minimum": 0.1},
                    "color": {"type": "string"},
                    "fontSize": {"type": "number", "minimum": 1, "maximum": 200},
                    "positionX": {"type": "number"},
                    "positionY": {"type": "number"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_element",
            "description": "Update text or visual properties of an existing element.",
            "parameters": {
                "type": "object",
                "properties": {
                    "trackId": {"type": "string"},
                    "elementId": {"type": "string"},
                    "content": {"type": "string"},
                    "startTime": {"type": "number", "minimum": 0},
                    "duration": {"type": "number", "minimum": 0.1},
                    "color": {"type": "string"},
                    "fontSize": {"type": "number", "minimum": 1, "maximum": 200},
                },
                "required": ["trackId", "elementId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_element",
            "description": "Delete an element from a timeline track.",
            "parameters": {
                "type": "object",
                "properties": {"trackId": {"type": "string"}, "elementId": {"type": "string"}},
                "required": ["trackId", "elementId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_project_settings",
            "description": "Update project canvas settings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "width": {"type": "integer", "minimum": 320, "maximum": 7680},
                    "height": {"type": "integer", "minimum": 320, "maximum": 7680},
                    "fps": {"type": "integer", "minimum": 1, "maximum": 120},
                    "backgroundColor": {"type": "string"},
                },
            },
        },
    },
]


class EditorAgentService:
    def __init__(self, repository: EditorProjectRepository | None = None):
        self.repository = repository or EditorProjectRepository()
        self._runs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _run_path(self, task_id: str, run_id: str) -> Path:
        path = self.repository.editor_dir(task_id) / "runs"
        path.mkdir(parents=True, exist_ok=True)
        return path / f"{run_id}.json"

    def _save_run(self, task_id: str, run: dict[str, Any]) -> None:
        path = self._run_path(task_id, run["id"])
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        with self._lock:
            self._runs[run["id"]] = run

    def get_run(self, task_id: str, run_id: str) -> dict[str, Any]:
        with self._lock:
            run = self._runs.get(run_id)
        if run:
            return run
        path = self._run_path(task_id, run_id)
        if not path.exists():
            raise ValueError("Agent run not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def _messages(self, task_id: str, content: str, role: str) -> list[dict[str, Any]]:
        snapshot = self.repository.snapshot(task_id)
        project = snapshot["project"]
        context = {
            "taskId": task_id,
            "revision": snapshot["revision"],
            "role": role,
            "project": {"name": project.get("metadata", {}).get("name"), "settings": project.get("settings"), "scenes": project.get("scenes", [])},
            "assets": [{key: asset.get(key) for key in ("id", "name", "type", "duration", "width", "height")} for asset in snapshot["assets"]],
            "characters": snapshot["characters"],
        }
        return [
            {"role": "system", "content": "You are a video editing assistant. Use tools for project changes. Only reference IDs present in the supplied context. Explain the completed edit concisely."},
            {"role": "system", "content": json.dumps(context, ensure_ascii=False)},
            {"role": "user", "content": content},
        ]

    def _client(self, manual_config: dict[str, str] | None) -> tuple[OpenAI, str]:
        if manual_config:
            base_url = manual_config.get("base_url", "").rstrip("/")
            api_key = manual_config.get("api_key", "")
            model = manual_config.get("model", "")
            if not base_url or not api_key or not model:
                raise ValueError("Manual OpenAI-compatible configuration is incomplete")
            return OpenAI(
                base_url=base_url, api_key=api_key, timeout=120, max_retries=0,
                # 忽略系统代理（VPN 全局代理），直接连接上游
                http_client=httpx.Client(timeout=120, trust_env=False),
            ), model
        llm = get_llm_client()
        config = llm._get_api_config("editor_agent")
        if not config["base_url"] or not config["api_key"]:
            raise ValueError("LLM router is not configured")
        return llm._make_client(config), config["model"]

    def _new_track(self, project: dict[str, Any], track_type: str) -> dict[str, Any]:
        scene = next((scene for scene in project.get("scenes", []) if scene.get("id") == project.get("currentSceneId")), project.get("scenes", [])[0])
        track = {"id": f"track_{uuid.uuid4().hex[:12]}", "type": track_type, "name": track_type.title(), "isMain": False, "elements": []}
        if track_type == "video":
            track["transitions"] = []
        scene.setdefault("tracks", []).append(track)
        return track

    def _find_track(self, project: dict[str, Any], track_id: str) -> dict[str, Any]:
        for scene in project.get("scenes", []):
            for track in scene.get("tracks", []):
                if track.get("id") == track_id:
                    return track
        raise ValueError("Timeline track not found")

    def _execute_tool(self, task_id: str, tool_name: str, arguments: dict[str, Any], expected_revision: int) -> dict[str, Any]:
        snapshot = self.repository.snapshot(task_id)
        if expected_revision != snapshot["revision"]:
            raise RevisionConflictError(snapshot["revision"])
        if tool_name == "get_project_info":
            return {"success": True, "message": "Project state loaded", "data": snapshot}
        project = snapshot["project"]
        assets = {asset["id"]: asset for asset in snapshot["assets"]}
        if tool_name in {"add_video_to_timeline", "add_audio_to_timeline"}:
            asset = assets.get(arguments["mediaId"])
            required_type = "audio" if tool_name == "add_audio_to_timeline" else None
            if not asset or (required_type and asset.get("type") != required_type) or (not required_type and asset.get("type") not in {"video", "image"}):
                raise ValueError("Selected media asset is unavailable for this operation")
            track_type = "audio" if required_type else "video"
            track = next((track for scene in project.get("scenes", []) for track in scene.get("tracks", []) if track.get("type") == track_type), None)
            if not track:
                track = self._new_track(project, track_type)
            duration = float(arguments.get("duration") or asset.get("duration") or 5)
            element = {"id": f"element_{uuid.uuid4().hex[:12]}", "type": asset["type"], "mediaId": asset["id"], "startTime": float(arguments.get("startTime") or 0), "duration": duration, "trimStart": 0, "trimEnd": 0, "opacity": 1, "transform": {"position": {"x": 0, "y": 0}, "scale": 1, "rotate": 0}}
            track.setdefault("elements", []).append(element)
            message = f"Added {asset['name']} to the {track_type} timeline"
        elif tool_name == "add_text_to_timeline":
            track = next((track for scene in project.get("scenes", []) for track in scene.get("tracks", []) if track.get("type") == "text"), None)
            if not track:
                track = self._new_track(project, "text")
            element = {"id": f"element_{uuid.uuid4().hex[:12]}", "type": "text", "content": arguments["content"], "startTime": float(arguments.get("startTime") or 0), "duration": float(arguments.get("duration") or 3), "fontSize": arguments.get("fontSize", 48), "color": arguments.get("color", "#ffffff"), "transform": {"position": {"x": arguments.get("positionX", 0), "y": arguments.get("positionY", 0)}, "scale": 1, "rotate": 0}, "opacity": 1}
            track.setdefault("elements", []).append(element)
            message = "Added text to the timeline"
        elif tool_name == "update_element":
            track = self._find_track(project, arguments["trackId"])
            element = next((item for item in track.get("elements", []) if item.get("id") == arguments["elementId"]), None)
            if not element:
                raise ValueError("Timeline element not found")
            for field in ("content", "startTime", "duration", "color", "fontSize"):
                if field in arguments:
                    element[field] = arguments[field]
            message = "Updated timeline element"
        elif tool_name == "delete_element":
            track = self._find_track(project, arguments["trackId"])
            before = len(track.get("elements", []))
            track["elements"] = [item for item in track.get("elements", []) if item.get("id") != arguments["elementId"]]
            if len(track["elements"]) == before:
                raise ValueError("Timeline element not found")
            message = "Deleted timeline element"
        elif tool_name == "update_project_settings":
            settings = project.setdefault("settings", {})
            canvas = settings.setdefault("canvasSize", {"width": 1920, "height": 1080})
            if "width" in arguments:
                canvas["width"] = arguments["width"]
            if "height" in arguments:
                canvas["height"] = arguments["height"]
            if "fps" in arguments:
                settings["fps"] = arguments["fps"]
            if "backgroundColor" in arguments:
                settings["background"] = {"type": "color", "color": arguments["backgroundColor"]}
            message = "Updated project settings"
        else:
            raise ValueError(f"Unsupported tool: {tool_name}")
        updated = self.repository.save_project(task_id, project, expected_revision, "agent")
        return {"success": True, "message": message, "data": {"revision": updated["revision"]}}

    def execute(self, task_id: str, content: str, role: str = "auto", expected_revision: int | None = None, manual_config: dict[str, str] | None = None) -> dict[str, Any]:
        snapshot = self.repository.snapshot(task_id)
        revision = expected_revision if expected_revision is not None else snapshot["revision"]
        run = {"id": uuid.uuid4().hex, "task_id": task_id, "status": "running", "createdAt": self._now(), "events": [], "toolCalls": [], "input_revision": revision}
        self._save_run(task_id, run)
        try:
            client, model = self._client(manual_config)
            messages = self._messages(task_id, content, role)
            final_content = ""
            for _ in range(8):
                response = client.chat.completions.create(model=model, messages=messages, tools=TOOL_SCHEMAS, tool_choice="auto")
                message = response.choices[0].message
                if message.content:
                    final_content += message.content
                    run["events"].append({"type": "content", "content": message.content})
                messages.append(message.model_dump(exclude_none=True))
                if not message.tool_calls:
                    break
                for call in message.tool_calls:
                    arguments = json.loads(call.function.arguments or "{}")
                    result = self._execute_tool(task_id, call.function.name, arguments, revision)
                    revision = result.get("data", {}).get("revision", revision)
                    record = {"id": call.id, "name": call.function.name, "arguments": arguments, "result": result}
                    run["toolCalls"].append(record)
                    run["events"].append({"type": "tool.completed", **record})
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)})
            run["status"] = "completed"
            run["content"] = final_content or "已完成项目分析和编辑。"
            run["output_revision"] = revision
        except Exception as exc:
            run["status"] = "failed"
            run["error"] = str(exc)
        run["completedAt"] = self._now()
        self._save_run(task_id, run)
        return run
